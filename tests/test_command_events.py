"""主站命令事件可观测性测试.

覆盖 ``MasterEvent.COMMAND_SENT`` 的事件发射完整性：遥控/设点/升降等各类命令
下发后，Web UI 依赖该事件在事件流中展示「已下发」记录。历史上
double_command / setpoint_normalized / setpoint_shortfloat 漏发该事件，
导致 UI 上看不到这些命令，本文件锁定该行为防止回归。

每个测试都同时断言「事件类型/字段正确」与「帧确实发出」，避免只测事件而
掩盖命令本身未发送的问题。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine.master import MasterEngine, MasterEvent  # noqa: E402
from core.protocol.asdu import ASDU  # noqa: E402


@pytest.fixture
def mock_tcp_client():
    with patch("core.engine.master.TCPClient") as MockClient:
        client = MockClient.return_value
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.send = AsyncMock()
        client.stats = MagicMock()
        yield client


@pytest.fixture
def engine(mock_tcp_client):
    eng = MasterEngine(
        host="127.0.0.1", port=2404, common_addr=1,
        auto_start=False, auto_gi=False, reconnect=False,
    )
    yield eng


class _EventSpy:
    """收集引擎事件，便于按类型检索."""

    def __init__(self) -> None:
        self.events: list[tuple[MasterEvent, dict]] = []
        self.sent_frames: list[bytes] = []

    def __call__(self, event: MasterEvent, data: dict) -> None:
        self.events.append((event, data))

    def command_events(self) -> list[dict]:
        return [d for e, d in self.events if e == MasterEvent.COMMAND_SENT]

    def by_type(self, cmd_type: str) -> list[dict]:
        return [d for d in self.command_events() if d.get("type") == cmd_type]


@pytest.fixture
def spy(engine):
    s = _EventSpy()
    engine.set_event_callback(s)
    # 拦截实际发送，记录并跳过网络
    async def fake_send(asdu_data: bytes) -> None:
        s.sent_frames.append(asdu_data)

    engine._send_command_asdu = fake_send
    return s


# ── 事件覆盖完整性 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_command_fires_event(engine, spy):
    await engine.single_command(100, True)
    evs = spy.by_type("single_command")
    assert len(evs) == 1
    assert evs[0]["ioa"] == 100
    assert evs[0]["state"] is True
    assert evs[0]["select"] is False
    assert len(spy.sent_frames) == 1


@pytest.mark.asyncio
async def test_double_command_fires_event(engine, spy):
    """回归：double_command 曾漏发 COMMAND_SENT."""
    await engine.double_command(200, 1)
    evs = spy.by_type("double_command")
    assert len(evs) == 1, f"expected 1 double_command event, got {spy.command_events()}"
    assert evs[0]["ioa"] == 200
    assert evs[0]["state"] == 1
    assert evs[0]["select"] is False
    assert len(spy.sent_frames) == 1


@pytest.mark.asyncio
async def test_setpoint_normalized_fires_event(engine, spy):
    """回归：setpoint_normalized 曾漏发 COMMAND_SENT."""
    await engine.setpoint_normalized(300, 0.5)
    evs = spy.by_type("setpoint_normalized")
    assert len(evs) == 1, f"expected 1 event, got {spy.command_events()}"
    assert evs[0]["ioa"] == 300
    assert evs[0]["value"] == 0.5
    assert evs[0]["select"] is False
    assert len(spy.sent_frames) == 1


@pytest.mark.asyncio
async def test_setpoint_shortfloat_fires_event(engine, spy):
    """回归：setpoint_shortfloat 曾漏发 COMMAND_SENT."""
    await engine.setpoint_shortfloat(400, 110.5)
    evs = spy.by_type("setpoint_shortfloat")
    assert len(evs) == 1, f"expected 1 event, got {spy.command_events()}"
    assert evs[0]["ioa"] == 400
    assert evs[0]["value"] == 110.5
    assert evs[0]["select"] is False
    assert len(spy.sent_frames) == 1


@pytest.mark.asyncio
async def test_setpoint_scaled_fires_event(engine, spy):
    await engine.setpoint_scaled(500, 1234)
    evs = spy.by_type("setpoint_scaled")
    assert len(evs) == 1
    assert evs[0]["value"] == 1234


@pytest.mark.asyncio
async def test_regulating_step_fires_event(engine, spy):
    await engine.regulating_step_command(600, 2)
    evs = spy.by_type("regulating_step")
    assert len(evs) == 1
    assert evs[0]["state"] == 2


@pytest.mark.asyncio
async def test_all_command_types_emit_events(engine, spy):
    """汇总：六类命令各发一次，事件数须与帧数一致（1:1）."""
    await engine.single_command(1, True)
    await engine.double_command(2, 1)
    await engine.setpoint_normalized(3, 0.5)
    await engine.setpoint_shortfloat(4, 1.0)
    await engine.setpoint_scaled(5, 10)
    await engine.regulating_step_command(6, 1)

    assert len(spy.command_events()) == 6
    assert len(spy.sent_frames) == 6
    assert {d["type"] for d in spy.command_events()} == {
        "single_command", "double_command", "setpoint_normalized",
        "setpoint_shortfloat", "setpoint_scaled", "regulating_step",
    }


# ── 事件载荷正确性 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_select_flag_reflects_frame(engine, spy):
    """事件的 select 字段须与实际发出的帧一致（选择 vs 执行）."""
    await engine.single_command(10, True, select=True)
    assert spy.by_type("single_command")[0]["select"] is True
    asdu = ASDU.decode(spy.sent_frames[-1])
    assert asdu.objects[0].data.select is True

    await engine.single_command(10, True, select=False)
    assert spy.by_type("single_command")[1]["select"] is False
    asdu = ASDU.decode(spy.sent_frames[-1])
    assert asdu.objects[0].data.select is False


@pytest.mark.asyncio
async def test_sbo_select_stage_emits_own_event(engine, spy):
    """SBO 自动两段式：选择帧与执行帧各自发射一次事件，UI 可见全过程."""
    from core.data.point_table import PointTable

    table = PointTable()
    table.load_yaml(
        str(Path(__file__).parent.parent / "configs" / "demo_points.yaml")
    )
    engine.set_point_table(table)

    # 选择阶段的肯定确认：在首个 _raw 发送后异步注入 ACTCON
    ack_count = {"n": 0}

    async def fake_send(asdu_data: bytes) -> None:
        spy.sent_frames.append(asdu_data)
        ack_count["n"] += 1
        if ack_count["n"] == 1:  # 仅对选择帧回 ACTCON
            def _ack() -> None:
                a = ASDU.decode(asdu_data)
                engine._resolve_pending_ack(a.objects[0].ioa, False, 7)

            asyncio.get_running_loop().call_soon(_ack)

    engine._send_command_asdu = fake_send

    await asyncio.wait_for(engine.single_command(2001, True), timeout=2.0)

    evs = spy.by_type("single_command")
    assert len(evs) == 2, f"SBO 应产生 2 个事件，实际 {evs}"
    assert evs[0]["select"] is True, "第 1 个事件应为选择阶段"
    assert evs[1]["select"] is False, "第 2 个事件应为执行阶段"
    assert len(spy.sent_frames) == 2
