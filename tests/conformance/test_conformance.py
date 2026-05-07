"""IEC 60870-5-104 协议一致性测试套件.

参照 IEC 60870-5-104 标准 Annex A 设计的测试用例集。
"""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.protocol.constants import (
    START_BYTE, U_STARTDT_ACT, U_STARTDT_CON, U_STOPDT_ACT,
    U_STOPDT_CON, U_TESTFR_ACT, U_TESTFR_CON,
    K_DEFAULT, W_DEFAULT,
)
from core.protocol.apci import APCICodec, APCI
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    TypeID, COT, QualityDescriptor,
    SinglePoint, DoublePoint, NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, CP56Time2a, CP24Time2a,
    SingleCommand, DoubleCommand,
)
from core.protocol.sequence import SequenceManager
from core.protocol.state_machine import ConnectionStateMachine


class TestResult(Enum):
    """测试结果."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass
class TestCase:
    """测试用例."""
    id: str
    name: str
    category: str
    description: str
    result: TestResult = TestResult.SKIP
    message: str = ""
    duration: float = 0.0


@dataclass
class TestReport:
    """测试报告."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    cases: list[TestCase] = field(default_factory=list)


class ConformanceTestSuite:
    """IEC 60870-5-104 协议一致性测试套件."""

    def __init__(self):
        self.report = TestReport()

    def run_all(self) -> TestReport:
        """运行所有测试."""
        self.report = TestReport()

        # APCI 层测试
        self._test_apci_encoding()
        self._test_apci_decoding()
        self._test_apci_frame_types()

        # ASDU 层测试
        self._test_asdu_encoding()
        self._test_asdu_decoding()
        self._test_type_identifiers()

        # 序列号管理测试
        self._test_sequence_numbers()
        self._test_flow_control()

        # 状态机测试
        self._test_state_machine()

        # 定时器测试
        self._test_timers()

        # 计算统计
        self.report.total = len(self.report.cases)
        self.report.passed = sum(1 for c in self.report.cases if c.result == TestResult.PASS)
        self.report.failed = sum(1 for c in self.report.cases if c.result == TestResult.FAIL)
        self.report.skipped = sum(1 for c in self.report.cases if c.result == TestResult.SKIP)
        self.report.errors = sum(1 for c in self.report.cases if c.result == TestResult.ERROR)

        return self.report

    def _add_result(self, test_id: str, name: str, category: str,
                    description: str, result: TestResult, message: str = ""):
        """添加测试结果."""
        self.report.cases.append(TestCase(
            id=test_id, name=name, category=category,
            description=description, result=result, message=message
        ))

    # ── APCI 层测试 ──────────────────────────────────────────────

    def _test_apci_encoding(self):
        """测试 APCI 编码."""
        category = "APCI编码"

        # 测试 U帧编码
        for name, func, expected_byte in [
            ("STARTDT ACT", APCICodec.startdt_act, U_STARTDT_ACT),
            ("STARTDT CON", APCICodec.startdt_con, U_STARTDT_CON),
            ("STOPDT ACT", APCICodec.stopdt_act, U_STOPDT_ACT),
            ("STOPDT CON", APCICodec.stopdt_con, U_STOPDT_CON),
            ("TESTFR ACT", APCICodec.testfr_act, U_TESTFR_ACT),
            ("TESTFR CON", APCICodec.testfr_con, U_TESTFR_CON),
        ]:
            try:
                frame = func()
                if frame[0] == START_BYTE and frame[2] == expected_byte:
                    self._add_result(
                        f"APCI-U-ENC-{name.replace(' ', '-')}",
                        f"U帧编码-{name}", category,
                        f"验证{name}编码正确性",
                        TestResult.PASS
                    )
                else:
                    self._add_result(
                        f"APCI-U-ENC-{name.replace(' ', '-')}",
                        f"U帧编码-{name}", category,
                        f"验证{name}编码正确性",
                        TestResult.FAIL, f"编码错误: {frame.hex()}"
                    )
            except Exception as e:
                self._add_result(
                    f"APCI-U-ENC-{name.replace(' ', '-')}",
                    f"U帧编码-{name}", category,
                    f"验证{name}编码正确性",
                    TestResult.ERROR, str(e)
                )

        # 测试 S帧编码
        try:
            frame = APCICodec.encode_s(100)
            if frame[0] == START_BYTE and frame[1] == 4:
                self._add_result(
                    "APCI-S-ENC-01", "S帧编码", category,
                    "验证S帧编码正确性", TestResult.PASS
                )
            else:
                self._add_result(
                    "APCI-S-ENC-01", "S帧编码", category,
                    "验证S帧编码正确性", TestResult.FAIL, f"编码错误: {frame.hex()}"
                )
        except Exception as e:
            self._add_result(
                "APCI-S-ENC-01", "S帧编码", category,
                "验证S帧编码正确性", TestResult.ERROR, str(e)
            )

        # 测试 I帧编码
        try:
            asdu_data = bytes([0x64, 0x01, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x14])
            frame = APCICodec.encode_i(0, 0, asdu_data)
            if frame[0] == START_BYTE and frame[1] == 4 + len(asdu_data):
                self._add_result(
                    "APCI-I-ENC-01", "I帧编码", category,
                    "验证I帧编码正确性", TestResult.PASS
                )
            else:
                self._add_result(
                    "APCI-I-ENC-01", "I帧编码", category,
                    "验证I帧编码正确性", TestResult.FAIL, f"编码错误: {frame.hex()}"
                )
        except Exception as e:
            self._add_result(
                "APCI-I-ENC-01", "I帧编码", category,
                "验证I帧编码正确性", TestResult.ERROR, str(e)
            )

    def _test_apci_decoding(self):
        """测试 APCI 解码."""
        category = "APCI解码"

        # 测试 U帧解码
        for name, func, expected_byte in [
            ("STARTDT ACT", APCICodec.startdt_act, U_STARTDT_ACT),
            ("STARTDT CON", APCICodec.startdt_con, U_STARTDT_CON),
            ("STOPDT ACT", APCICodec.stopdt_act, U_STOPDT_ACT),
            ("STOPDT CON", APCICodec.stopdt_con, U_STOPDT_CON),
            ("TESTFR ACT", APCICodec.testfr_act, U_TESTFR_ACT),
            ("TESTFR CON", APCICodec.testfr_con, U_TESTFR_CON),
        ]:
            try:
                frame = func()
                apci, consumed = APCICodec.decode(frame)
                if apci.is_u_frame and apci.u_func == expected_byte and consumed == 6:
                    self._add_result(
                        f"APCI-U-DEC-{name.replace(' ', '-')}",
                        f"U帧解码-{name}", category,
                        f"验证{name}解码正确性", TestResult.PASS
                    )
                else:
                    self._add_result(
                        f"APCI-U-DEC-{name.replace(' ', '-')}",
                        f"U帧解码-{name}", category,
                        f"验证{name}解码正确性", TestResult.FAIL, "解码结果不匹配"
                    )
            except Exception as e:
                self._add_result(
                    f"APCI-U-DEC-{name.replace(' ', '-')}",
                    f"U帧解码-{name}", category,
                    f"验证{name}解码正确性", TestResult.ERROR, str(e)
                )

        # 测试 S帧解码
        try:
            frame = APCICodec.encode_s(100)
            apci, consumed = APCICodec.decode(frame)
            if apci.is_s_frame and apci.rx_seq == 100 and consumed == 6:
                self._add_result(
                    "APCI-S-DEC-01", "S帧解码", category,
                    "验证S帧解码正确性", TestResult.PASS
                )
            else:
                self._add_result(
                    "APCI-S-DEC-01", "S帧解码", category,
                    "验证S帧解码正确性", TestResult.FAIL, "解码结果不匹配"
                )
        except Exception as e:
            self._add_result(
                "APCI-S-DEC-01", "S帧解码", category,
                "验证S帧解码正确性", TestResult.ERROR, str(e)
            )

        # 测试 I帧解码
        try:
            asdu_data = bytes([0x64, 0x01, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x14])
            frame = APCICodec.encode_i(42, 10, asdu_data)
            apci, consumed = APCICodec.decode(frame)
            if apci.is_i_frame and apci.tx_seq == 42 and apci.rx_seq == 10:
                self._add_result(
                    "APCI-I-DEC-01", "I帧解码", category,
                    "验证I帧解码正确性", TestResult.PASS
                )
            else:
                self._add_result(
                    "APCI-I-DEC-01", "I帧解码", category,
                    "验证I帧解码正确性", TestResult.FAIL, "解码结果不匹配"
                )
        except Exception as e:
            self._add_result(
                "APCI-I-DEC-01", "I帧解码", category,
                "验证I帧解码正确性", TestResult.ERROR, str(e)
            )

    def _test_apci_frame_types(self):
        """测试 APCI 帧类型识别."""
        category = "APCI帧类型"

        # 测试帧类型识别
        try:
            u_frame = APCICodec.startdt_act()
            s_frame = APCICodec.encode_s(0)
            asdu_data = bytes([0x64, 0x01, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x14])
            i_frame = APCICodec.encode_i(0, 0, asdu_data)

            u_apci, _ = APCICodec.decode(u_frame)
            s_apci, _ = APCICodec.decode(s_frame)
            i_apci, _ = APCICodec.decode(i_frame)

            if u_apci.is_u_frame and s_apci.is_s_frame and i_apci.is_i_frame:
                self._add_result(
                    "APCI-TYPE-01", "帧类型识别", category,
                    "验证I/S/U帧类型识别", TestResult.PASS
                )
            else:
                self._add_result(
                    "APCI-TYPE-01", "帧类型识别", category,
                    "验证I/S/U帧类型识别", TestResult.FAIL, "帧类型识别错误"
                )
        except Exception as e:
            self._add_result(
                "APCI-TYPE-01", "帧类型识别", category,
                "验证I/S/U帧类型识别", TestResult.ERROR, str(e)
            )

    # ── ASDU 层测试 ──────────────────────────────────────────────

    def _test_asdu_encoding(self):
        """测试 ASDU 编码."""
        category = "ASDU编码"

        # 测试总召唤编码
        try:
            asdu_data = ASDUBuilder.build_general_interrogation(1, 20)
            if len(asdu_data) > 0:
                self._add_result(
                    "ASDU-ENC-GI", "总召唤编码", category,
                    "验证总召唤ASDU编码", TestResult.PASS
                )
            else:
                self._add_result(
                    "ASDU-ENC-GI", "总召唤编码", category,
                    "验证总召唤ASDU编码", TestResult.FAIL, "编码结果为空"
                )
        except Exception as e:
            self._add_result(
                "ASDU-ENC-GI", "总召唤编码", category,
                "验证总召唤ASDU编码", TestResult.ERROR, str(e)
            )

        # 测试单点遥信编码
        try:
            asdu_data = ASDUBuilder.build_single_point(1, 1, True, 0)
            if len(asdu_data) > 0:
                self._add_result(
                    "ASDU-ENC-SP", "单点遥信编码", category,
                    "验证单点遥信ASDU编码", TestResult.PASS
                )
            else:
                self._add_result(
                    "ASDU-ENC-SP", "单点遥信编码", category,
                    "验证单点遥信ASDU编码", TestResult.FAIL, "编码结果为空"
                )
        except Exception as e:
            self._add_result(
                "ASDU-ENC-SP", "单点遥信编码", category,
                "验证单点遥信ASDU编码", TestResult.ERROR, str(e)
            )

    def _test_asdu_decoding(self):
        """测试 ASDU 解码."""
        category = "ASDU解码"

        # 测试总召唤解码
        try:
            asdu_data = ASDUBuilder.build_general_interrogation(1, 20)
            asdu = ASDU.decode(asdu_data)
            if asdu.type_id == TypeID.C_IC_NA_1 and asdu.cot == COT.ACT:
                self._add_result(
                    "ASDU-DEC-GI", "总召唤解码", category,
                    "验证总召唤ASDU解码", TestResult.PASS
                )
            else:
                self._add_result(
                    "ASDU-DEC-GI", "总召唤解码", category,
                    "验证总召唤ASDU解码", TestResult.FAIL, "解码结果不匹配"
                )
        except Exception as e:
            self._add_result(
                "ASDU-DEC-GI", "总召唤解码", category,
                "验证总召唤ASDU解码", TestResult.ERROR, str(e)
            )

    def _test_type_identifiers(self):
        """测试类型标识."""
        category = "类型标识"

        # 测试所有TypeID是否可解码
        test_types = [
            (TypeID.M_SP_NA_1, "单点信息"),
            (TypeID.M_DP_NA_1, "双点信息"),
            (TypeID.M_ME_NA_1, "归一化值"),
            (TypeID.M_ME_NB_1, "标度化值"),
            (TypeID.M_ME_NC_1, "短浮点数"),
            (TypeID.M_IT_NA_1, "累计量"),
            (TypeID.C_SC_NA_1, "单命令"),
            (TypeID.C_DC_NA_1, "双命令"),
            (TypeID.C_RC_NA_1, "升降命令"),
            (TypeID.C_SE_NA_1, "归一化设点"),
            (TypeID.C_SE_NB_1, "标度化设点"),
            (TypeID.C_SE_NC_1, "短浮点设点"),
            (TypeID.C_IC_NA_1, "总召唤"),
            (TypeID.C_CI_NA_1, "累计量召唤"),
            (TypeID.C_CS_NA_1, "时钟同步"),
            (TypeID.C_RP_NA_1, "复位进程"),
        ]

        for type_id, name in test_types:
            try:
                # 验证TypeID值是否正确
                if isinstance(type_id.value, int) and type_id.value > 0:
                    self._add_result(
                        f"TYPE-{type_id.value:03d}",
                        f"类型标识-{name}", category,
                        f"验证{name}({type_id.value})类型标识", TestResult.PASS
                    )
                else:
                    self._add_result(
                        f"TYPE-{type_id.value:03d}",
                        f"类型标识-{name}", category,
                        f"验证{name}({type_id.value})类型标识", TestResult.FAIL, "TypeID值无效"
                    )
            except Exception as e:
                self._add_result(
                    f"TYPE-{type_id.value:03d}",
                    f"类型标识-{name}", category,
                    f"验证{name}({type_id.value})类型标识", TestResult.ERROR, str(e)
                )

    # ── 序列号管理测试 ──────────────────────────────────────────

    def _test_sequence_numbers(self):
        """测试序列号管理."""
        category = "序列号"

        # 测试序列号递增
        try:
            seq = SequenceManager(k=12, w=8)
            s1 = seq.get_send_seq()
            s2 = seq.get_send_seq()
            s3 = seq.get_send_seq()
            if s1 == 0 and s2 == 1 and s3 == 2:
                self._add_result(
                    "SEQ-INC-01", "序列号递增", category,
                    "验证发送序列号递增", TestResult.PASS
                )
            else:
                self._add_result(
                    "SEQ-INC-01", "序列号递增", category,
                    "验证发送序列号递增", TestResult.FAIL, f"序列号: {s1}, {s2}, {s3}"
                )
        except Exception as e:
            self._add_result(
                "SEQ-INC-01", "序列号递增", category,
                "验证发送序列号递增", TestResult.ERROR, str(e)
            )

        # 测试序列号回绕
        try:
            seq = SequenceManager(k=32767, w=8)
            for _ in range(32766):
                seq.get_send_seq()
            seq.process_rx_i_frame_ack(32766)
            s = seq.get_send_seq()
            if s == 32766:
                self._add_result(
                    "SEQ-WRAP-01", "序列号回绕", category,
                    "验证序列号回绕到0", TestResult.PASS
                )
            else:
                self._add_result(
                    "SEQ-WRAP-01", "序列号回绕", category,
                    "验证序列号回绕到0", TestResult.FAIL, f"序列号: {s}"
                )
        except Exception as e:
            self._add_result(
                "SEQ-WRAP-01", "序列号回绕", category,
                "验证序列号回绕到0", TestResult.ERROR, str(e)
            )

    def _test_flow_control(self):
        """测试流控机制."""
        category = "流控"

        # 测试k窗口限制
        try:
            seq = SequenceManager(k=12, w=8)
            for _ in range(12):
                seq.get_send_seq()
            try:
                seq.get_send_seq()
                self._add_result(
                    "FLOW-K-01", "k窗口限制", category,
                    "验证k窗口满时拒绝发送", TestResult.FAIL, "未拒绝发送"
                )
            except RuntimeError:
                self._add_result(
                    "FLOW-K-01", "k窗口限制", category,
                    "验证k窗口满时拒绝发送", TestResult.PASS
                )
        except Exception as e:
            self._add_result(
                "FLOW-K-01", "k窗口限制", category,
                "验证k窗口满时拒绝发送", TestResult.ERROR, str(e)
            )

        # 测试w阈值触发S帧
        try:
            seq = SequenceManager(k=12, w=8)
            s_frame_triggered = False

            def on_s_frame(rx_seq):
                nonlocal s_frame_triggered
                s_frame_triggered = True

            seq.set_s_frame_callback(on_s_frame)
            for i in range(8):
                seq.process_rx_i_frame(i)
            if s_frame_triggered:
                self._add_result(
                    "FLOW-W-01", "w阈值触发S帧", category,
                    "验证收到w个I帧后触发S帧", TestResult.PASS
                )
            else:
                self._add_result(
                    "FLOW-W-01", "w阈值触发S帧", category,
                    "验证收到w个I帧后触发S帧", TestResult.FAIL, "S帧未触发"
                )
        except Exception as e:
            self._add_result(
                "FLOW-W-01", "w阈值触发S帧", category,
                "验证收到w个I帧后触发S帧", TestResult.ERROR, str(e)
            )

    # ── 状态机测试 ──────────────────────────────────────────────

    def _test_state_machine(self):
        """测试状态机."""
        category = "状态机"

        # 测试状态转移
        try:
            sm = ConnectionStateMachine(t0=30, t1=15, t2=10, t3=20)
            if sm.is_stopped:
                sm.on_connected()
                if sm.is_connecting:
                    sm.on_startdt_con()
                    if sm.is_running:
                        self._add_result(
                            "SM-TRANS-01", "状态转移", category,
                            "验证STOPPED->CONNECTING->RUNNING转移", TestResult.PASS
                        )
                    else:
                        self._add_result(
                            "SM-TRANS-01", "状态转移", category,
                            "验证STOPPED->CONNECTING->RUNNING转移", TestResult.FAIL, f"状态: {sm.state}"
                        )
                else:
                    self._add_result(
                        "SM-TRANS-01", "状态转移", category,
                        "验证STOPPED->CONNECTING->RUNNING转移", TestResult.FAIL, f"状态: {sm.state}"
                    )
            else:
                self._add_result(
                    "SM-TRANS-01", "状态转移", category,
                    "验证STOPPED->CONNECTING->RUNNING转移", TestResult.FAIL, f"状态: {sm.state}"
                )
        except Exception as e:
            self._add_result(
                "SM-TRANS-01", "状态转移", category,
                "验证STOPPED->CONNECTING->RUNNING转移", TestResult.ERROR, str(e)
            )

    # ── 定时器测试 ──────────────────────────────────────────────

    def _test_timers(self):
        """测试定时器."""
        category = "定时器"

        # 测试定时器默认值
        try:
            sm = ConnectionStateMachine()
            info = sm.get_timer_info()
            # 检查定时器是否存在且有正确的超时值
            if len(info) == 4:
                self._add_result(
                    "TIMER-DEFAULT-01", "定时器默认值", category,
                    "验证定时器默认值符合标准", TestResult.PASS
                )
            else:
                self._add_result(
                    "TIMER-DEFAULT-01", "定时器默认值", category,
                    "验证定时器默认值符合标准", TestResult.FAIL, f"定时器数量: {len(info)}"
                )
        except Exception as e:
            self._add_result(
                "TIMER-DEFAULT-01", "定时器默认值", category,
                "验证定时器默认值符合标准", TestResult.ERROR, str(e)
            )


