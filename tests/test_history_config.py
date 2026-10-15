"""历史库默认开启（T17）配置与清理策略测试.

覆盖:
- ``HistoryConfig`` 默认值 / YAML 装载 / save-load 往返
- ``resolve_history_path`` 路径解析
- 保留期（retention_days）与容量上限（max_size_mb）清理
- ``flush_interval`` 后台定时落盘（auto_flush）与 close() 不阻塞
- 缓冲区超限丢弃计数（防静默丢数据）

数据库一律落在 pytest ``tmp_path``；定时落盘用例使用极小间隔并轮询等待，
最长等待 2 秒。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import resolve_history_path
from core.config import AppConfig, HistoryConfig, load_config
from core.data.history import HistoryDB

TS = 1_700_000_000.0
DAY = 86400.0


# ── 配置 ─────────────────────────────────────────────────────────

class TestHistoryConfig:
    def test_defaults_enabled(self):
        cfg = HistoryConfig()
        assert cfg.enabled is True
        assert cfg.dir == ""
        assert cfg.retention_days == 7
        assert cfg.max_size_mb == 512
        assert cfg.flush_interval == 5.0

    def test_appconfig_has_history_enabled_by_default(self):
        assert AppConfig().history.enabled is True

    def test_load_from_yaml(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text(
            "history:\n"
            "  enabled: false\n"
            "  dir: /var/hist\n"
            "  retention_days: 30\n"
            "  max_size_mb: 1024\n"
            "  flush_interval: 1.5\n",
            encoding="utf-8",
        )
        h = load_config(p).history
        assert (h.enabled, h.dir, h.retention_days) == (False, "/var/hist", 30)
        assert (h.max_size_mb, h.flush_interval) == (1024, 1.5)

    def test_partial_yaml_keeps_defaults(self, tmp_path):
        p = tmp_path / "c.yaml"
        p.write_text("history:\n  retention_days: 1\n", encoding="utf-8")
        h = load_config(p).history
        assert h.retention_days == 1
        assert h.enabled is True and h.max_size_mb == 512

    def test_missing_file_and_missing_section_use_defaults(self, tmp_path):
        assert load_config(tmp_path / "nope.yaml").history.enabled is True
        p = tmp_path / "empty.yaml"
        p.write_text("mode: slave\n", encoding="utf-8")
        assert load_config(p).history == HistoryConfig()

    def test_save_load_roundtrip(self, tmp_path):
        cfg = AppConfig()
        cfg.history = HistoryConfig(enabled=False, dir="d", retention_days=3,
                                    max_size_mb=64, flush_interval=2.0)
        out = tmp_path / "saved.yaml"
        cfg.save(out)
        assert load_config(out).history == cfg.history


class TestResolveHistoryPath:
    def test_default_dir_when_empty(self):
        assert resolve_history_path("") == Path(__file__).parent.parent / "data" / "history.db"

    def test_cfg_dir_used(self):
        assert resolve_history_path("some/dir") == Path("some/dir") / "history.db"

    def test_override_wins(self):
        assert resolve_history_path("some/dir", "x/y.db") == Path("x/y.db")


# ── 清理策略 ─────────────────────────────────────────────────────

def _db(tmp_path, name="h.db", **kw) -> HistoryDB:
    db = HistoryDB(tmp_path / name, **kw)
    db.open()
    return db


class TestRetention:
    def test_old_rows_removed_recent_kept(self, tmp_path):
        db = _db(tmp_path, retention_days=7)
        now = time.time()
        db.record_data_change("yx", 1, True, timestamp=now - 10 * DAY)   # 过期
        db.record_data_change("yx", 2, True, timestamp=now - 1 * DAY)    # 保留
        db.record_frame("rx", b"\x01", timestamp=now - 30 * DAY)         # 过期
        db.flush()

        assert [r.ioa for r in db.query_data()] == [2]
        assert db.query_frames() == []
        db.close()

    def test_disabled_when_zero(self, tmp_path):
        db = _db(tmp_path, retention_days=0)
        db.record_data_change("yx", 1, True, timestamp=TS - 999 * DAY)
        db.flush()
        assert len(db.query_data()) == 1
        db.close()


class TestSizeCap:
    def test_tight_cap_keeps_db_smaller_than_unlimited(self, tmp_path):
        n = 6000

        unlimited = _db(tmp_path, name="a.db", max_records=0)
        for i in range(n):
            unlimited.record_data_change("yc", i, 1.5, timestamp=TS + i)
        unlimited.flush()
        size_a = unlimited._db_bytes()
        count_a = len(unlimited.query_data(limit=n + 1))
        unlimited.close()

        capped = _db(tmp_path, name="b.db", max_records=0,
                     max_size_mb=size_a / 2 / 1024 / 1024)
        for i in range(n):
            capped.record_data_change("yc", i, 1.5, timestamp=TS + i)
        capped.flush()
        size_b = capped._db_bytes()
        count_b = len(capped.query_data(limit=n + 1))
        capped.close()

        assert count_b < count_a, "容量上限应淘汰记录"
        assert size_b < size_a, "容量上限应使库小于无限制场景"

    def test_kept_rows_are_newest(self, tmp_path):
        n = 6000
        # 先用同一批数据量出"无上限"尺寸，再按其 60% 设定上限（避免依赖硬编码绝对值）
        pilot = _db(tmp_path, name="pilot.db", max_records=0)
        for i in range(n):
            pilot.record_data_change("yx", i, True, timestamp=TS + i)
        pilot.flush()
        pilot_size = pilot._db_bytes()
        pilot.close()

        db = _db(tmp_path, name="c.db", max_records=0,
                 max_size_mb=pilot_size * 0.6 / 1024 / 1024)
        for i in range(n):
            db.record_data_change("yx", i, True, timestamp=TS + i)
        db.flush()

        rows = db.query_data(limit=n + 1)
        assert 0 < len(rows) < n
        assert rows[0].ioa == n - 1          # 最新一条必保留（按时间倒序查询）
        db.close()


# ── 定时落盘 ─────────────────────────────────────────────────────

class TestAutoFlush:
    def test_no_thread_by_default(self, tmp_path):
        db = _db(tmp_path, name="d.db", flush_interval=5.0)
        assert db._flush_thread is None
        db.close()

    def test_auto_flush_persists_without_explicit_flush(self, tmp_path):
        db = _db(tmp_path, name="e.db", flush_interval=0.05, auto_flush=True)
        assert db._flush_thread is not None
        db.record_data_change("yx", 7, True, timestamp=TS)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not db.query_data():
            time.sleep(0.02)

        assert [r.ioa for r in db.query_data()] == [7]
        db.close()

    def test_close_stops_thread_promptly(self, tmp_path):
        db = _db(tmp_path, name="f.db", flush_interval=5.0, auto_flush=True)
        start = time.monotonic()
        db.close()
        assert time.monotonic() - start < 2.0
        assert db._flush_thread is None and db._running is False


# ── 缓冲区超限 ───────────────────────────────────────────────────

class TestBufferOverflow:
    def test_drops_oldest_and_counts(self, tmp_path):
        db = _db(tmp_path, name="g.db", buffer_size=3)
        for i in range(5):
            db.record_data_change("yx", i, True, timestamp=TS + i)

        assert len(db._write_buffer) == 3
        assert db.get_stats()["dropped_records"] == 2
        db.flush()
        assert [r.ioa for r in db.query_data()] == [4, 3, 2]    # 保留最新 3 条
        db.close()


class TestStatsExtras:
    def test_stats_expose_size_and_dropped(self, tmp_path):
        db = _db(tmp_path, name="h.db")
        db.record_data_change("yx", 1, True, timestamp=TS)
        db.flush()
        stats = db.get_stats()

        assert stats["dropped_records"] == 0
        assert stats["db_size_bytes"] > 0
        db.close()
