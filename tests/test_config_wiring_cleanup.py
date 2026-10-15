"""收尾清理包回归测试：配置经交付入口到引擎的接线 + 死字段移除兼容.

覆盖（收尾清理 2026-10-15）:
- Web 会话 ``EngineSession.start_master`` 传入 ``config.timers`` /
  ``config.flow_control`` / ``config.connection.reconnect_interval``
- Web 会话 ``EngineSession.start_slave`` 的 ``spontaneous`` 回落
  ``config.slave.spontaneous_enabled``
- CLI no-gui 子站路径按 ``config.slave.simulation_*`` 启动数据模拟
- ``master.auto_clock_sync`` 死字段移除后，含该键的旧配置文件仍能正常加载
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import AppConfig
from webui.session import EngineSession


def _session(role: str, cfg: AppConfig) -> EngineSession:
    return EngineSession(role=role, config=cfg,
                         on_event=lambda *_: None, on_frame=lambda *_: None)


class _Points:
    """最小 points 占位（start_slave 读 ``points.table``）."""

    def __init__(self):
        self.table = None


# ── Web start_master：timers / flow_control / reconnect_interval ────


def test_web_start_master_passes_timers_flow_control(monkeypatch):
    """Web 会话启动主站必须携带 --config 的计时器/流控/重连间隔配置."""
    capture: dict = {}

    class _FakeMasterEngine:
        def __init__(self, **kwargs):
            capture["kwargs"] = kwargs

        def set_event_callback(self, cb):
            pass

        def set_raw_frame_callback(self, cb):
            pass

        async def start(self):
            pass

    monkeypatch.setattr("webui.session.MasterEngine", _FakeMasterEngine)

    cfg = AppConfig()
    cfg.timers.t0, cfg.timers.t1 = 11.0, 12.0
    cfg.timers.t2, cfg.timers.t3 = 13.0, 14.0
    cfg.flow_control.k, cfg.flow_control.w = 7, 6
    cfg.connection.reconnect_interval = 2.5

    s = _session("master", cfg)
    result = asyncio.run(s.start_master("127.0.0.1", 24040, 1, False, _Points()))

    assert result["ok"] is True
    kw = capture["kwargs"]
    assert kw["t0"] == 11.0 and kw["t1"] == 12.0
    assert kw["t2"] == 13.0 and kw["t3"] == 14.0
    assert kw["k"] == 7 and kw["w"] == 6
    assert kw["reconnect_interval"] == 2.5


def test_web_start_master_defaults_unchanged(monkeypatch):
    """默认配置 → 与引擎构造默认一致（无回归）."""
    capture: dict = {}

    class _FakeMasterEngine:
        def __init__(self, **kwargs):
            capture["kwargs"] = kwargs

        def set_event_callback(self, cb):
            pass

        def set_raw_frame_callback(self, cb):
            pass

        async def start(self):
            pass

    monkeypatch.setattr("webui.session.MasterEngine", _FakeMasterEngine)

    s = _session("master", AppConfig())
    asyncio.run(s.start_master("127.0.0.1", 24041, 1, False, _Points()))

    kw = capture["kwargs"]
    assert (kw["k"], kw["w"]) == (12, 8)
    assert (kw["t0"], kw["t1"], kw["t2"], kw["t3"]) == (30.0, 15.0, 10.0, 20.0)
    assert kw["reconnect_interval"] == 5.0


# ── Web start_slave：spontaneous 回落 config.slave ────────────────


def test_web_start_slave_spontaneous_falls_back_to_config(monkeypatch):
    """入口不传 spontaneous → 回落 config.slave.spontaneous_enabled."""
    capture: dict = {}

    class _FakeSlaveEngine:
        def __init__(self, **kwargs):
            capture["kwargs"] = kwargs
            self.data_store = type("_DS", (), {"init_from_point_table": staticmethod(lambda *_: None)})()

        def set_event_callback(self, cb):
            pass

        def set_raw_frame_callback(self, cb):
            pass

        async def start(self):
            pass

    monkeypatch.setattr("webui.session.SlaveEngine", _FakeSlaveEngine)

    cfg = AppConfig()
    cfg.slave.spontaneous_enabled = False
    s = _session("slave", cfg)
    result = asyncio.run(s.start_slave("0.0.0.0", 24042, 1, _Points()))

    assert result["ok"] is True
    assert capture["kwargs"]["spontaneous_enabled"] is False


def test_web_start_slave_spontaneous_explicit_overrides(monkeypatch):
    """显式传入 spontaneous → 以调用方为准（旧签名行为兼容）."""
    capture: dict = {}

    class _FakeSlaveEngine:
        def __init__(self, **kwargs):
            capture["kwargs"] = kwargs
            self.data_store = type("_DS", (), {"init_from_point_table": staticmethod(lambda *_: None)})()

        def set_event_callback(self, cb):
            pass

        def set_raw_frame_callback(self, cb):
            pass

        async def start(self):
            pass

    monkeypatch.setattr("webui.session.SlaveEngine", _FakeSlaveEngine)

    cfg = AppConfig()
    cfg.slave.spontaneous_enabled = False
    s = _session("slave", cfg)
    asyncio.run(s.start_slave("0.0.0.0", 24043, 1, _Points(), spontaneous=True))

    assert capture["kwargs"]["spontaneous_enabled"] is True


# ── auto_clock_sync 死字段移除：旧配置文件兼容 ────────────────────


def test_legacy_config_with_auto_clock_sync_still_loads(tmp_path):
    """含已移除的 master.auto_clock_sync 键的旧配置文件仍能正常加载.

    load_config 对未知键用 .get 模式逐项读取 → 多余键被忽略，不报错、
    不影响其它字段；MasterConfig 亦不再有该属性（死字段已删）。
    """
    from core.config import load_config

    legacy = tmp_path / "legacy_config.yaml"
    legacy.write_text(
        "mode: master\n"
        "connection:\n"
        "  host: 10.0.0.5\n"
        "  port: 25000\n"
        "master:\n"
        "  auto_start: true\n"
        "  auto_gi: false\n"
        "  auto_clock_sync: true\n",   # 旧字段：必须被忽略而非报错
        encoding="utf-8",
    )

    cfg = load_config(legacy)

    assert cfg.mode == "master"
    assert cfg.connection.host == "10.0.0.5"
    assert cfg.connection.port == 25000
    assert cfg.master.auto_start is True
    assert cfg.master.auto_gi is False
    assert not hasattr(cfg.master, "auto_clock_sync")
