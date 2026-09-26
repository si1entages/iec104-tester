"""协议符合性修复回归测试 (P2 批次, Task #6-#9).

覆盖:
- #6 TypeID 58-64 带时标 CP56Time2a 控制命令的编解码 + 子站 ACTCON 回显 + 主站发送
- #7 COT 42/43/44 未知类型/传送原因/公共地址应答 + 主站优雅处理
- #8 子站 t0 移除 / t1 覆盖 U 帧 / 主站 k 耗尽等待 t1 / 失序断开策略统一
- #9 CP24 时标保真 (13 字节) / M_ME_ND_1 (11 字节) / ProtectionEvent.to_bytes / M_PS_NA_1 对称
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.state_machine import ConnectionStateMachine, TimerType
from core.protocol.types import (
    COT,
    CP24Time2a,
    CP56Time2a,
    ProtectionEvent,
    QualityDescriptor,
    SingleCommand,
    SinglePoint,
    TypeID,
)

# ═══════════════════════════════════════════════════════════════════
#  公共 helper
# ═══════════════════════════════════════════════════════════════════

def _fixed_time() -> CP56Time2a:
    """固定 CP56Time2a，便于确定性断言."""
    return CP56Time2a(millisecond=12345, minute=30, hour=12,
                      day=1, month=6, year=24, weekday=6)


def _make_slave() -> tuple[SlaveEngine, MagicMock, object]:
    """构造子站引擎 + 单个已连接客户端，返回 (engine, conn, state)."""
    with patch("core.engine.slave.TCPServer"):
        engine = SlaveEngine(host="0.0.0.0", port=2404, common_addr=1)
    conn = MagicMock()
    conn.name = "c1"
    conn.is_connected = True
    conn.send_frame = AsyncMock()
    conn.stop = AsyncMock()
    engine._on_client_connected(conn)
    state = engine._client_states["c1"]
    state.data_transfer_enabled = True
    return engine, conn, state


def _make_master(**kwargs) -> tuple[MasterEngine, MagicMock]:
    """构造主站引擎 + 模拟 TCPClient，返回 (engine, client)."""
    with patch("core.engine.master.TCPClient") as MockClient:
        client = MockClient.return_value
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.disconnect = AsyncMock()
        client.send = AsyncMock()
        client.stats = MagicMock()
        engine = MasterEngine(host="127.0.0.1", port=2404, common_addr=1,
                              auto_start=False, auto_gi=False, reconnect=False, **kwargs)
    from core.protocol.types import ConnState
    engine._state_machine._state = ConnState.RUNNING
    return engine, client


def _apci_of(frame: bytes):
    """从完整帧中解析出 APCI 头对象."""
    apci, _consumed = APCICodec.decode(frame)
    return apci


# ═══════════════════════════════════════════════════════════════════
#  #6: TypeID 58-64 带时标控制命令 (round-trip 长度)
# ═══════════════════════════════════════════════════════════════════

def test_typeid_58_to_64_values():
    """类型标识 58-64 数值应与标准一致."""
    assert TypeID.C_SC_TA_1 == 58
    assert TypeID.C_DC_TA_1 == 59
    assert TypeID.C_RC_TA_1 == 60
    assert TypeID.C_SE_TA_1 == 61
    assert TypeID.C_SE_TB_1 == 62
    assert TypeID.C_SE_TC_1 == 63
    assert TypeID.C_BO_TA_1 == 64


def test_c_sc_ta_1_roundtrip():
    raw = ASDUBuilder.build_single_command_with_time(1, 100, True, time_tag=_fixed_time())
    assert len(raw) == 17  # 6(头) + 3(IOA) + 1(命令) + 7(CP56)
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_SC_TA_1
    assert dec.cot == COT.ACT
    assert dec.objects[0].data.state is True
    assert isinstance(dec.objects[0].time_tag, CP56Time2a)
    assert len(dec.encode()) == 17


def test_c_dc_ta_1_roundtrip():
    raw = ASDUBuilder.build_double_command_with_time(1, 200, 2, time_tag=_fixed_time())
    assert len(raw) == 17
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_DC_TA_1
    assert dec.objects[0].data.state == 2
    assert len(dec.encode()) == 17


def test_c_rc_ta_1_roundtrip():
    raw = ASDUBuilder.build_regulating_step_command_with_time(1, 300, 2, time_tag=_fixed_time())
    assert len(raw) == 17
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_RC_TA_1
    assert dec.objects[0].data.state == 2
    assert len(dec.encode()) == 17


def test_c_se_ta_1_roundtrip():
    raw = ASDUBuilder.build_setpoint_normalized_with_time(1, 400, 0.5, time_tag=_fixed_time())
    assert len(raw) == 19  # 6 + 3 + 3 + 7
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_SE_TA_1
    assert abs(dec.objects[0].data.value - 0.5) < 0.001
    assert len(dec.encode()) == 19


def test_c_se_tb_1_roundtrip():
    raw = ASDUBuilder.build_setpoint_scaled_with_time(1, 400, 12345, time_tag=_fixed_time())
    assert len(raw) == 19
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_SE_TB_1
    assert dec.objects[0].data.value == 12345
    assert len(dec.encode()) == 19


def test_c_se_tc_1_roundtrip():
    raw = ASDUBuilder.build_setpoint_shortfloat_with_time(1, 400, 220.5, time_tag=_fixed_time())
    assert len(raw) == 21  # 6 + 3 + 5 + 7
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_SE_TC_1
    assert abs(dec.objects[0].data.value - 220.5) < 0.1
    assert len(dec.encode()) == 21


def test_c_bo_ta_1_roundtrip():
    raw = ASDUBuilder.build_bitstring_command_with_time(1, 500, 0x12345678, time_tag=_fixed_time())
    assert len(raw) == 20  # 6 + 3 + 4 + 7
    dec = ASDU.decode(raw)
    assert dec.type_id == TypeID.C_BO_TA_1
    assert dec.objects[0].data.value == 0x12345678
    assert len(dec.encode()) == 20


@pytest.mark.asyncio
async def test_slave_ta_single_command_echoes_same_type():
    """子站对 C_SC_TA_1 的 ACTCON 回显须保持同类型并带时标."""
    engine, conn, state = _make_slave()
    asdu = ASDU(type_id=TypeID.C_SC_TA_1, sq=False, num=1, cot=COT.ACT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=100, data=SingleCommand(ioa=100, state=True, select=True),
        time_tag=_fixed_time(),
    ))
    await engine._handle_single_command(state, asdu)

    frame = conn.send_frame.call_args[0][0]
    dec = ASDU.decode(frame[6:])
    assert dec.type_id == TypeID.C_SC_TA_1
    assert dec.cot == COT.ACTCON
    assert isinstance(dec.objects[0].time_tag, CP56Time2a)


@pytest.mark.asyncio
async def test_slave_ta_command_dispatched_via_process_asdu():
    """C_DC_TA_1 经 _process_asdu 分发后应回 ACTCON (同类型)."""
    engine, conn, state = _make_slave()
    raw = ASDUBuilder.build_double_command_with_time(1, 200, 2, time_tag=_fixed_time())
    frame = APCICodec.encode_i(0, 0, raw)
    engine._handle_i_frame(state, _apci_of(frame), frame)
    await _drain()

    frame_sent = conn.send_frame.call_args[0][0]
    dec = ASDU.decode(frame_sent[6:])
    assert dec.type_id == TypeID.C_DC_TA_1
    assert dec.cot == COT.ACTCON


@pytest.mark.asyncio
async def test_master_ta_send_methods():
    """主站带时标发送方法应产生正确类型/长度帧."""
    cases = [
        ("single_command_with_time", (100, True), TypeID.C_SC_TA_1, 17),
        ("double_command_with_time", (200, 2), TypeID.C_DC_TA_1, 17),
        ("regulating_step_command_with_time", (300, 2), TypeID.C_RC_TA_1, 17),
        ("setpoint_normalized_with_time", (400, 0.5), TypeID.C_SE_TA_1, 19),
        ("setpoint_scaled_with_time", (400, 12345), TypeID.C_SE_TB_1, 19),
        ("setpoint_shortfloat_with_time", (400, 220.5), TypeID.C_SE_TC_1, 21),
        ("bitstring_command_with_time", (500, 0x12345678), TypeID.C_BO_TA_1, 20),
    ]
    for method_name, args, expected_type, expected_len in cases:
        engine, client = _make_master()
        await getattr(engine, method_name)(*args)
        frame = client.send.call_args[0][0]
        dec = ASDU.decode(frame[6:])
        assert dec.type_id == expected_type, method_name
        assert len(frame[6:]) == expected_len, method_name


@pytest.mark.asyncio
async def test_master_ta_command_ack_updates_yk():
    """主站应能处理带时标命令的 ACTCON 确认."""
    engine, _client = _make_master()
    asdu = ASDU(type_id=TypeID.C_SC_TA_1, sq=False, num=1, cot=COT.ACTCON, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=100, data=SingleCommand(ioa=100, state=True), time_tag=_fixed_time(),
    ))
    engine._process_asdu(asdu)
    yk = engine._data_store.get_yk(100)
    assert yk is not None
    assert yk.last_command == "ack"


# ═══════════════════════════════════════════════════════════════════
#  #7: COT 42/43/44 未知类型/原因/地址应答
# ═══════════════════════════════════════════════════════════════════

def test_cot_unknown_constants():
    assert COT.UNKNOWN_TYPE == 42
    assert COT.UNKNOWN_COT == 43
    assert COT.UNKNOWN_CA == 44
    assert COT.UNKNOWN_IOA == 45


def test_decode_header_parses_unknown_type():
    """decode_header 对未知类型不应抛错，保留原始 TypeID 整数."""
    asdu_data = bytes([55, 0x01, COT.ACT, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
    header = ASDU.decode_header(asdu_data)
    assert header.type_id == 55
    assert header.cot == COT.ACT
    assert header.common_addr == 1
    assert header.objects == []


def test_decode_raises_on_unknown_type():
    """ASDU.decode 遇未知类型应抛 ValueError（用于触发 COT=42 应答）."""
    asdu_data = bytes([55, 0x01, COT.ACT, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
    with pytest.raises(ValueError):
        ASDU.decode(asdu_data)


@pytest.mark.asyncio
async def test_slave_unknown_type_replies_cot42():
    """未知 TypeID → 子站回送 COT=42，且连接保持."""
    engine, conn, state = _make_slave()
    asdu_data = bytes([55, 0x01, COT.ACT, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
    frame = APCICodec.encode_i(0, 0, asdu_data)
    engine._handle_i_frame(state, _apci_of(frame), frame)
    await _drain()

    sent = conn.send_frame.call_args[0][0]
    dec = ASDU.decode_header(sent[6:])
    assert dec.cot == COT.UNKNOWN_TYPE
    assert dec.type_id == 55
    assert conn.stop.called is False  # 连接保持


@pytest.mark.asyncio
async def test_slave_unknown_ca_replies_cot44():
    """公共地址不匹配 → 子站回送 COT=44."""
    engine, conn, state = _make_slave()
    asdu = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=99)
    asdu.objects.append(InformationObject(ioa=100, data=SingleCommand(ioa=100, state=True)))
    engine._process_asdu(state, asdu)
    await _drain()

    dec = ASDU.decode(conn.send_frame.call_args[0][0][6:])
    assert dec.cot == COT.UNKNOWN_CA


@pytest.mark.asyncio
async def test_slave_unknown_cot_replies_cot43():
    """未知传送原因 → 子站回送 COT=43."""
    engine, conn, state = _make_slave()
    asdu = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=1, cot=60, common_addr=1)
    asdu.objects.append(InformationObject(ioa=100, data=SingleCommand(ioa=100, state=True)))
    engine._process_asdu(state, asdu)
    await _drain()

    dec = ASDU.decode(conn.send_frame.call_args[0][0][6:])
    assert dec.cot == COT.UNKNOWN_COT


@pytest.mark.asyncio
async def test_master_handles_cot42_gracefully():
    """主站收到 COT=42 应答应触发事件但不抛出/不断连."""
    engine, client = _make_master()
    events: list = []
    engine.set_event_callback(lambda e, d: events.append((e, d)))

    asdu = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=0, cot=COT.UNKNOWN_TYPE, common_addr=1)
    engine._process_asdu(asdu)
    assert client.stop.called is False
    assert any(d.get("error_reply") for _e, d in events)


@pytest.mark.asyncio
async def test_master_handles_cot44_with_echoed_wrong_ca():
    """COT=44 应答会回显错误 CA，主站仍须优雅处理（不被地址校验丢弃）."""
    engine, client = _make_master()
    events: list = []
    engine.set_event_callback(lambda e, d: events.append((e, d)))

    # 回显的 CA=99 ≠ 本地 CA=1
    asdu = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=0, cot=COT.UNKNOWN_CA, common_addr=99)
    engine._process_asdu(asdu)
    assert client.stop.called is False
    assert any(d.get("error_reply") for _e, d in events)


# ═══════════════════════════════════════════════════════════════════
#  #8: t0 归属 / t1 覆盖 U 帧 / k 耗尽对称 / 失序策略统一
# ═══════════════════════════════════════════════════════════════════

def test_slave_state_machine_has_no_t0():
    """被控站 (use_t0=False) 不应启动 t0."""
    sm = ConnectionStateMachine(t0=0.05, use_t0=False)
    sm.on_connected()
    time.sleep(0.12)
    assert sm.check_timers() is None


def test_control_station_state_machine_uses_t0():
    """控制站 (use_t0=True) 应启动并在超时后返回 t0."""
    sm = ConnectionStateMachine(t0=0.05, use_t0=True)
    sm.on_connected()
    time.sleep(0.12)
    assert sm.check_timers() == TimerType.T0


def test_u_frame_act_sent_starts_t1():
    """STOPDT/TESTFR ACT 发送后应启动 t1（覆盖 U 帧）."""
    sm = ConnectionStateMachine(t1=0.05)
    sm.on_u_frame_act_sent()
    time.sleep(0.12)
    assert sm.check_timers() == TimerType.T1


def test_startdt_act_sent_also_starts_t1():
    sm = ConnectionStateMachine(t1=0.05)
    sm.on_startdt_act_sent()
    info = sm.get_timer_info()
    assert info[TimerType.T1].active is True


@pytest.mark.asyncio
async def test_master_k_exhaustion_waits_t1_then_raises():
    """主站 k 窗口耗尽时应等待 t1 后抛 RuntimeError（与子站对称）."""
    engine, _client = _make_master(k=2, t1=0.2)
    await engine.general_interrogation()   # seq 0
    await engine.general_interrogation()   # seq 1 → 窗口满
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="t1"):
        await engine.general_interrogation()
    assert time.monotonic() - t0 >= 0.15  # 确实等待了 t1


@pytest.mark.asyncio
async def test_master_out_of_order_disconnects():
    """主站收到失序 I 帧应断开连接（与子站策略统一）."""
    engine, client = _make_master()
    asdu_data = ASDUBuilder.build_general_interrogation_ack(1, 20)
    frame = APCICodec.encode_i(5, 0, asdu_data)  # 期望 tx_seq=0
    engine._on_frame_received(frame)
    await _drain()
    # 使用 disconnect()（仅重建连接，保留重连循环），而非 stop()
    assert client.disconnect.called is True


@pytest.mark.asyncio
async def test_slave_out_of_order_disconnects():
    """子站收到失序 I 帧应断开连接."""
    engine, conn, state = _make_slave()
    asdu_data = ASDUBuilder.build_general_interrogation_ack(1, 20)
    frame = APCICodec.encode_i(5, 0, asdu_data)  # 期望 tx_seq=0
    engine._handle_i_frame(state, _apci_of(frame), frame)
    await _drain()
    assert conn.stop.called is True


# ═══════════════════════════════════════════════════════════════════
#  #9: CP24 时标保真 / M_ME_ND_1 长度 / ProtectionEvent / M_PS_NA_1
# ═══════════════════════════════════════════════════════════════════

def test_m_sp_ta_1_uses_cp24_13_bytes():
    """M_SP_TA_1 时标须为 CP24Time2a，编解码保持 13 字节（不得膨胀为 17）."""
    asdu = ASDU(type_id=TypeID.M_SP_TA_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=1, data=SinglePoint(value=True),
        time_tag=CP24Time2a(millisecond=12345, minute=30),
    ))
    raw = asdu.encode()
    assert len(raw) == 13  # 6 + 3 + 1 + 3

    dec = ASDU.decode(raw)
    assert isinstance(dec.objects[0].time_tag, CP24Time2a)
    assert dec.objects[0].time_tag.millisecond == 12345
    assert len(dec.encode()) == 13  # round-trip 不膨胀


def test_m_sp_tb_1_uses_cp56_17_bytes():
    """对照组: M_SP_TB_1 时标为 CP56Time2a，长度 17 字节."""
    asdu = ASDU(type_id=TypeID.M_SP_TB_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=1, data=SinglePoint(value=True), time_tag=_fixed_time(),
    ))
    assert len(asdu.encode()) == 17
    dec = ASDU.decode(asdu.encode())
    assert isinstance(dec.objects[0].time_tag, CP56Time2a)
    assert len(dec.encode()) == 17


def test_m_me_nd_1_is_11_bytes():
    """M_ME_ND_1 信息体仅 2 字节 NVA（无 QDS），ASDU 共 11 字节."""
    from core.protocol.types import NormalizedValue
    asdu = ASDU(type_id=TypeID.M_ME_ND_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=1, data=NormalizedValue(value=0.5, quality=QualityDescriptor()),
    ))
    raw = asdu.encode()
    assert len(raw) == 11  # 6 + 3 + 2

    dec = ASDU.decode(raw)
    assert abs(dec.objects[0].data.value - 0.5) < 0.001
    assert len(dec.encode()) == 11


def test_m_me_na_1_is_12_bytes():
    """对照组: M_ME_NA_1 带 QDS，长度 12 字节."""
    from core.protocol.types import NormalizedValue
    asdu = ASDU(type_id=TypeID.M_ME_NA_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=1, data=NormalizedValue(value=0.5, quality=QualityDescriptor()),
    ))
    assert len(asdu.encode()) == 12


def test_protection_event_to_bytes():
    """ProtectionEvent.to_bytes 应输出 3 字节 (event 2 + QDP 1)，不含时标."""
    pe = ProtectionEvent(ioa=1, event_value=0x0102, quality=QualityDescriptor(0x00))
    data = pe.to_bytes()
    assert len(data) == 3
    assert data == bytes([0x02, 0x01, 0x00])


def test_m_ep_ta_1_roundtrip_15_bytes():
    """M_EP_TA_1 (CP24) 编解码 15 字节，事件值与时标保真."""
    asdu = ASDU(type_id=TypeID.M_EP_TA_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=1, data=ProtectionEvent(ioa=1, event_value=0x0102),
        time_tag=CP24Time2a(millisecond=1234, minute=30),
    ))
    raw = asdu.encode()
    assert len(raw) == 15  # 6 + 3 + 3 + 3
    dec = ASDU.decode(raw)
    assert dec.objects[0].data.event_value == 0x0102
    assert isinstance(dec.objects[0].time_tag, CP24Time2a)
    assert len(dec.encode()) == 15


def test_m_ep_td_1_roundtrip_19_bytes():
    """M_EP_TD_1 (CP56) 编解码 19 字节."""
    asdu = ASDU(type_id=TypeID.M_EP_TD_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=1, data=ProtectionEvent(ioa=1, event_value=0x0203), time_tag=_fixed_time(),
    ))
    raw = asdu.encode()
    assert len(raw) == 19  # 6 + 3 + 3 + 7
    dec = ASDU.decode(raw)
    assert dec.objects[0].data.event_value == 0x0203
    assert isinstance(dec.objects[0].time_tag, CP56Time2a)
    assert len(dec.encode()) == 19


@pytest.mark.parametrize("type_id,expected_len", [
    (TypeID.M_EP_TA_1, 15),
    (TypeID.M_EP_TB_1, 15),
    (TypeID.M_EP_TC_1, 15),
    (TypeID.M_EP_TD_1, 19),
    (TypeID.M_EP_TE_1, 19),
    (TypeID.M_EP_TF_1, 19),
])
def test_all_protection_event_types_roundtrip(type_id, expected_len):
    """全部 6 种继电保护事件类型编解码成功且长度正确."""
    short = type_id in (TypeID.M_EP_TA_1, TypeID.M_EP_TB_1, TypeID.M_EP_TC_1)
    asdu = ASDU(type_id=type_id, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    tt = CP24Time2a(millisecond=500, minute=10) if short else _fixed_time()
    asdu.objects.append(InformationObject(
        ioa=1, data=ProtectionEvent(ioa=1, event_value=0x00FF), time_tag=tt,
    ))
    raw = asdu.encode()
    assert len(raw) == expected_len
    dec = ASDU.decode(raw)
    assert dec.objects[0].data.event_value == 0x00FF
    assert len(dec.encode()) == expected_len


def test_m_ps_na_1_symmetric():
    """M_PS_NA_1 成组单点编解码对称."""
    from core.protocol.types import GroupSinglePointWithStatus
    pts = [(True, True), (False, True), (True, False)]
    asdu = ASDU(type_id=TypeID.M_PS_NA_1, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    asdu.objects.append(InformationObject(ioa=1, data=GroupSinglePointWithStatus(points=pts)))
    raw = asdu.encode()
    assert len(raw) == 11  # 6 + 3 + 2
    dec = ASDU.decode(raw)
    assert dec.objects[0].data.points[:3] == pts
    assert len(dec.encode()) == 11


# ═══════════════════════════════════════════════════════════════════
#  QA 回归 (Round 1 发现): 假 NACK (Bug A) / 失序状态残留 (Bug B)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_master_positive_select_ack_is_not_nack():
    """Bug A 回归: SBO 选择确认 (命令字节 S/E=1) 不得被误判为 NACK.

    C_SC_NA_1 COT=ACTCON、pn=False，命令数据字节 bit7=1 (选择) →
    主站必须记为 ack（不再退回解析数据字节 bit7）。
    """
    engine, _client = _make_master()
    cmd = SingleCommand(ioa=2001, state=True, select=True)
    assert (cmd.to_bytes()[0] & 0x80) == 0x80  # 前置: S/E 位确为 1

    asdu = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=1, cot=COT.ACTCON, common_addr=1)
    asdu.objects.append(InformationObject(ioa=2001, data=cmd))
    engine._process_asdu(asdu)

    yk = engine._data_store.get_yk(2001)
    assert yk is not None
    assert yk.last_command == "ack"


@pytest.mark.asyncio
async def test_master_true_nack_still_recorded_as_nack():
    """Bug A 回归: 真否定确认 (COT bit6 pn=1) 仍须记为 NACK."""
    engine, _client = _make_master()
    asdu = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                cot=COT.ACTCON, pn=True, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=2002, data=SingleCommand(ioa=2002, state=True, select=False),
    ))
    engine._process_asdu(asdu)

    yk = engine._data_store.get_yk(2002)
    assert yk is not None
    assert yk.last_command == "nack"


@pytest.mark.asyncio
async def test_tcpclient_disconnect_closes_connection_keeps_loop():
    """Bug B 回归: disconnect() 仅关底层连接，保留重连循环 (区别于 stop)."""
    from core.transport.connection import TCPClient
    client = TCPClient()
    conn = MagicMock()
    conn.stop = AsyncMock()
    client._connection = conn
    client._running = True

    await client.disconnect()

    conn.stop.assert_awaited_once()
    assert client._running is True          # 重连循环未被停止
    assert client._connection is conn       # 引用未被清空


@pytest.mark.asyncio
async def test_master_out_of_order_e2e_leaves_running_state():
    """Bug B 回归 (真 TCP): 失序后主站状态机应离开 Running 并触发断开."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    async def _server(reader, writer):
        try:
            hdr = await reader.readexactly(2)
            body = await reader.readexactly(hdr[1])
            if body and body[0] == 0x07:  # STARTDT ACT
                writer.write(bytes([0x68, 0x04, 0x0B, 0x00, 0x00, 0x00]))
                await writer.drain()
            await asyncio.sleep(0.1)
            asdu = ASDUBuilder.build_single_point(1, 1, True)
            writer.write(APCICodec.encode_i(9, 0, asdu))  # tx_seq=9，期望 0
            await writer.drain()
            while True:
                if not await reader.read(100):
                    break
        except Exception:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(_server, "127.0.0.1", port)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)
    disconnected: list = []
    master.set_event_callback(
        lambda e, d: disconnected.append(e) if e.value == "disconnected" else None
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=5)
        # 注入失序帧 → 状态机应离开 Running（原缺陷: 残留 Running）
        assert await _wait_until(lambda: not master.is_running, timeout=3), \
            f"master stayed Running after sequence error, state={master.state}"
        assert master._client.is_connected is False
        assert any(getattr(e, "value", None) == "disconnected" for e in disconnected)
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=5)
        except Exception:
            pass
        server.close()
        await asyncio.sleep(0.05)


