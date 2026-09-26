"""pytest 配置和共享 fixtures."""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDUBuilder
from core.protocol.sequence import SequenceManager
from core.protocol.state_machine import ConnectionStateMachine
from core.protocol.types import (
    BitString32,
    CounterInterrogationCommand,
    CounterValue,
    CP24Time2a,
    CP56Time2a,
    DoubleCommand,
    DoublePoint,
    FileReady,
    FileSegment,
    InterrogationCommand,
    NormalizedValue,
    ParameterActivation,
    ParameterCommandFloat,
    ParameterCommandNormalized,
    QualityDescriptor,
    RegulatingStepCommand,
    ScaledValue,
    SectionReady,
    SetpointCommandN,
    SetpointCommandS,
    SetpointCommandScaled,
    ShortFloat,
    SingleCommand,
    SinglePoint,
    StepPosition,
)
from core.protocol.types import (
    ParameterCommandScaled as ParamCmdScaled,
)


@pytest.fixture
def apci_codec():
    """APCI 编解码器 fixture."""
    return APCICodec


@pytest.fixture
def asdu_builder():
    """ASDU Builder fixture."""
    return ASDUBuilder


@pytest.fixture
def sequence_manager():
    """序列号管理器 fixture."""
    return SequenceManager(k=12, w=8)


@pytest.fixture
def state_machine():
    """连接状态机 fixture."""
    return ConnectionStateMachine(t0=30, t1=15, t2=10, t3=20)


@pytest.fixture
def quality_descriptor():
    """品质描述词 fixture."""
    return QualityDescriptor()


@pytest.fixture
def cp56time2a():
    """CP56Time2a 时标 fixture."""
    return CP56Time2a.now()


@pytest.fixture
def cp24time2a():
    """CP24Time2a 时标 fixture."""
    return CP24Time2a(millisecond=0, minute=0, invalid=False)


@pytest.fixture
def single_point():
    """单点信息 fixture."""
    return SinglePoint(value=True, quality=QualityDescriptor())


@pytest.fixture
def double_point():
    """双点信息 fixture."""
    return DoublePoint(value=2, quality=QualityDescriptor())  # 合(ON)


@pytest.fixture
def normalized_value():
    """归一化值 fixture."""
    return NormalizedValue(value=0.5, quality=QualityDescriptor())


@pytest.fixture
def scaled_value():
    """标度化值 fixture."""
    return ScaledValue(value=12345, quality=QualityDescriptor())


@pytest.fixture
def short_float():
    """短浮点数 fixture."""
    return ShortFloat(value=220.5, quality=QualityDescriptor())


@pytest.fixture
def counter_value():
    """累计量 fixture."""
    return CounterValue(value=123456, quality=QualityDescriptor(), sequence=5)


@pytest.fixture
def step_position():
    """步位置信息 fixture."""
    return StepPosition(value=32, quality=QualityDescriptor(), transient=False)


@pytest.fixture
def bitstring32():
    """32比特串 fixture."""
    return BitString32(value=0x12345678)


@pytest.fixture
def single_command():
    """单命令 fixture."""
    return SingleCommand(ioa=100, state=True, select=False, qu=0)


@pytest.fixture
def double_command():
    """双命令 fixture."""
    return DoubleCommand(ioa=100, state=2, select=False, qu=0)


@pytest.fixture
def regulating_step_command():
    """升降命令 fixture."""
    return RegulatingStepCommand(ioa=100, state=2, select=False, qu=0)


@pytest.fixture
def setpoint_command_n():
    """归一化设点命令 fixture."""
    return SetpointCommandN(ioa=100, value=0.5, select=False, qu=0)


@pytest.fixture
def setpoint_command_s():
    """短浮点设点命令 fixture."""
    return SetpointCommandS(ioa=100, value=220.5, select=False, qu=0)


@pytest.fixture
def setpoint_command_scaled():
    """标度化设点命令 fixture."""
    return SetpointCommandScaled(ioa=100, value=12345, select=False, qu=0)


@pytest.fixture
def interrogation_command():
    """总召唤命令 fixture."""
    return InterrogationCommand(ioa=0, qoi=20)


@pytest.fixture
def counter_interrogation_command():
    """累计量召唤命令 fixture."""
    return CounterInterrogationCommand(ioa=0, qcc=0)


@pytest.fixture
def parameter_normalized():
    """归一化参数命令 fixture."""
    return ParameterCommandNormalized(ioa=100, value=0.75, param_change=1)


@pytest.fixture
def parameter_scaled():
    """标度化参数命令 fixture."""
    return ParamCmdScaled(ioa=100, value=500, param_change=2)


@pytest.fixture
def parameter_float():
    """短浮点参数命令 fixture."""
    return ParameterCommandFloat(ioa=100, value=220.5, param_change=0)


@pytest.fixture
def parameter_activation():
    """参数激活命令 fixture."""
    return ParameterActivation(ioa=100, qualifier=1)


@pytest.fixture
def file_ready():
    """文件准备就绪 fixture."""
    return FileReady(ioa=0, file_name=1, file_length=1024, status=0)


@pytest.fixture
def section_ready():
    """节准备就绪 fixture."""
    return SectionReady(ioa=0, file_name=1, section_name=1, section_length=512, status=0)


@pytest.fixture
def file_segment():
    """段 fixture."""
    return FileSegment(ioa=0, file_name=1, section_name=1, segment_number=1, data=b'\x01\x02\x03')
