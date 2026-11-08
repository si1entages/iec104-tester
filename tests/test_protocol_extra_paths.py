"""协议层补充路径测试（覆盖率整改）：`types.py` / `asdu.py` 的零散分支.

覆盖：COT/QOI/QCC 边界、品质描述词全标志、时标短报文异常、命令负数编码、
继保事件时标序列化、成组单点带时标往返、简单命令类型编解码、
自定义类型校验与 dict 装载、CA 长度=1 解码、未知类型解码、
带时标构建器、组召唤响应、SQ=1 序列、APDU 编解码。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol.asdu import (
    APDU,
    ASDU,
    CUSTOM_TYPES,
    ASDUBuilder,
    CustomField,
    CustomObject,
    CustomTypeDef,
    CustomTypeRegistry,
    InformationObject,
)
from core.protocol.types import (
    COT,
    CP24Time2a,
    CP56Time2a,
    GroupSinglePointWithStatus,
    ParameterCommandNormalized,
    ParameterCommandScaled,
    ProtectionEvent,
    QualifierOfCounterInterrogation,
    QualifierOfInterrogation,
    QualityDescriptor,
    ReadCommand,
    RegulatingStepCommand,
    ResetProcessCommand,
    SingleCommand,
    SinglePoint,
    TypeID,
    get_type_info,
)
from core.protocol.types import (
    TestCommand as PatternCommand,
)
from core.protocol.types import (
    TestCommandWithTime as PatternCommandWithTime,
)

# ── types.py 分支 ────────────────────────────────────────────────────────


def test_cot_group_number_boundaries():
    assert COT.get_group_number(21) == 1
    assert COT.get_group_number(36) == 16
    with pytest.raises(ValueError):
        COT.get_group_number(20)


def test_quality_descriptor_str_all_flags():
    # 标准位：OV=0x01 BL=0x10 SB=0x20 NT=0x40 IV=0x80；按严重度排列
    assert str(QualityDescriptor(0x71)) == "NT|SB|BL|OV"   # NT+SB+BL+OV
    assert str(QualityDescriptor(0x70)) == "NT|SB|BL"
    assert str(QualityDescriptor(0x80)) == "IV"
    assert str(QualityDescriptor(0xF1)) == "IV|NT|SB|BL|OV"
    assert str(QualityDescriptor(0)) == "GOOD"
    assert QualityDescriptor(0xFF).to_int() == 0xFF
    assert QualityDescriptor(0x80).to_int() == 0x80


def test_time_tag_short_inputs_raise():
    with pytest.raises(ValueError):
        CP24Time2a.from_bytes(b"\x00\x00")
    with pytest.raises(ValueError):
        CP56Time2a.from_bytes(b"\x00" * 6)


def test_command_action_str():
    assert SingleCommand(select=True).action_str == "选择"
    assert SingleCommand(select=False).action_str == "执行"
    assert RegulatingStepCommand(select=True).action_str == "选择"
    assert RegulatingStepCommand(select=False).action_str == "执行"


def test_negative_parameter_encoding():
    normalized = ParameterCommandNormalized(ioa=1, value=-0.5)
    assert len(normalized.to_bytes()) == 3
    scaled = ParameterCommandScaled(ioa=2, value=-100)
    assert len(scaled.to_bytes()) == 3


def test_protection_event_time_serialization():
    event = ProtectionEvent(ioa=1, event_value=0x1234)
    assert event.has_short_time is False
    assert event.has_long_time is False
    assert len(event.to_bytes_short_time()) == 3
    assert len(event.to_bytes_long_time()) == 3

    event.time_short = CP24Time2a.now()
    assert event.has_short_time is True
    assert len(event.to_bytes_short_time()) == 6

    event.time_long = CP56Time2a.now()
    assert event.has_long_time is True
    assert len(event.to_bytes_long_time()) == 10


def test_group_single_point_with_time_roundtrip():
    payload = bytes([0b00000011, 0b00000010]) + CP56Time2a.now().to_bytes()
    obj = GroupSinglePointWithStatus.from_bytes_with_time(payload, count=2)
    assert obj.points == [(False, True), (True, True)]
    assert obj.time_long is not None
    assert obj.to_bytes() == payload

    no_time = GroupSinglePointWithStatus.from_bytes_with_time(bytes([0, 1]))
    assert no_time.time_long is None


def test_simple_command_types_roundtrip():
    test_command = PatternCommand.from_bytes(bytes([0xAA, 0x55]), ioa=7)
    assert test_command.test_pattern == 0x55AA
    assert test_command.to_bytes() == bytes([0xAA, 0x55])

    with_time = PatternCommandWithTime.from_bytes(
        bytes([0xAA, 0x55]) + CP56Time2a.now().to_bytes(), ioa=1)
    assert len(with_time.to_bytes()) == 9
    # 信息体不足 9 字节 → 用当前时间补齐
    short = PatternCommandWithTime.from_bytes(bytes([0xAA, 0x55]))
    assert len(short.to_bytes()) == 9

    read = ReadCommand.from_bytes(b"", ioa=9)
    assert read.ioa == 9 and read.to_bytes() == b""

    reset = ResetProcessCommand.from_bytes(bytes([1]), ioa=3)
    assert reset.qualifier == 1 and reset.to_bytes() == b"\x01"


def test_get_type_info_known_and_unknown():
    assert get_type_info(TypeID.M_SP_NA_1) == "M_SP_NA_1"
    assert get_type_info(9999) == "未知类型(9999)"


def test_interrogation_and_counter_qualifiers():
    assert QualifierOfInterrogation.is_valid(20)
    assert QualifierOfInterrogation.is_valid(21)
    assert QualifierOfInterrogation.is_valid(36)
    assert not QualifierOfInterrogation.is_valid(19)
    assert not QualifierOfInterrogation.is_valid(37)

    assert QualifierOfInterrogation.get_group_number(21) == 1
    assert QualifierOfInterrogation.get_group_number(36) == 16
    assert QualifierOfInterrogation.get_group_number(20) is None

    assert QualifierOfCounterInterrogation.is_freeze_request(5)
    assert QualifierOfCounterInterrogation.is_freeze_request(8)
    assert not QualifierOfCounterInterrogation.is_freeze_request(4)


# ── asdu.py 分支 ─────────────────────────────────────────────────────────


def test_custom_field_and_typedef_sizes():
    with pytest.raises(ValueError):
        CustomField(name="blob", type="bytes", length=0).size()
    with pytest.raises(ValueError):
        CustomField(name="x", type="nope").size()

    typedef = CustomTypeDef(
        type_id=200,
        fields=[
            CustomField(name="a", type="u16"),
            CustomField(name="b", type="bytes", length=3),
        ],
    )
    assert typedef.data_size() == 5


def test_custom_object_unregistered_raises():
    tid = 254
    if tid in CUSTOM_TYPES.ids():
        pytest.skip(f"type {tid} 已被其它测试注册")
    with pytest.raises(ValueError):
        CustomObject(type_id=tid).to_bytes()


def test_custom_registry_validation_and_dict_loading():
    registry = CustomTypeRegistry()

    with pytest.raises(ValueError):
        registry.register(CustomTypeDef(type_id=300))
    with pytest.raises(ValueError):
        registry.register(CustomTypeDef(type_id=int(TypeID.M_SP_NA_1)))

    registry.register(CustomTypeDef(
        type_id=200, name="V", fields=[CustomField(name="v", type="u16")]))
    assert registry.get(200).name == "V"
    assert registry.get("bad") is None          # TypeError → None
    assert registry.ids() == [200]

    assert registry.unregister(200) is True
    assert registry.unregister(200) is False

    count = registry.load_dict({
        200: {"name": "A", "fields": [{"name": "v", "type": "u8"}]},
        201: {"name": "B", "fields": [{"name": "v", "type": "u8"}]},
    })
    assert count == 2
    assert registry.ids() == [200, 201]

    registry.clear()
    assert registry.ids() == []


def test_encode_data_rejects_unknown_object():
    asdu = ASDU(type_id=TypeID.M_SP_NA_1)
    with pytest.raises(TypeError):
        asdu._encode_data(object(), TypeID.M_SP_NA_1)


def test_decode_with_one_byte_common_address():
    # M_SP_NA_1, 1 object, COT=3, OA=0, CA=1 (1 byte), IOA=1, SIQ=1
    payload = bytes([1, 1, 3, 0, 1, 1, 0, 0, 1])
    asdu = ASDU.decode(payload, ca_length=1)
    assert asdu.common_addr == 1
    assert len(asdu.objects) == 1
    assert asdu.objects[0].ioa == 1

    header = ASDU.decode_header(bytes([1, 1, 3, 0, 1]), ca_length=1)
    assert header.common_addr == 1


def test_decode_unknown_type_yields_none_object():
    tid = 254
    if tid in CUSTOM_TYPES.ids():
        pytest.skip(f"type {tid} 已被其它测试注册")
    # 未注册类型在对象数据层被跳过（调用方据解码失败回 COT=42）；
    # 注意 ASDU.decode 对未注册 raw TypeID 会直接 ValueError，故直接测数据层
    obj_data, time_tag, consumed = ASDU._decode_object_data(tid, b"", COT.SPONT)
    assert obj_data is None
    assert time_tag is None
    assert consumed == 0


def test_builder_with_time_variants_decode():
    blobs = [
        ASDUBuilder.build_normalized_value(1, 100, 0.5, with_time=True),
        ASDUBuilder.build_double_point(1, 101, 2, with_time=True),
        ASDUBuilder.build_bitstring32(1, 102, 0xDEADBEEF, with_time=True),
        ASDUBuilder.build_counter_value(1, 103, 42, with_time=True),
    ]
    expected = [
        TypeID.M_ME_TD_1,
        TypeID.M_DP_TB_1,
        TypeID.M_BO_TB_1,
        TypeID.M_IT_TB_1,
    ]
    for blob, type_id in zip(blobs, expected, strict=True):
        decoded = ASDU.decode(blob)
        assert decoded.type_id == type_id
        assert decoded.objects[0].time_tag is not None


def test_scaled_values_sequence_sq_one():
    blob = ASDUBuilder.build_scaled_values_sequence(1, 5000, [1, 2, 3])
    asdu = ASDU.decode(blob)
    assert asdu.type_id == TypeID.M_ME_NB_1
    assert asdu.sq is True
    assert asdu.num == 3
    assert [obj.ioa for obj in asdu.objects] == [5000, 5001, 5002]


def test_group_response_builder():
    objects = [InformationObject(ioa=1, data=SinglePoint(value=True))]
    blob = ASDUBuilder.build_group_response(1, group=3, objects=objects)
    asdu = ASDU.decode(blob)
    assert asdu.cot == COT.group_response(3)


def test_bitstring_command_and_test_command_with_time_builders():
    command = ASDU.decode(ASDUBuilder.build_bitstring_command(1, 700, 0x01))
    assert command.type_id == TypeID.C_BO_NA_1

    test = ASDU.decode(ASDUBuilder.build_test_command_with_time(1))
    assert test.type_id == TypeID.C_TS_TA_1


def test_parameter_no_quality_builder():
    blob = ASDUBuilder.build_parameter_normalized_no_quality(1, 800, -0.25)
    asdu = ASDU.decode(blob)
    assert asdu.type_id == TypeID.P_ME_ND_1
    assert asdu.objects[0].data.value == pytest.approx(-0.25, abs=0.01)


def test_apdu_encode_decode_i_and_u_frames():
    inner = ASDU.decode(ASDUBuilder.build_general_interrogation(1, 20))
    apdu = APDU(tx_seq=5, rx_seq=3, asdu=inner, is_i_frame=True)
    frame = apdu.encode()
    decoded = APDU.decode(frame)
    assert decoded.is_i_frame is True
    assert decoded.tx_seq == 5
    assert decoded.rx_seq == 3
    assert decoded.asdu.type_id == TypeID.C_IC_NA_1

    u_frame = APDU(u_func=0x07, is_i_frame=False).encode()
    decoded_u = APDU.decode(u_frame)
    assert decoded_u.is_i_frame is False
    assert decoded_u.u_func == 0x07
