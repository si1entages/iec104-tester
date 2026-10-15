"""D1 回归测试：主站可发送撤销命令（COT=8 DEACT）.

覆盖（QA 互调报告 2026-10-15 §C2/D1）:
- ASDUBuilder 命令构造支持 ``cot`` 参数（默认 ACT，不破坏既有调用）
- 引擎层 ``single_command`` / ``double_command`` / 设点命令
  ``deactivate=True`` → 实际下发 COT=8 (DEACT) 帧，且不走 SBO 两段式
- HTTP API ``POST /api/master/yk`` / ``/api/master/setpoint`` 接受
  ``deactivate: bool=false`` 字段并透传（D1）
- 子站侧 DEACT→DEACTCON (COT=9) 处理已由 QA 裸 APCI 探针实测正确，不改动

标准依据：IEC 60870-5-101/104 中 C_SC/C_DC/C_SE 的传输原因含
ACT(6) 与 DEACT(8)；子站应答 DEACTCON(9)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.types import COT, TypeID
from webui.bridge import EngineBridge
from webui.server import create_app


def _cot_of(raw: bytes) -> int:
    """解码 ASDU 并返回其传送原因."""
    return ASDU.decode(raw).cot


# ── ASDUBuilder 层 ───────────────────────────────────────────────


def test_single_command_default_cot_is_act():
    """默认 COT=ACT(6)：既有调用方零改动."""
    raw = ASDUBuilder.build_single_command(1, 100, True)
    assert _cot_of(raw) == COT.ACT


@pytest.mark.parametrize("builder,args,type_id", [
    (ASDUBuilder.build_single_command, (1, 100, True), TypeID.C_SC_NA_1),
    (ASDUBuilder.build_double_command, (1, 100, 1), TypeID.C_DC_NA_1),
    (ASDUBuilder.build_setpoint_normalized, (1, 100, 0.5), TypeID.C_SE_NA_1),
    (ASDUBuilder.build_setpoint_scaled, (1, 100, 500), TypeID.C_SE_NB_1),
    (ASDUBuilder.build_setpoint_shortfloat, (1, 100, 0.5), TypeID.C_SE_NC_1),
])
def test_command_builders_accept_deactivate_cot(builder, args, type_id):
    """``cot=COT.DEACT`` → 帧内 COT=8，TypeID 不变."""
    raw = builder(*args, cot=COT.DEACT)
    asdu = ASDU.decode(raw)
    assert asdu.cot == COT.DEACT
    assert asdu.type_id == type_id


@pytest.mark.parametrize("builder,args", [
    (ASDUBuilder.build_single_command_with_time, (1, 100, True)),
    (ASDUBuilder.build_double_command_with_time, (1, 100, 1)),
    (ASDUBuilder.build_setpoint_normalized_with_time, (1, 100, 0.5)),
    (ASDUBuilder.build_setpoint_scaled_with_time, (1, 100, 500)),
    (ASDUBuilder.build_setpoint_shortfloat_with_time, (1, 100, 0.5)),
])
def test_timed_command_builders_accept_deactivate_cot(builder, args):
    """带时标变体同样支持 ``cot`` 覆盖（D1：撤销 + 带时标组合）."""
    raw = builder(*args, cot=COT.DEACT)
    assert _cot_of(raw) == COT.DEACT


# ── 引擎层（真实 MasterEngine，帧捕获）────────────────────────────


class _FrameCapture:
    def __init__(self):
        self.frames: list[bytes] = []

    async def __call__(self, asdu_data: bytes) -> None:
        self.frames.append(asdu_data)


@pytest.mark.asyncio
async def test_master_single_command_deactivate_sends_cot8():
    """engine.single_command(deactivate=True) → 下发 COT=8，不走 SBO 等待."""
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 24100, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        capture = _FrameCapture()
        bridge.engine._send_command_asdu = capture
        await bridge.send_yk(100, 1, deactivate=True)
        assert len(capture.frames) == 1  # 撤销单帧直发，无 SBO 选择帧
        assert _cot_of(capture.frames[0]) == COT.DEACT
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_master_double_command_deactivate_sends_cot8():
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 24101, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        capture = _FrameCapture()
        bridge.engine._send_command_asdu = capture
        await bridge.send_yk(2001, 1, double=True, deactivate=True)
        assert len(capture.frames) == 1
        asdu = ASDU.decode(capture.frames[0])
        assert asdu.cot == COT.DEACT
        assert asdu.type_id == TypeID.C_DC_NA_1
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_master_setpoint_deactivate_sends_cot8():
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 24102, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        capture = _FrameCapture()
        bridge.engine._send_command_asdu = capture
        await bridge.send_setpoint(4001, 12.5, deactivate=True)
        assert len(capture.frames) == 1
        asdu = ASDU.decode(capture.frames[0])
        assert asdu.cot == COT.DEACT
        assert asdu.type_id == TypeID.C_SE_NC_1
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_master_yk_without_deactivate_sends_cot6():
    """缺省（不传 deactivate）→ COT=ACT(6)，与改动前行为一致."""
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        r = await bridge.start_master("127.0.0.1", 24103, 1,
                                      reconnect=False, gi_interval=0)
        assert r["ok"] is True
        capture = _FrameCapture()
        bridge.engine._send_command_asdu = capture
        await bridge.send_yk(100, 1)
        assert len(capture.frames) == 1
        assert _cot_of(capture.frames[0]) == COT.ACT
    finally:
        await bridge.shutdown()


# ── HTTP API 层 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_yk_accepts_deactivate_field():
    """POST /api/master/yk 带 deactivate=true → 引擎下发 COT=8."""
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        async with TestClient(TestServer(create_app(bridge))) as c:
            r = await c.post("/api/master/start", json={
                "host": "127.0.0.1", "port": 24104, "reconnect": False,
            })
            assert (await r.json())["ok"] is True
            capture = _FrameCapture()
            bridge.engine._send_command_asdu = capture
            r = await c.post("/api/master/yk", json={
                "ioa": 100, "state": 1, "deactivate": True,
            })
            assert (await r.json())["ok"] is True
            assert len(capture.frames) == 1
            assert _cot_of(capture.frames[0]) == COT.DEACT
            await c.post("/api/master/stop")
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_api_yk_rejects_non_bool_deactivate():
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        async with TestClient(TestServer(create_app(bridge))) as c:
            r = await c.post("/api/master/start", json={
                "host": "127.0.0.1", "port": 24105, "reconnect": False,
            })
            assert (await r.json())["ok"] is True
            r = await c.post("/api/master/yk", json={
                "ioa": 100, "state": 1, "deactivate": "yes",
            })
            assert r.status == 400
            await c.post("/api/master/stop")
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_api_setpoint_accepts_deactivate_field():
    """POST /api/master/setpoint 带 deactivate=true → C_SE 撤销帧 COT=8."""
    bridge = EngineBridge(role="master")
    bridge.ensure_demo_points()
    try:
        async with TestClient(TestServer(create_app(bridge))) as c:
            r = await c.post("/api/master/start", json={
                "host": "127.0.0.1", "port": 24106, "reconnect": False,
            })
            assert (await r.json())["ok"] is True
            capture = _FrameCapture()
            bridge.engine._send_command_asdu = capture
            r = await c.post("/api/master/setpoint", json={
                "ioa": 4001, "value": 1.0, "deactivate": True,
            })
            assert (await r.json())["ok"] is True
            assert len(capture.frames) == 1
            assert _cot_of(capture.frames[0]) == COT.DEACT
            await c.post("/api/master/stop")
    finally:
        await bridge.shutdown()
