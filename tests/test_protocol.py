"""IEC 60870-5-104 协议核心测试 - 向后兼容版本.

此文件保留用于向后兼容，实际测试已拆分到以下文件：
- test_apci.py: APCI帧编解码测试
- test_types.py: 数据类型编解码测试
- test_asdu.py: ASDU编解码测试
- test_commands.py: 命令类型测试
- test_sequence.py: 序列号管理器测试
- test_state_machine.py: 状态机测试
- test_integration.py: 集成测试
"""

import sys
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入所有测试模块，保持向后兼容
from tests.test_apci import test_apci_u_frame, test_apci_s_frame, test_apci_i_frame
from tests.test_types import (
    test_single_point, test_double_point, test_normalized_value,
    test_short_float, test_scaled_value, test_step_position,
    test_bitstring32, test_counter_value, test_cp56time2a, test_cp24time2a,
)
from tests.test_asdu import (
    test_asdu_general_interrogation, test_asdu_single_point,
    test_asdu_short_float, test_asdu_single_command,
    test_asdu_clock_sync, test_asdu_with_parameter_commands,
)
from tests.test_commands import (
    test_regulating_step_command, test_setpoint_commands,
    test_interrogation_command, test_counter_interrogation_command,
    test_parameter_commands, test_file_transfer_types,
)
from tests.test_sequence import test_sequence_manager
from tests.test_state_machine import test_state_machine
from tests.test_integration import test_full_apdu_roundtrip


def main():
    """运行所有测试."""
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
    test_scaled_value()
    test_step_position()
    test_bitstring32()
    test_counter_value()
    test_cp24time2a()
    test_regulating_step_command()
    test_setpoint_commands()
    test_interrogation_command()
    test_counter_interrogation_command()
    test_parameter_commands()
    test_file_transfer_types()
    test_asdu_with_parameter_commands()

    print()
    print("=" * 50)
    print("✅ ALL TESTS PASSED")
    print("=" * 50)


if __name__ == "__main__":
    main()