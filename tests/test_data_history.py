"""`core/data/history.py` 历史库（SQLite）单元测试.

覆盖建表/开关库、变化数据与报文记录的缓冲与批量提交、按类型/IOA/时间范围/条数
查询、CSV 流式导出、自动清理超额记录、统计与清空。

数据库落在 pytest ``tmp_path``（或 ``:memory:``），不使用真实网络/端口；
无任何 sleep 或真实等待。
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.data.history import FrameRecord, HistoryDB, HistoryRecord

TS = 1_700_000_000.0


def _db(tmp_path, **kwargs) -> HistoryDB:
    db = HistoryDB(tmp_path / "history.db", **kwargs)
    db.open()
    return db


# ── 建库 / 关闭 ──────────────────────────────────────────────────

def test_open_creates_tables_and_sets_running(tmp_path):
    db = _db(tmp_path)

    assert db._running is True
    names = {
        row[0] for row in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"data_history", "frame_history"} <= names


def test_close_flushes_and_is_idempotent(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yx", 1, True, timestamp=TS)

    db.close()
    assert db._running is False
    assert db._conn is None
    assert len(db._write_buffer) == 0        # close 前已刷盘

    db.close()                               # 二次 close 安全


def test_close_without_open_is_safe():
    db = HistoryDB(":memory:")
    db.close()                               # 从未 open → flush 提前返回
    assert db._conn is None


def test_records_persist_across_reopen(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yc", 300, 220.5, timestamp=TS)
    db.close()

    db2 = HistoryDB(tmp_path / "history.db")
    db2.open()
    rows = db2.query_data()
    db2.close()

    assert len(rows) == 1
    assert rows[0].ioa == 300
    assert rows[0].value == "220.5"


# ── 数据写入与查询 ───────────────────────────────────────────────

def test_record_data_change_buffers_with_stringified_value(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yx", 100, True, quality="GOOD", source="spont",
                          timestamp=TS)

    assert len(db._write_buffer) == 1
    buffered = db._write_buffer[0]
    assert buffered == (TS, "yx", 100, "True", "GOOD", "spont")
    assert db.query_data() == []             # 尚未刷盘


def test_record_data_change_auto_timestamp_when_zero(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yx", 1, False)    # 不传 timestamp

    ts = db._write_buffer[0][0]
    assert ts > 0


def test_flush_inserts_and_clears_buffer(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yx", 100, True, quality="GOOD", timestamp=TS)
    db.record_data_change("yc", 200, 1.5, timestamp=TS + 1)
    db.flush()

    assert len(db._write_buffer) == 0
    rows = db.query_data()
    assert {r.ioa for r in rows} == {100, 200}
    assert all(isinstance(r, HistoryRecord) for r in rows)


def test_query_data_filters_and_orders(tmp_path):
    db = _db(tmp_path)
    for ioa, ts in ((1, TS), (2, TS + 10), (3, TS + 20)):
        db.record_data_change("yx", ioa, True, timestamp=ts)
    db.record_data_change("yc", 9, 1.0, timestamp=TS + 30)
    db.flush()

    assert [r.ioa for r in db.query_data(point_type="yx")] == [3, 2, 1]   # 时间倒序
    assert [r.ioa for r in db.query_data(ioa=2)] == [2]
    assert [r.ioa for r in db.query_data(start_time=TS + 5, end_time=TS + 25)] == [3, 2]
    assert len(db.query_data(limit=1)) == 1
    assert db.query_data(ioa=999) == []


def test_query_data_without_connection_returns_empty():
    db = HistoryDB(":memory:")
    assert db.query_data() == []


def test_record_frame_hex_and_str(tmp_path):
    db = _db(tmp_path)
    db.record_frame("rx", b"\x68\x04\x0b\x00\x00\x00", frame_type="U",
                    client_id="c1", timestamp=TS)
    db.record_frame("tx", "plain-text", timestamp=TS + 1)
    db.flush()

    rows = db.query_frames()
    by_dir = {r.direction: r for r in rows}
    assert by_dir["rx"].hex_data == "68040B000000"
    assert by_dir["rx"].frame_type == "U"
    assert by_dir["rx"].client_id == "c1"
    assert by_dir["tx"].hex_data == "plain-text"


def test_query_frames_filters_and_limit(tmp_path):
    db = _db(tmp_path)
    db.record_frame("rx", b"\x01", timestamp=TS)
    db.record_frame("tx", b"\x02", timestamp=TS + 5)
    db.record_frame("rx", b"\x03", timestamp=TS + 10)
    db.flush()

    assert len(db.query_frames(direction="rx")) == 2
    assert len(db.query_frames(start_time=TS + 4)) == 2
    assert len(db.query_frames(end_time=TS + 6)) == 2
    assert len(db.query_frames(limit=1)) == 1
    assert all(isinstance(r, FrameRecord) for r in db.query_frames())


def test_query_frames_without_connection_returns_empty():
    db = HistoryDB(":memory:")
    assert db.query_frames() == []


def test_flush_without_connection_keeps_buffers():
    db = HistoryDB(":memory:")
    db.record_data_change("yx", 1, True, timestamp=TS)
    db.flush()                               # _conn 为 None → 提前返回

    assert len(db._write_buffer) == 1


def test_flush_only_frames_or_only_data(tmp_path):
    db = _db(tmp_path)
    db.record_frame("rx", b"\x01", timestamp=TS)
    db.flush()
    assert len(db.query_frames()) == 1
    assert db.query_data() == []

    db.record_data_change("yx", 1, True, timestamp=TS)
    db.flush()
    assert len(db.query_data()) == 1


class _FailingConn:
    """sqlite3.Connection 替身：按需让指定方法抛错.

    sqlite3.Connection 是 C 扩展类型、其方法属性只读，无法用 monkeypatch 直接替换，
    故整体替换 ``db._conn``。
    """

    def __init__(self, fail_on: str):
        self.fail_on = fail_on

    def execute(self, *_args, **_kwargs):
        if self.fail_on == "execute":
            raise sqlite3.OperationalError("connection broken")
        return SimpleNamespace(fetchone=lambda: (0,), fetchmany=lambda _n: [])

    def executemany(self, *_args, **_kwargs):
        if self.fail_on == "executemany":
            raise sqlite3.OperationalError("db broken")
        return None

    def commit(self):
        return None

    def close(self):
        return None


def test_flush_error_is_logged_not_raised(tmp_path):
    """刷盘异常（如连接失效）只记日志，不向调用方抛出."""
    db = _db(tmp_path)
    db.record_data_change("yx", 1, True, timestamp=TS)
    db._conn = _FailingConn("executemany")

    db.flush()                               # 不应抛出

    assert len(db._write_buffer) == 1        # 未提交成功 → 缓冲保留


# ── 自动清理 ─────────────────────────────────────────────────────

def test_cleanup_trims_excess_data_records(tmp_path):
    db = _db(tmp_path, max_records=2)
    for ioa in range(5):
        db.record_data_change("yx", ioa, True, timestamp=TS + ioa)
    db.flush()

    rows = db.query_data()
    assert len(rows) == 2
    assert {r.ioa for r in rows} == {3, 4}   # 保留最新的两条


def test_cleanup_trims_excess_frame_records(tmp_path):
    db = _db(tmp_path, max_records=1)
    for i in range(3):
        db.record_frame("rx", bytes([i]), timestamp=TS + i)
    db.flush()

    rows = db.query_frames()
    assert len(rows) == 1
    assert rows[0].hex_data == "02"          # 保留最新


def test_cleanup_error_is_logged_not_raised(tmp_path):
    db = _db(tmp_path, max_records=0)
    db._conn = _FailingConn("execute")

    db._cleanup()                            # 不应抛出


# ── CSV 导出 ─────────────────────────────────────────────────────

def test_export_data_csv_writes_header_and_rows(tmp_path):
    db = _db(tmp_path)
    for ioa in (1, 2, 3):
        db.record_data_change("yx", ioa, True, quality="GOOD", source="spont",
                              timestamp=TS + ioa)
    db.flush()

    out = tmp_path / "data.csv"
    count = db.export_data_csv(out, point_type="yx")

    assert count == 3
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["时间戳", "类型", "IOA", "值", "品质", "来源"]
    assert len(rows) == 4
    assert {r[2] for r in rows[1:]} == {"1", "2", "3"}


def test_export_data_csv_applies_time_filters(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yc", 1, 1.0, timestamp=TS)
    db.record_data_change("yc", 2, 2.0, timestamp=TS + 100)
    db.flush()

    out = tmp_path / "filtered.csv"
    count = db.export_data_csv(out, start_time=TS + 50, end_time=TS + 200)

    assert count == 1
    assert "2" in out.read_text(encoding="utf-8")


def test_export_frames_csv_writes_header_and_rows(tmp_path):
    db = _db(tmp_path)
    db.record_frame("rx", b"\x68\x04", frame_type="U", parsed="STARTDT",
                    client_id="c1", timestamp=TS)
    db.record_frame("tx", b"\x68\x04", frame_type="U", timestamp=TS + 1)
    db.flush()

    out = tmp_path / "frames.csv"
    count = db.export_frames_csv(out, direction="rx", start_time=TS - 1, end_time=TS + 100)

    assert count == 1
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["时间戳", "方向", "帧类型", "HEX数据", "解析", "客户端"]
    assert rows[1][1] == "rx"
    assert rows[1][2] == "U"


def test_export_data_without_connection_produces_empty_csv(tmp_path):
    """未打开数据库：导出得到仅表头的空 CSV，计数为 0（不抛异常）."""
    db = HistoryDB(":memory:")
    out = tmp_path / "empty.csv"

    assert db.export_data_csv(out) == 0
    assert "时间戳" in out.read_text(encoding="utf-8")


def test_iter_history_rows_batches_and_closes_cursor(tmp_path):
    """分批游标：跨多批产出全部行，_conn 为 None 时为空迭代."""
    db = _db(tmp_path)
    for ioa in range(5):
        db.record_data_change("yx", ioa, True, timestamp=TS + ioa)
    db.flush()

    sql = ("SELECT timestamp, point_type, ioa, value, quality, source "
           "FROM data_history ORDER BY id ASC")
    rows = list(db._iter_history_rows(sql, [], batch_size=2))
    assert len(rows) == 5

    empty = HistoryDB(":memory:")
    assert list(empty._iter_history_rows(sql, [])) == []


# ── 统计与清空 ───────────────────────────────────────────────────

def test_get_stats_counts_and_buffers(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yx", 1, True, timestamp=TS)
    db.record_data_change("yx", 2, True, timestamp=TS + 10)
    db.record_frame("rx", b"\x01", timestamp=TS)
    db.flush()

    db.record_data_change("yc", 3, 1.0, timestamp=TS + 20)   # 留在缓冲
    stats = db.get_stats()

    assert stats["data_records"] == 2
    assert stats["frame_records"] == 1
    assert stats["buffered_data"] == 1
    assert stats["buffered_frames"] == 0
    assert stats["oldest_data"] == pytest.approx(TS)
    assert stats["newest_data"] == pytest.approx(TS + 10)


def test_get_stats_without_connection_returns_empty():
    assert HistoryDB(":memory:").get_stats() == {}


def test_get_stats_on_empty_tables_reports_zero_range(tmp_path):
    db = _db(tmp_path)
    stats = db.get_stats()

    assert stats["data_records"] == 0
    assert stats["oldest_data"] == 0
    assert stats["newest_data"] == 0


def test_clear_empties_tables_and_buffers(tmp_path):
    db = _db(tmp_path)
    db.record_data_change("yx", 1, True, timestamp=TS)
    db.record_frame("rx", b"\x01", timestamp=TS)
    db.flush()
    db.record_data_change("yx", 2, True, timestamp=TS + 1)   # 未刷盘的缓冲

    db.clear()

    assert db.query_data() == []
    assert db.query_frames() == []
    assert len(db._write_buffer) == 0
    assert len(db._frame_buffer) == 0


def test_clear_without_connection_only_clears_buffers():
    db = HistoryDB(":memory:")
    db.record_data_change("yx", 1, True, timestamp=TS)

    db.clear()

    assert len(db._write_buffer) == 0
