"""结构化日志管理器 — 工业调试工具的统一日志设施.

设计目标（ISA-101 思路：信息可检索、可追溯）:
- **结构化字段**: ts / level / source / category / message / data
- **三路输出**:
    1. 内存环形缓冲（查询最近记录，O(1)）
    2. JSONL 会话文件（落盘 + 按大小轮转，便于机器分析）
    3. 订阅回调（Web 层据此把日志实时推给浏览器）
- **Python logging 桥**: 把既有 ``iec104.*`` logger 的记录自动转发进来，
  引擎/传输层日志零改动即可被收纳（不重复造轮子）

级别沿用 logging 标准: DEBUG < INFO < WARNING < ERROR < CRITICAL。
类别（category）用于业务过滤: connection / protocol / command / data / ui / system。

用法:
    mgr = LogManager(source="slave", log_dir="logs")
    mgr.info("子站启动", source="slave", category="connection")
    mgr.attach_python_logging()          # 收纳 iec104.* 引擎日志
    rows = mgr.query(level_min="WARNING", limit=50)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
DEFAULT_CATEGORIES = ("connection", "protocol", "command", "data", "ui", "system")


@dataclass
class LogEntry:
    """一条结构化日志."""

    ts: float
    level: str
    source: str
    category: str
    message: str
    data: dict | None = None

    def to_dict(self) -> dict:
        out = {
            "ts": self.ts,
            "level": self.level,
            "source": self.source,
            "category": self.category,
            "message": self.message,
        }
        if self.data:
            out["data"] = self.data
        return out


class _RotatingJsonlFile:
    """JSONL 追加写 + 按大小轮转（file → file.1 → file.2 ...）."""

    def __init__(self, path: Path, max_bytes: int, backups: int) -> None:
        self.path = Path(path)
        self.max_bytes = max(1024, int(max_bytes))
        self.backups = max(1, int(backups))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, line: str) -> None:
        if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
            self._rotate()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _rotate(self) -> None:
        oldest = self.path.with_suffix(self.path.suffix + f".{self.backups}")
        if oldest.exists():
            oldest.unlink()
        for i in range(self.backups - 1, 0, -1):
            src = self.path.with_suffix(self.path.suffix + f".{i}")
            dst = self.path.with_suffix(self.path.suffix + f".{i + 1}")
            if src.exists():
                src.replace(dst)
        self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))

    def read_all(self) -> list[str]:
        """按新→旧顺序读取所有轮转文件的内容行."""
        lines: list[str] = []
        for i in range(self.backups, 0, -1):
            p = self.path.with_suffix(self.path.suffix + f".{i}")
            if p.exists():
                lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines())
        if self.path.exists():
            lines.extend(self.path.read_text(encoding="utf-8", errors="replace").splitlines())
        return lines


class LogManager:
    """日志管理器：内存环形缓冲 + JSONL 落盘 + 订阅推送."""

    def __init__(self, source: str = "master", max_memory: int = 5000,
                 log_dir: str | Path | None = None, file_enabled: bool = True,
                 file_max_bytes: int = 5_000_000, file_backups: int = 5) -> None:
        self.source = source
        self._buf: deque[LogEntry] = deque(maxlen=max(100, int(max_memory)))
        self._lock = threading.Lock()
        self._subscribers: list = []
        self._file = None
        if file_enabled:
            directory = Path(log_dir) if log_dir else Path("logs")
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self._file = _RotatingJsonlFile(
                directory / f"iec104_{source}_{stamp}.jsonl",
                file_max_bytes, file_backups,
            )

    # ── 写入 ──────────────────────────────────────────────────────

    def log(self, level: str, message: str, *, source: str | None = None,
            category: str = "system", data: dict | None = None) -> LogEntry:
        level_u = str(level).upper()
        entry = LogEntry(
            ts=time.time(),
            level=level_u if level_u in LEVEL_ORDER else "INFO",
            source=source or self.source, category=category or "system",
            message=str(message), data=data,
        )
        with self._lock:
            self._buf.append(entry)
        if self._file is not None:
            try:
                self._file.append(json.dumps(entry.to_dict(), ensure_ascii=False))
            except Exception:            # 落盘失败不影响内存与推送
                pass
        for cb in list(self._subscribers):
            try:
                cb(entry)
            except Exception:
                pass
        return entry

    def debug(self, message: str, **kw) -> LogEntry:
        return self.log("DEBUG", message, **kw)

    def info(self, message: str, **kw) -> LogEntry:
        return self.log("INFO", message, **kw)

    def warning(self, message: str, **kw) -> LogEntry:
        return self.log("WARNING", message, **kw)

    def error(self, message: str, **kw) -> LogEntry:
        return self.log("ERROR", message, **kw)

    # ── 查询 ──────────────────────────────────────────────────────

    def query(self, *, level_min: str = "DEBUG", source: str | None = None,
              category: str | None = None, contains: str | None = None,
              limit: int = 200, newest_first: bool = True) -> list[LogEntry]:
        """按条件过滤内存缓冲；level_min 之上（含）全取."""
        min_order = LEVEL_ORDER.get(str(level_min).upper(), 10)
        needle = contains.lower() if contains else None
        with self._lock:
            rows = list(self._buf)
        rows = [r for r in rows if LEVEL_ORDER.get(r.level, 20) >= min_order]
        if source:
            rows = [r for r in rows if r.source == source]
        if category:
            rows = [r for r in rows if r.category == category]
        if needle:
            rows = [r for r in rows if needle in r.message.lower()
                    or needle in json.dumps(r.data or {}, ensure_ascii=False).lower()]
        rows.sort(key=lambda r: r.ts, reverse=newest_first)
        return rows[: max(1, int(limit))]

    def clear_memory(self) -> None:
        with self._lock:
            self._buf.clear()

    def stats(self) -> dict:
        with self._lock:
            rows = list(self._buf)
        by_level: dict[str, int] = {}
        for r in rows:
            by_level[r.level] = by_level.get(r.level, 0) + 1
        return {
            "total": len(rows),
            "by_level": by_level,
            "file": str(self._file.path) if self._file else None,
            "file_bytes": (self._file.path.stat().st_size
                           if self._file and self._file.path.exists() else 0),
        }

    # ── 订阅（Web 实时推送用）─────────────────────────────────────

    def subscribe(self, callback) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ── Python logging 桥 ─────────────────────────────────────────

    def attach_python_logging(self, logger_names: tuple[str, ...] = ("iec104",),
                              level: int = logging.INFO) -> None:
        """把既有 ``iec104.*`` logger 的记录收纳进来（幂等，重复调用只挂一次）.

        单进程双角色（master+slave）时每个 LogManager 各挂一个 handler；
        ``_PythonLogBridge.emit`` 按 logger 名的角色段过滤，避免两边日志混在一起。
        """
        for name in logger_names:
            lg = logging.getLogger(name)
            lg.setLevel(level)
            if any(
                isinstance(h, _PythonLogBridge) and h.manager is self
                for h in lg.handlers
            ):
                continue
            lg.addHandler(_PythonLogBridge(self))


class _PythonLogBridge(logging.Handler):
    """logging.Handler → LogManager：引擎日志零改动进入日志模块."""

    _CATEGORY_BY_NAME = {
        "transport": "connection",
        "master": "protocol",
        "slave": "protocol",
        "webui": "ui",
    }

    def __init__(self, manager: LogManager) -> None:
        super().__init__()
        self.manager = manager

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # 单进程双角色：iec104.master.* / iec104.slave.* 只进对应角色的
            # LogManager；iec104.transport / webui 等共享日志两边都收。
            parts = record.name.split(".")
            if (
                len(parts) >= 2
                and parts[1] in ("master", "slave")
                and self.manager.source in ("master", "slave")
                and parts[1] != self.manager.source
            ):
                return
            level = record.levelname
            if level not in LEVEL_ORDER:
                level = "INFO"
            tail = record.name.rsplit(".", 1)[-1]
            category = self._CATEGORY_BY_NAME.get(tail, "system")
            message = record.getMessage()
            data = None
            if record.exc_info:
                import traceback
                data = {"traceback": "".join(traceback.format_exception(*record.exc_info))[-2000:]}
            self.manager.log(level, message, source=record.name,
                             category=category, data=data)
        except Exception:                 # 日志桥绝不反噬业务
            pass
