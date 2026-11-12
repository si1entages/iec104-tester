"""SQLite 连接初始化（P1 收口：修复多进程 WAL 竞争）.

CI 的 ``e2e-full-flow`` 会同时起 master(8765) 与 slave(8766) 两个进程，
两者都打开 ``data/commissioning.db`` / ``data/audit.db``。SQLite 切换
``journal_mode=WAL`` 需要短暂独占锁；若另一进程正持有连接，会直接抛
``sqlite3.OperationalError: database is locked``（2026-11-12 CI run
43203899666 的 slave.log 实证）。

WAL 只是性能优化，不是正确性前提：先设 busy_timeout，再尝试 WAL，
竞争时保持库当前的 journal 模式继续工作即可。这样既不影响单进程行为，
也不用改库文件名（避免升级后旧会话/审计链丢失）。
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger("iec104.data")


def open_sqlite(db_path: str, *, detect_types: bool = False) -> sqlite3.Connection:
    """打开 SQLite 连接并尽力启用 WAL；竞争时安全降级。"""
    conn = sqlite3.connect(
        db_path,
        check_same_thread=False,
        **({"detect_types": sqlite3.PARSE_DECLTYPES} if detect_types else {}),
    )
    # busy_timeout 必须先设：后续 WAL 切换与建表都可能遇到跨进程锁。
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as e:
        # 另一进程正在切换/持有 WAL 锁：保持默认 journal 模式，功能不受影响。
        logger.warning("SQLite %s 启用 WAL 失败（%s），保持当前 journal 模式继续",
                       db_path, e)
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
