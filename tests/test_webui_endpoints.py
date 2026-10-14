"""Web 后端能力 REST 接线测试（T08 参数状态 / T09 步位置 / T16 多站）.

用**进程内 aiohttp 客户端**（``aiohttp.test_utils.TestServer/TestClient``）实测
真实路由与处理函数，而非仅断言路由存在。
"""

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.engine.master import ParameterResult, ParameterState
from webui.bridge import EngineBridge
from webui.server import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    import asyncio

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


class _FakeParamEngine:
    """仅实现参数状态查询接口的假引擎（用于确定性验证 REST 序列化）."""

    def __init__(self, states: dict[int, ParameterState]):
        self._states = states

    def get_parameter_state(self, ioa: int) -> ParameterState | None:
        return self._states.get(ioa)

    def parameter_states(self) -> dict[int, ParameterState]:
        return dict(self._states)


# ── T08 参数状态 ─────────────────────────────────────────────────

class TestParamStateEndpoints:
    @pytest.mark.asyncio
    async def test_not_connected(self):
        bridge = EngineBridge(role="master")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.get("/api/master/param_state?ioa=100")
                assert r.status == 200
                data = await r.json()
                assert data["ok"] is False and data["error"]
                r2 = await c.get("/api/master/params")
                assert r2.status == 200
                assert (await r2.json())["ok"] is False
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_invalid_ioa(self):
        bridge = EngineBridge(role="master")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                assert (await c.get("/api/master/param_state")).status == 400
                assert (await c.get("/api/master/param_state?ioa=abc")).status == 400
                assert (await c.get("/api/master/param_state?ioa=-1")).status == 400
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_state_serialization_and_null(self):
        states = {
            100: ParameterState(
                ioa=100,
                load_result=ParameterResult.OK,
                load_cot=7,
                load_updated_at=1234.5,
                activation_result=ParameterResult.TERMINATED,
                activation_cot=10,
                activation_updated_at=1235.5,
            ),
        }
        bridge = EngineBridge(role="master")
        bridge.session.engine = _FakeParamEngine(states)
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.get("/api/master/param_state?ioa=100")
                assert r.status == 200
                data = await r.json()
                assert data["ok"] is True and data["ioa"] == 100
                st = data["state"]
                # ParameterResult 必须是字符串枚举值（.value），非 Enum 对象
                assert st["loadResult"] == "ok"
                assert st["activationResult"] == "terminated"
                assert st["loadCot"] == 7
                assert st["activationCot"] == 10
                assert st["loadUpdatedAt"] == 1234.5

                # 未跟踪的 IOA → state 为 null
                r2 = await c.get("/api/master/param_state?ioa=999")
                d2 = await r2.json()
                assert d2["ok"] is True and d2["state"] is None

                # 列表：按 IOA 升序
                bridge.session.engine = _FakeParamEngine({
                    200: ParameterState(ioa=200, load_result=ParameterResult.TIMEOUT),
                    100: ParameterState(ioa=100, load_result=ParameterResult.PENDING),
                })
                r3 = await c.get("/api/master/params")
                d3 = await r3.json()
                assert d3["ok"] is True
                assert [x["ioa"] for x in d3["params"]] == [100, 200]
                assert d3["params"][1]["loadResult"] == "timeout"
        finally:
            await bridge.shutdown()


# ── T09 子站步位置 ───────────────────────────────────────────────

class TestSlaveStepEndpoint:
    @pytest.mark.asyncio
    async def test_set_step_and_upload(self):
        port = _free_port()
        bridge = EngineBridge(role="slave")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/slave/start",
                                 json={"host": "127.0.0.1", "port": port})
                assert (await r.json())["ok"] is True

                # 演示点表含 STEP 点（IOA 4001+）
                r = await c.get("/api/points")
                pts = (await r.json())["points"]
                steps = [p for p in pts if p["type"] == "STEP"]
                assert steps, "点表快照未带出 STEP 点"
                ioa = steps[0]["ioa"]

                r = await c.post("/api/slave/step", json={"ioa": ioa, "value": 5})
                assert (await r.json())["ok"] is True

                # 置数后快照反射新档位
                r = await c.get("/api/points")
                row = next(p for p in (await r.json())["points"] if p["ioa"] == ioa)
                assert row["value"] == 5

                # 边界/类型校验
                assert (await c.post("/api/slave/step",
                                     json={"ioa": ioa, "value": 999})).status == 400
                assert (await c.post("/api/slave/step",
                                     json={"ioa": -1, "value": 1})).status == 400

                await c.post("/api/slave/stop")
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_step_without_engine(self):
        bridge = EngineBridge(role="slave")
        bridge.ensure_demo_points()
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                r = await c.post("/api/slave/step", json={"ioa": 4001, "value": 1})
                assert r.status == 200
                assert (await r.json())["ok"] is False
        finally:
            await bridge.shutdown()


# ── T16 多站 ─────────────────────────────────────────────────────

class TestMultiEndpoints:
    @pytest.mark.asyncio
    async def test_start_status_summary_stop(self):
        ports = [_free_port(), _free_port()]
        bridge = EngineBridge(role="slave")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                # 初始：未运行
                d = await (await c.get("/api/multi/status")).json()
                assert d["ok"] is True and d["running"] is False and d["stations"] == []

                body = {"stations": [
                    {"station_id": "a", "host": "127.0.0.1", "port": ports[0],
                     "common_addr": 1, "auto_generate": True, "yx_count": 3, "yc_count": 2},
                    {"station_id": "b", "host": "127.0.0.1", "port": ports[1],
                     "common_addr": 2, "auto_generate": True, "yx_count": 3, "yc_count": 2},
                ]}
                r = await c.post("/api/multi/start", json=body)
                d = await r.json()
                assert d["ok"] is True and d["stations"] == 2

                d = await (await c.get("/api/multi/status")).json()
                assert d["running"] is True
                assert {s["station_id"] for s in d["stations"]} == {"a", "b"}
                assert all(s["port"] in ports for s in d["stations"])

                d = await (await c.get("/api/multi/summary")).json()
                assert d["ok"] is True and d["station_count"] == 2
                assert len(d["stations"]) == 2

                # 重复启动 → 业务失败
                r = await c.post("/api/multi/start", json=body)
                assert (await r.json())["ok"] is False

                r = await c.post("/api/multi/stop")
                assert (await r.json())["ok"] is True
                d = await (await c.get("/api/multi/status")).json()
                assert d["running"] is False and d["stations"] == []

                # 端口释放：可重新绑定
                for p in ports:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        s.bind(("127.0.0.1", p))
                    finally:
                        s.close()
        finally:
            await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_validation(self):
        bridge = EngineBridge(role="slave")
        try:
            async with TestClient(TestServer(create_app(bridge))) as c:
                assert (await c.post("/api/multi/start", json={})).status == 400
                assert (await c.post("/api/multi/start",
                                     json={"stations": []})).status == 400
                assert (await c.post("/api/multi/start", json={
                    "stations": [{"port": 2404}]})).status == 400  # 缺 station_id
                assert (await c.post("/api/multi/start", json={
                    "stations": [{"station_id": "x", "port": 99999}]})).status == 400
        finally:
            await bridge.shutdown()
