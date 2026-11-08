"""合并模式（单进程双角色、同端口）路由单测.

主站 API 在 `/api/*`，子站挂在 `/slave` 前缀下；两者共享一个 TestServer，
验证路由、schema roles、auth 中间件按前缀生效。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).parent.parent))

from webui.bridge import EngineBridge
from webui.server import create_app


def _combined_app(auth_token: str | None = None):
    master = EngineBridge("master")
    slave = EngineBridge("slave")
    master.ensure_demo_points()
    slave.ensure_demo_points()
    roles = ["master", "slave"]
    app = create_app(
        master, auth_token=auth_token, available_roles=roles, slave_api_prefix="/slave"
    )
    app.add_subapp(
        "/slave",
        create_app(
            slave, auth_token=auth_token, path_prefix="/slave",
            available_roles=roles, slave_api_prefix="/slave",
        ),
    )
    return app, master, slave


async def _shutdown(*bridges) -> None:
    for b in bridges:
        try:
            await asyncio.wait_for(b.shutdown(), timeout=2)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_combined_routes_and_schema():
    app, master, slave = _combined_app()
    try:
        async with TestClient(TestServer(app)) as client:
            r = await client.get("/api/status")
            assert r.status == 200 and (await r.json())["role"] == "master"

            r = await client.get("/slave/api/status")
            assert r.status == 200 and (await r.json())["role"] == "slave"

            r = await client.get("/api/schema")
            body = await r.json()
            assert body["roles"] == ["master", "slave"]
            assert body["slaveApiPrefix"] == "/slave"

            r = await client.get("/slave/api/schema")
            assert r.status == 200 and (await r.json())["roles"] == ["master", "slave"]

            assert (await client.get("/app/")).status == 200
            assert (await client.get("/slave/app/")).status == 200
    finally:
        await _shutdown(master, slave)


@pytest.mark.asyncio
async def test_combined_auth_applies_to_slave_prefix():
    app, master, slave = _combined_app(auth_token="secret")
    try:
        async with TestClient(TestServer(app)) as client:
            r = await client.get("/slave/api/status")
            assert r.status == 401
            r = await client.get(
                "/slave/api/status", headers={"X-Auth-Token": "secret"}
            )
            assert r.status == 200 and (await r.json())["role"] == "slave"
            # 静态页放行，供前端显示令牌输入框
            assert (await client.get("/slave/app/")).status == 200
    finally:
        await _shutdown(master, slave)