# ═══════════════════════════════════════════════════════════════════
#  收尾: 文件传输发送方法接入窗口等待 (消除 k 窗口不对称)
# ═══════════════════════════════════════════════════════════════════

async def _occupy_window(engine, n: int) -> None:
    """发送 n 个 I 帧占满发送窗口."""
    for _ in range(n):
        await engine.general_interrogation()


@pytest.mark.asyncio
async def test_file_transfer_send_waits_for_window_release():
    """窗口满时文件传输发送应等待（非立即失败），窗口释放后成功发送."""
    engine, client = _make_master(k=2, t1=0.5)
    await _occupy_window(engine, 2)                 # 打满 k=2 窗口
    assert engine._seq.send_window_available is False

    async def _release():
        await asyncio.sleep(0.05)
        # 模拟收到 S 帧确认 (确认到 seq 1 → 释放一个窗口位)
        apci, _ = APCICodec.decode(APCICodec.encode_s(1))
        engine._handle_s_frame(apci)

    releaser = asyncio.ensure_future(_release())
    task = asyncio.ensure_future(engine.file_call_directory())
    done, _pending = await asyncio.wait({task}, timeout=0.03)
    assert not done, "窗口满时应阻塞等待，而非立即完成/抛异常"

    await asyncio.wait_for(task, timeout=2.0)
    await releaser
    assert client.send.call_count == 3               # 2×GI + 1×文件目录


