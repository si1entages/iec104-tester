"""协议解码器 fuzz / 属性测试.

目标：本工具会连接任意第三方装置/接受任意现场抓包，**畸形输入不得让解析器
抛出未约定异常**。约定：

- ``APCICodec.decode`` / ``ASDU.decode`` 对非法输入只抛 ``ValueError``；
- 文件传输信息体（F_FR/F_SR/F_SC/F_LS/F_AF/F_SG/F_DR/F_*_NB）直接解析同样只允许
  ``ValueError``（截断段数据必须报错，不得静默返回半段）；
- 合法输入的编码 → 解码应可往返（浮点按 IEC 104 的量化精度比较）；
- Web 端「报文逐段翻译」对任意 HEX 文本都必须返回结构化结果，绝不 500。
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.constants import (
    U_STARTDT_ACT,
    U_STARTDT_CON,
    U_TESTFR_ACT,
    U_TESTFR_CON,
)
from core.protocol.types import (
    COT,
    AckFileSection,
    CallDirectory,
    DirectoryEntry,
    FileReady,
    FileReadyAck,
    FileSegment,
    FileSelectCallGet,
    LastSection,
    SectionReady,
    SectionReadyAck,
    TypeID,
)
from webui.frame_translate import translate_hex

FUZZ = settings(max_examples=300, deadline=None)

FILE_OBJECT_CLASSES = [
    FileReady,
    SectionReady,
    CallDirectory,
    LastSection,
    AckFileSection,
    FileSegment,
    DirectoryEntry,
    FileSelectCallGet,
    FileReadyAck,
    SectionReadyAck,
]

FILE_TYPE_IDS = [120, 121, 122, 123, 124, 125, 126, 127, 128, 129]


# ── APCI ──────────────────────────────────────────────────────────

@given(st.binary(max_size=300))
@FUZZ
def test_apci_decode_only_raises_value_error(data: bytes) -> None:
    try:
        apci, consumed = APCICodec.decode(data)
    except ValueError:
        return
    assert 2 <= consumed <= len(data)
    if apci.is_i_frame:
        assert apci.asdu_length == consumed - 6
    else:
        assert apci.asdu_length == 0


@given(
    st.integers(min_value=0, max_value=32767),
    st.integers(min_value=0, max_value=32767),
    st.binary(max_size=240),
)
@FUZZ
def test_apci_i_frame_roundtrip(tx_seq: int, rx_seq: int, payload: bytes) -> None:
    frame = APCICodec.encode_i(tx_seq, rx_seq, payload)
    apci, consumed = APCICodec.decode(frame)
    assert consumed == len(frame)
    assert apci.is_i_frame
    assert (apci.tx_seq, apci.rx_seq) == (tx_seq, rx_seq)
    assert frame[6:] == payload


@pytest.mark.parametrize("func", [U_STARTDT_ACT, U_STARTDT_CON, U_TESTFR_ACT, U_TESTFR_CON])
def test_apci_u_frame_roundtrip(func: int) -> None:
    apci, consumed = APCICodec.decode(APCICodec.encode_u(func))
    assert consumed == 6
    assert apci.is_u_frame and apci.u_func == func


@given(st.integers(min_value=0, max_value=32767))
@FUZZ
def test_apci_s_frame_roundtrip(rx_seq: int) -> None:
    apci, consumed = APCICodec.decode(APCICodec.encode_s(rx_seq))
    assert consumed == 6
    assert apci.is_s_frame and apci.rx_seq == rx_seq


# ── ASDU ──────────────────────────────────────────────────────────

@given(st.binary(min_size=1, max_size=300))
@FUZZ
def test_asdu_decode_only_raises_value_error(data: bytes) -> None:
    try:
        asdu = ASDU.decode(data)
    except ValueError:
        return
    # 成功解码时必须保持基本不变量
    assert asdu.num >= 0
    assert len(asdu.objects) == asdu.num


@given(st.binary(min_size=1, max_size=300))
@FUZZ
def test_asdu_decode_header_only_raises_value_error(data: bytes) -> None:
    try:
        header = ASDU.decode_header(data)
    except ValueError:
        return
    assert 0 <= int(header.type_id) <= 255
    assert 0 <= int(header.cot) <= 255


@given(
    ioa=st.integers(min_value=0, max_value=65535),
    value=st.booleans(),
    cot=st.sampled_from([COT.SPONT, COT.INTROGEN, COT.ACTCON]),
)
@FUZZ
def test_single_point_roundtrip(ioa: int, value: bool, cot: int) -> None:
    asdu = ASDU.decode(ASDUBuilder.build_single_point(1, ioa, value, cot=cot))
    assert asdu.type_id == TypeID.M_SP_NA_1
    assert int(asdu.cot) == int(cot)
    assert asdu.objects[0].ioa == ioa
    assert asdu.objects[0].data.value is value


@given(
    ioa=st.integers(min_value=0, max_value=65535),
    value=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)
@FUZZ
def test_short_float_roundtrip(ioa: int, value: float) -> None:
    asdu = ASDU.decode(ASDUBuilder.build_short_float(1, ioa, value))
    assert asdu.type_id == TypeID.M_ME_NC_1
    assert asdu.objects[0].ioa == ioa
    # 编码为 IEEE 754 float32，按相对误差比较
    assert asdu.objects[0].data.value == pytest.approx(value, rel=1e-6, abs=1e-3)


@given(
    ioa=st.integers(min_value=0, max_value=65535),
    value=st.integers(min_value=-32768, max_value=32767),
)
@FUZZ
def test_scaled_value_roundtrip(ioa: int, value: int) -> None:
    asdu = ASDU.decode(ASDUBuilder.build_scaled_value(1, ioa, value))
    assert asdu.type_id == TypeID.M_ME_NB_1
    assert asdu.objects[0].data.value == value
    assert asdu.objects[0].ioa == ioa


@given(
    ioa=st.integers(min_value=0, max_value=65535),
    value=st.floats(min_value=-1.0, max_value=1.0, allow_nan=False),
)
@FUZZ
def test_normalized_value_roundtrip(ioa: int, value: float) -> None:
    asdu = ASDU.decode(ASDUBuilder.build_normalized_value(1, ioa, value))
    assert asdu.type_id == TypeID.M_ME_NA_1
    # 归一化值量化为 int16，误差上限约 1/32768
    assert asdu.objects[0].data.value == pytest.approx(value, abs=1e-4)
    assert asdu.objects[0].ioa == ioa


@given(
    ioa=st.integers(min_value=0, max_value=65535),
    value=st.integers(min_value=-2147483648, max_value=2147483647),
)
@FUZZ
def test_counter_value_roundtrip(ioa: int, value: int) -> None:
    asdu = ASDU.decode(ASDUBuilder.build_counter_value(1, ioa, value))
    assert asdu.type_id == TypeID.M_IT_NA_1
    assert asdu.objects[0].data.value == value
    assert asdu.objects[0].ioa == ioa


@given(
    base=st.integers(min_value=0, max_value=65000),
    states=st.lists(
        st.tuples(st.booleans(), st.sampled_from([0x00, 0x10, 0x20, 0x40, 0x80, 0xF0])),
        min_size=1, max_size=10,
    ),
)
@FUZZ
def test_single_point_sequence_roundtrip(base: int, states) -> None:
    points = [(base + i, value, quality) for i, (value, quality) in enumerate(states)]
    asdu = ASDU.decode(ASDUBuilder.build_single_point_sequence(1, points, cot=COT.INTROGEN))
    assert asdu.type_id == TypeID.M_SP_NA_1
    assert asdu.sq
    assert len(asdu.objects) == len(points)
    for obj, (ioa, value, _quality) in zip(asdu.objects, points, strict=True):
        assert obj.ioa == ioa
        assert obj.data.value is value


# ── 文件传输信息体解析（F_FR/F_SR/F_SC/F_LS/F_AF/F_SG/F_DR/F_*_NB）──

@given(st.binary(max_size=300))
@FUZZ
def test_file_transfer_object_parsers_only_raise_value_error(data: bytes) -> None:
    """任意字节喂给 10 类文件传输信息体：只允许 ValueError，不得 IndexError."""
    for cls in FILE_OBJECT_CLASSES:
        try:
            obj = cls.from_bytes(data)
        except ValueError:
            continue
        if cls is FileSegment:
            # LOS（第 4 字节）声明的段长度必须被完整解析，不能静默截断
            assert len(obj.data) == data[3]


@given(
    type_id=st.sampled_from(FILE_TYPE_IDS),
    body=st.binary(max_size=260),
)
@FUZZ
def test_asdu_file_transfer_decode_only_raises_value_error(
    type_id: int, body: bytes,
) -> None:
    """文件传输 ASDU 的随机信息体：只允许 ValueError，成功时对象数一致."""
    data = bytes([type_id, 1, 6, 0, 1, 0]) + body
    try:
        asdu = ASDU.decode(data)
    except ValueError:
        return
    assert asdu.type_id == TypeID(type_id)
    assert len(asdu.objects) == 1
    if type_id == int(TypeID.F_SG_NA_1):
        # body = IOA(3) + NOF(2) + NOS(1) + LOS(1) + data
        assert len(asdu.objects[0].data.data) == body[6]


def test_file_segment_truncated_payload_is_rejected() -> None:
    """LOS 声明 10 字节但只剩 3 字节：必须报错，不得返回半段."""
    with pytest.raises(ValueError, match="FileSegment"):
        FileSegment.from_bytes(bytes([1, 0, 0, 10, 0xAA, 0xBB, 0xCC]))


# ── Web 报文翻译（脏数据不得 500）────────────────────────────────

@given(st.text(alphabet="0123456789abcdefABCDEF", max_size=520))
@FUZZ
def test_translate_hex_never_raises(text: str) -> None:
    result = translate_hex(text)
    assert isinstance(result, dict)
    assert "ok" in result
    if result["ok"]:
        assert "segments" in result
