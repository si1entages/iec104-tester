"""IEC 60870-5-104 协议核心测试."""

import sys
import struct
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.protocol.constants import (
    START_BYTE, U_STARTDT_ACT, U_STARTDT_CON, U_STOPDT_ACT,
    U_STOPDT_CON, U_TESTFR_ACT, U_TESTFR_CON,
)
from core.protocol.apci import APCICodec, APCI
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    TypeID, COT, QualityDescriptor,
    SinglePoint, DoublePoint, NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, CP56Time2a, CP24Time2a,
    SingleCommand, DoubleCommand,
)
from core.protocol.sequence import SequenceManager
from core.protocol.state_machine import ConnectionStateMachine


def test_apci_u_frame():
    """测试 U 帧编解码."""
    print("=== U-Frame Tests ===")

    for name, func, expected_byte in [
        ("STARTDT ACT", APCICodec.startdt_act, U_STARTDT_ACT),
        ("STARTDT CON", APCICodec.startdt_con, U_STARTDT_CON),
        ("STOPDT ACT", APCICodec.stopdt_act, U_STOPDT_ACT),
        ("STOPDT CON", APCICodec.stopdt_con, U_STOPDT_CON),
        ("TESTFR ACT", APCICodec.testfr_act, U_TESTFR_ACT),
        ("TESTFR CON", APCICodec.testfr_con, U_TESTFR_CON),
    ]:
        frame = func()
        assert frame[0] == START_BYTE, f"{name}: wrong start byte"
        assert frame[1] == 4, f"{name}: wrong length"
        assert frame[2] == expected_byte, f"{name}: wrong control byte"

        apci, consumed = APCICodec.decode(frame)
        assert apci.is_u_frame, f"{name}: not U-frame"
        assert apci.u_func == expected_byte, f"{name}: wrong func"
        assert consumed == 6, f"{name}: wrong consumed"

    print("  ✅ All U-frame tests passed")


def test_apci_s_frame():
    """测试 S 帧编解码."""
    print("=== S-Frame Tests ===")

    for rx_seq in [0, 1, 100, 32767]:
        frame = APCICodec.encode_s(rx_seq)
        assert frame[0] == START_BYTE
        assert frame[1] == 4

        apci, _ = APCICodec.decode(frame)
        assert apci.is_s_frame
        assert apci.rx_seq == rx_seq

    print("  ✅ All S-frame tests passed")


def test_apci_i_frame():
    """测试 I 帧编解码."""
    print("=== I-Frame Tests ===")

    for tx_seq, rx_seq in [(0, 0), (1, 1), (100, 50), (32767, 32767)]:
        asdu_data = bytes([0x01, 0x01, 0x03, 0x00, 0x01, 0x00, 0x01, 0x00])
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        assert frame[0] == START_BYTE
        assert frame[1] == 4 + len(asdu_data)

        apci, consumed = APCICodec.decode(frame)
        assert apci.is_i_frame
        assert apci.tx_seq == tx_seq
        assert apci.rx_seq == rx_seq
        assert apci.asdu_length == len(asdu_data)

    print("  ✅ All I-frame tests passed")


def test_single_point():
    """测试单点信息编解码."""
    print("=== Single Point Tests ===")

    for value in [True, False]:
        sp = SinglePoint(value=value)
        data = sp.to_bytes()
        assert len(data) == 1

        sp2 = SinglePoint.from_bytes(data)
        assert sp2.value == value

    # 带品质
    sp = SinglePoint(value=True, quality=QualityDescriptor(0x40))  # IV
    data = sp.to_bytes()
    sp2 = SinglePoint.from_bytes(data)
    assert sp2.value == True
    assert sp2.quality.invalid == True

    print("  ✅ All single point tests passed")


def test_double_point():
    """测试双点信息编解码."""
    print("=== Double Point Tests ===")

    for val in [0, 1, 2, 3]:
        dp = DoublePoint(value=val)
        data = dp.to_bytes()
        dp2 = DoublePoint.from_bytes(data)
        assert dp2.value == val

    print("  ✅ All double point tests passed")


def test_normalized_value():
    """测试归一化值编解码."""
    print("=== Normalized Value Tests ===")

    for val in [0.0, 0.5, -0.5, 1.0, -1.0]:
        nv = NormalizedValue(value=val)
        data = nv.to_bytes()
        assert len(data) == 3

        nv2 = NormalizedValue.from_bytes(data)
        assert abs(nv2.value - val) < 0.001, f"Expected {val}, got {nv2.value}"

    print("  ✅ All normalized value tests passed")


def test_short_float():
    """测试短浮点数编解码."""
    print("=== Short Float Tests ===")

    for val in [0.0, 3.14, -273.15, 100.0, 0.001]:
        sf = ShortFloat(value=val)
        data = sf.to_bytes()
        assert len(data) == 5

        sf2 = ShortFloat.from_bytes(data)
        assert abs(sf2.value - val) < 0.001, f"Expected {val}, got {sf2.value}"

    print("  ✅ All short float tests passed")


def test_cp56time2a():
    """测试 CP56Time2a 时标编解码."""
    print("=== CP56Time2a Tests ===")

    t = CP56Time2a(
        millisecond=12345,
        minute=30,
        hour=14,
        day=15,
        month=6,
        year=25,
        weekday=7,
    )
    data = t.to_bytes()
    assert len(data) == 7

    t2 = CP56Time2a.from_bytes(data)
    assert t2.millisecond == 12345
    assert t2.minute == 30
    assert t2.hour == 14
    assert t2.day == 15
    assert t2.month == 6
    assert t2.year == 25

    # now()
    now = CP56Time2a.now()
    assert 1 <= now.month <= 12
    assert 1 <= now.day <= 31
    assert 0 <= now.hour <= 23

    print("  ✅ All CP56Time2a tests passed")


