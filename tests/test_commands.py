"""命令类型测试."""

from core.protocol.types import (
    AckFileSection,
    CallDirectory,
    CounterInterrogationCommand,
    FileReady,
    FileSegment,
    InterrogationCommand,
    LastSection,
    ParameterActivation,
    ParameterCommandFloat,
    ParameterCommandNormalized,
    ParameterCommandNormalizedNoQuality,
    RegulatingStepCommand,
    SectionReady,
    SetpointCommandN,
    SetpointCommandS,
    SetpointCommandScaled,
)
from core.protocol.types import (
    ParameterCommandScaled as ParamCmdScaled,
)


def test_regulating_step_command():
    """测试升降命令编解码."""
    print("=== RegulatingStepCommand Tests ===")

    # 测试升一步
    rc = RegulatingStepCommand(ioa=100, state=2, select=False, qu=0)
    data = rc.to_bytes()
    rc2 = RegulatingStepCommand.from_bytes(data, ioa=100)
    assert rc2.state == 2
    assert rc2.select == False
    assert rc2.state_str == "升一步"

    # 测试降一步
    rc = RegulatingStepCommand(ioa=100, state=1, select=True, qu=5)
    data = rc.to_bytes()
    rc2 = RegulatingStepCommand.from_bytes(data, ioa=100)
    assert rc2.state == 1
    assert rc2.select == True
    assert rc2.qu == 5

    print("  ✅ RegulatingStepCommand tests passed")


def test_setpoint_commands():
    """测试设点命令编解码."""
    print("=== SetpointCommand Tests ===")

    # 归一化设点
    sn = SetpointCommandN(ioa=100, value=0.5, select=False, qu=0)
    data = sn.to_bytes()
    sn2 = SetpointCommandN.from_bytes(data, ioa=100)
    assert abs(sn2.value - 0.5) < 0.001
    assert sn2.select == False

    # 标度化设点
    ss = SetpointCommandScaled(ioa=100, value=12345, select=True, qu=3)
    data = ss.to_bytes()
    ss2 = SetpointCommandScaled.from_bytes(data, ioa=100)
    assert ss2.value == 12345
    assert ss2.select == True
    assert ss2.qu == 3

    # 短浮点设点
    sf = SetpointCommandS(ioa=100, value=220.5, select=False, qu=0)
    data = sf.to_bytes()
    sf2 = SetpointCommandS.from_bytes(data, ioa=100)
    assert abs(sf2.value - 220.5) < 0.1

    print("  ✅ SetpointCommand tests passed")


def test_interrogation_command():
    """测试总召唤命令编解码."""
    print("=== InterrogationCommand Tests ===")

    # 站召唤
    ic = InterrogationCommand(ioa=0, qoi=20)
    data = ic.to_bytes()
    ic2 = InterrogationCommand.from_bytes(data, ioa=0)
    assert ic2.qoi == 20
    assert ic2.qoi_str == "站召唤"

    # 组召唤 (标准: QOI = 20 + 组号; 第5组 → QOI=25)
    ic = InterrogationCommand(ioa=0, qoi=25)
    data = ic.to_bytes()
    ic2 = InterrogationCommand.from_bytes(data, ioa=0)
    assert ic2.qoi == 25
    assert ic2.qoi_str == "第5组召唤"

    print("  ✅ InterrogationCommand tests passed")


def test_counter_interrogation_command():
    """测试累计量召唤命令编解码."""
    print("=== CounterInterrogationCommand Tests ===")

    # qcc=0x45 = 0b01000101: freeze_code=2 (冻结复位), group=5
    cic = CounterInterrogationCommand(ioa=0, qcc=0x45)
    data = cic.to_bytes()
    cic2 = CounterInterrogationCommand.from_bytes(data, ioa=0)
    assert cic2.qcc == 0x45
    assert cic2.freeze_code == 2  # (0x45 >> 5) & 0x07 = 2
    assert cic2.group == 5        # 0x45 & 0x07 = 5

    # qcc=0x20 = 0b00100000: freeze_code=1 (冻结不复位), group=0 (站)
    cic = CounterInterrogationCommand(ioa=0, qcc=0x20)
    data = cic.to_bytes()
    cic2 = CounterInterrogationCommand.from_bytes(data, ioa=0)
    assert cic2.freeze_code == 1
    assert cic2.group == 0
    assert cic2.freeze_str == "冻结不复位"

    print("  ✅ CounterInterrogationCommand tests passed")


