"""Web API 可选访问令牌测试（B7）.

覆盖：未配置令牌时直通；配置后 /api/* 401 / 三种携带形态 / 公开探测端点 /
静态页放行 / WS 握手令牌校验。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp import WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app

TOKEN = "s3cret-token"


async def _client(auth_token: str | None, role: str = "master") -> TestClient:
    bridge = EngineBridge(role=role)
    return TestClient(TestServer(create_app(bridge, auth_token=auth_token)))


@pytest.mark.asyncio
async def test_auth_disabled_passthrough():
    async with await _client(None) as client:
        r = await client.get("/api/auth")
        assert await r.json() == {"ok": True, "required": False, "valid": True}
        r = await client.get("/api/status")
        assert r.status == 200


@pytest.mark.asyncio
async def test_auth_probe_reports_validity():
    async with await _client(TOKEN) as client:
        r = await client.get("/api/auth")
        body = await r.json()
        assert body == {"ok": True, "required": True, "valid": False}

        r = await client.get("/api/auth", headers={"Authorization": f"Bearer {TOKEN}"})
        assert (await r.json())["valid"] is True

        r = await client.get("/api/auth", headers={"X-Auth-Token": TOKEN})
        assert (await r.json())["valid"] is True

        r = await client.get("/api/auth", params={"token": TOKEN})
        assert (await r.json())["valid"] is True


@pytest.mark.asyncio
async def test_auth_required_from_all_api_paths():
    async with await _client(TOKEN) as client:
        # 缺失/错误令牌 → 401
        r = await client.get("/api/status")
        assert r.status == 401
        assert (await r.json())["error"] == "unauthorized"
        r = await client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert r.status == 401
        r = await client.post("/api/master/stop", headers={"Authorization": "Bearer wrong"})
        assert r.status == 401

        # 三种正确形态 → 200
        for kwargs in (
            {"headers": {"Authorization": f"Bearer {TOKEN}"}},
            {"headers": {"X-Auth-Token": TOKEN}},
            {"params": {"token": TOKEN}},
        ):
            r = await client.get("/api/status", **kwargs)
            assert r.status == 200, kwargs
            assert (await r.json())["role"] == "master"

        # 静态页/页面路由不拦截（产物存在时 200，否则 404；但不得是 401）
        r = await client.get("/app/")
        assert r.status != 401
        r = await client.get("/")
        assert r.status != 401


@pytest.mark.asyncio
async def test_auth_ws_handshake():
    async with await _client(TOKEN) as client:
        with pytest.raises(WSServerHandshakeError) as exc:
            await client.ws_connect("/ws")
        assert exc.value.status == 401

        async with client.ws_connect(f"/ws?token={TOKEN}") as ws:
            msg = await ws.receive_json()
            assert msg["kind"] == "snapshot"
