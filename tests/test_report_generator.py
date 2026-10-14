"""ReportGenerator 回归测试 — 覆盖 text / json / html / junit 四种格式.

回归背景：HTML 格式的模板曾引用 ``TestResult`` 上并不存在的 ``description``
属性（``core/testing/report.py``），而 ``run_tests.py`` 会**无条件**生成 HTML
报告，导致脚本一跑就 ``AttributeError`` 崩溃。根因是 ``TestRunner`` 未把
``TestScript.description`` 传递到 ``TestResult``。本测试为四种格式建立护栏，
并显式断言 HTML 头部能渲染脚本描述。

说明：以模块别名 ``tctx`` 访问 ``TestResult``/``TestStatus``，避免 pytest 把
导入到本模块的同名类误当测试类收集（PytestCollectionWarning）。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from core.testing import context as tctx
from core.testing.report import ReportGenerator


def _make_result() -> tctx.TestResult:
    """构造一个含 3 步（通过 / 失败 / 跳过）的 TestResult."""
    result = tctx.TestResult(
        script_name="demo_script",
        script_path="tests/scripts/demo_script.yaml",
        description="演示脚本：连接 + 总召唤",
        status=tctx.TestStatus.FAILED,
        start_time=100.0,
        end_time=102.5,
        error_message="step 1 failed",
    )
    result.steps = [
        tctx.StepResult(
            step_index=0, action="connect", description="连接子站",
            status=tctx.StepStatus.PASSED, duration_ms=12.5,
            assertions=[{"passed": True, "message": "connected"}],
        ),
        tctx.StepResult(
            step_index=1, action="gi", description="总召唤",
            status=tctx.StepStatus.FAILED, duration_ms=8.0, message="no data",
            assertions=[{"passed": False, "message": "expected >=1 frame"}],
        ),
        tctx.StepResult(
            step_index=2, action="disconnect", description="断开",
            status=tctx.StepStatus.SKIPPED, duration_ms=0.0,
        ),
    ]
    return result


def test_generate_text() -> None:
    text = ReportGenerator.generate(_make_result(), "text")
    assert "demo_script" in text
    assert "FAILED" in text
    assert "connect" in text
    assert "3 total" in text


def test_generate_json() -> None:
    raw = ReportGenerator.generate(_make_result(), "json")
    data = json.loads(raw)
    assert data["script"] == "demo_script"
    assert data["path"] == "tests/scripts/demo_script.yaml"
    assert data["status"] == "failed"
    assert data["summary"] == {
        "total": 3, "passed": 1, "failed": 1, "errors": 0, "skipped": 1,
    }
    assert len(data["steps"]) == 3
    assert data["error_message"] == "step 1 failed"


def test_generate_html() -> None:
    html = ReportGenerator.generate(_make_result(), "html")
    assert "<!DOCTYPE html>" in html
    assert "demo_script" in html
    assert "Step 0" in html
    # 回归：HTML 头部必须渲染脚本描述（曾引用不存在的 result.description）
    assert "演示脚本：连接 + 总召唤" in html


def test_generate_html_without_description() -> None:
    """description 语义可选（默认空串）时 HTML 仍应正常生成."""
    result = tctx.TestResult(script_name="bare", status=tctx.TestStatus.PASSED)
    html = ReportGenerator.generate(result, "html")
    assert "bare" in html
    assert "<!DOCTYPE html>" in html


def test_generate_junit() -> None:
    xml = ReportGenerator.generate(_make_result(), "junit")
    root = ET.fromstring(xml)
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.get("name") == "demo_script"
    assert suite.get("tests") == "3"
    assert suite.get("failures") == "1"
    assert suite.get("errors") == "0"
    assert suite.get("skipped") == "1"
    # 失败步骤应产出 <failure>，跳过步骤应产出 <skipped>
    assert suite.find(".//failure") is not None
    assert suite.find(".//skipped") is not None


def test_generate_unknown_format_raises() -> None:
    with pytest.raises(ValueError):
        ReportGenerator.generate(_make_result(), "yaml-unknown")


def test_save_infers_format_from_suffix(tmp_path) -> None:
    """save() 无显式 format 时应按扩展名推断四种格式均能落盘."""
    result = _make_result()
    cases = (
        (".txt", "demo_script"),
        (".json", "demo_script"),
        (".html", "<!DOCTYPE html>"),
        (".xml", "testsuite"),
    )
    for suffix, marker in cases:
        path = tmp_path / f"report{suffix}"
        ReportGenerator.save(result, path)
        assert path.exists()
        assert marker in path.read_text(encoding="utf-8")
