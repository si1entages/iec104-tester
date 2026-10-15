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


class TestMultiStationTlsPolicy:
    """多站 TLS 失败语义：无效配置**不启动该站、绝不静默降级为明文**（T20 策略
    与单站 ok=False 一致），其余站不受牵连；status/summary 反映 TLS 实况。"""

    def _two_station_body(self, port_ok: int) -> list[dict]:
        return [
            {"station_id": "tls_ok", "station_name": "OK", "port": port_ok,
             "common_addr": 1, "auto_generate": True, "spontaneous_enabled": False,
             "tls": {"enabled": True, "certfile": SERVER_CRT, "keyfile": SERVER_KEY}},
            {"station_id": "tls_bad", "station_name": "BAD", "port": port_ok + 1,
             "common_addr": 1, "auto_generate": True, "spontaneous_enabled": False,
             "tls": {"enabled": True, "certfile": str(CERTS / "nope.pem"),
                     "keyfile": SERVER_KEY}},
        ]

    @pytest.mark.asyncio
    async def test_invalid_tls_station_not_started_no_plaintext_fallback(self):
        """红线：TLS 配置无效的站不启动（不存在"明文替身"），其余站正常."""
        from core.engine.multi_station import (
            MultiStationConfig,
            MultiStationManager,
            StationConfig,
        )

        port = _free_port()
        cfgs = [StationConfig(**s) for s in self._two_station_body(port)]
        mgr = MultiStationManager(MultiStationConfig(stations=cfgs))
        try:
            await mgr.start_all()  # 不得抛出、不得回滚好站
            assert mgr.station_count == 1, "坏站不得启动"
            assert "tls_ok" in mgr._engines and "tls_bad" not in mgr._engines
            assert set(mgr.start_errors) == {"tls_bad"}
            assert "TLS 配置无效" in mgr.start_errors["tls_bad"]
            # 好站 TLS 实况为启用
            st = mgr.get_station_status("tls_ok")
            assert st is not None and st.tls_enabled is True
        finally:
            await mgr.stop_all()

    @pytest.mark.asyncio
    async def test_all_invalid_tls_fails_without_manager(self):
        """全部站 TLS 无效 → 整体失败，不保留管理器."""
        bridge = EngineBridge(role="slave")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/multi/start", json={"stations": [
                    {"station_id": "bad1", "port": _free_port(),
                     "tls": {"enabled": True, "certfile": str(CERTS / "nope.pem")}},
                ]})
                data = await r.json()
                assert data["ok"] is False
                assert "TLS 配置无效" in data["error"]
                assert data["failed"][0]["station_id"] == "bad1"
                assert bridge.session.multi_station is None  # 管理器已回收
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_multi_start_partial_failure_reported_in_status(self):
        """逐站结果：partial 失败经 /api/multi/start 与 /status 均可见."""
        bridge = EngineBridge(role="slave")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/multi/start",
                                 json={"stations": self._two_station_body(_free_port())})
                data = await r.json()
                assert data["ok"] is True
                assert data["stations"] == 1
                assert [f["station_id"] for f in data["failed"]] == ["tls_bad"]
                assert data["failed"][0]["ok"] is False
                assert "TLS" in data["failed"][0]["error"]

                # status：TLS 实况 + failed 可查（不能只看启动响应/日志）
                r = await c.get("/api/multi/status")
                st = await r.json()
                assert st["ok"] is True and st["running"] is True
                assert len(st["stations"]) == 1
                assert st["stations"][0]["station_id"] == "tls_ok"
                assert st["stations"][0]["tls_enabled"] is True
                assert [f["station_id"] for f in st["failed"]] == ["tls_bad"]

                # summary：StationSummary 带 tls_enabled，failed 同步可见
                r = await c.get("/api/multi/summary")
                sm = await r.json()
                assert sm["stations"][0]["tls_enabled"] is True
                assert [f["station_id"] for f in sm["failed"]] == ["tls_bad"]

                await c.post("/api/multi/stop")
                # 停止后 failed 清空
                sm = await (await c.get("/api/multi/summary")).json()
                assert sm["failed"] == []
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_plaintext_station_reports_tls_disabled(self):
        """未配 tls 的站 tls_enabled=False（未启用，与启用的站可区分）。"""
        bridge = EngineBridge(role="slave")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/multi/start", json={"stations": [
                    {"station_id": "plain", "port": _free_port(),
                     "auto_generate": True, "spontaneous_enabled": False},
                ]})
                assert (await r.json())["ok"] is True
                r = await c.get("/api/multi/status")
                st = await r.json()
                assert st["stations"][0]["tls_enabled"] is False
                await c.post("/api/multi/stop")
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