def test_parameter_commands():
    """测试参数命令编解码."""
    print("=== ParameterCommand Tests ===")

    # 归一化参数
    pn = ParameterCommandNormalized(ioa=100, value=0.75, param_change=1)
    data = pn.to_bytes()
    pn2 = ParameterCommandNormalized.from_bytes(data, ioa=100)
    assert abs(pn2.value - 0.75) < 0.001
    assert pn2.param_change == 1

    # 标度化参数
    ps = ParamCmdScaled(ioa=100, value=500, param_change=2)
    data = ps.to_bytes()
    ps2 = ParamCmdScaled.from_bytes(data, ioa=100)
    assert ps2.value == 500
    assert ps2.param_change == 2

    # 短浮点参数
    pf = ParameterCommandFloat(ioa=100, value=220.5, param_change=0)
    data = pf.to_bytes()
    pf2 = ParameterCommandFloat.from_bytes(data, ioa=100)
    assert abs(pf2.value - 220.5) < 0.1

    # 不带品质描述词的归一化参数
    pnd = ParameterCommandNormalizedNoQuality(ioa=100, value=0.5)
    data = pnd.to_bytes()
    pnd2 = ParameterCommandNormalizedNoQuality.from_bytes(data, ioa=100)
    assert abs(pnd2.value - 0.5) < 0.001

    # 参数激活
    pa = ParameterActivation(ioa=100, qualifier=1)
    data = pa.to_bytes()
    pa2 = ParameterActivation.from_bytes(data, ioa=100)
    assert pa2.qualifier == 1
    assert pa2.action_str == "激活"

    print("  ✅ ParameterCommand tests passed")


def test_file_transfer_types():
    """测试文件传输类型编解码."""
    print("=== FileTransfer Tests ===")

    # 文件准备就绪
    fr = FileReady(ioa=0, file_name=1, file_length=1024, status=0)
    data = fr.to_bytes()
    fr2 = FileReady.from_bytes(data, ioa=0)
    assert fr2.file_name == 1
    assert fr2.file_length == 1024
    assert fr2.status == 0

    # 节准备就绪
    sr = SectionReady(ioa=0, file_name=1, section_name=1, section_length=512, status=0)
    data = sr.to_bytes()
    sr2 = SectionReady.from_bytes(data, ioa=0)
    assert sr2.file_name == 1
    assert sr2.section_name == 1
    assert sr2.section_length == 512

    # 召唤目录
    cd = CallDirectory(ioa=0, file_name=0, section_name=0, qualifier=5)
    data = cd.to_bytes()
    cd2 = CallDirectory.from_bytes(data, ioa=0)
    assert cd2.qualifier == 5
    assert cd2.qualifier_str == "选择节"   # 标准 SCQ=5 = SELECT_SECTION

    # 最后的节（信息体 = NOF(2)+NOS(1)+LSQ(1)+CHS(1)，无"段号/状态"字段）
    ls = LastSection(ioa=0, file_name=1, section_name=1, lsq=2, chs=0)
    data = ls.to_bytes()
    assert data == bytes([1, 0, 1, 2, 0])
    ls2 = LastSection.from_bytes(data, ioa=0)
    assert ls2.lsq == 2
    assert ls2.lsq_str == "FILE_TRANSFER_WITH_DEACT"

    # 确认文件/节
    af = AckFileSection(ioa=0, file_name=1, section_name=1, qualifier=1)
    data = af.to_bytes()
    af2 = AckFileSection.from_bytes(data, ioa=0)
    assert af2.qualifier == 1
    assert af2.qualifier_str == "肯定文件"

    # 段（F_SG_NA_1 信息体 = NOF(2)+NOS(1)+LOS(1)+数据，无段号字段）
    sg = FileSegment(ioa=0, file_name=1, section_name=1, data=b'\x01\x02\x03')
    data = sg.to_bytes()
    assert data == bytes([1, 0, 1, 3]) + b'\x01\x02\x03'   # LOS=3 在第 4 字节
    sg2 = FileSegment.from_bytes(data, ioa=0)
    assert sg2.data == b'\x01\x02\x03'

    print("  ✅ FileTransfer tests passed")
