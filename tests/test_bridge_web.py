"""桥角色 Web 端点测试（T74）.

覆盖：status 默认形状、启停往返、帧流（echo 上游回环 → 双向观察）、
引擎专属路由在桥应用上不可达（404）、schema roles 上报。
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app

STARTDT_ACT = bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00])
STARTDT_CON = bytes([0x68, 0x04, 0x0B, 0x00, 0x00, 0x00])


async def _echo_server():
    """回环上游：收到的字节原样回发（帧透传回环校验用）."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


@pytest_asyncio.fixture
async def bridge_client():
    bridge = EngineBridge("bridge")
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
async def test_bridge_status_defaults(bridge_client):
    client, _ = bridge_client
    r = await client.get("/api/status")
    body = await r.json()
    assert body["role"] == "bridge"
    assert body["running"] is False and body["started"] is False
    assert "bridge_stats" not in body
    # schema 上报 bridge 角色
    schema = await (await client.get("/api/schema")).json()
    assert schema["roles"] == ["bridge"]


@pytest.mark.asyncio
async def test_bridge_start_stop_and_frame_flow(bridge_client):
    """启停往返 + echo 上游回环：STARTDT 透传、双向帧进观察总线."""
    client, bridge = bridge_client
    echo = await _echo_server()
    upstream_port = echo.sockets[0].getsockname()[1]
    try:
        r = await client.post("/api/bridge/start", json={
            "listen_host": "127.0.0.1", "listen_port": 0,
            "upstream_host": "127.0.0.1", "upstream_port": upstream_port,
        })
        body = await r.json()
        assert body["ok"] is True, body

        st = await (await client.get("/api/status")).json()
        assert st["running"] is True and st["started"] is True
        assert st["bridge_cfg"]["upstream_port"] == upstream_port
        assert st["bridge_stats"]["clients_total"] == 0

        # 客户端 → 桥 → echo 上游 → 桥 → 客户端：STARTDT_ACT 回环成 STARTDT_ACT
        port = bridge.tcp_bridge.listen_port
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(STARTDT_ACT)
        await writer.drain()
        data = await asyncio.wait_for(reader.readexactly(len(STARTDT_ACT)), timeout=5.0)
        assert data == STARTDT_ACT
        writer.close()

        # 帧进了观察总线（_on_raw_frame → bus.publish("frame")）
        for _ in range(50):
            if bridge.recent("frame"):
                break
            await asyncio.sleep(0.05)
        frames = bridge.recent("frame")
        assert frames, "桥应观察到双向帧"
        assert {f["data"]["direction"] for f in frames} == {"tx", "rx"}
        assert frames[0]["data"]["client"].startswith("c")

        # stats 经节流后的 status 可见
        st = await (await client.get("/api/status")).json()
        assert st["bridge_stats"]["frames_dn"] >= 1
        assert st["bridge_stats"]["frames_up"] >= 1

        # 停止
        r = await client.post("/api/bridge/stop")
        assert (await r.json())["ok"] is True
        st = await (await client.get("/api/status")).json()
        assert st["running"] is False and "bridge_stats" not in st
    finally:
        echo.close()
        await echo.wait_closed()


@pytest.mark.asyncio
async def test_bridge_engine_routes_are_absent(bridge_client):
    """桥应用不注册引擎专属路由（404 而非 500）——纵深防御."""
    client, _ = bridge_client
    for path in ("/api/master/start", "/api/slave/start",
                 "/api/points/batch", "/api/points/import", "/api/slave/sim"):
        r = await client.post(path, data="{}")
        assert r.status == 404, f"{path} 应为 404"


@pytest.mark.asyncio
async def test_bridge_start_twice_and_bad_port(bridge_client):
    client, bridge = bridge_client
    echo = await _echo_server()
    upstream_port = echo.sockets[0].getsockname()[1]
    try:
        r = await client.post("/api/bridge/start", json={
            "listen_port": 0, "upstream_port": upstream_port})
        assert (await r.json())["ok"] is True
        # 重复启动 → 明确错误（不破坏现有桥）
        r2 = await client.post("/api/bridge/start", json={"listen_port": 0})
        body2 = await r2.json()
        assert body2["ok"] is False and "already running" in body2["error"]
        assert bridge.tcp_bridge is not None  # 原桥未被破坏
        # 非法端口 → 400
        r3 = await client.post("/api/bridge/start", json={"listen_port": 99999})
        assert r3.status == 400
    finally:
        echo.close()
        await echo.wait_closed()


@pytest.mark.asyncio
async def test_bridge_endpoints_on_master_role_rejected():
    """桥端点在所有应用上注册（契约单一表），非桥角色业务拒绝（200 + ok:false）."""
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        r = await client.post("/api/bridge/start", json={"listen_port": 0})
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is False and "bridge" in body["error"]
        r2 = await client.post("/api/bridge/stop")
        assert r2.status == 200 and (await r2.json())["ok"] is False
    finally:
        await bridge.shutdown()
        await client.close()


@pytest.mark.asyncio
async def test_bridge_condition_endpoint(bridge_client):
    """条件端点：设置后 status 可见描述/统计字段；非桥角色业务拒绝."""
    client, bridge = bridge_client
    echo = await _echo_server()
    upstream_port = echo.sockets[0].getsockname()[1]
    try:
        await client.post("/api/bridge/start", json={
            "listen_port": 0, "upstream_port": upstream_port})
        r = await client.post("/api/bridge/condition", json={"loss_rate": 0.5})
        assert (await r.json())["ok"] is True
        st = await (await client.get("/api/status")).json()
        assert "loss" in st["condition"] and st["condition_active"] is True
        assert "total" in st["injection"]
        # 清空条件
        r2 = await client.post("/api/bridge/condition", json={})
        assert (await r2.json())["active"] is False
    finally:
        echo.close()
        await echo.wait_closed()


@pytest.mark.asyncio
async def test_bridge_condition_role_guard():
    """非 bridge 角色调用条件端点 → 200 + ok:false（业务拒绝，巡检不计 4xx）."""
    from webui.bridge import EngineBridge
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        r = await client.post("/api/bridge/condition", json={"loss_rate": 1.0})
        assert r.status == 200 and (await r.json())["ok"] is False
    finally:
        await bridge.shutdown()
        await client.close()
