"""Web UI 安全响应头与 HTTPS 上下文（E4）."""

from __future__ import annotations

import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app, create_web_ssl_context

CERTS = Path(__file__).parent / "certs"


@pytest_asyncio.fixture
async def client():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    test_client = TestClient(TestServer(create_app(bridge)))
    await test_client.start_server()
    yield test_client
    await bridge.shutdown()
    await test_client.close()


def _assert_security_headers(resp) -> None:
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert "script-src 'self'" in resp.headers["Content-Security-Policy"]
    assert "geolocation=()" in resp.headers["Permissions-Policy"]


@pytest.mark.asyncio
async def test_api_and_static_responses_have_security_headers(client):
    for path in ("/api/status", "/api/schema", "/app/", "/app/deep/route"):
        resp = await client.get(path)
        _assert_security_headers(resp)


@pytest.mark.asyncio
async def test_auth_401_also_has_security_headers():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    async with TestClient(TestServer(create_app(bridge, auth_token="secret"))) as c:
        resp = await c.get("/api/status")
        assert resp.status == 401
        _assert_security_headers(resp)
    await bridge.shutdown()


def test_create_web_ssl_context():
    ctx = create_web_ssl_context(str(CERTS / "server.pem"), str(CERTS / "server.key"))
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


def test_create_web_ssl_context_missing_file():
    with pytest.raises(OSError):
        create_web_ssl_context(str(CERTS / "definitely-missing.pem"))
