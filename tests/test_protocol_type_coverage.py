"""协议类型覆盖测试 — 保证每个已实现类型的「构造 → 解码」闭环.

背景：审计发现协议层能**解码** CP24Time2a 变体、继电保护事件、成组单点等类型，
但没有对应的构造器（子站无法模拟这些来报），即"半实现"。
本文件逐类型断言「能构造、能解码、类型与时标一致」，防止再次退化为半实现。

覆盖类型：
- CP24 短时标变体：M_SP_TA_1(2) / M_DP_TA_1(4) / M_ST_TA_1(6) / M_BO_TA_1(8) /
  M_ME_TA_1(10) / M_ME_TB_1(12) / M_ME_TC_1(14) / M_IT_TA_1(16)
- 继电保护事件：M_EP_TA_1(17) / M_EP_TB_1(18) / M_EP_TC_1(19) /
  M_EP_TD_1(38) / M_EP_TE_1(39) / M_EP_TF_1(40)
- 成组单点带状态检出：M_PS_NA_1(20) / M_PS_TB_1(71)
- 无品质测量值：M_ME_ND_1(21)；无品质参数：P_ME_ND_1(109)
- 位模式测试命令：C_TS_NB_1(108)
"""

from __future__ import annotations

import pytest

from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.types import COT, CP24Time2a, CP56Time2a, TypeID

# (类型, 构造好的 ASDU 字节, 期望时标类)
CP24_CASES = [
    ("M_SP_TA_1", TypeID.M_SP_TA_1, lambda: ASDUBuilder.build_single_point_cp24(1, 100, True)),
    ("M_DP_TA_1", TypeID.M_DP_TA_1, lambda: ASDUBuilder.build_double_point_cp24(1, 101, 2)),
    ("M_ST_TA_1", TypeID.M_ST_TA_1, lambda: ASDUBuilder.build_step_position_cp24(1, 102, 5)),
    ("M_BO_TA_1", TypeID.M_BO_TA_1, lambda: ASDUBuilder.build_bitstring_cp24(1, 103, 0x1234)),
    ("M_ME_TA_1", TypeID.M_ME_TA_1, lambda: ASDUBuilder.build_normalized_cp24(1, 104, 0.5)),
    ("M_ME_TB_1", TypeID.M_ME_TB_1, lambda: ASDUBuilder.build_scaled_cp24(1, 105, 1234)),
    ("M_ME_TC_1", TypeID.M_ME_TC_1, lambda: ASDUBuilder.build_short_float_cp24(1, 106, 3.25)),
    ("M_IT_TA_1", TypeID.M_IT_TA_1, lambda: ASDUBuilder.build_counter_cp24(1, 107, 999)),
]

EP_CASES = [
    ("M_EP_TA_1", TypeID.M_EP_TA_1,
     lambda: ASDUBuilder.build_protection_event(1, 108, 3, with_time=False), CP24Time2a),
    ("M_EP_TD_1", TypeID.M_EP_TD_1,
     lambda: ASDUBuilder.build_protection_event(1, 108, 3, with_time=True), CP56Time2a),
    ("M_EP_TB_1", TypeID.M_EP_TB_1,
     lambda: ASDUBuilder.build_protection_events_start(1, 109, 0x11, with_time=False), CP24Time2a),
    ("M_EP_TE_1", TypeID.M_EP_TE_1,
     lambda: ASDUBuilder.build_protection_events_start(1, 109, 0x11, with_time=True), CP56Time2a),
    ("M_EP_TC_1", TypeID.M_EP_TC_1,
     lambda: ASDUBuilder.build_protection_events_output(1, 110, 0x22, with_time=False), CP24Time2a),
    ("M_EP_TF_1", TypeID.M_EP_TF_1,
     lambda: ASDUBuilder.build_protection_events_output(1, 110, 0x22, with_time=True), CP56Time2a),
]


@pytest.mark.parametrize("name,type_id,build", CP24_CASES, ids=[c[0] for c in CP24_CASES])
def test_cp24_variants_round_trip(name, type_id, build):
    """CP24 短时标变体：能构造、能解码，且时标保持 CP24（3 字节，不膨胀为 7 字节）."""
    raw = build()
    asdu = ASDU.decode(raw)
    assert int(asdu.type_id) == int(type_id), f"{name}: 解码类型 {int(asdu.type_id)}"
    assert isinstance(asdu.objects[0].time_tag, CP24Time2a), (
        f"{name}: 时标应为 CP24Time2a，实测 {type(asdu.objects[0].time_tag).__name__}"
    )
    assert asdu.objects[0].ioa == 100 + CP24_CASES.index((name, type_id, build))


@pytest.mark.parametrize("name,type_id,build,tag_cls", EP_CASES,
                         ids=[c[0] for c in EP_CASES])
def test_protection_events_round_trip(name, type_id, build, tag_cls):
    """继电保护事件（M_EP_*）：CP24 与 CP56 两个变体都要能构造并解回."""
    asdu = ASDU.decode(build())
    assert int(asdu.type_id) == int(type_id)
    assert isinstance(asdu.objects[0].time_tag, tag_cls)