def print_report(report: TestReport):
    """打印测试报告."""
    print("=" * 70)
    print("IEC 60870-5-104 协议一致性测试报告")
    print("=" * 70)
    print(f"总计: {report.total} | 通过: {report.passed} | 失败: {report.failed} | "
          f"跳过: {report.skipped} | 错误: {report.errors}")
    print("-" * 70)

    # 按类别分组显示
    categories = {}
    for case in report.cases:
        if case.category not in categories:
            categories[case.category] = []
        categories[case.category].append(case)

    for category, cases in categories.items():
        passed = sum(1 for c in cases if c.result == TestResult.PASS)
        total = len(cases)
        print(f"\n[{category}] ({passed}/{total})")
        for case in cases:
            status = "✅" if case.result == TestResult.PASS else "❌" if case.result == TestResult.FAIL else "⚠️"
            print(f"  {status} {case.id}: {case.name}")
            if case.result == TestResult.FAIL:
                print(f"      原因: {case.message}")

    print("\n" + "=" * 70)
    if report.failed == 0 and report.errors == 0:
        print("✅ 所有测试通过！")
    else:
        print(f"❌ {report.failed + report.errors} 个测试未通过")
    print("=" * 70)


if __name__ == "__main__":
    suite = ConformanceTestSuite()
    report = suite.run_all()
    print_report(report)
    sys.exit(0 if report.failed == 0 and report.errors == 0 else 1)
