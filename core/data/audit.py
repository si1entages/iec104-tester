"""操作审计流水（WP4）：本地哈希链防篡改存储.

与 commissioning.db 同理独立于历史库：审计记录**低频、长期留存、
不可被自动清理、不可被静默改写**，单独建库 ``data/audit.db``。

防篡改：每条记录 ``hash = SHA256(prev_hash || canonical_json)``，
首条 ``prev_hash`` 为全零 genesis；任何一条被删/改都会让
:meth:`AuditStore.verify` 报出断点 id。哈希只防**事后篡改与删改顺序**，
不防「整链重算」——攻击者若能改库就能重算整链；本地威胁模型的边界
是「操作人无数据库写权限 / 篡改可被发现」，与外部 SIEM 的差异已在
optimization_plan_v111.md §WP4 候选对比中说明（现场离线环境不适用）。

连接参数沿用 HistoryDB / CommissionStore 的 WAL + busy_timeout +
``check_same_thread=False`` 组合；同步方法由调用方在 asyncio handler
里用 ``asyncio.to_thread`` 包装，不阻塞事件循环。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# 首条记录的 prev_hash（genesis）
GENESIS_HASH = "0" * 64

# 单条帧证据最长保留的 hex 字符数（256 B 足够任何单帧；控制行宽）
_MAX_FRAME_HEX = 512


def canonical_record(
    ts: float,
    operator: str,
    role: str,
    source_ip: str,
    action: str,
    target: str,
    result: str,
    reason: str,
    tx_frame: str,
    rx_frame: str,
) -> str:
    """参与哈希的规范化 JSON（sort_keys + 紧凑分隔符，跨平台稳定）."""
    obj = {
        "ts": round(float(ts), 6),
        "operator": operator,
        "role": role,
        "source_ip": source_ip,
        "action": action,
        "target": target,
        "result": result,
        "reason": reason,
        "tx_frame": tx_frame[:_MAX_FRAME_HEX],
        "rx_frame": rx_frame[:_MAX_FRAME_HEX],
    }
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def chain_hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


@dataclass
class AuditRecord:
    """单条审计记录（``id/prev_hash/hash`` 由存储层落库时填充）."""

    ts: float
    operator: str = ""
    role: str = ""
    source_ip: str = ""
    action: str = ""
    target: str = ""
    result: str = ""  # ok | fail
    reason: str = ""
    tx_frame: str = ""
    rx_frame: str = ""
    id: int | None = None
    prev_hash: str = ""
    hash: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {
            "ts": self.ts,
            "operator": self.operator,
            "role": self.role,
            "source_ip": self.source_ip,
            "action": self.action,
            "target": self.target,
            "result": self.result,
            "reason": self.reason,
            "tx_frame": self.tx_frame,
            "rx_frame": self.rx_frame,
        }
        if self.id is not None:
            d["id"] = self.id
        if self.hash:
            d["prev_hash"] = self.prev_hash
            d["hash"] = self.hash
        if self.extra:
            d["extra"] = self.extra
        return d


class AuditStore:
    """审计流水的 SQLite 存储：锁内串行追加 + 全链校验."""

    def __init__(self, db_path: str | Path = "data/audit.db"):
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        # RLock：append 取链尾 + INSERT 必须原子；verify 全表读也要持锁
        self._lock = threading.RLock()
        self._tail_hash: str = GENESIS_HASH

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
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS audit_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    operator TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    source_ip TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    target TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    tx_frame TEXT NOT NULL DEFAULT '',
                    rx_frame TEXT NOT NULL DEFAULT '',
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_records(ts DESC);
            """)
            self._conn.commit()
            row = self._conn.execute(
                "SELECT hash FROM audit_records ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self._tail_hash = row[0] if row else GENESIS_HASH

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    # ── 追加 / 查询 ───────────────────────────────────────────────

    def append(self, record: AuditRecord) -> AuditRecord:
        """追加一条记录：锁内取链尾算哈希并落库，返回带 id/hash 的记录."""
        with self._lock:
            conn = self.conn
            canonical = canonical_record(
                record.ts, record.operator, record.role, record.source_ip,
                record.action, record.target, record.result, record.reason,
                record.tx_frame, record.rx_frame,
            )
            prev = self._tail_hash
            h = chain_hash(prev, canonical)
            cur = conn.execute(
                """
                INSERT INTO audit_records
                    (ts, operator, role, source_ip, action, target,
                     result, reason, tx_frame, rx_frame, prev_hash, hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    round(record.ts, 6), record.operator, record.role,
                    record.source_ip, record.action, record.target,
                    record.result, record.reason,
                    record.tx_frame[:_MAX_FRAME_HEX],
                    record.rx_frame[:_MAX_FRAME_HEX],
                    prev, h,
                ),
            )
            conn.commit()
            self._tail_hash = h
            record.id = int(cur.lastrowid)
            record.prev_hash = prev
            record.hash = h
            # 与库里一致：返回前回写截断后的帧证据
            record.tx_frame = record.tx_frame[:_MAX_FRAME_HEX]
            record.rx_frame = record.rx_frame[:_MAX_FRAME_HEX]
            return record

    def list_records(
        self,
        limit: int = 200,
        operator: str | None = None,
        action: str | None = None,
        result: str | None = None,
        since: float | None = None,
    ) -> list[AuditRecord]:
        """按时间倒序列出记录（过滤条件可选；均不参与哈希）."""
        sql = (
            "SELECT id, ts, operator, role, source_ip, action, target, "
            "result, reason, tx_frame, rx_frame, prev_hash, hash "
            "FROM audit_records WHERE 1=1"
        )
        params: list[object] = []
        if operator:
            sql += " AND operator = ?"
            params.append(operator)
        if action:
            sql += " AND action = ?"
            params.append(action)
        if result:
            sql += " AND result = ?"
            params.append(result)
        if since is not None:
            sql += " AND ts >= ?"
            params.append(since)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to(r) for r in rows]

    def stats(self) -> dict:
        with self._lock:
            conn = self.conn
            total = int(conn.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0])
            operators = int(
                conn.execute(
                    "SELECT COUNT(DISTINCT operator) FROM audit_records "
                    "WHERE operator != ''"
                ).fetchone()[0]
            )
            row = conn.execute(
                "SELECT ts FROM audit_records ORDER BY id DESC LIMIT 1"
            ).fetchone()
            fails = int(
                conn.execute(
                    "SELECT COUNT(*) FROM audit_records WHERE result = 'fail'"
                ).fetchone()[0]
            )
        return {
            "total": total,
            "operators": operators,
            "fails": fails,
            "last_ts": row[0] if row else None,
        }

    def verify(self) -> dict:
        """全链校验：重算每条哈希并检查 prev_hash 链接，报出首个断点."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, ts, operator, role, source_ip, action, target, "
                "result, reason, tx_frame, rx_frame, prev_hash, hash "
                "FROM audit_records ORDER BY id ASC"
            ).fetchall()
        prev = GENESIS_HASH
        for r in rows:
            rid, ts, operator, role, ip, action, target, result, reason, tx, rx, p_hash, h_hash = r
            if p_hash != prev:
                return {
                    "ok": False,
                    "valid": False,
                    "total": len(rows),
                    "broken_at": rid,
                    "reason": f"chain_break: id={rid} prev_hash 不接上一条",
                }
            canonical = canonical_record(
                ts, operator, role, ip, action, target, result, reason, tx, rx,
            )
            if chain_hash(prev, canonical) != h_hash:
                return {
                    "ok": False,
                    "valid": False,
                    "total": len(rows),
                    "broken_at": rid,
                    "reason": f"hash_mismatch: id={rid} 内容与哈希不符（被篡改）",
                }
            prev = h_hash
        return {"ok": True, "valid": True, "total": len(rows), "broken_at": None, "reason": ""}

    # ── 内部 ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to(r: tuple) -> AuditRecord:
        return AuditRecord(
            id=int(r[0]), ts=float(r[1]), operator=r[2], role=r[3],
            source_ip=r[4], action=r[5], target=r[6], result=r[7],
            reason=r[8], tx_frame=r[9], rx_frame=r[10],
            prev_hash=r[11], hash=r[12],
        )


def now_ts() -> float:
    return time.time()