@pytest.mark.asyncio
async def test_file_transfer_send_times_out_when_window_stuck():
    """窗口始终不释放时，文件传输发送须等待 t1 后抛 RuntimeError（不无限等待）."""
    engine, _client = _make_master(k=2, t1=0.2)
    await _occupy_window(engine, 2)
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="t1"):
        await engine.file_select(0, 1)
    assert time.monotonic() - t0 >= 0.15


@pytest.mark.parametrize("method,args", [
    ("file_call_directory", (0,)),
    ("file_select", (0, 1)),
    ("file_request", (0, 1)),
    ("file_ack", (0, 1)),
])
async def test_all_file_transfer_methods_apply_window_wait(method, args):
    """4 个文件传输发送方法均接入窗口等待（窗口满 → 等待 t1 后 RuntimeError）."""
    engine, _client = _make_master(k=1, t1=0.15)
    await _occupy_window(engine, 1)                  # k=1 一次性打满
    with pytest.raises(RuntimeError, match="t1"):
        await getattr(engine, method)(*args)


# ═══════════════════════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════════════════════

async def _drain(times: int = 5) -> None:
    """让事件循环处理已派发的后台任务."""
    for _ in range(times):
        await asyncio.sleep(0)


async def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.05) -> bool:
    """轮询等待 predicate 成立."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()
