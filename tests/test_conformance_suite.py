"""一致性测试套件接入 pytest（C 类：conformance → CI）.

`tests/conformance/test_conformance.py` 是独立的、自建 runner 的一致性套件
（50 个 case，11 个 `_test_*` 方法，可单独运行）。本文件把它接入 pytest：

- 方法级参数化：每个 `_test_*` 各成一个 pytest 用例，失败时列出具体 case
  （id/name/result/message），便于定位到标准条目；
- 汇总用例：跑全量并锁死 `total == 50`、无 FAIL/ERROR/SKIP——套件被悄悄删减
  或某个子项未产生结果都会红灯（防止「0 个用例也算通过」）。

注意：不改动原套件的独立运行方式（`python tests/conformance/test_conformance.py`），
两套入口共用同一份测试逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from tests.conformance.test_conformance import (
    ConformanceTestSuite,
)
from tests.conformance.test_conformance import (
    TestResult as SuiteResult,
)

# 套件期望的 case 总数（与 PROJECT.md / tests/README 的「42 个用例」一致）
EXPECTED_TOTAL = 50

SUITE_METHODS = [
    "_test_apci_encoding",
    "_test_apci_decoding",
    "_test_apci_frame_types",
    "_test_asdu_encoding",
    "_test_asdu_decoding",
    "_test_type_identifiers",
    "_test_sequence_numbers",
    "_test_flow_control",
    "_test_state_machine",
    "_test_timers",
    "_test_negative_cases",
]


def _bad_cases(suite: ConformanceTestSuite):
    return [
        c for c in suite.report.cases
        if c.result in (SuiteResult.FAIL, SuiteResult.ERROR, SuiteResult.SKIP)
    ]


def _format(cases) -> str:
    return "\n".join(
        f"  {c.id} [{c.category}] {c.name}: {c.result.value}"
        + (f" — {c.message}" if c.message else "")
        for c in cases
    )


@pytest.mark.parametrize("method_name", SUITE_METHODS)
def test_conformance_method(method_name: str):
    """逐个套件方法执行：不允许 FAIL/ERROR/SKIP，且必须产生 case."""
    suite = ConformanceTestSuite()
    getattr(suite, method_name)()
    cases = suite.report.cases
    assert cases, f"{method_name} 未产生任何测试结果"
    bad = _bad_cases(suite)
    assert not bad, f"{method_name} 存在未通过项：\n{_format(bad)}"


def test_conformance_suite_total_and_all_pass():
    """全量汇总：50 个 case 全部 PASS（防止套件删减 / 静默跳过）."""
    report = ConformanceTestSuite().run_all()
    assert report.total == EXPECTED_TOTAL, (
        f"一致性套件 case 数变化：{report.total} != {EXPECTED_TOTAL}"
        "（如确为新增/删减，请同步 PROJECT.md、tests/README 与本常量）"
    )
    bad = [c for c in report.cases if c.result != SuiteResult.PASS]
    assert not bad, f"一致性套件存在未通过项：\n{_format(bad)}"
    assert report.skipped == 0 and report.errors == 0 and report.failed == 0
