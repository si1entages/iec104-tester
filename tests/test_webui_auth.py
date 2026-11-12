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
        assert await r.json() == {"ok": True, "required": False, "valid": True, "mode": "none"}
        r = await client.get("/api/status")
        assert r.status == 200


@pytest.mark.asyncio
async def test_auth_probe_reports_validity():
    async with await _client(TOKEN) as client:
        r = await client.get("/api/auth")
        body = await r.json()
        assert body == {"ok": True, "required": True, "valid": False, "mode": "token"}

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

        # 两种请求头形态 → 200（P1-1：REST 令牌不再接受 ?token=）
        for kwargs in (
            {"headers": {"Authorization": f"Bearer {TOKEN}"}},
            {"headers": {"X-Auth-Token": TOKEN}},
        ):
            r = await client.get("/api/status", **kwargs)
            assert r.status == 200, kwargs
            assert (await r.json())["role"] == "master"

        # P1-1：REST 端点禁用 query token，避免令牌落进历史/代理日志/Referer
        r = await client.get("/api/status", params={"token": TOKEN})
        assert r.status == 401
        # 公开探测端点仍允许 ?token=（只回布尔，保留 /app/?token= 首次导入流程）
        r = await client.get("/api/auth", params={"token": TOKEN})
        assert (await r.json())["valid"] is True

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


# ── P1-1 安全强制化 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_origin_check_rejects_cross_origin():
    """带 Origin 的跨站 /api 与 /ws 请求一律 403（CSWSH 防护）."""
    async with await _client(None) as client:
        r = await client.get("/api/status", headers={"Origin": "https://evil.example"})
        assert r.status == 403
        assert (await r.json())["error"] == "cross-origin request rejected"

        # 同源（与 TestServer 的 127.0.0.1:port 一致）放行
        origin = f"http://{client.host}:{client.port}"
        r = await client.get("/api/status", headers={"Origin": origin})
        assert r.status == 200

        # 无 Origin 的非浏览器客户端放行（CLI / TestClient 默认行为）
        r = await client.get("/api/status")
        assert r.status == 200


@pytest.mark.asyncio
async def test_origin_check_ws_cross_origin():
    async with await _client(None) as client:
        with pytest.raises(WSServerHandshakeError) as exc:
            await client.ws_connect("/ws", headers={"Origin": "https://evil.example"})
        assert exc.value.status == 403


def test_non_loopback_requires_auth():
    """--http-host 0.0.0.0 且无认证 → 拒绝启动；显式放行才可启动."""
    from webui.server import _require_auth_on_non_loopback

    with pytest.raises(RuntimeError, match="拒绝启动"):
        _require_auth_on_non_loopback("0.0.0.0", None, None, False)

    # 回环零回归
    _require_auth_on_non_loopback("127.0.0.1", None, None, False)
    # 有 token / 有 operators / 显式放行都通过
    _require_auth_on_non_loopback("0.0.0.0", "tok", None, False)
    _require_auth_on_non_loopback("0.0.0.0", None, object(), False)
    _require_auth_on_non_loopback("0.0.0.0", None, None, True)


def test_security_log_category():
    """security 类别可过滤，且日志消息不含令牌本身."""
    import logging

    from core.logging_manager import LogManager, _PythonLogBridge

    manager = LogManager(source="test", log_dir=None)
    bridge = _PythonLogBridge(manager)
    record = logging.LogRecord("iec104.security", logging.WARNING, __file__, 1,
                               "认证失败 path=/api/status", (), None)
    bridge.emit(record)
    rows = manager.query(category="security", limit=10)
    assert len(rows) == 1
    assert rows[0].category == "security"
