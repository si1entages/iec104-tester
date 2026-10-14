"""主站参数命令状态跟踪测试 (T08).

覆盖主站侧对参数命令应答的状态跟踪：

- 装载成功（ACTCON, PN=0）→ ``load_result == OK``
- 装载终止（ACTTERM）→ ``load_result == TERMINATED``
- 激活确认 → 激活终止（ACTCON → ACTTERM）→ 两个阶段可分别观测
- 否定确认（ACTCON, PN=1）→ ``REJECTED``
- 应答超时未回（t1 内无任何应答）→ ``TIMEOUT``
- 查询接口语义：未知 IOA 返回 None、返回快照副本、装载/激活两维互不干扰

全部用 Mock 传输层（不建真连接），写法参照 ``tests/test_master_engine.py``。
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


@pytest.fixture
def engine() -> MasterEngine:
    return _make_engine(t1=0.1)


# ── 装载 / ACTCON / ACTTERM ──────────────────────────────────────

@pytest.mark.asyncio
async def test_load_actcon_records_ok(engine):
    """装载成功：ACTCON(PN=0) → load_result=OK，并记录 COT 与时间戳."""
    ioa = 100
    await engine.parameter_normalized(ioa, 0.75)
    await asyncio.sleep(0)  # 让后台等待者登记 Future（与 SBO 测试同法）

    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))
    await asyncio.sleep(0)  # 让等待者收尾并从登记表清理

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
    await asyncio.sleep(0)

    engine._process_asdu(_ack(TypeID.P_ME_NC_1, ioa, COT.ACTCON))
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.OK

    engine._process_asdu(_ack(TypeID.P_ME_NC_1, ioa, COT.ACTTERM))
    await asyncio.sleep(0)

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.TERMINATED
    assert st.load_cot == COT.ACTTERM


# ── 激活 ACTCON → ACTTERM ────────────────────────────────────────

@pytest.mark.asyncio
async def test_activation_actcon_then_actterm(engine):
    """激活流程：ACTCON → activation_result=OK；随后 ACTTERM → TERMINATED."""
    ioa = 200
    await engine.parameter_activation(ioa, 1)
    await asyncio.sleep(0)

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTCON))
    await asyncio.sleep(0)
    st = engine.get_parameter_state(ioa)
    assert st.activation_result is ParameterResult.OK
    assert st.activation_cot == COT.ACTCON

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTTERM))
    await asyncio.sleep(0)
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
    await asyncio.sleep(0)

    engine._process_asdu(_ack(TypeID.P_ME_NB_1, ioa, COT.ACTCON, pn=True))
    await asyncio.sleep(0)

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.REJECTED
    assert st.load_cot == COT.ACTCON
    assert (ioa, "load") not in engine._pending_parameter_acks


@pytest.mark.asyncio
async def test_negative_activation_confirmation_records_rejected(engine):
    """激活被拒：P_AC_NA_1 + ACTCON(PN=1) → activation_result=REJECTED."""
    ioa = 301
    await engine.parameter_activation(ioa, 1)
    await asyncio.sleep(0)

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTCON, pn=True))
    await asyncio.sleep(0)

    st = engine.get_parameter_state(ioa)
    assert st.activation_result is ParameterResult.REJECTED
    assert st.activation_cot == COT.ACTCON


# ── 应答超时 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_recorded_when_no_reply():
    """应答超时未回：t1 内无应答 → TIMEOUT（下发后立即查询应为 PENDING）."""
    engine = _make_engine(t1=0.05)
    ioa = 400

    await engine.parameter_normalized(ioa, 0.5)
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.PENDING

    await asyncio.sleep(0.2)  # 超过 t1

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.TIMEOUT
    assert st.load_updated_at is not None
    assert (ioa, "load") not in engine._pending_parameter_acks


@pytest.mark.asyncio
async def test_timeout_does_not_overwrite_confirmed_result():
    """竞态防护：ACTCON 先于等待者登记到达时，超时不得把 OK 覆盖为 TIMEOUT.

    与 SBO 侧同类竞态的修复经验一致：ACTTERM 等滞后帧不唤醒等待；等待者超时
    只在状态仍为 PENDING 时写入 TIMEOUT。
    """
    engine = _make_engine(t1=0.05)
    ioa = 401

    await engine.parameter_normalized(ioa, 0.5)
    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))  # 先于登记到达

    await asyncio.sleep(0.2)  # 等待者必然超时

    assert engine.get_parameter_state(ioa).load_result is ParameterResult.OK


@pytest.mark.asyncio
async def test_actterm_alone_does_not_wake_waiter():
    """滞后 ACTTERM 不唤醒等待：随后无 ACTCON → 仍记 TIMEOUT（不误判为成功）."""
    engine = _make_engine(t1=0.05)
    ioa = 402

    await engine.parameter_activation(ioa, 1)
    await asyncio.sleep(0)

    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTTERM))
    assert engine.get_parameter_state(ioa).activation_result is ParameterResult.TERMINATED

    await asyncio.sleep(0.2)
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
    await asyncio.sleep(0)
    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))
    await asyncio.sleep(0)

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
    await asyncio.sleep(0)
    engine._process_asdu(_ack(TypeID.P_ME_NA_1, ioa, COT.ACTCON))
    await asyncio.sleep(0)

    await engine.parameter_activation(ioa, 1)
    await asyncio.sleep(0)
    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTCON))
    engine._process_asdu(_ack(TypeID.P_AC_NA_1, ioa, COT.ACTTERM))
    await asyncio.sleep(0)

    st = engine.get_parameter_state(ioa)
    assert st.load_result is ParameterResult.OK
    assert st.activation_result is ParameterResult.TERMINATED


@pytest.mark.asyncio
async def test_send_failure_rolls_back_pending_state():
    """下发失败（未进入 Running）→ 抛异常且状态回退 UNKNOWN，不误记为超时."""
    engine = _make_engine(t1=0.05)
    engine._state_machine._state = ConnState.STOPPED
    ioa = 700

    with pytest.raises(RuntimeError, match="Not in running state"):
        await engine.parameter_normalized(ioa, 0.5)

    assert engine.get_parameter_state(ioa).load_result is ParameterResult.UNKNOWN

    await asyncio.sleep(0.2)  # 等待者已撤销，不得落入 TIMEOUT
    assert engine.get_parameter_state(ioa).load_result is ParameterResult.UNKNOWN