def test_asdu_general_interrogation():
    """测试总召唤报文编解码."""
    print("=== ASDU General Interrogation ===")

    # 构造总召唤
    asdu_data = ASDUBuilder.build_general_interrogation(common_addr=1, qoi=20)
    assert len(asdu_data) > 0

    # 解码
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.C_IC_NA_1
    assert asdu.cot == COT.ACT
    assert asdu.common_addr == 1
    assert len(asdu.objects) == 1

    print("  ✅ General interrogation test passed")


def test_asdu_single_point():
    """测试单点遥信报文."""
    print("=== ASDU Single Point ===")

    # 不带时标
    asdu_data = ASDUBuilder.build_single_point(
        common_addr=1, ioa=100, value=True, cot=COT.SPONT
    )
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.M_SP_NA_1
    assert asdu.cot == COT.SPONT
    assert len(asdu.objects) == 1
    assert asdu.objects[0].ioa == 100
    assert asdu.objects[0].data.value == True

    # 带时标 (SOE)
    asdu_data = ASDUBuilder.build_single_point(
        common_addr=1, ioa=200, value=False,
        cot=COT.SPONT, with_time=True
    )
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.M_SP_TB_1
    assert asdu.objects[0].time_tag is not None

    print("  ✅ Single point ASDU test passed")


def test_asdu_short_float():
    """测试短浮点遥测报文."""
    print("=== ASDU Short Float ===")

    asdu_data = ASDUBuilder.build_short_float(
        common_addr=1, ioa=1001, value=220.5, cot=COT.SPONT
    )
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.M_ME_NC_1
    assert len(asdu.objects) == 1
    assert asdu.objects[0].ioa == 1001
    assert abs(asdu.objects[0].data.value - 220.5) < 0.1

    print("  ✅ Short float ASDU test passed")


def test_asdu_single_command():
    """测试单命令报文."""
    print("=== ASDU Single Command ===")

    # 执行
    asdu_data = ASDUBuilder.build_single_command(
        common_addr=1, ioa=500, state=True, select=False
    )
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.C_SC_NA_1
    assert asdu.cot == COT.ACT
    cmd = asdu.objects[0].data
    assert cmd.state == True
    assert cmd.select == False

    # 选择
    asdu_data = ASDUBuilder.build_single_command(
        common_addr=1, ioa=500, state=True, select=True
    )
    asdu = ASDU.decode(asdu_data)
    cmd = asdu.objects[0].data
    assert cmd.select == True

    print("  ✅ Single command ASDU test passed")


def test_asdu_clock_sync():
    """测试时钟同步报文."""
    print("=== ASDU Clock Sync ===")

    t = CP56Time2a.now()
    asdu_data = ASDUBuilder.build_clock_sync(common_addr=1, time_tag=t)
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.C_CS_NA_1
    assert asdu.cot == COT.ACT

    print("  ✅ Clock sync ASDU test passed")


def test_sequence_manager():
    """测试序列号管理器."""
    print("=== Sequence Manager Tests ===")

    seq = SequenceManager(k=12, w=8)

    # 初始状态
    assert seq.send_seq == 0
    assert seq.recv_seq == 0
    assert seq.send_window_available == True
    assert seq.unconfirmed_count == 0

    # 发送
    for i in range(12):
        s = seq.get_send_seq()
        assert s == i

    # 窗口满
    assert seq.send_window_available == False
    try:
        seq.get_send_seq()
        assert False, "Should raise"
    except RuntimeError:
        pass

    # 确认
    seq.process_rx_s_frame(12)
    assert seq.send_window_available == True

    # 接收
    for i in range(8):
        result = seq.process_rx_i_frame(i)
        assert result == True

    print("  ✅ Sequence manager tests passed")


def test_state_machine():
    """测试连接状态机."""
    print("=== State Machine Tests ===")

    sm = ConnectionStateMachine()
    assert sm.state == "Stopped"

    sm.on_connected()
    assert sm.state == "Connecting"

    sm.on_startdt_con()
    assert sm.state == "Running"

    sm.on_disconnected()
    assert sm.state == "Stopped"

    print("  ✅ State machine tests passed")


def test_full_apdu_roundtrip():
    """测试完整 APDU 编解码往返."""
    print("=== Full APDU Roundtrip ===")

    # I帧
    asdu_data = ASDUBuilder.build_short_float(1, 1001, 220.5, cot=COT.SPONT)
    frame = APCICodec.encode_i(42, 10, asdu_data)

    apci, _ = APCICodec.decode(frame)
    assert apci.is_i_frame
    assert apci.tx_seq == 42
    assert apci.rx_seq == 10

    asdu = ASDU.decode(frame[6:6 + apci.asdu_length])
    assert asdu.type_id == TypeID.M_ME_NC_1
    assert abs(asdu.objects[0].data.value - 220.5) < 0.1

    print("  ✅ Full APDU roundtrip test passed")


def main():
    print("IEC 60870-5-104 Protocol Tests")
    print("=" * 50)

    test_apci_u_frame()
    test_apci_s_frame()
    test_apci_i_frame()
    test_single_point()
    test_double_point()
    test_normalized_value()
    test_short_float()
    test_cp56time2a()
    test_asdu_general_interrogation()
    test_asdu_single_point()
    test_asdu_short_float()
    test_asdu_single_command()
    test_asdu_clock_sync()
    test_sequence_manager()
    test_state_machine()
    test_full_apdu_roundtrip()

    print()
    print("=" * 50)
    print("✅ ALL TESTS PASSED")
    print("=" * 50)


if __name__ == "__main__":
    main()
