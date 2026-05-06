"""历史数据存储 — SQLite 持久化.

提供:
- 遥信/遥测变化记录
- SOE 事件记录
- 报文记录
- 历史查询与导出
"""

from __future__ import annotations

import sqlite3
import threading
import time
import json
import csv
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from collections import deque


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
    - 自动清理过期数据
    """

    def __init__(self, db_path: str | Path = ":memory:", max_records: int = 1000000):
        self._db_path = str(db_path)
        self._max_records = max_records
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._write_buffer: deque = deque(maxlen=1000)
        self._frame_buffer: deque = deque(maxlen=1000)
        self._flush_interval = 5.0  # 批量提交间隔
        self._running = False

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

    def close(self) -> None:
        """关闭数据库."""
        self._running = False
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
        self._write_buffer.append((ts, point_type, ioa, str(value), quality, source))

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
        self._frame_buffer.append((ts, direction, frame_type, hex_data, parsed, client_id))

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
                print(f"History flush error: {e}")

    def _cleanup(self) -> None:
        """清理过期数据."""
        try:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM data_history"
            ).fetchone()[0]

            if count > self._max_records:
                excess = count - self._max_records
                self._conn.execute(
                    "DELETE FROM data_history WHERE id IN "
                    "(SELECT id FROM data_history ORDER BY id ASC LIMIT ?)",
                    (excess,),
                )

            count = self._conn.execute(
                "SELECT COUNT(*) FROM frame_history"
            ).fetchone()[0]

            if count > self._max_records:
                excess = count - self._max_records
                self._conn.execute(
                    "DELETE FROM frame_history WHERE id IN "
                    "(SELECT id FROM frame_history ORDER BY id ASC LIMIT ?)",
                    (excess,),
                )

        except Exception:
            pass

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

    def export_data_csv(
        self,
        path: str | Path,
        point_type: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
    ) -> int:
        """导出数据历史到 CSV."""
        records = self.query_data(
            point_type=point_type,
            start_time=start_time,
            end_time=end_time,
            limit=1000000,
        )

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["时间戳", "类型", "IOA", "值", "品质", "来源"])
            for r in records:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp)),
                    r.point_type, r.ioa, r.value, r.quality, r.source,
                ])

        return len(records)

    def export_frames_csv(
        self,
        path: str | Path,
        direction: str = "",
        start_time: float = 0.0,
        end_time: float = 0.0,
    ) -> int:
        """导出报文历史到 CSV."""
        records = self.query_frames(
            direction=direction,
            start_time=start_time,
            end_time=end_time,
            limit=1000000,
        )

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["时间戳", "方向", "帧类型", "HEX数据", "解析", "客户端"])
            for r in records:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp)),
                    r.direction, r.frame_type, r.hex_data, r.parsed, r.client_id,
                ])

        return len(records)

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
