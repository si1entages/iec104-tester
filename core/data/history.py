"""历史数据存储 — SQLite 持久化.

提供:
- 遥信/遥测变化记录
- SOE 事件记录
- 报文记录
- 历史查询与导出
"""

from __future__ import annotations

import csv
import logging
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("iec104.history")


@dataclass
class HistoryRecord:
    """历史记录."""
    id: int = 0
    timestamp: float = 0.0
    point_type: str = ""        # yx/yc/ym
    ioa: int = 0
    value: str = ""
    quality: str = ""
    source: str = ""            # spont/gi/periodic


@dataclass
class FrameRecord:
    """报文记录."""
    id: int = 0
    timestamp: float = 0.0
    direction: str = ""         # rx/tx
    frame_type: str = ""        # I/S/U
    hex_data: str = ""
    parsed: str = ""
    client_id: str = ""


class HistoryDB:
    """历史数据库 — SQLite 实现.

    线程安全，支持:
    - 高频写入（批量提交优化）
    - 按时间/IOA/类型查询
    - CSV 导出
    - 自动清理过期数据（记录数 / 保留期 / 容量上限）

    清理策略（三者可独立开关，互不干扰）:
    - ``max_records``: 每张表最多保留的记录条数（默认 100 万）。
    - ``retention_days``: 删除早于 ``now - retention_days*86400`` 的记录；``<=0`` 关闭。
    - ``max_size_mb``: 库文件超过该容量后按最旧优先淘汰；``<=0`` 关闭。

    ``flush_interval`` 配合 ``auto_flush=True`` 时，由后台线程周期刷盘；
    默认 ``auto_flush=False``，保持"仅显式 ``flush()`` 落盘"的既有语义。

    ``buffer_size`` 为单个缓冲区容量上限。历史库默认开启后，写入速率可能
    远高于刷盘频率（如繁忙链路上的报文记录），缓冲区过小会**静默丢记录**；
    故上限提升至 5 万并按水位告警，同时仍保留上限以约束内存
    （最坏约 ``2 × buffer_size`` 条记录，量级 ~50 MB）。
    """

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        max_records: int = 1000000,
        retention_days: int = 0,
        max_size_mb: float = 0,
        flush_interval: float = 0.0,
        auto_flush: bool = False,
        buffer_size: int = 50000,
    ):
        self._db_path = str(db_path)
        self._max_records = max_records
        self._retention_days = retention_days
        self._max_size_mb = max_size_mb
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._write_buffer: deque = deque(maxlen=buffer_size)
        self._frame_buffer: deque = deque(maxlen=buffer_size)
        self._flush_interval = flush_interval if flush_interval > 0 else 5.0
        self._auto_flush = bool(auto_flush) and flush_interval > 0
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._dropped_records = 0
        self._running = False

    def _buffer_append(self, buf: deque, item: tuple) -> None:
        """写入缓冲区；超限时丢弃最旧记录并周期性告警（避免静默丢数据）."""
        maxlen = buf.maxlen
        if maxlen is not None and len(buf) >= maxlen:
            self._dropped_records += 1
            if self._dropped_records == 1 or self._dropped_records % 10000 == 0:
                logger.warning(
                    f"History buffer full (maxlen={maxlen}), dropping oldest "
                    f"records (total dropped: {self._dropped_records}); "
                    f"请调小 flush_interval 或降低记录频率"
                )
        buf.append(item)

    def open(self) -> None:
        """打开数据库."""
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()
        self._running = True
        self._stop_event.clear()        # 支持 close() 后重新 open()
        if self._auto_flush:
            self._start_auto_flush()

    def _start_auto_flush(self) -> None:
        """启动后台定时刷盘线程（守护线程，随进程退出）."""
        self._flush_thread = threading.Thread(
            target=self._auto_flush_loop,
            name="history-auto-flush",
            daemon=True,
        )
        self._flush_thread.start()

    def _auto_flush_loop(self) -> None:
        """周期刷盘循环；``close()`` 触发 ``_stop_event`` 后立即退出（不阻塞关闭）."""
        while not self._stop_event.wait(self._flush_interval):
            if not self._running:
                break
            self.flush()

    def close(self) -> None:
        """关闭数据库（先停止后台刷盘线程，再落盘并关闭连接）."""
        self._running = False
        self._stop_event.set()
        thread = self._flush_thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._flush_thread = None
        self.flush()
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_tables(self) -> None:
        """创建表结构."""
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS data_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    point_type TEXT NOT NULL,
                    ioa INTEGER NOT NULL,
                    value TEXT,
                    quality TEXT,
                    source TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_data_ts
                    ON data_history(timestamp);
                CREATE INDEX IF NOT EXISTS idx_data_ioa
                    ON data_history(point_type, ioa);
                CREATE INDEX IF NOT EXISTS idx_data_type
                    ON data_history(point_type);

                CREATE TABLE IF NOT EXISTS frame_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    direction TEXT NOT NULL,
                    frame_type TEXT,
                    hex_data TEXT,
                    parsed TEXT,
                    client_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_frame_ts
                    ON frame_history(timestamp);
                CREATE INDEX IF NOT EXISTS idx_frame_dir
                    ON frame_history(direction);
            """)

    # ── 数据写入 ──────────────────────────────────────────────────

    def record_data_change(
        self,
        point_type: str,
        ioa: int,
        value,
        quality: str = "",
        source: str = "spont",
        timestamp: float = 0.0,
    ) -> None:
        """记录数据变化."""
        ts = timestamp or time.time()
        self._buffer_append(
            self._write_buffer, (ts, point_type, ioa, str(value), quality, source)
        )

    def record_frame(
        self,
        direction: str,
        data: bytes,
        frame_type: str = "",
        parsed: str = "",
        client_id: str = "",
        timestamp: float = 0.0,
    ) -> None:
        """记录报文."""
        ts = timestamp or time.time()
        hex_data = data.hex().upper() if isinstance(data, bytes) else str(data)
        self._buffer_append(
            self._frame_buffer, (ts, direction, frame_type, hex_data, parsed, client_id)
        )

    def flush(self) -> None:
        """批量提交缓冲区."""
        if not self._conn:
            return

        with self._lock:
            try:
                if self._write_buffer:
                    self._conn.executemany(
                        "INSERT INTO data_history "
                        "(timestamp, point_type, ioa, value, quality, source) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        list(self._write_buffer),
                    )
                    self._write_buffer.clear()

                if self._frame_buffer:
                    self._conn.executemany(
                        "INSERT INTO frame_history "
                        "(timestamp, direction, frame_type, hex_data, parsed, client_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        list(self._frame_buffer),
                    )
                    self._frame_buffer.clear()

                self._conn.commit()

                # 自动清理
                self._cleanup()

            except Exception as e:
                logger.error(f"History flush error: {e}")

    def _db_bytes(self) -> int:
        """库文件逻辑占用（排除 freelist 空洞），单位字节；``:memory:`` 返回 0.

        删除行后 SQLite 不会立刻缩小文件，而是把页标记为空闲（freelist）。
        故以 ``(page_count - freelist_count) * page_size`` 衡量"实际数据占用"，
        使容量清理循环必然收敛；清理结束后再用 ``wal_checkpoint(TRUNCATE)``
        把 WAL 收口，磁盘占用随之回落。
        """
        if self._db_path == ":memory:" or self._conn is None:
            return 0
        try:
            page_size = self._conn.execute("PRAGMA page_size").fetchone()[0]
            page_count = self._conn.execute("PRAGMA page_count").fetchone()[0]
            freelist = self._conn.execute("PRAGMA freelist_count").fetchone()[0]
        except (sqlite3.Error, TypeError, AttributeError):
            return 0
        return max(0, int(page_count) - int(freelist)) * int(page_size)

    def _delete_oldest(self, table: str, limit: int) -> int:
        """删除 ``table`` 中最旧的 ``limit`` 行，返回实际删除行数."""
        cur = self._conn.execute(
            f"DELETE FROM {table} WHERE id IN "
            f"(SELECT id FROM {table} ORDER BY id ASC LIMIT ?)",
            (int(limit),),
        )
        return getattr(cur, "rowcount", 0) or 0

    def _trim_table(self, table: str) -> int:
        """对单表依次执行 保留期 → 记录数 → 容量上限 清理，返回删除行数.

        三条策略相互独立，各自未启用时跳过；任何一步都不向调用方抛异常
        （``_cleanup`` 统一兜底）。
        """
        deleted = 0

        # 1) 保留期：删除早于 cutoff 的记录
        if self._retention_days > 0:
            cutoff = time.time() - self._retention_days * 86400
            cur = self._conn.execute(
                f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,)
            )
            deleted += getattr(cur, "rowcount", 0) or 0

        # 2) 记录数上限：超出则淘汰最旧
        if self._max_records > 0:
            count = self._conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            if count > self._max_records:
                deleted += self._delete_oldest(table, count - self._max_records)

        # 3) 容量上限：按最旧优先分批淘汰，直到低于上限或表已空
        if self._max_size_mb > 0:
            limit = int(self._max_size_mb * 1024 * 1024)
            for _ in range(1000):        # 硬性迭代上限，杜绝病态循环
                if self._db_bytes() <= limit:
                    break
                count = self._conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                if count <= 0:
                    break
                chunk = max(1000, count // 100)
                removed = self._delete_oldest(table, chunk)
                if removed <= 0:
                    break
                deleted += removed
                self._conn.commit()

        # 有删除则落盘并把 WAL 收口，使磁盘占用真正回落
        if deleted:
            self._conn.commit()
            if self._max_size_mb > 0:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error as e:      # pragma: no cover - 并发读者占用时
                    logger.debug(f"wal_checkpoint skipped: {e}")

        return deleted

    def _cleanup(self) -> None:
        """清理过期数据（记录数 / 保留期 / 容量上限）."""
        try:
            self._trim_table("data_history")
            self._trim_table("frame_history")
        except Exception as e:
            logger.warning(f"History cleanup error: {e}")

    # ── 数据查询 ──────────────────────────────────────────────────

    def query_data(
        self,
        point_type: str = "",
        ioa: int = -1,
        start_time: float = 0.0,
        end_time: float = 0.0,
        limit: int = 1000,
    ) -> list[HistoryRecord]:
        """查询数据历史."""
        if not self._conn:
            return []

        conditions = []
        params = []

        if point_type:
            conditions.append("point_type = ?")
            params.append(point_type)

        if ioa >= 0:
            conditions.append("ioa = ?")
            params.append(ioa)

        if start_time > 0:
            conditions.append("timestamp >= ?")
            params.append(start_time)

        if end_time > 0:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT id, timestamp, point_type, ioa, value, quality, source FROM data_history {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        return [
            HistoryRecord(
                id=r[0], timestamp=r[1], point_type=r[2],
                ioa=r[3], value=r[4], quality=r[5], source=r[6],
            )
            for r in rows
        ]

    def query_frames(
        self,
        direction: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
        limit: int = 1000,
    ) -> list[FrameRecord]:
        """查询报文历史."""
        if not self._conn:
            return []

        conditions = []
        params = []

        if direction:
            conditions.append("direction = ?")
            params.append(direction)

        if start_time > 0:
            conditions.append("timestamp >= ?")
            params.append(start_time)

        if end_time > 0:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"SELECT id, timestamp, direction, frame_type, hex_data, parsed, client_id FROM frame_history {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        return [
            FrameRecord(
                id=r[0], timestamp=r[1], direction=r[2],
                frame_type=r[3], hex_data=r[4], parsed=r[5], client_id=r[6],
            )
            for r in rows
        ]

    # ── 导出 ──────────────────────────────────────────────────────

    def _iter_history_rows(self, sql: str, params: list, batch_size: int = 5000):
        """分批游标读取（每批短暂持锁），避免大结果集一次性载入内存."""
        if not self._conn:
            return
        with self._lock:
            cur = self._conn.execute(sql, params)
        try:
            while True:
                with self._lock:
                    rows = cur.fetchmany(batch_size)
                if not rows:
                    return
                yield from rows
        finally:
            cur.close()

    def export_data_csv(
        self,
        path: str | Path,
        point_type: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
        limit: int = 1_000_000,
    ) -> int:
        """导出数据历史到 CSV（流式分批读取，防 OOM）."""
        conditions = ["1=1"]
        params: list = []
        if point_type:
            conditions.append("point_type = ?")
            params.append(point_type)
        if start_time > 0:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time > 0:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        where = "WHERE " + " AND ".join(conditions)
        sql = (
            "SELECT timestamp, point_type, ioa, value, quality, source "
            f"FROM data_history {where} ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        count = 0
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["时间戳", "类型", "IOA", "值", "品质", "来源"])
            for r in self._iter_history_rows(sql, params):
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r[0])),
                    r[1], r[2], r[3], r[4], r[5],
                ])
                count += 1
        return count

    def export_frames_csv(
        self,
        path: str | Path,
        direction: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
        limit: int = 1_000_000,
    ) -> int:
        """导出报文历史到 CSV（流式分批读取，防 OOM）."""
        conditions = ["1=1"]
        params: list = []
        if direction:
            conditions.append("direction = ?")
            params.append(direction)
        if start_time > 0:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time > 0:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        where = "WHERE " + " AND ".join(conditions)
        sql = (
            "SELECT timestamp, direction, frame_type, hex_data, parsed, client_id "
            f"FROM frame_history {where} ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)

        count = 0
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["时间戳", "方向", "帧类型", "HEX数据", "解析", "客户端"])
            for r in self._iter_history_rows(sql, params):
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r[0])),
                    r[1], r[2], r[3], r[4], r[5],
                ])
                count += 1
        return count

    # ── 统计 ──────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取数据库统计."""
        if not self._conn:
            return {}

        with self._lock:
            data_count = self._conn.execute(
                "SELECT COUNT(*) FROM data_history"
            ).fetchone()[0]
            frame_count = self._conn.execute(
                "SELECT COUNT(*) FROM frame_history"
            ).fetchone()[0]

            # 获取时间范围
            data_range = self._conn.execute(
                "SELECT MIN(timestamp), MAX(timestamp) FROM data_history"
            ).fetchone()

        return {
            "data_records": data_count,
            "frame_records": frame_count,
            "buffered_data": len(self._write_buffer),
            "buffered_frames": len(self._frame_buffer),
            "oldest_data": data_range[0] if data_range and data_range[0] else 0,
            "newest_data": data_range[1] if data_range and data_range[1] else 0,
            "db_size_bytes": self._db_bytes(),
            "dropped_records": self._dropped_records,
        }

    def clear(self) -> None:
        """清空所有历史数据."""
        with self._lock:
            if self._conn:
                self._conn.execute("DELETE FROM data_history")
                self._conn.execute("DELETE FROM frame_history")
                self._conn.commit()
            self._write_buffer.clear()
            self._frame_buffer.clear()
