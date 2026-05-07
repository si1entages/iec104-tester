"""信息对象解析器 — 带时标/品质描述的完整解析.

提供高层 API，将 ASDU 原始数据解析为结构化的信息对象列表，
包含时标、品质描述词、值的完整信息。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Optional

from .types import (
    TypeID, COT, QualityDescriptor,
    SinglePoint, DoublePoint, StepPosition,
    NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, BitString32,
    SingleCommand, DoubleCommand,
    SetpointCommandN, SetpointCommandS, SetpointCommandScaled,
    RegulatingStepCommand, BitString32Command,
    InterrogationCommand, CounterInterrogationCommand,
    ReadCommand, ClockSyncCommand,
    TestCommand, TestCommandWithTime, TestCommandBitPattern,
    ResetProcessCommand, DelayCommand,
    InitializationEnd, ProtectionEvent, GroupSinglePointWithStatus,
    ParameterCommandNormalized, ParameterCommandScaled as ParamCmdScaled,
    ParameterCommandFloat, ParameterCommandNormalizedNoQuality,
    ParameterActivation,
    FileReady, SectionReady, CallDirectory, LastSection, AckFileSection,
    FileSegment, DirectoryEntry, FileSelectCallGet, FileReadyAck, SectionReadyAck,
    CP24Time2a, CP56Time2a,
)


@dataclass
class ParsedIO:
    """解析后的信息对象 — 包含完整上下文."""
    ioa: int = 0                    # 信息对象地址
    type_id: TypeID = TypeID.M_SP_NA_1
    cot: int = 0                    # 传送原因
    value: Any = None               # 原始值对象
    display_value: str = ""         # 显示用字符串
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    time_tag: Optional[CP56Time2a] = None
    raw_bytes: bytes = b""

    @property
    def has_time(self) -> bool:
        return self.time_tag is not None

    @property
    def quality_str(self) -> str:
        return str(self.quality) if not self.quality.is_good else "GOOD"

    @property
    def time_str(self) -> str:
        if self.time_tag:
            return self.time_tag.to_datetime_str()
        return ""

    def to_dict(self) -> dict:
        """转为字典（便于序列化）."""
        result = {
            "ioa": self.ioa,
            "type_id": self.type_id.name,
            "cot": self.cot,
            "display_value": self.display_value,
            "quality": self.quality_str,
        }
        if self.time_tag:
            result["timestamp"] = self.time_str
        return result


def parse_single_point(raw: bytes, offset: int = 0) -> tuple[SinglePoint, int]:
    """解析单点信息，返回 (值, 消耗字节数)."""
    sp = SinglePoint.from_bytes(raw, offset)
    return sp, 1


def parse_double_point(raw: bytes, offset: int = 0) -> tuple[DoublePoint, int]:
    """解析双点信息."""
    dp = DoublePoint.from_bytes(raw, offset)
    return dp, 1


def parse_step_position(raw: bytes, offset: int = 0) -> tuple[StepPosition, int]:
    """解析步位置信息."""
    sp = StepPosition.from_bytes(raw, offset)
    return sp, 2


def parse_normalized(raw: bytes, offset: int = 0) -> tuple[NormalizedValue, int]:
    """解析归一化值."""
    nv = NormalizedValue.from_bytes(raw, offset)
    return nv, 3


def parse_scaled(raw: bytes, offset: int = 0) -> tuple[ScaledValue, int]:
    """解析标度化值."""
    sv = ScaledValue.from_bytes(raw, offset)
    return sv, 3


def parse_short_float(raw: bytes, offset: int = 0) -> tuple[ShortFloat, int]:
    """解析短浮点数."""
    sf = ShortFloat.from_bytes(raw, offset)
    return sf, 5


def parse_counter(raw: bytes, offset: int = 0) -> tuple[CounterValue, int]:
    """解析累计量."""
    cv = CounterValue.from_bytes(raw, offset)
    return cv, 5


def parse_bitstring32(raw: bytes, offset: int = 0) -> tuple[BitString32, int]:
    """解析32比特串."""
    bs = BitString32.from_bytes(raw, offset)
    return bs, 4


def parse_single_command(raw: bytes, offset: int = 0, ioa: int = 0) -> tuple[SingleCommand, int]:
    """解析单命令."""
    sc = SingleCommand.from_bytes(raw, offset, ioa)
    return sc, 1


def parse_double_command(raw: bytes, offset: int = 0, ioa: int = 0) -> tuple[DoubleCommand, int]:
    """解析双命令."""
    dc = DoubleCommand.from_bytes(raw, offset, ioa)
    return dc, 1


def format_value_display(type_id: TypeID, value: Any) -> str:
    """格式化信息对象的显示值."""
    if isinstance(value, SinglePoint):
        return "合(ON)" if value.value else "分(OFF)"
    elif isinstance(value, DoublePoint):
        return value.state_str
    elif isinstance(value, StepPosition):
        return f"{value.value} {'T' if value.transient else ''}"
    elif isinstance(value, NormalizedValue):
        return f"{value.value:.6f}"
    elif isinstance(value, ScaledValue):
        return f"{value.value}"
    elif isinstance(value, ShortFloat):
        return f"{value.value:.4f}"
    elif isinstance(value, CounterValue):
        return f"{value.value}"
    elif isinstance(value, BitString32):
        return f"0x{value.value:08X}"
    elif isinstance(value, SingleCommand):
        return f"{'选择' if value.select else '执行'} {'ON' if value.state else 'OFF'}"
    elif isinstance(value, DoubleCommand):
        return f"{'选择' if value.select else '执行'} state={value.state}"
    elif isinstance(value, SetpointCommandN):
        return f"{'选择' if value.select else '执行'} {value.value:.6f}"
    elif isinstance(value, SetpointCommandS):
        return f"{'选择' if value.select else '执行'} {value.value:.4f}"
    elif isinstance(value, SetpointCommandScaled):
        return f"{'选择' if value.select else '执行'} {value.value}"
    elif isinstance(value, RegulatingStepCommand):
        return f"{'选择' if value.select else '执行'} {value.state_str}"
    elif isinstance(value, BitString32Command):
        return f"0x{value.value:08X}"
    elif isinstance(value, InterrogationCommand):
        return f"QOI={value.qoi} ({value.qoi_str})"
    elif isinstance(value, CounterInterrogationCommand):
        return f"QCC=0x{value.qcc:02X} (冻结={value.freeze_code}, 组={value.group})"
    elif isinstance(value, ReadCommand):
        return f"IOA={value.ioa}"
    elif isinstance(value, ClockSyncCommand):
        return f"时间={value.time_tag.to_datetime_str()}"
    elif isinstance(value, TestCommand):
        return f"测试模式=0x{value.test_pattern:04X}"
    elif isinstance(value, TestCommandWithTime):
        return f"测试模式=0x{value.test_pattern:04X} 时间={value.time_tag.to_datetime_str()}"
    elif isinstance(value, TestCommandBitPattern):
        return f"测试模式=0x{value.pattern:04X}"
    elif isinstance(value, ResetProcessCommand):
        return f"限定词={value.qualifier}"
    elif isinstance(value, DelayCommand):
        return f"延时={value.delay_ms}ms"
    elif isinstance(value, InitializationEnd):
        return f"原因={value.cause_str}"
    elif isinstance(value, ParameterCommandNormalized):
        return f"值={value.value:.6f} 变更={value.param_change}"
    elif isinstance(value, ParameterCommandScaled):
        return f"值={value.value} 变更={value.param_change}"
    elif isinstance(value, ParameterCommandFloat):
        return f"值={value.value:.4f} 变更={value.param_change}"
    elif isinstance(value, ParameterCommandNormalizedNoQuality):
        return f"值={value.value:.6f}"
    elif isinstance(value, ParameterActivation):
        return f"操作={value.action_str}"
    elif isinstance(value, ProtectionEvent):
        return f"事件值={value.event_value} 品质={value.quality}"
    elif isinstance(value, GroupSinglePointWithStatus):
        points_str = ", ".join([f"{i}:{'合' if s else '分'}({'检' if d else '未检'})"
                                for i, (s, d) in enumerate(value.points)])
        return f"[{points_str}]"
    elif isinstance(value, FileReady):
        return f"文件={value.file_name} 长度={value.file_length} 状态={value.status_str}"
    elif isinstance(value, SectionReady):
        return f"文件={value.file_name} 节={value.section_name} 长度={value.section_length} 状态={value.status}"
    elif isinstance(value, CallDirectory):
        return f"文件={value.file_name} 节={value.section_name} 限定词={value.qualifier_str}"
    elif isinstance(value, LastSection):
        return f"文件={value.file_name} 节={value.section_name} 最后段={value.last_segment} 状态={value.status_str}"
    elif isinstance(value, AckFileSection):
        return f"文件={value.file_name} 节={value.section_name} 限定词={value.qualifier_str}"
    elif isinstance(value, FileSegment):
        return f"文件={value.file_name} 节={value.section_name} 段={value.segment_number} 数据长度={len(value.data)}"
    elif isinstance(value, DirectoryEntry):
        return f"文件={value.file_name} 长度={value.file_length} 状态={value.status} 时间={value.time_tag.to_datetime_str()}"
    elif isinstance(value, FileSelectCallGet):
        return f"文件={value.file_name} 节={value.section_name} 限定词={value.qualifier_str}"
    elif isinstance(value, FileReadyAck):
        return f"文件={value.file_name} 长度={value.file_length} 状态={value.status}"
    elif isinstance(value, SectionReadyAck):
        return f"文件={value.file_name} 节={value.section_name} 长度={value.section_length} 状态={value.status}"
    elif isinstance(value, bytes):
        return value.hex().upper()
    elif isinstance(value, (int, float)):
        return str(value)
    else:
        return str(value) if value is not None else ""


def get_value_quality(value: Any) -> QualityDescriptor:
    """从信息对象值中提取品质描述词."""
    if hasattr(value, 'quality'):
        return value.quality
    return QualityDescriptor()


def get_value_timestamp(value: Any) -> Optional[CP56Time2a]:
    """从信息对象值中提取时标."""
    if hasattr(value, 'time_tag'):
        return value.time_tag
    return None
