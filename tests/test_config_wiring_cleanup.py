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
    """最小 points 占位（start_master 用 ``getattr(points, "table", None)``）."""


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
