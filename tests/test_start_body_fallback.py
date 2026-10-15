"""start 端点 body 缺省回落 CLI/--config 的接线回归测试.

``app.py`` 把 ``--port``/``--host``/``--addr`` 写入 ``config.connection``；
``/api/slave/start`` 与 ``/api/master/start`` 在 body 省略这些字段时必须
回落 config（body 显式传入优先）。打包 exe 冒烟实测曾暴露：slave 空 body
start 忽略 ``--port`` 恒绑 2404——CLI 覆盖被 body 解析层的硬编码默认吞掉。
"""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.config import AppConfig
from webui.bridge import EngineBridge
from webui.server import create_app


def _bridge(role: str, port: int, common_addr: int) -> EngineBridge:
    cfg = AppConfig()
    cfg.mode = role
    cfg.connection.port = port
    cfg.connection.common_addr = common_addr
    bridge = EngineBridge(role, app_config=cfg)
    bridge.ensure_demo_points()
    return bridge


@pytest.mark.asyncio
async def test_slave_start_omitted_fields_fall_back_to_config(monkeypatch):
    """slave 空 body start：port/addr 应回落 config.connection（而非硬编码 2404/1）."""
    bridge = _bridge("slave", port=27777, common_addr=9)
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    captured: dict = {}

    async def fake_start_slave(host, port, addr, points, tls=None, spontaneous=None):
        captured.update(host=host, port=port, addr=addr)
        return {"ok": True}

    monkeypatch.setattr(bridge.session, "start_slave", fake_start_slave)
    try:
        resp = await client.post("/api/slave/start", json={})
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
        assert captured["port"] == 27777, "空 body 必须回落 config.port（CLI --port）"
        assert captured["addr"] == 9, "空 body 必须回落 config.common_addr"

        resp = await client.post("/api/slave/start", json={"port": 28001})
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
        assert captured["port"] == 28001, "body 显式传入优先于 config"
    finally:
        await client.close()
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_master_start_omitted_fields_fall_back_to_config(monkeypatch):
    """master 空 body start：host/port/addr 应回落 config.connection."""
    bridge = _bridge("master", port=27778, common_addr=7)
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    captured: dict = {}

    async def fake_start_master(host, port, addr, reconnect, points,
                                gi_interval=0.0, tls=None):
        captured.update(host=host, port=port, addr=addr)
        return {"ok": True}

    monkeypatch.setattr(bridge.session, "start_master", fake_start_master)
    try:
        resp = await client.post("/api/master/start", json={})
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
        assert captured["port"] == 27778, "空 body 必须回落 config.port（CLI --port）"
        assert captured["host"] == "127.0.0.1", "host 回落 config 默认"
        assert captured["addr"] == 7, "空 body 必须回落 config.common_addr"

        resp = await client.post(
            "/api/master/start", json={"host": "10.0.0.5", "port": 28002})
        assert resp.status == 200
        assert (await resp.json())["ok"] is True
        assert captured["host"] == "10.0.0.5"
        assert captured["port"] == 28002, "body 显式传入优先于 config"
    finally:
        await client.close()
        await bridge.shutdown()
