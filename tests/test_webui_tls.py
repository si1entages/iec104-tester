"""Web UI 单站模式 TLS 接线测试（T20 技术债收口）.

覆盖:
- POST /api/slave/start、/api/master/start 携带可选 ``tls`` 字段 → 引擎
  传输层 ``tls_enabled`` 为真（与多站 ``StationConfig.tls`` 同一形态）
- 未传 ``tls`` → 行为与之前完全一致（明文）
- 证书路径无效 → 业务失败（``ok=False``），不静默降级为明文
- Web UI 全链路 E2E：TLS 子站 + TLS 主站握手成功进入 Running
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app

CERTS = Path(__file__).parent / "certs"
CA1 = str(CERTS / "ca1.pem")
SERVER_CRT = str(CERTS / "server.pem")
SERVER_KEY = str(CERTS / "server.key")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


class TestSingleStationTlsStart:
    @pytest.mark.asyncio
    async def test_slave_start_with_tls_enables_tls(self):
        port = _free_port()
        bridge = EngineBridge(role="slave")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/slave/start", json={
                    "host": "127.0.0.1", "port": port,
                    "tls": {"enabled": True,
                            "certfile": SERVER_CRT, "keyfile": SERVER_KEY},
                })
                assert (await r.json())["ok"] is True
                assert bridge.engine is not None
                assert bridge.engine._server.tls_enabled is True
                await c.post("/api/slave/stop")
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_master_start_with_tls_enables_tls(self):
        port = _free_port()  # 不真实监听也可验证注入
        bridge = EngineBridge(role="master")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/master/start", json={
                    "host": "127.0.0.1", "port": port,
                    "tls": {"enabled": True, "cafile": CA1,
                            "server_hostname": "localhost"},
                })
                assert (await r.json())["ok"] is True
                assert bridge.engine is not None
                assert bridge.engine._client.tls_enabled is True
                await c.post("/api/master/stop")
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_start_without_tls_unchanged(self):
        """未传 tls → 行为与之前完全一致（明文）。"""
        port = _free_port()
        bridge = EngineBridge(role="slave")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/slave/start",
                                 json={"host": "127.0.0.1", "port": port})
                assert (await r.json())["ok"] is True
                assert bridge.engine is not None
                assert bridge.engine._server.tls_enabled is False
                await c.post("/api/slave/stop")
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_invalid_tls_cert_path_fails(self):
        """证书路径不存在 → ok=False 且错误信息可读，不静默降级。"""
        port = _free_port()
        bridge = EngineBridge(role="slave")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/slave/start", json={
                    "host": "127.0.0.1", "port": port,
                    "tls": {"enabled": True,
                            "certfile": str(CERTS / "nope.pem"),
                            "keyfile": SERVER_KEY},
                })
                data = await r.json()
                assert data["ok"] is False
                assert "TLS" in data.get("error", "")
                assert bridge.engine is None  # 未产生半启动引擎
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_tls_must_be_object(self):
        bridge = EngineBridge(role="slave")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/slave/start",
                                 json={"tls": "enabled"})
                assert r.status == 400
                r = await c.post("/api/master/start",
                                 json={"tls": [1, 2]})
                assert r.status == 400
        finally:
            await bridge.shutdown()


class TestSingleStationTlsEndToEnd:
    @pytest.mark.asyncio
    async def test_webui_tls_master_slave_handshake(self):
        """全链路：两个 Web 会话分别以 TLS 启动子站/主站，握手进入 Running。"""
        port = _free_port()
        slave_bridge = EngineBridge(role="slave")
        slave_bridge.ensure_demo_points()
        master_bridge = EngineBridge(role="master")
        master_bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(slave_bridge))) as cs, \
                    TestClient(TestServer(create_app(master_bridge))) as cm:
                r = await cs.post("/api/slave/start", json={
                    "host": "127.0.0.1", "port": port,
                    "tls": {"enabled": True,
                            "certfile": SERVER_CRT, "keyfile": SERVER_KEY},
                })
                assert (await r.json())["ok"] is True

                r = await cm.post("/api/master/start", json={
                    "host": "127.0.0.1", "port": port,
                    "tls": {"enabled": True, "cafile": CA1,
                            "server_hostname": "localhost"},
                })
                assert (await r.json())["ok"] is True

                assert await _wait_until(
                    lambda: master_bridge.engine is not None
                    and master_bridge.engine.is_running), \
                    "Web UI 单站 TLS 下主站未进入 Running"

                await cm.post("/api/master/stop")
                await cs.post("/api/slave/stop")
        finally:
            await master_bridge.shutdown()
            await slave_bridge.shutdown()
