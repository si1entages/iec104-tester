"""D4 回归测试：``config.redundancy`` 必须经交付入口真实传入 MasterEngine.

覆盖（QA 互调报告 2026-10-15 §C8/D4）:
- CLI no-gui 入口：``_run_cli`` 构造 MasterEngine 时传入 ``redundancy=config.redundancy``
- Web 会话入口：``EngineSession.start_master`` 传入 ``redundancy=self.config.redundancy``
- ``enabled=True`` → 引擎实际创建 ``MasterRedundancy``（主/备双通道）；
  ``enabled=False``（默认）→ 单通道，行为与改动前一致

引擎层冗余切换行为（0.50s 切换、STARTDT+GI 重建、VS/VR 归零、不抢占）已由
QA ``test_reports/partc_c8_redundancy.py`` 程序化实测通过，本文件只验证
「配置经交付入口到引擎」的接线不再断裂。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import app as app_module
from core.config import AppConfig
from webui.bridge import EngineBridge


def _master_config(redundancy_enabled: bool) -> AppConfig:
    cfg = AppConfig()
    cfg.connection.reconnect = False
    cfg.redundancy.enabled = redundancy_enabled
    cfg.redundancy.standby_port = 24050
    return cfg


# ── CLI no-gui 入口 ──────────────────────────────────────────────


def test_run_cli_passes_redundancy_to_master_engine(monkeypatch):
    """_run_cli 构造 MasterEngine 必须携带 redundancy=config.redundancy."""
    capture: dict = {}

    class _FakeMasterEngine:
        def __init__(self, **kwargs):
            capture["kwargs"] = kwargs

        def set_event_callback(self, cb):
            pass

        def set_raw_frame_callback(self, cb):
            pass

        async def start(self):
            # 启动即取消：跳出 _run_cli 的常驻循环，足以完成构造参数断言
            raise asyncio.CancelledError

        async def stop(self):
            pass

    import core.engine.master as master_mod

    monkeypatch.setattr(master_mod, "MasterEngine", _FakeMasterEngine)

    cfg = _master_config(redundancy_enabled=True)
    with pytest.raises(asyncio.CancelledError):
        app_module._run_cli(cfg, None, None, logging.getLogger("test"))

    assert capture["kwargs"]["redundancy"] is cfg.redundancy
    assert capture["kwargs"]["redundancy"].enabled is True


def test_run_cli_redundancy_disabled_unchanged(monkeypatch):
    """默认（未启用冗余）→ 仍传入配置对象，由引擎按 enabled=False 走单通道."""
    capture: dict = {}

    class _FakeMasterEngine:
        def __init__(self, **kwargs):
            capture["kwargs"] = kwargs

        def set_event_callback(self, cb):
            pass

        def set_raw_frame_callback(self, cb):
            pass

        async def start(self):
            raise asyncio.CancelledError

        async def stop(self):
            pass

    import core.engine.master as master_mod

    monkeypatch.setattr(master_mod, "MasterEngine", _FakeMasterEngine)

    cfg = _master_config(redundancy_enabled=False)
    with pytest.raises(asyncio.CancelledError):
        app_module._run_cli(cfg, None, None, logging.getLogger("test"))

    assert capture["kwargs"]["redundancy"].enabled is False


# ── Web 会话入口 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_web_session_start_master_creates_redundant_engine():
    """经 Web 会话（HTTP 启动路径同款代码）启用冗余 → 引擎持有双通道管理器."""
    bridge = EngineBridge(role="master", app_config=_master_config(True))
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 24051, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        assert bridge.engine is not None
        assert bridge.engine._redundancy is not None
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_web_session_without_redundancy_stays_single_channel():
    """默认配置 → 单通道（_redundancy 为 None），与改动前行为一致."""
    bridge = EngineBridge(role="master", app_config=_master_config(False))
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 24052, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        assert bridge.engine is not None
        assert bridge.engine._redundancy is None
    finally:
        await bridge.shutdown()