def test_group_single_point_with_status():
    """成组单点带状态检出：状态与检出位需逐位可解回."""
    raw = ASDUBuilder.build_group_single_point(1, 111, [(True, True), (False, True)])
    asdu = ASDU.decode(raw)
    assert int(asdu.type_id) == int(TypeID.M_PS_NA_1)
    states = [bool(s) for s, _ in asdu.objects[0].data.points[:2]]
    detected = [bool(d) for _, d in asdu.objects[0].data.points[:2]]
    assert states == [True, False]
    assert detected == [True, True]

    # 带时标变体必须带 CP56 时标
    raw_tb = ASDUBuilder.build_group_single_point(1, 111, [(True, True)], with_time=True)
    asdu_tb = ASDU.decode(raw_tb)
    assert int(asdu_tb.type_id) == int(TypeID.M_PS_TB_1)
    assert isinstance(asdu_tb.objects[0].time_tag, CP56Time2a)


def test_no_quality_variants():
    """M_ME_ND_1 / P_ME_ND_1 不带品质描述词：对象体仅 2 字节归一化值."""
    for name, expected, builder in (
        ("M_ME_ND_1", 0.25, lambda: ASDUBuilder.build_normalized_no_quality(1, 112, 0.25)),
        ("P_ME_ND_1", 0.75, lambda: ASDUBuilder.build_parameter_no_quality(1, 113, 0.75)),
    ):
        asdu = ASDU.decode(builder())
        assert int(asdu.type_id) == int(getattr(TypeID, name))
        value = asdu.objects[0].data.value
        # 2 字节归一化精度有限
        assert abs(value - expected) < 1e-3, f"{name}: {value} != {expected}"


def test_scaled_value_cp56_variant():
    """M_ME_TE_1（标度化 + CP56）：补齐后与 M_ME_NA_1/M_ME_NC_1 的时标变体对称."""
    asdu = ASDU.decode(ASDUBuilder.build_scaled_value(1, 120, 1234, with_time=True))
    assert int(asdu.type_id) == int(TypeID.M_ME_TE_1)
    assert isinstance(asdu.objects[0].time_tag, CP56Time2a)
    assert asdu.objects[0].data.value == 1234

    no_time = ASDU.decode(ASDUBuilder.build_scaled_value(1, 120, -50))
    assert int(no_time.type_id) == int(TypeID.M_ME_NB_1)
    assert no_time.objects[0].time_tag is None


def test_initialization_end_builder():
    """M_EI_NA_1 初始化结束（子站 STARTDT 激活后上送）."""
    asdu = ASDU.decode(ASDUBuilder.build_initialization_end(1, cause=0))
    assert int(asdu.type_id) == int(TypeID.M_EI_NA_1)
    assert int(asdu.cot) == int(COT.INIT)
    assert asdu.objects[0].data.cause == 0


def test_test_command_bit_pattern():
    """C_TS_NB_1 位模式测试命令：模式字可解回."""
    asdu = ASDU.decode(ASDUBuilder.build_test_command_bit_pattern(1, 0x12, 0x34))
    assert int(asdu.type_id) == int(TypeID.C_TS_NB_1)
    assert asdu.objects[0].data.pattern == 0x3412


def test_every_builder_output_is_decodable():
    """回归护栏：ASDUBuilder 的每个 build_* 都应产出可解码的 ASDU.

    用典型参数逐个调用；无法自动构造参数的方法（需要复杂对象）在下方白名单里跳过。
    """
    skip = {
        # 需要传入复杂对象/文件节等，已有专门用例覆盖
        "build_file_segment", "build_section_ready", "build_file_ready",
        "build_file_select_call_get", "build_section_ready_ack", "build_file_ready_ack",
        "build_last_section", "build_ack_file_section", "build_call_directory",
        "build_group_response", "build_scaled_values_sequence", "build_counter_sequence",
        "build_single_point_sequence", "build_short_float_sequence", "build_double_point_sequence",
        "build_protection_event", "build_protection_events_start", "build_protection_events_output",
        "build_group_single_point",
    }
    checked = 0
    for attr in dir(ASDUBuilder):
        if not attr.startswith("build_") or attr in skip:
            continue
        fn = getattr(ASDUBuilder, attr)
        sig = fn.__code__.co_varnames[: fn.__code__.co_argcount]
        if "common_addr" not in sig:
            continue
        # 仅用 (common_addr,) 调用的方法：其余参数依赖默认值
        try:
            raw = fn(1)
        except TypeError:
            continue
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{attr}(1) 构造失败: {type(e).__name__}: {e}")
        ASDU.decode(raw)          # 不抛异常即视为可解码
        checked += 1
    # 仅统计"只用 common_addr 即可调用"的方法（其余需必填参数，另有专门用例）
    assert checked >= 12, f"护栏覆盖的方法过少（{checked}），检查是否被误跳过"
