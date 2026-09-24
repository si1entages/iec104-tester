"""Web UI / EngineBridge 自动化测试."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app


@pytest_asyncio.fixture
async def slave_client():
    bridge = EngineBridge("slave")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest_asyncio.fixture
async def master_client():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
async def test_static_and_status(slave_client):
    client, bridge = slave_client
    r = await client.get("/")
    assert r.status == 200
    html = await r.text()
    assert "IEC104" in html
    r = await client.get("/static/css/app.css")
    assert r.status == 200
    r = await client.get("/static/js/app.js")
    assert r.status == 200
    r = await client.get("/api/status")
    st = await r.json()
    assert st["role"] == "slave"
    assert st["running"] is False
    assert st["points"] > 0
    assert "dropped" in st


@pytest.mark.asyncio
async def test_points_schema(slave_client):
    client, _ = slave_client
    r = await client.get("/api/points")
    pts = (await r.json())["points"]
    assert pts
    assert {"ioa", "type", "name", "group", "enabled", "value"} <= set(pts[0].keys())
    types = {p["type"] for p in pts}
    assert types >= {"YX", "YC"}


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_slave_lifecycle_yx_yc_response(slave_client):
    client, bridge = slave_client
    port = _free_port()
    r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"] is True
    assert bridge.engine is not None

    r = await client.post("/api/slave/yx", json={"ioa": 1, "value": True})
    assert (await r.json())["ok"] is True
    assert bridge.engine.data_store.get_yx(1).value is True

    pts = (await (await client.get("/api/points")).json())["points"]
    yc_ioa = next(p["ioa"] for p in pts if p["type"] == "YC")
    r = await client.post("/api/slave/yc", json={"ioa": yc_ioa, "value": 3.25})
    body = await r.json()
    assert body["ok"] is True
    d = bridge.engine.data_store.get_yc(yc_ioa)
    assert d is not None and abs(float(d.value) - 3.25) < 1e-6

    r = await client.post("/api/slave/response", json={
        "delays": {"gi": 0.5, "command": 0},
        "errors": {"drop_frames": True, "drop_rate": 0.2, "no_response": False},
    })
    assert (await r.json())["ok"] is True
    assert bridge.engine.response_behavior.gi_delay == 0.5
    assert bridge.engine.response_behavior.drop_frames is True

    r = await client.post("/api/slave/stop")
    assert (await r.json())["ok"] is True
    assert bridge.engine is None


@pytest.mark.asyncio
async def test_master_api_error_paths(master_client):
    client, bridge = master_client
    # 未连接时命令应失败但 ok=false
    r = await client.post("/api/master/gi")
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/clock")
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/ci")
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/yk", json={"ioa": 1, "state": 1})
    assert (await r.json())["ok"] is False


@pytest.mark.asyncio
async def test_master_start_stop_against_slave(slave_client, master_client):
    sc, sbridge = slave_client
    mc, mbridge = master_client
    port = _free_port()
    r = await sc.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"]
    assert sbridge.engine is not None and sbridge.engine.is_running
    try:
        r = await mc.post("/api/master/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
        assert (await r.json())["ok"] is True
        # 等待进入 Running（TCP 握手 + STARTDT）
        for _ in range(80):
            await asyncio.sleep(0.05)
            if mbridge.engine and mbridge.engine.is_running:
                break
        assert mbridge.engine and mbridge.engine.is_running
        r = await mc.post("/api/master/gi")
        assert (await r.json())["ok"] is True
        await asyncio.sleep(0.3)
        r = await mc.post("/api/master/clock")
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/ci")
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/stop")
        assert (await r.json())["ok"] is True
    finally:
        await sc.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_points_batch(slave_client):
    client, bridge = slave_client
    pts = (await (await client.get("/api/points")).json())["points"]
    yx = [p["ioa"] for p in pts if p["type"] == "YX"][:3]
    r = await client.post("/api/points/batch", json={
        "type": "YX", "ioas": yx, "action": "group", "group": 7,
    })
    body = await r.json()
    assert body["ok"] is True
    assert body["changed"] == len(yx)
    for p in bridge.point_table.get_all_yx():
        if p.ioa in set(yx):
            assert p.group == 7

    r = await client.post("/api/points/batch", json={
        "type": "YX", "ioas": yx, "action": "disable",
    })
    assert (await r.json())["ok"] is True
    for p in bridge.point_table.get_all_yx():
        if p.ioa in set(yx):
            assert p.enabled is False

    r = await client.post("/api/points/batch", json={
        "type": "YX", "ioas": yx, "action": "enable",
    })
    body = await r.json()
    assert body["ok"] is True
    assert body["changed"] == len(yx)
    for p in bridge.point_table.get_all_yx():
        if p.ioa in set(yx):
            assert p.enabled is True

    # 非法 action / 缺 group 应失败
    r = await client.post("/api/points/batch", json={"type": "YX", "ioas": yx, "action": "nope"})
    assert (await r.json())["ok"] is False
    r = await client.post("/api/points/batch", json={"type": "YX", "ioas": yx, "action": "group"})
    assert (await r.json())["ok"] is False


@pytest.mark.asyncio
async def test_pending_response_applied_on_start(slave_client):
    client, bridge = slave_client
    r = await client.post("/api/slave/response", json={"delays": {"gi": 1.25, "command": 0}})
    assert (await r.json())["ok"] is True
    port = _free_port()
    r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"] is True
    assert bridge.engine.response_behavior.gi_delay == 1.25
    await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_sim_enable_on_slave(slave_client):
    client, bridge = slave_client
    port = _free_port()
    await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    r = await client.post("/api/slave/sim", json={"enabled": True, "yx_interval": 1.0})
    assert (await r.json())["ok"] is True
    assert bridge.status().get("simulation") is True
    r = await client.post("/api/slave/sim", json={"enabled": False})
    assert (await r.json())["ok"] is True
    await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_publish_queue_backpressure_dropped(slave_client):
    _, bridge = slave_client
    q = bridge.subscribe()
    try:
        # 塞满队列后 publish 应计 dropped 且不抛异常
        for i in range(q.maxsize + 5):
            bridge._publish("event", {"type": "ui", "data": {"i": i}})
        assert bridge.status()["dropped"] > 0
    finally:
        bridge.unsubscribe(q)


@pytest.mark.asyncio
async def test_ws_snapshot(slave_client):
    client, bridge = slave_client
    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["kind"] == "snapshot"
        assert "points" in msg["data"] and "status" in msg["data"]
        assert msg["data"]["status"]["role"] == "slave"


@pytest.mark.asyncio
async def test_sim_toggle_requires_listen(master_client):
    client, bridge = master_client
    # 主站角色不可设模拟
    r = await client.post("/api/slave/sim", json={"enabled": True})
    body = await r.json()
    assert body["ok"] is False
