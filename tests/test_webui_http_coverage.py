"""WebUI HTTP 处理函数覆盖率补齐（D1）.

目标是把 ``webui/server.py`` 从 70% 提升到可设门禁的水平：
- 所有 POST 端点的非法 JSON / 非法字段分支（400）；
- 合法请求的成功分支（用 AsyncMock 替换会话方法，不启动真实引擎）；
- 点表导入的 csv/yaml/json 嗅探与异常分支；
- 静态资源、favicon、SPA 回落、WS 快照/刷新、历史查询参数校验。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app

# 会解析 JSON body 的端点（非法 JSON 一律 400）
_JSON_ENDPOINTS = [
    "/api/master/start",
    "/api/master/yk",
    "/api/master/step",
    "/api/master/bitstring",
    "/api/master/delay",
    "/api/master/setpoint",
    "/api/master/read",
    "/api/master/param",
    "/api/master/file",
    "/api/points/batch",
    "/api/slave/response",
    "/api/slave/ym",
    "/api/slave/ep",
    "/api/slave/ps",
    "/api/slave/sim",
    "/api/slave/start",
    "/api/slave/yx",
    "/api/slave/yc",
    "/api/slave/step",
    "/api/multi/start",
    "/api/simulation",
]


@pytest_asyncio.fixture
async def master_client():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    client = TestClient(TestServer(create_app(bridge)))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest_asyncio.fixture
async def slave_client():
    bridge = EngineBridge("slave")
    bridge.ensure_demo_points()
    client = TestClient(TestServer(create_app(bridge)))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


# ── 非法 JSON / 非法字段 ─────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", _JSON_ENDPOINTS)
async def test_invalid_json_returns_400(master_client, path):
    client, _ = master_client
    r = await client.post(path, data=b"{not json",
                          headers={"Content-Type": "application/json"})
    assert r.status == 400, path
    assert (await r.json())["error"] == "invalid JSON"


_INVALID_FIELDS = [
    ("/api/master/start", {"host": 1}),
    ("/api/master/start", {"port": "x"}),
    ("/api/master/start", {"addr": -1}),
    ("/api/master/start", {"gi_interval": -1}),
    ("/api/master/start", {"tls": 1}),
    ("/api/master/yk", {"ioa": -1}),
    ("/api/master/yk", {"ioa": 1, "deactivate": "x"}),
    ("/api/master/step", {"ioa": -1, "state": 1}),
    ("/api/master/step", {"ioa": 1, "state": 3}),
    ("/api/master/bitstring", {"ioa": 1, "value": -1}),
    ("/api/master/delay", {"delay_ms": 60001}),
    ("/api/master/setpoint", {"ioa": -1, "value": 1}),
    ("/api/master/setpoint", {"ioa": 1, "value": "x"}),
    ("/api/master/setpoint", {"ioa": 1, "value": 1, "deactivate": 1}),
    ("/api/master/read", {"ioa": -1}),
    ("/api/master/param", {"ioa": -1}),
    ("/api/master/param", {"ioa": 1, "value": "x"}),
    ("/api/master/file", {"action": 1}),
    ("/api/master/file", {"action": "dir", "ioa": -1}),
    ("/api/master/file", {"action": "dir", "file_name": -1}),
    ("/api/points/batch", {"type": 1}),
    ("/api/points/batch", {"ioas": "x"}),
    ("/api/points/batch", {"action": 1}),
    ("/api/points/batch", {"group": "x"}),
    ("/api/slave/response", []),
    ("/api/slave/ym", {"ioa": 1, "value": "x"}),
    ("/api/slave/ep", {"ioa": 1, "event_value": 70000}),
    ("/api/slave/ep", {"ioa": -1}),
    ("/api/slave/ps", {"ioa": -1}),
    ("/api/slave/ps", {"ioa": 1, "states": []}),
    ("/api/slave/ps", {"ioa": 1, "states": [2]}),
    ("/api/slave/sim", []),
    ("/api/slave/start", {"host": 1}),
    ("/api/slave/start", {"port": -1}),
    ("/api/slave/start", {"addr": -1}),
    ("/api/slave/start", {"tls": 1}),
    ("/api/slave/yx", {"ioa": 1, "value": 1}),
    ("/api/slave/yc", {"ioa": 1, "value": "x"}),
    ("/api/slave/step", {"ioa": 1, "value": 64}),
    ("/api/multi/start", {"stations": []}),
    ("/api/multi/start", {"stations": [1]}),
    ("/api/multi/start", {"stations": [{}]}),
    ("/api/multi/start", {"stations": [{"station_id": "a", "port": -1}]}),
    ("/api/simulation", {"enabled": "yes"}),
    ("/api/simulation", {"enabled": True, "preset": 1}),
    ("/api/simulation", {"enabled": True, "condition": 1}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", _INVALID_FIELDS)
async def test_invalid_fields_return_400(master_client, path, payload):
    client, _ = master_client
    r = await client.post(path, json=payload)
    assert r.status == 400, (path, payload, await r.text())


# ── 成功分支（替换会话方法，不启动引擎）────────────────────────


_MASTER_COMMANDS = [
    ("/api/master/yk", {"ioa": 1, "state": 1}, "send_yk"),
    ("/api/master/step", {"ioa": 1, "state": 2}, "send_step_command"),
    ("/api/master/bitstring", {"ioa": 1, "value": 7}, "send_bitstring"),
    ("/api/master/delay", {"delay_ms": 100}, "send_delay_request"),
    ("/api/master/setpoint", {"ioa": 1, "value": 1.5}, "send_setpoint"),
    ("/api/master/read", {"ioa": 1}, "read_command"),
    ("/api/master/param", {"kind": "float", "ioa": 1, "value": 1.0}, "parameter_command"),
    ("/api/master/file", {"action": "directory", "ioa": 1}, "file_action"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload,method", _MASTER_COMMANDS)
async def test_master_command_success(master_client, path, payload, method):
    client, bridge = master_client
    mocked = AsyncMock(return_value={"ok": True})
    setattr(bridge.session, method, mocked)
    try:
        r = await client.post(path, json=payload)
        assert r.status == 200
        assert (await r.json())["ok"] is True
        assert mocked.await_count == 1
    finally:
        # 恢复类方法，避免影响同 fixture 内其它断言
        delattr(bridge.session, method)


@pytest.mark.asyncio
async def test_master_start_success(master_client):
    client, bridge = master_client
    bridge.start_master = AsyncMock(return_value={"ok": True})
    r = await client.post("/api/master/start",
                          json={"host": "127.0.0.1", "port": 2404, "addr": 1})
    assert (await r.json())["ok"] is True
    bridge.start_master.assert_awaited_once_with(
        "127.0.0.1", 2404, 1, True, 0.0, tls=None, redundancy=None)


_SLAVE_COMMANDS = [
    ("/api/slave/yx", {"ioa": 1, "value": True}, "slave_set_yx"),
    ("/api/slave/yc", {"ioa": 1, "value": 1.5}, "slave_set_yc"),
    ("/api/slave/ym", {"ioa": 1, "value": 5}, "slave_set_ym"),
    ("/api/slave/step", {"ioa": 1, "value": 5}, "slave_set_step"),
    ("/api/slave/ep", {"ioa": 1, "event_value": 1}, "slave_protection_event"),
    ("/api/slave/ps", {"ioa": 1, "states": [1, 0]}, "slave_group_single_point"),
    ("/api/slave/response", {"delays": {"gi": 0}}, "set_response"),
    ("/api/slave/sim", {"enabled": False}, "set_simulation"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload,method", _SLAVE_COMMANDS)
async def test_slave_command_success(slave_client, path, payload, method):
    client, bridge = slave_client
    mocked = AsyncMock(return_value={"ok": True})
    setattr(bridge.session, method, mocked)
    try:
        r = await client.post(path, json=payload)
        assert r.status == 200
        assert (await r.json())["ok"] is True
        assert mocked.await_count == 1
    finally:
        delattr(bridge.session, method)


@pytest.mark.asyncio
async def test_slave_start_port_in_use_rolls_back(slave_client):
    client, bridge = slave_client
    busy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    port = busy.getsockname()[1]
    try:
        r = await client.post("/api/slave/start",
                              json={"host": "127.0.0.1", "port": port, "addr": 1})
        body = await r.json()
        assert body["ok"] is False and body["error"]
        # 启动失败必须回滚：不能留下“started=true 但 running=false”的僵尸引擎
        assert bridge.engine is None
        assert bridge.status()["started"] is False
        # 释放端口后可在新端口重试
        r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": 0})
        assert (await r.json())["ok"] is True
    finally:
        busy.close()
        await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_slave_start_success_and_response_get(slave_client):
    client, bridge = slave_client
    bridge.start_slave = AsyncMock(return_value={"ok": True})
    r = await client.post("/api/slave/start", json={"port": 0, "addr": 1})
    assert (await r.json())["ok"] is True
    bridge.start_slave.assert_awaited_once_with("0.0.0.0", 0, 1, tls=None)

    r = await client.get("/api/slave/response")
    body = await r.json()
    assert body["ok"] is True and "response" in body


@pytest.mark.asyncio
async def test_multi_start_success(master_client):
    client, bridge = master_client
    bridge.multi_start = AsyncMock(return_value={"ok": True, "stations": 1})
    r = await client.post("/api/multi/start", json={
        "stations": [{"station_id": "s1", "port": 2404}]})
    assert (await r.json())["ok"] is True
    bridge.multi_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_master_gi_invalid_json_falls_back(master_client):
    client, bridge = master_client
    mocked = AsyncMock(return_value={"ok": True})
    bridge.session.general_interrogation = mocked
    try:
        r = await client.post("/api/master/gi", data=b"{bad",
                              headers={"Content-Type": "application/json"})
        assert (await r.json())["ok"] is True
        mocked.assert_awaited_once_with(20)
    finally:
        delattr(bridge.session, "general_interrogation")


# ── 点表导入 / 导出 / 日志 / 历史参数 ────────────────────────────


@pytest.mark.asyncio
async def test_points_import_sniffing(slave_client):
    client, bridge = slave_client

    # yaml（auto 嗅探）
    yaml_text = bridge.export_points_yaml()
    r = await client.post("/api/points/import", data=yaml_text.encode("utf-8"))
    assert (await r.json())["ok"] is True

    # csv（auto 嗅探）
    csv_text = bridge.export_points_csv()
    r = await client.post("/api/points/import", data=csv_text.encode("utf-8"))
    assert (await r.json())["ok"] is True

    # json（auto 嗅探）：把当前 YAML 点表转成 JSON，走 JSON 解析分支
    import json as _json

    import yaml

    r = await client.post(
        "/api/points/import",
        data=_json.dumps(yaml.safe_load(yaml_text)).encode("utf-8"))
    assert (await r.json())["ok"] is True

    # 非法 JSON → 400
    r = await client.post("/api/points/import", data=b"{broken",
                          headers={"Content-Type": "application/json"})
    assert r.status == 400

    # 显式 format=csv
    r = await client.post("/api/points/import?format=csv", data=csv_text.encode("utf-8"))
    assert (await r.json())["ok"] is True


@pytest.mark.asyncio
async def test_points_yaml_put_and_logs(master_client):
    client, bridge = master_client
    yaml_text = bridge.export_points_yaml()
    r = await client.post("/api/points/yaml", data=yaml_text.encode("utf-8"))
    assert (await r.json())["ok"] is True

    r = await client.get("/api/logs", params={"limit": "1"})
    body = await r.json()
    assert body["ok"] is True and "logs" in body

    r = await client.get("/api/logs/export")
    assert r.status == 200
    assert "attachment" in r.headers["Content-Disposition"]


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [
    {"start": "x"}, {"start": "-1"}, {"end": "x"}, {"end": "-1"},
    {"limit": "x"}, {"limit": "0"},
])
async def test_history_invalid_query(params):
    from core.data.history import HistoryDB

    db = HistoryDB(":memory:")
    db.open()
    bridge = EngineBridge("master", history_db=db)
    try:
        async with TestClient(TestServer(create_app(bridge))) as client:
            r = await client.get("/api/history/data", params=params)
            assert r.status == 400
    finally:
        await bridge.shutdown()
        db.close()


@pytest.mark.asyncio
async def test_frames_decode_and_schema(master_client):
    client, _ = master_client
    assert (await client.get("/api/frames/decode")).status == 400
    assert (await client.get("/api/frames/decode",
                             params={"hex": "00" * 3000})).status == 400
    r = await client.get("/api/frames/decode", params={"hex": "680401000000"})
    body = await r.json()
    assert body["ok"] is True and body["format"] == "S"

    r = await client.get("/api/schema")
    body = await r.json()
    assert body["ok"] is True and body["schemaVersion"] >= 1
    r = await client.get("/api/recent")
    assert "frames" in await r.json()


# ── 静态资源 / favicon / WS ──────────────────────────────────────


@pytest.mark.asyncio
async def test_static_assets_and_favicon(master_client):
    client, _ = master_client
    r = await client.get("/app", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/app/"
    r = await client.get("/app/index.html")
    assert r.status == 200
    # SPA 路由回落 index.html
    r = await client.get("/app/some/deep/route")
    assert r.status == 200
    r = await client.get("/favicon.ico")
    assert r.status == 200


@pytest.mark.asyncio
async def test_app_index_missing(monkeypatch, master_client):
    from webui import server as server_mod

    client, _ = master_client
    monkeypatch.setattr(server_mod, "APP_STATIC", Path("definitely-missing-dir"))
    r = await client.get("/app/")
    assert r.status == 404
    assert "前端产物缺失" in await r.text()


@pytest.mark.asyncio
async def test_websocket_snapshot_and_refresh(master_client):
    client, _ = master_client
    async with client.ws_connect("/ws") as ws:
        first = await ws.receive_json()
        assert first["kind"] == "snapshot"
        assert "points" in first["data"]
        await ws.send_str("refresh")
        second = await ws.receive_json()
        assert second["kind"] == "snapshot"
        assert "points" in second["data"]


# ── P1-5 API 错误可诊断性 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_error_has_machine_readable_code_field_request_id():
    """4xx 带 code/field/request_id；ok/error 两键保持兼容（okSchema 忽略未知键）."""
    from webui.bridge import EngineBridge
    from webui.server import create_app

    bridge = EngineBridge(role="master")
    async with TestClient(TestServer(create_app(bridge))) as client:
        r = await client.get("/api/frames/decode", params={"hex": ""})
        assert r.status == 400
        body = await r.json()
        assert body["ok"] is False
        assert body["error"] == "missing hex"          # 旧消费方不受影响
        assert body["code"] == "missing_field"
        assert body["field"] == "hex"
        assert len(body["request_id"]) == 12

        r = await client.get("/api/frames/decode", params={"hex": "00" * 2100})
        assert r.status == 400
        assert (await r.json())["code"] == "value_too_long"

        r = await client.post("/api/master/start", json={"host": 123})
        assert r.status == 400
        body = await r.json()
        assert body["field"] == "host"
        assert body["code"] == "invalid_field"

        # 每次 request_id 不同（可关联日志）
        ids = set()
        for _ in range(3):
            r = await client.get("/api/frames/decode", params={"hex": ""})
            ids.add((await r.json())["request_id"])
        assert len(ids) == 3
