"""冗余双通道 Web 接线（E3）：启动参数校验、会话配置、状态快照."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from core.config import AppConfig
from webui.bridge import EngineBridge
from webui.server import create_app
from webui.session import EngineSession


@pytest_asyncio.fixture
async def master_client():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    client = TestClient(TestServer(create_app(bridge)))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("redundancy", [
    "x",
    {"enabled": 1},
    {"standby_host": ""},
    {"standby_port": 0},
    {"standby_port": True},
    {"switch_timeout": 0},
    {"switch_timeout": "x"},
    {"dedup_window": -1},
])
async def test_invalid_redundancy_returns_400(master_client, redundancy):
    client, _ = master_client
    r = await client.post("/api/master/start", json={
        "host": "127.0.0.1", "port": 2404, "redundancy": redundancy,
    })
    assert r.status == 400


@pytest.mark.asyncio
async def test_redundancy_passed_to_bridge(master_client):
    client, bridge = master_client
    bridge.start_master = AsyncMock(return_value={"ok": True})
    cfg = {
        "enabled": True,
        "standby_host": "127.0.0.1",
        "standby_port": 2405,
        "switch_timeout": 3.0,
        "dedup_window": 5.0,
    }
    r = await client.post("/api/master/start", json={
        "host": "127.0.0.1", "port": 2404, "redundancy": cfg,
    })
    assert (await r.json())["ok"] is True
    bridge.start_master.assert_awaited_once_with(
        "127.0.0.1", 2404, 1, True, 0.0, tls=None, redundancy=cfg)


class _FakeMaster:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_running = False

    def set_event_callback(self, cb):
        pass

    def set_raw_frame_callback(self, cb):
        pass

    async def start(self):
        self.is_running = True


@pytest.mark.asyncio
async def test_session_builds_redundancy_config(monkeypatch):
    import webui.session as session_mod

    monkeypatch.setattr(session_mod, "MasterEngine", _FakeMaster)
    s = EngineSession("master", AppConfig(), lambda *a: None, lambda *a: None)
    r = await s.start_master(
        "127.0.0.1", 2404, 1, True, None,
        redundancy={"enabled": True, "standby_host": "127.0.0.1", "standby_port": 2405},
    )
    assert r["ok"] is True
    red = s.engine.kwargs["redundancy"]
    assert red.enabled is True
    assert red.standby_host == "127.0.0.1"
    assert red.standby_port == 2405


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg", [
    {"enabled": True, "standby_host": "", "standby_port": 2405},
    {"enabled": True, "standby_host": "127.0.0.1", "standby_port": 0},
    {"enabled": True, "standby_host": "127.0.0.1", "standby_port": 2404},
])
async def test_session_rejects_invalid_redundancy(monkeypatch, cfg):
    import webui.session as session_mod

    monkeypatch.setattr(session_mod, "MasterEngine", _FakeMaster)
    s = EngineSession("master", AppConfig(), lambda *a: None, lambda *a: None)
    r = await s.start_master("127.0.0.1", 2404, 1, True, None, redundancy=cfg)
    assert r["ok"] is False
    assert "冗余配置无效" in r["error"]


def test_status_includes_redundancy_snapshot():
    s = EngineSession("master", AppConfig(), lambda *a: None, lambda *a: None)
    status = {
        "enabled": True, "active": "standby", "primary_connected": False,
        "standby_connected": True, "standby_host": "10.0.0.2",
        "standby_port": 2405, "switch_timeout": 2.0, "dedup_window": 5.0,
        "failovers": 1,
    }
    s.engine = SimpleNamespace(
        state="running", is_running=True, connection_stats=None,
        sequence_manager=None, redundancy_status=lambda: status,
    )
    assert s.status_fields()["redundancy"] == status


def test_status_redundancy_config_fallback():
    cfg = AppConfig()
    cfg.redundancy.enabled = True
    cfg.redundancy.standby_host = "10.0.0.9"
    cfg.redundancy.standby_port = 2406
    s = EngineSession("master", cfg, lambda *a: None, lambda *a: None)
    s.engine = SimpleNamespace(
        state="connecting", is_running=False, connection_stats=None,
        sequence_manager=None, redundancy_status=lambda: None,
    )
    red = s.status_fields()["redundancy"]
    assert red["enabled"] is True
    assert red["standby_host"] == "10.0.0.9"
    assert red["standby_port"] == 2406
