"""主站参数命令状态跟踪测试 (T08).

覆盖主站侧对参数命令应答的状态跟踪：

- 装载成功（ACTCON, PN=0）→ ``load_result == OK``
- 装载终止（ACTTERM）→ ``load_result == TERMINATED``
- 激活确认 → 激活终止（ACTCON → ACTTERM）→ 两个阶段可分别观测
- 否定确认（ACTCON, PN=1）→ ``REJECTED``
- 应答超时未回（t1 内无任何应答）→ ``TIMEOUT``
- 查询接口语义：未知 IOA 返回 None、返回快照副本、装载/激活两维互不干扰

全部用 Mock 传输层（不建真连接），写法参照 ``tests/test_master_engine.py``。

**确定性**：等待后台等待任务（``_wait_parameter_ack``）收敛一律用**显式推进
事件循环**（``_drive_until`` / ``_drain_background``，有界轮转 ``sleep(0)``），
且超时用例把 ``t1`` 置为 0——断言不再依赖真实时间与机器负载。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.engine.master import MasterEngine, ParameterResult
from core.protocol.asdu import ASDU, InformationObject
from core.protocol.types import COT, ConnState, TypeID

# ── fixtures / helpers ───────────────────────────────────────────

def _make_engine(**kwargs) -> MasterEngine:
    """构造主站引擎 + 模拟 TCPClient，并置状态机为 Running."""
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
    return engine


def _ack(type_id: TypeID, ioa: int, cot: int, pn: bool = False) -> ASDU:
    """构造参数命令应答 ASDU（对象数据与本用例无关，只需 IOA）."""
    asdu = ASDU(
        type_id=type_id, sq=False, num=1, cot=cot, pn=pn, common_addr=1,
    )
    asdu.objects.append(InformationObject(ioa=ioa))
    return asdu


async def _drive_until(predicate, *, rounds: int = 200) -> None:
    """显式推进事件循环直到 ``predicate()`` 为真.

    **不消耗真实时间**：仅以 ``await asyncio.sleep(0)`` 轮转事件循环，让引擎
    ``_spawn`` 派发的后台等待任务完成登记/唤醒/超时收尾。断言因此不依赖调度
    时机与机器负载（取代了原先「真实 sleep 0.2s 后再断言」的写法）。超过
    ``rounds`` 轮仍未成立即判失败，而不是靠等待「碰巧通过」。
    """
    for _ in range(rounds):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"显式驱动 {rounds} 轮后条件仍未成立")


async def _wait_ack_registered(engine: MasterEngine, ioa: int, kind: str) -> None:
    """推进到后台等待者已在 ``_pending_parameter_acks`` 登记（正在等 ACTCON）."""
    await _drive_until(lambda: (ioa, kind) in engine._pending_parameter_acks)


async def _wait_ack_settled(engine: MasterEngine, ioa: int, kind: str) -> None:
    """推进到后台等待者已收尾（被唤醒或超时）并把自己的登记项清理掉."""
    await _wait_ack_registered(engine, ioa, kind)
    await _drive_until(lambda: (ioa, kind) not in engine._pending_parameter_acks)


async def _drain_background(engine: MasterEngine) -> None:
    """推进到引擎派发的后台任务全部结束（含被撤销者完成取消）."""
    await _drive_until(
        lambda: not [t for t in engine._background_tasks if not t.done()]
    )


@pytest.fixture
def engine() -> MasterEngine:
    return _make_engine(t1=0.1)


# ── 装载 / ACTCON / ACTTERM ──────────────────────────────────────

@pytest.mark.asyncio
async def test_load_actcon_records_ok(engine):
    """装载成功：ACTCON(PN=0) → load_result=OK，并记录 COT 与时间戳."""
    ioa = 100
    await engine.parameter_normalized(ioa, 0.75)
    await _wait_ack_registered(engine, ioa, "load")

    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))
    await _wait_ack_settled(engine, ioa, "load")

    st = engine.get_parameter_state(ioa)
    assert st is not None
    assert st.load_result is ParameterResult.OK
    assert st.load_cot == COT.ACTCON
    assert st.load_updated_at is not None
    assert (ioa, "load") not in engine._pending_parameter_acks


@pytest.mark.asyncio
async def test_load_actterm_records_terminated(engine):
    """装载终止：ACTTERM → load_result=TERMINATED（与 ACTCON 区分）."""
    ioa = 101
    await engine.parameter_float(ioa, 220.5)
    await _wait_ack_registered(engine, ioa, "load")

    engine._process_asdu(_ack(TypeID.P_ME_NC_1, ioa, COT.ACTCON))
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.OK

    engine._process_asdu(_ack(TypeID.P_ME_NC_1, ioa, COT.ACTTERM))
    await _wait_ack_settled(engine, ioa, "load")

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.TERMINATED
    assert st.load_cot == COT.ACTTERM


# ── 激活 ACTCON → ACTTERM ────────────────────────────────────────

@pytest.mark.asyncio
async def test_activation_actcon_then_actterm(engine):
    """激活流程：ACTCON → activation_result=OK；随后 ACTTERM → TERMINATED."""
    ioa = 200
    await engine.parameter_activation(ioa, 1)
    await _wait_ack_registered(engine, ioa, "activation")

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTCON))
    await _wait_ack_settled(engine, ioa, "activation")
    st = engine.get_parameter_state(ioa)
    assert st.activation_result is ParameterResult.OK
    assert st.activation_cot == COT.ACTCON

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTTERM))
    st = engine.get_parameter_state(ioa)
    assert st.activation_result is ParameterResult.TERMINATED
    assert st.activation_cot == COT.ACTTERM
    # 装载维度未被激活应答污染
    assert st.load_result is ParameterResult.UNKNOWN


# ── 否定确认 PN=1 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_negative_confirmation_records_rejected(engine):
    """否定确认：ACTCON 携带 PN=1 → load_result=REJECTED（COT 仍为 ACTCON）."""
    ioa = 300
    await engine.parameter_scaled(ioa, 500)
    await _wait_ack_registered(engine, ioa, "load")

    engine._process_asdu(_ack(TypeID.P_ME_NB_1, ioa, COT.ACTCON, pn=True))
    await _wait_ack_settled(engine, ioa, "load")

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.REJECTED
    assert st.load_cot == COT.ACTCON
    assert (ioa, "load") not in engine._pending_parameter_acks


@pytest.mark.asyncio
async def test_negative_activation_confirmation_records_rejected(engine):
    """激活被拒：P_AC_NA_1 + ACTCON(PN=1) → activation_result=REJECTED."""
    ioa = 301
    await engine.parameter_activation(ioa, 1)
    await _wait_ack_registered(engine, ioa, "activation")

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTCON, pn=True))
    await _wait_ack_settled(engine, ioa, "activation")

    st = engine.get_parameter_state(ioa)
    assert st.activation_result is ParameterResult.REJECTED
    assert st.activation_cot == COT.ACTCON


# ── 应答超时 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_recorded_when_no_reply():
    """应答超时未回：t1 内无应答 → TIMEOUT（下发后立即查询应为 PENDING）.

    ``t1=0`` 使超时成为确定事件（一轮事件循环即到期），无需真实等待。
    """
    engine = _make_engine(t1=0.0)
    ioa = 400

    await engine.parameter_normalized(ioa, 0.5)
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.PENDING

    await _wait_ack_settled(engine, ioa, "load")

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.TIMEOUT
    assert st.load_updated_at is not None
    assert (ioa, "load") not in engine._pending_parameter_acks


@pytest.mark.asyncio
async def test_timeout_does_not_overwrite_confirmed_result():
    """竞态防护：ACTCON 先于等待者登记到达时，超时不得把 OK 覆盖为 TIMEOUT.

    与 SBO 侧同类竞态的修复经验一致：ACTTERM 等滞后帧不唤醒等待；等待者超时
    只在状态仍为 PENDING 时写入 TIMEOUT。``t1=0`` 让该竞态成为**确定**前置条件
    （ACTCON 必然先于登记到达），不再依赖调度运气。
    """
    engine = _make_engine(t1=0.0)
    ioa = 401

    await engine.parameter_normalized(ioa, 0.5)
    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))  # 先于登记到达

    await _wait_ack_settled(engine, ioa, "load")  # 等待者必然超时并收尾

    assert engine.get_parameter_state(ioa).load_result is ParameterResult.OK


@pytest.mark.asyncio
async def test_actterm_alone_does_not_wake_waiter():
    """滞后 ACTTERM 不唤醒等待：随后无 ACTCON → 仍记 TIMEOUT（不误判为成功）."""
    engine = _make_engine(t1=0.0)
    ioa = 402

    await engine.parameter_activation(ioa, 1)
    await _wait_ack_registered(engine, ioa, "activation")

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTTERM))
    assert engine.get_parameter_state(ioa).activation_result is ParameterResult.TERMINATED

    await _wait_ack_settled(engine, ioa, "activation")
    # ACTTERM 已写入终态，超时不得覆盖
    assert engine.get_parameter_state(ioa).activation_result is ParameterResult.TERMINATED


# ── 查询接口语义 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_unknown_ioa_returns_none(engine):
    """从未下发过的 IOA → get_parameter_state 返回 None."""
    assert engine.get_parameter_state(9999) is None
    assert engine.parameter_states() == {}


@pytest.mark.asyncio
async def test_query_returns_snapshot_copy(engine):
    """查询返回快照副本：外部修改不影响引擎内部状态."""
    ioa = 500
    await engine.parameter_normalized(ioa, 0.5)
    await _wait_ack_registered(engine, ioa, "load")
    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))
    await _wait_ack_settled(engine, ioa, "load")

    snapshot = engine.get_parameter_state(ioa)
    snapshot.load_result = ParameterResult.TIMEOUT
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.OK

    states = engine.parameter_states()
    assert set(states) == {ioa}
    states[ioa].load_result = ParameterResult.UNKNOWN
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.OK


@pytest.mark.asyncio
async def test_load_and_activation_tracked_independently(engine):
    """同一 IOA 的装载与激活两维独立记录，互不覆盖."""
    ioa = 600
    await engine.parameter_normalized(ioa, 0.25)
    await _wait_ack_registered(engine, ioa, "load")
    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))
    await _wait_ack_settled(engine, ioa, "load")

    await engine.parameter_activation(ioa, 1)
    await _wait_ack_registered(engine, ioa, "activation")
    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTCON))
    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTTERM))
    await _wait_ack_settled(engine, ioa, "activation")

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.OK
    assert st.activation_result is ParameterResult.TERMINATED


@pytest.mark.asyncio
async def test_send_failure_rolls_back_pending_state():
    """下发失败（未进入 Running）→ 抛异常且状态回退 UNKNOWN，不误记为超时.

    显式驱动到后台等待者被**完全撤销**（而非「等 0.2s 看它没变」）：若撤销失效，
    等待者会在 t1 后写入 TIMEOUT，本用例即失败。
    """
    engine = _make_engine(t1=0.05)
    engine._state_machine._state = ConnState.STOPPED
    ioa = 700

    with pytest.raises(RuntimeError, match="Not in running state"):
        await engine.parameter_normalized(ioa, 0.5)

    assert engine.get_parameter_state(ioa).load_result is ParameterResult.UNKNOWN

    await _drain_background(engine)   # 等待者必须已被撤销并回收
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.UNKNOWN
