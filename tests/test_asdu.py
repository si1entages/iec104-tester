"""ASDU编解码测试."""

from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    COT,
    CP56Time2a,
    SinglePoint,
    TypeID,
)


def test_asdu_common_address_little_endian_roundtrip():
    """公共地址 0x0102 必须按小端写入并在解码后还原."""
    data = ASDUBuilder.build_general_interrogation(common_addr=0x0102, qoi=20)
    assert data[4:6] == b"\x02\x01"
    assert ASDU.decode(data).common_addr == 0x0102


def test_asdu_cot_pn_and_test_bits_roundtrip():
    """COT 字节的 P/N(bit6) 与 T(bit7) 必须独立于原因码保留."""
    asdu = ASDU(
        type_id=TypeID.M_SP_NA_1, sq=False, num=1, cot=COT.SPONT,
        pn=True, test=True, common_addr=1,
    )
    asdu.objects.append(InformationObject(ioa=5, data=SinglePoint(value=True)))

    data = asdu.encode()
    assert data[2] == (int(COT.SPONT) & 0x3F) | 0x40 | 0x80

    decoded = ASDU.decode(data)
    assert int(decoded.cot) == int(COT.SPONT)
    assert decoded.pn is True
    assert decoded.test is True


def test_asdu_vsq_number_roundtrip():
    """VSQ 低 7 位是对象数量；SQ 位不得污染数量."""
    data = ASDUBuilder.build_single_point_sequence(
        1, [(i, True, 0) for i in range(1, 11)], cot=COT.INTROGEN,
    )
    assert data[1] & 0x7F == 10
    decoded = ASDU.decode(data)
    assert decoded.num == 10
    assert len(decoded.objects) == 10


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


def test_asdu_with_parameter_commands():
    """测试参数命令ASDU编解码."""
    print("=== ASDU ParameterCommand Tests ===")

    # 归一化参数
    asdu_data = ASDUBuilder.build_parameter_normalized(1, 100, 0.75, 1)
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.P_ME_NA_1
    assert asdu.cot == COT.ACT
    assert len(asdu.objects) == 1
    obj = asdu.objects[0]
    assert obj.ioa == 100
    assert abs(obj.data.value - 0.75) < 0.001
    assert obj.data.param_change == 1

    # 标度化参数
    asdu_data = ASDUBuilder.build_parameter_scaled(1, 100, 500, 2)
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.P_ME_NB_1
    assert asdu.objects[0].data.value == 500

    # 短浮点参数
    asdu_data = ASDUBuilder.build_parameter_float(1, 100, 220.5, 0)
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.P_ME_NC_1
    assert abs(asdu.objects[0].data.value - 220.5) < 0.1

    # 参数激活
    asdu_data = ASDUBuilder.build_parameter_activation(1, 100, 1)
    asdu = ASDU.decode(asdu_data)
    assert asdu.type_id == TypeID.P_AC_NA_1
    assert asdu.objects[0].data.qualifier == 1

    print("  ✅ ASDU ParameterCommand tests passed")
