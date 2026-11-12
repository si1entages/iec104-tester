"""对点 / 传动验收会话持久化（WP2）.

独立于历史库（``HistoryDB``）：历史库按帧/点值高频写入并带保留期淘汰，
验收记录是**低频、需长期留存、不可被自动清理**的交付物，因此单独建库
``data/commissioning.db``。连接参数沿用 HistoryDB 的 WAL + busy_timeout +
``check_same_thread=False`` 组合（跨线程/多进程安全），同步方法由调用方
在 asyncio handler 里用 ``asyncio.to_thread`` 包装，不阻塞事件循环。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from core.data.commissioning import (
    CommissionItem,
    CommissionSession,
    SessionStatus,
    Verdict,
)


class CommissionStore:
    """验收会话的 SQLite 存储（会话整体 JSON 列，点数级规模，无需分表）."""

    def __init__(self, db_path: str | Path = "data/commissioning.db"):
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        # RLock：conn 属性的 lazy open 与 save/list 的显式锁可能嵌套
        self._lock = threading.RLock()

    # ── 生命周期 ──────────────────────────────────────────────────

    def open(self) -> None:
        if self._conn is not None:
            return
        path = Path(self._db_path)
        if path.parent != Path("") and str(path.parent) not in (".", ""):
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS commission_sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_commission_created
                    ON commission_sessions(created_at DESC);
            """)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        # lazy open：EngineBridge 构造时（含契约自检/单测）不产生磁盘副作用
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    # ── 写 ────────────────────────────────────────────────────────

    @staticmethod
    def new_id() -> str:
        return f"c-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"

    def _payload(self, s: CommissionSession) -> str:
        return json.dumps({
            "id": s.id,
            "name": s.name,
            "created_at": s.created_at,
            "operator": s.operator,
            "status": s.status.value,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
            "cursor": s.cursor,
            "note": s.note,
            "point_table_snapshot": s.point_table_snapshot,
            "items": [i.to_dict() for i in s.items],
        }, ensure_ascii=False)

    def save(self, s: CommissionSession) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO commission_sessions "
                "(id, name, created_at, status, payload) VALUES (?, ?, ?, ?, ?)",
                (s.id, s.name, s.created_at, s.status.value, self._payload(s)),
            )
            self.conn.commit()

    def delete(self, session_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM commission_sessions WHERE id = ?", (session_id,))
            self.conn.commit()
            return cur.rowcount > 0

    # ── 读 ────────────────────────────────────────────────────────

    def list_sessions(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM commission_sessions "
                "ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for (raw,) in rows:
            try:
                d = json.loads(raw)
                items = [CommissionItem.from_dict(x) for x in d.get("items", [])]
                s = self._session_from(d, items)
                out.append(s.to_dict(with_items=False))
            except Exception:  # noqa: BLE001 — 单条损坏不影响列表
                continue
        return out

    def load(self, session_id: str) -> CommissionSession | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM commission_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        d = json.loads(row[0])
        items = [CommissionItem.from_dict(x) for x in d.get("items", [])]
        return self._session_from(d, items)

    @staticmethod
    def _session_from(d: dict, items: list[CommissionItem]) -> CommissionSession:
        return CommissionSession(
            id=d["id"],
            name=d.get("name", ""),
            created_at=d.get("created_at", 0.0),
            operator=d.get("operator", ""),
            status=SessionStatus(d.get("status", "idle")),
            items=items,
            point_table_snapshot=d.get("point_table_snapshot", []),
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
            cursor=d.get("cursor", 0),
            note=d.get("note", ""),
        )

    # ── 单条改判 ──────────────────────────────────────────────────

    def set_verdict(self, session_id: str, ioa: int, verdict: str,
                    note: str, operator: str) -> dict | None:
        """人工复核/改判；返回更新后的 item dict，找不到返回 None。"""
        s = self.load(session_id)
        if s is None:
            return None
        try:
            v = Verdict(verdict)
        except ValueError as exc:
            raise ValueError(f"invalid verdict: {verdict}") from exc
        for it in s.items:
            if it.ioa == ioa:
                it.verdict = v
                it.note = note or it.note
                it.operator = operator
                it.checked_at = time.time()
                self.save(s)
                return it.to_dict()
        return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM commission_sessions").fetchone()
        return {"sessions": row[0]}
