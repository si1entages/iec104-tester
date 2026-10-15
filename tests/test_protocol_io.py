"""`core/protocol/io.py` 信息对象解析器单元测试.

覆盖 ParsedIO 的属性/序列化、全部 ``parse_*`` 便捷解析入口（含消耗字节数）、
``format_value_display`` 的全部值类型分支、以及品质/时标提取助手。

（该模块此前零覆盖；它是抓包分析/记录回放等上层功能的公共解析入口。）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol import io as pio
from core.protocol.types import (
    AckFileSection,
    BitString32,
    BitString32Command,
    CallDirectory,
    ClockSyncCommand,
    CounterInterrogationCommand,
    CounterValue,
    CP56Time2a,
    DelayCommand,
    DirectoryEntry,
    DoubleCommand,
    DoublePoint,
    FileReady,
    FileReadyAck,
    FileSegment,
    FileSelectCallGet,
    GroupSinglePointWithStatus,
    InitializationEnd,
    InterrogationCommand,
    LastSection,
    NormalizedValue,
    ParameterCommandFloat,
    ParameterCommandNormalized,
    ParameterCommandNormalizedNoQuality,
    ProtectionEvent,
    QualityDescriptor,
    ReadCommand,
    RegulatingStepCommand,
    ResetProcessCommand,
    ScaledValue,
    SectionReady,
    SectionReadyAck,
    SetpointCommandN,
    SetpointCommandS,
    SetpointCommandScaled,
    ShortFloat,
    SingleCommand,
    SinglePoint,
    StepPosition,
    TypeID,
)
from core.protocol.types import (
    TestCommand as TSTestCommand,
)
from core.protocol.types import (
    TestCommandBitPattern as TSTestBitPattern,
)
from core.protocol.types import (
    TestCommandWithTime as TSTestWithTime,
)

# ── ParsedIO ─────────────────────────────────────────────────────

def test_parsed_io_without_time_tag():
    """无时标：has_time=False、time_str 为空、to_dict 不含 timestamp."""
    obj = pio.ParsedIO(ioa=100, type_id=TypeID.M_SP_NA_1, cot=3,
                      value=SinglePoint(value=True, quality=QualityDescriptor()),
                      display_value="合(ON)")

    assert obj.has_time is False
    assert obj.time_str == ""
    assert obj.quality_str == "GOOD"
    d = obj.to_dict()
    assert d == {
        "ioa": 100,
        "type_id": "M_SP_NA_1",
        "cot": 3,
        "display_value": "合(ON)",
        "quality": "GOOD",
    }
    assert "timestamp" not in d


def test_parsed_io_with_time_tag_and_bad_quality():
    """有时标 + 非 GOOD 品质：time_str/to_dict.timestamp 均填充，quality_str 展开品质位."""
    ts = CP56Time2a.now()
    obj = pio.ParsedIO(ioa=1, time_tag=ts, quality=QualityDescriptor(raw=0x11))

    assert obj.has_time is True
    assert obj.time_str == ts.to_datetime_str()
    assert obj.quality_str == "OV|BL"
    assert obj.to_dict()["timestamp"] == ts.to_datetime_str()
    assert obj.to_dict()["quality"] == "OV|BL"


# ── parse_* 便捷入口 ─────────────────────────────────────────────

@pytest.mark.parametrize("value,factory,expected_size", [
    (SinglePoint(value=True, quality=QualityDescriptor()), pio.parse_single_point, 1),
    (DoublePoint(value=2, quality=QualityDescriptor()), pio.parse_double_point, 1),
    (StepPosition(value=32, quality=QualityDescriptor(), transient=False),
     pio.parse_step_position, 2),
    (NormalizedValue(value=0.5, quality=QualityDescriptor()), pio.parse_normalized, 3),
    (ScaledValue(value=12345, quality=QualityDescriptor()), pio.parse_scaled, 3),
    (ShortFloat(value=220.5, quality=QualityDescriptor()), pio.parse_short_float, 5),
    (CounterValue(value=123456, quality=QualityDescriptor(), sequence=5),
     pio.parse_counter, 5),
    (BitString32(value=0x12345678), pio.parse_bitstring32, 4),
])
def test_parse_value_roundtrip_and_consumed_size(value, factory, expected_size):
    """各 parse_* 应解析回等价对象，并返回正确的消耗字节数."""
    raw = value.to_bytes()
    parsed, consumed = factory(raw)

    assert consumed == expected_size
    assert consumed == len(raw)
    assert type(parsed) is type(value)
    assert parsed.to_bytes() == raw


def test_parse_single_command():
    """parse_single_command 应返回单命令对象与 1 字节消耗."""
    cmd = SingleCommand(ioa=100, state=True, select=False, qu=0)
    parsed, consumed = pio.parse_single_command(cmd.to_bytes(), 0, 100)

    assert consumed == 1
    assert parsed.state is True
    assert parsed.select is False


def test_parse_double_command():
    """parse_double_command 应返回双命令对象与 1 字节消耗."""
    cmd = DoubleCommand(ioa=200, state=2, select=True, qu=0)
    parsed, consumed = pio.parse_double_command(cmd.to_bytes(), 0, 200)

    assert consumed == 1
    assert parsed.state == 2
    assert parsed.select is True


def test_parse_offset_is_respected():
    """偏移解析：跳过前缀字节后仍能正确解析."""
    raw = b"\xaa\xbb" + SinglePoint(value=True, quality=QualityDescriptor()).to_bytes()
    parsed, consumed = pio.parse_single_point(raw, offset=2)

    assert consumed == 1
    assert parsed.value is True


# ── format_value_display ─────────────────────────────────────────

def test_format_single_point_on_off():
    """单点：合(ON) / 分(OFF) 两种显示."""
    assert pio.format_value_display(
        TypeID.M_SP_NA_1, SinglePoint(value=True, quality=QualityDescriptor())
    ) == "合(ON)"
    assert pio.format_value_display(
        TypeID.M_SP_NA_1, SinglePoint(value=False, quality=QualityDescriptor())
    ) == "分(OFF)"


def test_format_double_point_uses_state_str():
    dp = DoublePoint(value=2, quality=QualityDescriptor())
    assert pio.format_value_display(TypeID.M_DP_NA_1, dp) == dp.state_str


def test_format_regulating_step_uses_state_str():
    rc = RegulatingStepCommand(ioa=1, state=2, select=False, qu=0)
    shown = pio.format_value_display(TypeID.C_RC_NA_1, rc)
    assert shown.startswith("执行 ")
    assert shown.endswith(rc.state_str)


def test_format_double_command_select_and_state():
    dc = DoubleCommand(ioa=1, state=2, select=True, qu=0)
    assert pio.format_value_display(TypeID.C_DC_NA_1, dc) == "选择 state=2"


@pytest.mark.parametrize("value,expected", [
    # 遥测/遥信类
    (StepPosition(value=32, quality=QualityDescriptor(), transient=True), "32 T"),
    (StepPosition(value=32, quality=QualityDescriptor(), transient=False), "32 "),
    (NormalizedValue(value=0.5, quality=QualityDescriptor()), "0.500000"),
    (ScaledValue(value=12345, quality=QualityDescriptor()), "12345"),
    (ShortFloat(value=220.5, quality=QualityDescriptor()), "220.5000"),
    (CounterValue(value=123456, quality=QualityDescriptor(), sequence=5), "123456"),
    (BitString32(value=0x12345678), "0x12345678"),
    # 控制类
    (SingleCommand(ioa=1, state=True, select=False, qu=0), "执行 ON"),
    (SingleCommand(ioa=1, state=False, select=True, qu=0), "选择 OFF"),
    (SetpointCommandN(ioa=1, value=0.5, select=False, qu=0), "执行 0.500000"),
    (SetpointCommandS(ioa=1, value=220.5, select=True, qu=0), "选择 220.5000"),
    (SetpointCommandScaled(ioa=1, value=12345, select=False, qu=0), "执行 12345"),
    (BitString32Command(ioa=1, value=0x0A0B0C0D), "0x0A0B0C0D"),
    # 系统命令
    (InterrogationCommand(ioa=0, qoi=20), "QOI=20 (站召唤)"),
    (CounterInterrogationCommand(ioa=0, qcc=0), "QCC=0x00 (冻结=0, 组=0)"),
    (ReadCommand(ioa=100), "IOA=100"),
    (ResetProcessCommand(ioa=0, qualifier=1), "限定词=1"),
    (DelayCommand(ioa=0, delay_ms=500), "延时=500ms"),
    # 参数命令
    (ParameterCommandNormalized(ioa=1, value=0.75, param_change=1), "值=0.750000 变更=1"),
    (ParameterCommandFloat(ioa=1, value=220.5, param_change=0), "值=220.5000 变更=0"),
    (ParameterCommandNormalizedNoQuality(ioa=1, value=0.25), "值=0.250000"),
    # 文件传输
    (FileReady(ioa=0, file_name=1, file_length=1024, status=0), "文件=1 长度=1024 状态=缺省"),
    (SectionReady(ioa=0, file_name=1, section_name=1, section_length=512, status=0),
     "文件=1 节=1 长度=512 状态=0"),
    (CallDirectory(ioa=0, file_name=1, section_name=1, qualifier=5),
     "文件=1 节=1 限定词=目录"),
    (LastSection(ioa=0, file_name=1, section_name=2, last_segment=3, status=0),
     "文件=1 节=2 最后段=3 状态=缺省"),
    (AckFileSection(ioa=0, file_name=1, section_name=1, qualifier=3),
     "文件=1 节=1 限定词=肯定节"),
    (FileSegment(ioa=0, file_name=1, section_name=1, data=b"\x01\x02\x03"),
     "文件=1 节=1 数据长度=3"),
    (FileSelectCallGet(ioa=0, file_name=1, section_name=1, qualifier=1),
     "文件=1 节=1 限定词=请求读"),
    (FileReadyAck(ioa=0, file_name=1, file_length=10, status=0), "文件=1 长度=10 状态=0"),
    (SectionReadyAck(ioa=0, file_name=1, section_name=1, section_length=10, status=0),
     "文件=1 节=1 长度=10 状态=0"),
    # 兜底分支
    (b"\x01\xff", "01FF"),
    (5, "5"),
    (1.5, "1.5"),
    (None, ""),
])
def test_format_value_display_branches(value, expected):
    """各值类型分支的显示格式（含 bytes / 数值 / None 兜底）."""
    assert pio.format_value_display(TypeID.M_SP_NA_1, value) == expected


def test_format_value_display_fallback_uses_str():
    """未识别对象走 ``str(value)`` 兜底."""
    marker = object()
    assert pio.format_value_display(TypeID.M_SP_NA_1, marker) == str(marker)


def test_format_parameter_scaled_alias():
    """标度化参数（别名导入）显示格式."""
    from core.protocol.types import ParameterCommandScaled as ParamCmdScaled

    assert pio.format_value_display(
        TypeID.P_ME_NB_1, ParamCmdScaled(ioa=1, value=500, param_change=2)
    ) == "值=500 变更=2"


def test_format_parameter_activation_and_protection_event():
    """参数激活 / 继电保护事件 / 成组单点 的显示格式."""
    from core.protocol.types import ParameterActivation as ParamAct

    act = ParamAct(ioa=1, qualifier=1)
    assert pio.format_value_display(TypeID.P_AC_NA_1, act) == f"操作={act.action_str}"

    evt = ProtectionEvent(ioa=1, event_value=7, quality=QualityDescriptor())
    assert pio.format_value_display(TypeID.M_EP_TA_1, evt).startswith("事件值=7")

    grp = GroupSinglePointWithStatus(ioa=1, points=[(True, False), (False, True)])
    assert pio.format_value_display(
        TypeID.M_PS_NA_1, grp
    ) == "[0:合(未检), 1:分(检)]"


def test_format_clock_sync_and_test_commands():
    """时钟同步 / 测试命令系列（含时标）的显示格式含时间字段."""
    assert pio.format_value_display(
        TypeID.C_CS_NA_1, ClockSyncCommand(ioa=0)
    ).startswith("时间=")

    tc = TSTestCommand(ioa=0)
    assert pio.format_value_display(TypeID.C_TS_NA_1, tc) == f"测试模式=0x{tc.test_pattern:04X}"

    tct = TSTestWithTime(ioa=0)
    shown = pio.format_value_display(TypeID.C_TS_TA_1, tct)
    assert shown.startswith(f"测试模式=0x{tct.test_pattern:04X}")
    assert "时间=" in shown

    tcb = TSTestBitPattern(ioa=0)
    assert pio.format_value_display(
        TypeID.C_TS_NB_1, tcb
    ).startswith("测试模式=0x")


def test_format_initialization_end():
    ie = InitializationEnd(ioa=0, cause=0)
    assert pio.format_value_display(
        TypeID.M_EI_NA_1, ie
    ) == f"原因={ie.cause_str}"


def test_format_directory_entry_includes_time():
    """目录项显示含时间字段（CP56 → 可读时间）."""
    entry = DirectoryEntry(ioa=0, file_name=1, file_length=10, status=0)
    shown = pio.format_value_display(TypeID.F_DR_TA_1, entry)
    assert entry.time_tag.to_datetime_str() in shown


# ── 品质 / 时标提取 ──────────────────────────────────────────────

def test_get_value_quality_from_value_object():
    """带 quality 属性 → 返回其品质."""
    quality = QualityDescriptor()
    quality.quality = 0x10
    value = SinglePoint(value=True, quality=quality)

    assert pio.get_value_quality(value) is quality


def test_get_value_quality_fallback_is_good():
    """无 quality 属性（如 int）→ 返回默认 GOOD 品质."""
    result = pio.get_value_quality(123)
    assert isinstance(result, QualityDescriptor)
    assert result.is_good


def test_get_value_timestamp_from_value_object():
    """带 time_tag 属性 → 返回其时标."""
    cmd = ClockSyncCommand(ioa=0)
    assert pio.get_value_timestamp(cmd) is cmd.time_tag


def test_get_value_timestamp_fallback_is_none():
    """无 time_tag 属性 → 返回 None."""
    assert pio.get_value_timestamp(123) is None
    assert pio.get_value_timestamp(SinglePoint(value=True, quality=QualityDescriptor())) is None
