"""连接医生 REST 接线测试（T94）.

进程内 aiohttp TestClient 实测 /api/master/doctor：真实子站（四层全绿 +
证据存入 bridge.last_doctor）、参数校验 400、无人监听端口（TCP 层失败不抛 500）。
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.engine.slave import SlaveEngine
from webui.bridge import EngineBridge
from webui.server import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_doctor_against_own_slave_and_param_validation():
    bridge = EngineBridge(role="master")
    async with TestClient(TestServer(create_app(bridge))) as client:
        # 参数校验
        r = await client.post("/api/master/doctor", data={"host": ""})
        assert r.status == 400
        r = await client.post("/api/master/doctor", json={"host": "127.0.0.1", "port": 0})
        assert r.status == 400

        # 真实子站：四层全绿，证据入库
        port = _free_port()
        slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1)
        await slave.start()
        try:
            r = await client.post(
                "/api/master/doctor", json={"host": "127.0.0.1", "port": port, "observe_seconds": 1})
            assert r.status == 200
            body = await r.json()
            assert body["ok"] is True
            steps = body["report"]["steps"]
            assert [s["key"] for s in steps] == ["tcp", "startdt", "dataflow"]
            assert all(s["ok"] for s in steps)
            assert "全部通过" in body["report"]["conclusion"]
            assert getattr(bridge, "last_doctor", None) == body["report"]
        finally:
            await asyncio.wait_for(slave.stop(), timeout=6)


@pytest.mark.asyncio
async def test_doctor_unreachable_port_returns_step_failure():
    bridge = EngineBridge(role="master")
    async with TestClient(TestServer(create_app(bridge))) as client:
        port = _free_port()  # 已关闭
        r = await client.post(
            "/api/master/doctor", json={"host": "127.0.0.1", "port": port, "observe_seconds": 1})
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is False
        assert body["report"]["steps"][0]["key"] == "tcp"
        assert body["report"]["steps"][0]["ok"] is False
        assert "TCP" in body["report"]["conclusion"]
