"""`core/capture/filter.py` 帧过滤器单元测试.

覆盖方向/帧类型/时间/长度/ASDU 层（类型标识、传送原因、公共地址、IOA）/
自定义条件各维度，以及 describe() 与 from_dict()。全部用真实编码的 IEC 104
帧作为输入（APCI + ASDU），不依赖网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.capture.filter import FrameFilter
from core.capture.format import DIRECTION_RX, DIRECTION_TX, FrameEntry
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDUBuilder
from core.protocol.types import COT, TypeID

# ── 构造真实帧 ───────────────────────────────────────────────────

def _i_frame(ioa: int = 100, common_addr: int = 1, value: bool = True,
             type_id_cot: int = COT.SPONT) -> FrameEntry:
    """构造一帧真实 I 帧（单点遥信自发上送）."""
    asdu = ASDUBuilder.build_single_point(common_addr, ioa, value, cot=type_id_cot)
    frame = APCICodec.encode_i(0, 0, asdu)
    return FrameEntry(timestamp=1.0, direction=DIRECTION_RX, frame_data=frame)


def _u_frame(timestamp: float = 0.0, direction: int = DIRECTION_TX) -> FrameEntry:
    return FrameEntry(timestamp=timestamp, direction=direction,
                      frame_data=APCICodec.startdt_act())


def _s_frame(timestamp: float = 0.0) -> FrameEntry:
    return FrameEntry(timestamp=timestamp, direction=DIRECTION_TX,
                      frame_data=APCICodec.encode_s(1))


# ── 基础维度 ─────────────────────────────────────────────────────

def test_no_filter_matches_everything():
    frames = [_i_frame(), _u_frame(), _s_frame()]
    f = FrameFilter()
    assert f.apply(frames) == frames
    assert f.describe() == "(no filter)"


def test_direction_filter_is_case_insensitive():
    rx, tx = _i_frame(), _u_frame()
    assert FrameFilter(direction="rx").apply([rx, tx]) == [rx]
    assert FrameFilter(direction="RX").apply([rx, tx]) == [rx]
    assert FrameFilter(direction="tx").apply([rx, tx]) == [tx]


def test_frame_type_filter():
    i, s, u = _i_frame(), _s_frame(), _u_frame()
    frames = [i, s, u]
    assert FrameFilter(frame_type="I").apply(frames) == [i]
    assert FrameFilter(frame_type="s").apply(frames) == [s]  # 小写同样识别
    assert FrameFilter(frame_type="U").apply(frames) == [u]


def test_time_range_filter_inclusive_bounds():
    a = _i_frame()
    a.timestamp = 1.0
    b = _i_frame()
    b.timestamp = 2.0
    c = _i_frame()
    c.timestamp = 3.0

    assert FrameFilter(time_start=1.0, time_end=3.0).apply([a, b, c]) == [a, b, c]
    assert FrameFilter(time_start=1.5).apply([a, b, c]) == [b, c]
    assert FrameFilter(time_end=2.0).apply([a, b, c]) == [a, b]


def test_length_range_filter():
    short = _u_frame()            # 6 字节
    long_ = _i_frame()            # > 12 字节
    frames = [short, long_]

    assert FrameFilter(min_length=7).apply(frames) == [long_]
    assert FrameFilter(max_length=6).apply(frames) == [short]
    assert FrameFilter(min_length=6, max_length=100).apply(frames) == frames


# ── ASDU 层维度（仅 I 帧）────────────────────────────────────────

def test_asdu_type_filter():
    good = _i_frame(ioa=100)
    frames = [good, _u_frame()]

    assert FrameFilter(asdu_type=int(TypeID.M_SP_NA_1)).apply(frames) == [good]
    assert FrameFilter(asdu_type=999).apply(frames) == []


def test_cot_filter():
    spont = _i_frame(ioa=100, type_id_cot=COT.SPONT)
    gi = _i_frame(ioa=100, type_id_cot=COT.INTROGEN)

    assert FrameFilter(cot=COT.SPONT).apply([spont, gi]) == [spont]
    assert FrameFilter(cot=COT.INTROGEN).apply([spont, gi]) == [gi]
    # COT 过滤时非 I 帧一律不匹配
    assert FrameFilter(cot=COT.SPONT).apply([_u_frame()]) == []


def test_common_addr_filter():
    ca1 = _i_frame(ioa=100, common_addr=1)
    ca2 = _i_frame(ioa=100, common_addr=2)

    assert FrameFilter(common_addr=2).apply([ca1, ca2]) == [ca2]


def test_ioa_filter():
    f100 = _i_frame(ioa=100)
    f200 = _i_frame(ioa=200)

    assert FrameFilter(ioa=100).apply([f100, f200]) == [f100]
    assert FrameFilter(ioa=200).apply([f100, f200]) == [f200]
    assert FrameFilter(ioa=300).apply([f100, f200]) == []


def test_asdu_filter_skips_non_i_frames_and_short_frames():
    """ASDU 维度存在时：非 I 帧与过短帧直接不匹配."""
    filt = FrameFilter(asdu_type=int(TypeID.M_SP_NA_1))
    assert filt.apply([_u_frame(), _s_frame()]) == []
    assert filt.apply([FrameEntry(frame_data=b"\x68\x04\x00\x00\x00\x00")]) == []


def test_asdu_filter_short_ioa_absent_does_not_reject():
    """IOA 过滤但 ASDU 体不足 9 字节：不做 IOA 判定（保留帧）."""
    asdu = bytes([int(TypeID.M_SP_NA_1) & 0xFF, 0x01, COT.SPONT & 0x3F, 0x00, 0x01, 0x00])
    frame = APCICodec.encode_i(0, 0, asdu)   # 长度 = 6 + 6 = 12 → 满足 >=12

    assert FrameFilter(ioa=100).apply([FrameEntry(frame_data=frame)]) != []


def test_multiple_asdu_conditions_are_anded():
    f = _i_frame(ioa=100, common_addr=1, type_id_cot=COT.SPONT)

    assert FrameFilter(asdu_type=int(TypeID.M_SP_NA_1),
                       cot=COT.SPONT, common_addr=1, ioa=100).apply([f]) == [f]
    assert FrameFilter(asdu_type=int(TypeID.M_SP_NA_1), ioa=999).apply([f]) == []
    assert FrameFilter(cot=COT.INTROGEN).apply([f]) == []


def test_match_asdu_handles_malformed_frame():
    """畸形帧（触发 IndexError/ValueError）→ 不匹配而非抛异常."""
    long_enough_but_ca_short = bytes([0x68, 0x0A, 0x00, 0x00]) + b"\x00" * 8
    assert FrameFilter(asdu_type=1).apply([FrameEntry(frame_data=long_enough_but_ca_short)]) == []


# ── 自定义条件 ───────────────────────────────────────────────────

def test_custom_condition_is_applied():
    a, b = _i_frame(ioa=100), _i_frame(ioa=200)

    assert FrameFilter(custom=lambda fr: len(fr.frame_data) > 10).apply([a, b]) == [a, b]
    assert FrameFilter(custom=lambda fr: False).apply([a, b]) == []


def test_custom_combined_with_builtin_conditions():
    a, b = _i_frame(ioa=100), _i_frame(ioa=200)
    filt = FrameFilter(direction="rx", custom=lambda fr: fr.frame_length > 10)
    assert filt.apply([a, b]) == [a, b]
    assert FrameFilter(direction="tx", custom=lambda fr: True).apply([a, b]) == []


# ── describe / from_dict ─────────────────────────────────────────

def test_describe_lists_all_active_conditions():
    f = FrameFilter(direction="rx", frame_type="I", time_start=1.0, time_end=2.0,
                    asdu_type=1, cot=3, common_addr=1, ioa=100,
                    min_length=12, max_length=64)
    desc = f.describe()

    for token in ("direction=rx", "type=I", "t>=1.000", "t<=2.000", "asdu=1",
                  "cot=3", "addr=1", "ioa=100", "len>=12", "len<=64"):
        assert token in desc, token
    assert desc.count(" AND ") == 9


def test_describe_partial_conditions():
    assert FrameFilter(direction="tx").describe() == "direction=tx"
    assert FrameFilter(min_length=6).describe() == "len>=6"


def test_from_dict_maps_all_fields():
    data = {
        "direction": "rx", "frame_type": "I", "time_start": 0.5, "time_end": 9.5,
        "asdu_type": 3, "cot": 3, "common_addr": 1, "ioa": 42,
        "min_length": 6, "max_length": 253,
    }
    f = FrameFilter.from_dict(data)

    assert f.direction == "rx"
    assert f.frame_type == "I"
    assert f.time_start == 0.5
    assert f.time_end == 9.5
    assert f.asdu_type == 3
    assert f.cot == 3
    assert f.common_addr == 1
    assert f.ioa == 42
    assert f.min_length == 6
    assert f.max_length == 253


def test_from_dict_defaults_to_no_filter():
    f = FrameFilter.from_dict({})
    assert f.describe() == "(no filter)"
    assert f.apply([_i_frame()]) != []
