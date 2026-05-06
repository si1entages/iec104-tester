"""自动化测试脚本引擎.

支持 YAML 脚本定义测试序列，自动执行并判定 PASS/FAIL。

用法:
    from core.testing import TestRunner

    runner = TestRunner()
    runner.load_script("tests/scripts/basic_gi.yaml")
    result = runner.run()
    print(result.summary())
"""

from .runner import TestRunner
from .context import TestContext, StepResult, TestResult
from .script import ScriptLoader, TestScript, TestStep
from .actions import ActionRegistry
from .assertions import AssertionEngine
from .report import ReportGenerator

__all__ = [
    "TestRunner",
    "TestContext",
    "StepResult",
    "TestResult",
    "ScriptLoader",
    "TestScript",
    "TestStep",
    "ActionRegistry",
    "AssertionEngine",
    "ReportGenerator",
]
