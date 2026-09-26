"""SBO 选择等待并发/竞态回归测试 (Task #1 追加).

背景:
    主站 SBO 两段式下发在 ``_wait_select_ack`` 中等待 ACTCON。旧实现的问题:

    1. ``_resolve_pending_ack`` 对 ACTTERM 也会 set_result —— 若存在上一次命令的
       滞后 ACTTERM，会错误唤醒本次选择等待，导致 ``cot != ACTCON`` → 误判
       "选择被拒" → 偶发遥控失败（真机网络延迟下才易暴露，本机难复现）。
    2. ``_pending_acks[ioa]`` 静默覆盖 + 无条件 pop —— 同一 IOA 并发等待时会
       悬挂旧等待、并可能误删他人登记。

这些测试通过直接向 ``_process_asdu`` 喂 ASDU 来锁定上述行为。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.data.point_table import PointTable, YcPointDef, YkPointDef
from core.engine.master import MasterEngine
from core.protocol.asdu import ASDU, InformationObject
from core.protocol.types import (
    COT,
    ConnState,
    SingleCommand,
    TypeID,
)


def _make_master(**kwargs) -> tuple[MasterEngine, MagicMock]:
    """构造主站引擎 + 模拟 TCPClient，返回 (engine, client)."""
    with patch("core.engine.master.TCPClient") as MockClient:
        client = MockClient.return_value
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.disconnect = AsyncMock()
        client.send = AsyncMock()
        client.stats = MagicMock()
        engine = MasterEngine(
            host="127.0.0.1", port=2404, common_addr=1,
            auto_start=False, auto_gi=False, reconnect=False, **kwargs,
        )
    engine._state_machine._state = ConnState.RUNNING
    return engine, client


def _cmd_ack_asdu(ioa: int, cot: int, pn: bool = False) -> ASDU:
    """构造 C_SC_NA_1 命令确认帧 (ACTCON/ACTTERM 等)."""
    asdu = ASDU(
        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
        cot=cot, pn=pn, common_addr=1,
    )
    asdu.objects.append(InformationObject(
        ioa=ioa, data=SingleCommand(ioa=ioa, state=True, select=True),
    ))
    return asdu


# ═══════════════════════════════════════════════════════════════════
#  回归 1: 滞后 ACTTERM 不得误判为"选择被拒"
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_stale_actterm_does_not_fail_select_wait():
    """滞后 ACTTERM 先到，随后 ACTCON(PN=0) 到 → _wait_select_ack 应返回 True.

    旧实现中 ACTTERM 会唤醒等待，导致返回 False（误判被拒）。
    """
    engine, _client = _make_master()
    ioa = 3001

    async def feed():
        # 稍作等待，确保 _wait_select_ack 已登记 Future
        await asyncio.sleep(0.02)
        # 先喂一条上一条命令的滞后 ACTTERM（不应唤醒选择等待）
        engine._process_asdu(_cmd_ack_asdu(ioa, COT.ACTTERM))
        await asyncio.sleep(0.02)
        # 再喂真正的选择确认
        engine._process_asdu(_cmd_ack_asdu(ioa, COT.ACTCON, pn=False))

    feeder = asyncio.create_task(feed())
    acked = await engine._wait_select_ack(ioa, timeout=1.0)
    await feeder

    assert acked is True, "stale ACTTERM must not cause select to be judged rejected"
    # 等待结束后登记应被清理
    assert ioa not in engine._pending_acks


# ═══════════════════════════════════════════════════════════════════
#  回归 2: 真 NACK (ACTCON, PN=1) 仍须中止
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_true_nack_aborts_select_wait():
    """ACTCON 携带 PN=1 → _wait_select_ack 应返回 False（中止执行）."""
    engine, _client = _make_master()
    ioa = 3002

    async def feed():
        await asyncio.sleep(0.02)
        engine._process_asdu(_cmd_ack_asdu(ioa, COT.ACTCON, pn=True))

    feeder = asyncio.create_task(feed())
    acked = await engine._wait_select_ack(ioa, timeout=1.0)
    await feeder

    assert acked is False, "true NACK (PN=1) must abort the select wait"
    assert ioa not in engine._pending_acks


# ═══════════════════════════════════════════════════════════════════
#  回归 3: 超时应返回 False 且清理登记
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_select_wait_timeout_returns_false_and_cleans_up():
    """无任何应答 → 超时返回 False，且 _pending_acks 不留残留."""
    engine, _client = _make_master()
    ioa = 3003

    acked = await engine._wait_select_ack(ioa, timeout=0.1)
    assert acked is False
    assert ioa not in engine._pending_acks


# ═══════════════════════════════════════════════════════════════════
#  回归 4: 同 IOA 并发等待安全 (覆盖防护 + 只删自己的登记)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_concurrent_wait_same_ioa_cancels_stale_waiter():
    """同一 IOA 并发等待: 新等待应取消旧等待，旧的返回 False，新的收到 ACTCON 返回 True."""
    engine, _client = _make_master()
    ioa = 3004

    first = asyncio.create_task(engine._wait_select_ack(ioa, timeout=0.5))
    await asyncio.sleep(0.02)  # 让 first 完成登记
    second = asyncio.create_task(engine._wait_select_ack(ioa, timeout=0.5))
    await asyncio.sleep(0.02)  # 让 second 取消 first 并完成登记

    # 只为最新的等待喂 ACTCON
    engine._process_asdu(_cmd_ack_asdu(ioa, COT.ACTCON, pn=False))

    first_result = await first
    second_result = await second

    assert first_result is False, "stale waiter must be cancelled and resolve False"
    assert second_result is True, "latest waiter should receive the ACTCON"
    assert ioa not in engine._pending_acks


# ═══════════════════════════════════════════════════════════════════
#  设点 (YC) SBO 路径: 与子站 _command_requires_sbo(is_setpoint=True) 对称
#
#  子站语义: 设点命令先查 YK 点表；命中则按该点的 select_before_execute 判定，
#  未命中则直发执行 (False)。主站 _sbo_required(ioa, "yc") 必须严格对称，
#  否则会出现"主站直发 / 子站要求 SBO → PN=1 拒绝"的不一致缺陷。
# ═══════════════════════════════════════════════════════════════════

def _point_table_with_sbo(ioa: int, sbo: bool) -> PointTable:
    """构造仅含一个 YK 点的点表."""
    pt = PointTable()
    pt.common_addr = 1
    pt.add_yk(YkPointDef(ioa=ioa, name=f"YK{ioa}", select_before_execute=sbo))
    return pt


async def _install_frame_capture(engine: MasterEngine, auto_ack: bool = True) -> list[bytes]:
    """替换 _send_command_asdu 为帧捕获，并在收到首帧后延迟回 ACTCON(PN=0).

    返回捕获到的发送帧列表（ASDU 字节）。``auto_ack`` 为 True 时，对首帧（选择帧）
    延时回 ACTCON(PN=0)，模拟子站配合，使两段式得以继续。

    注意: ACK 必须**延迟**回，因为选择帧在 ``_wait_select_ack`` 登记 Future 之前
    就已发出；若同步回 ACK，等待者尚未建立，唤醒会丢失。
    """
    sent: list[bytes] = []

    async def fake_send_command_asdu(asdu_data: bytes) -> None:
        sent.append(asdu_data)
        if auto_ack and len(sent) == 1:
            hdr = ASDU.decode(asdu_data)
            ioa = hdr.objects[0].ioa

            async def _ack_later():
                await asyncio.sleep(0.01)
                engine._process_asdu(_cmd_ack_asdu(ioa, COT.ACTCON, pn=False))

            asyncio.create_task(_ack_later())

    engine._send_command_asdu = fake_send_command_asdu  # type: ignore[method-assign]
    return sent


@pytest.mark.asyncio
async def test_setpoint_sbo_point_triggers_two_stage():
    """设点 IOA 命中 YK 点表且 sbo=True → 自动两段式 (2 帧).

    用 ``wait_for`` 限制 1s: 若延迟 ACK 未送达等待者，会退化为 t1=15s 超时并
    被 wait_for 截断 → 测试失败，从而排除"靠超时碰巧通过"的假阳性。
    """
    ioa = 4001
    pt = _point_table_with_sbo(ioa, sbo=True)
    engine, _client = _make_master(point_table=pt)
    sent = await _install_frame_capture(engine)

    await asyncio.wait_for(engine.setpoint_shortfloat(ioa, 123.45), timeout=1.0)

    assert len(sent) == 2, "SBO setpoint must send SELECT then EXECUTE"
    # 首帧为选择 (S/E bit7 = 1)，次帧为执行 (S/E = 0)
    assert _se_bit(sent[0]) == 1, "first frame must be SELECT"
    assert _se_bit(sent[1]) == 0, "second frame must be EXECUTE"


def _se_bit(asdu_data: bytes) -> int:
    """从命令 ASDU 数据对象读取 S/E 位 (1=选择, 0=执行)."""
    asdu = ASDU.decode(asdu_data)
    return 1 if bool(getattr(asdu.objects[0].data, "select", False)) else 0


@pytest.mark.asyncio
async def test_setpoint_non_sbo_point_single_frame():
    """设点 IOA 未命中 YK 点表 → 直发执行 (1 帧), 向后兼容."""
    ioa = 4002
    pt = PointTable()
    pt.common_addr = 1
    pt.add_yc(YcPointDef(ioa=ioa, name="YC4002"))  # 仅 YC 点, 无 YK 定义
    engine, _client = _make_master(point_table=pt)
    sent = await _install_frame_capture(engine)

    await engine.setpoint_shortfloat(ioa, 1.0)

    assert len(sent) == 1, "non-SBO setpoint must send a single EXECUTE frame"
    assert _se_bit(sent[0]) == 0, "non-SBO setpoint frame must be EXECUTE (S/E=0)"


@pytest.mark.asyncio
async def test_setpoint_sbo_point_explicit_select_only():
    """显式 select=True → 只发选择帧 (1 帧), 不受自动两段式影响."""
    ioa = 4003
    pt = _point_table_with_sbo(ioa, sbo=True)
    engine, _client = _make_master(point_table=pt)
    sent = await _install_frame_capture(engine)

    await engine.setpoint_shortfloat(ioa, 1.0, select=True)

    assert len(sent) == 1, "explicit select=True must send only the SELECT frame"
    assert _se_bit(sent[0]) == 1, "explicit select frame must have S/E=1"


@pytest.mark.asyncio
async def test_setpoint_sbo_point_select_rejected_aborts_before_execute():
    """设点 SBO 选择被拒 (PN=1) → 抛异常且绝不发执行帧.

    关键: NACK 必须**延迟**注入 —— 选择帧在 ``_wait_select_ack`` 登记 Future 之前
    就已发出，同步注入会被丢弃，导致测试退化为"等 t1 超时"的假阳性。此处用
    ``asyncio.create_task`` + ``await asyncio.sleep(0)`` 让出事件循环，确保等待者
    已注册后再注入 NACK；并用 ``wait_for`` 限制 1s 内完成，佐证走的是拒绝路径
    （真拒绝毫秒级；若误走超时，t1=15s 会被 wait_for 截断而失败）。
    """
    ioa = 4004
    pt = _point_table_with_sbo(ioa, sbo=True)
    engine, _client = _make_master()
    engine._point_table = pt
    sent: list[bytes] = []

    async def fake_send_command_asdu(asdu_data: bytes) -> None:
        sent.append(asdu_data)
        hdr = ASDU.decode(asdu_data)
        ioa_sent = hdr.objects[0].ioa

        async def _deferred_nack():
            await asyncio.sleep(0)  # 让出，等 _wait_select_ack 注册 Future
            engine._process_asdu(_cmd_ack_asdu(ioa_sent, COT.ACTCON, pn=True))

        asyncio.create_task(_deferred_nack())

    engine._send_command_asdu = fake_send_command_asdu  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="SBO select failed"):
        # 1s 上限: 真拒绝路径应毫秒级完成；若误走 15s 超时路径则超时失败
        await asyncio.wait_for(engine.setpoint_shortfloat(ioa, 1.0), timeout=1.0)

    assert len(sent) == 1, "must NOT send EXECUTE after rejected SELECT"
    # 确认 NACK 确实被等待者收到（而非被丢弃）
    assert ioa not in engine._pending_acks


@pytest.mark.asyncio
async def test_unknown_ioa_command_does_not_raise():
    """点表中不存在的 IOA (如 9999) 直发执行, 不抛异常 (缺陷 3)."""
    pt = _point_table_with_sbo(4001, sbo=True)
    engine, _client = _make_master(point_table=pt)
    sent: list[bytes] = []

    async def fake_send_command_asdu(asdu_data: bytes) -> None:
        sent.append(asdu_data)

    engine._send_command_asdu = fake_send_command_asdu  # type: ignore[method-assign]

    # 不应抛异常；不强制 SBO → 单帧
    await engine.single_command(9999, True)
    assert len(sent) == 1
