"""网络异常模拟 REST 接线测试（B6）.

覆盖：默认状态、预设/自定义条件、参数校验 400、安装到引擎后的 RX 统计、
手动断线与停用语义、统计重置。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app


class _FakeEngine:
    """最小引擎：仅提供代理安装所需的方法/回调."""

    def __init__(self):
        self._raw_callback = lambda *a, **k: None
        self.sent: list[bytes] = []
        self.received: list[bytes] = []

    def get_raw_frame_callback(self):
        return self._raw_callback

    def set_raw_frame_callback(self, callback):
        self._raw_callback = callback

    def _send_frame(self, frame: bytes) -> None:
        self.sent.append(frame)

    def _on_frame_received(self, frame: bytes, *args, **kwargs) -> None:
        self.received.append(frame)


@pytest.mark.asyncio
async def test_simulation_default_status():
    bridge = EngineBridge(role="master")
    async with TestClient(TestServer(create_app(bridge))) as client:
        r = await client.get("/api/simulation")
        body = await r.json()
        assert r.status == 200
        assert body["ok"] is True
        assert body["enabled"] is False
        assert body["installed"] is False
        assert body["active"] is False
        assert "poor_wifi" in body["presets"]
        assert body["condition"]["loss_rate"] == 0.0


@pytest.mark.asyncio
async def test_simulation_preset_and_validation():
    bridge = EngineBridge(role="master")
    async with TestClient(TestServer(create_app(bridge))) as client:
        # 预设（引擎未启动：enabled=true，但 installed=false）
        r = await client.post(
            "/api/simulation", json={"enabled": True, "preset": "poor_wifi"})
        body = await r.json()
        assert r.status == 200 and body["ok"] is True
        assert body["status"]["enabled"] is True
        assert body["status"]["installed"] is False
        assert body["status"]["condition"]["loss_rate"] == 0.05
        assert "loss=5%" in body["status"]["describe"]

        # 未知预设 → 400
        r = await client.post(
            "/api/simulation", json={"enabled": True, "preset": "bogus"})
        assert r.status == 400

        # 非法条件字段/取值 → 400
        for condition in (
            {"loss_rate": 2},
            {"delay_ms": -1},
            {"bogus_field": 1},
            {"direction": "up"},
            {"corrupt_bits": 0},
        ):
            r = await client.post(
                "/api/simulation", json={"enabled": True, "condition": condition})
            assert r.status == 400, f"{condition} 应 400"

        # enabled 非 bool → 400；非法 JSON → 400
        r = await client.post("/api/simulation", json={"enabled": "yes"})
        assert r.status == 400
        r = await client.post(
            "/api/simulation", data="not-json",
            headers={"Content-Type": "application/json"})
        assert r.status == 400


@pytest.mark.asyncio
async def test_simulation_install_and_stats():
    bridge = EngineBridge(role="master")
    fake = _FakeEngine()
    bridge.session.engine = fake
    async with TestClient(TestServer(create_app(bridge))) as client:
        # clean 预设：无丢包/损坏，确保通过代理的帧必然被转发
        r = await client.post(
            "/api/simulation", json={"enabled": True, "preset": "clean"})
        body = await r.json()
        assert body["status"]["installed"] is True
        assert body["status"]["active"] is True

        # 收帧经过代理包装 → rx_total 递增，且原回调仍被调用
        fake._on_frame_received(bytes.fromhex("680401000000"))
        assert fake.received == [bytes.fromhex("680401000000")]
        r = await client.get("/api/simulation")
        stats = (await r.json())["stats"]
        assert stats.get("rx_total", 0) >= 1

        # 手动断线：合法时长 OK，非法时长 400
        r = await client.post("/api/simulation/disconnect", json={"duration": 1})
        assert r.status == 200 and (await r.json())["ok"] is True
        r = await client.post("/api/simulation/disconnect", json={"duration": 0})
        assert r.status == 400

        # 统计重置
        r = await client.post("/api/simulation/reset")
        assert (await r.json())["ok"] is True
        r = await client.get("/api/simulation")
        assert (await r.json())["stats"].get("rx_total", 0) == 0

        # 停用：enabled/active=false，但代理保留安装（避免反复包装叠加）
        r = await client.post("/api/simulation", json={"enabled": False})
        status = (await r.json())["status"]
        assert status["enabled"] is False
        assert status["active"] is False
        assert status["installed"] is True


@pytest.mark.asyncio
async def test_disconnect_requires_engine():
    bridge = EngineBridge(role="master")
    async with TestClient(TestServer(create_app(bridge))) as client:
        r = await client.post("/api/simulation/disconnect", json={"duration": 1})
        assert r.status == 400
        body = await r.json()
        assert body["ok"] is False and "install" in body["error"]
