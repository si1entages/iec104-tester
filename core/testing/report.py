"""报告生成器 — 输出测试结果."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .context import TestResult, StepResult, TestStatus, StepStatus


class ReportGenerator:
    """测试报告生成器.

    支持格式:
    - text: 纯文本（终端输出）
    - json: JSON 结构化数据
    - html: HTML 可视化报告
    - junit: JUnit XML（CI 集成）
    """

    @staticmethod
    def generate(result: TestResult, format: str = "text") -> str:
        if format == "text":
            return ReportGenerator._to_text(result)
        elif format == "json":
            return ReportGenerator._to_json(result)
        elif format == "html":
            return ReportGenerator._to_html(result)
        elif format == "junit":
            return ReportGenerator._to_junit(result)
        else:
            raise ValueError(f"Unknown format: {format}")

    @staticmethod
    def save(result: TestResult, path: str | Path, format: str = None) -> None:
        """保存报告到文件."""
        path = Path(path)
        if format is None:
            suffix = path.suffix.lower()
            format = {
                ".txt": "text",
                ".json": "json",
                ".html": "html",
                ".xml": "junit",
            }.get(suffix, "text")

        content = ReportGenerator.generate(result, format)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # ── Text ──────────────────────────────────────────────────────

    @staticmethod
    def _to_text(result: TestResult) -> str:
        lines = []
        status_icon = "✅" if result.status == TestStatus.PASSED else "❌"

        lines.append("=" * 60)
        lines.append(f"  {status_icon} Test Report: {result.script_name}")
        lines.append("=" * 60)
        lines.append(f"  Status:   {result.status.value.upper()}")
        lines.append(f"  Duration: {result.duration_s:.2f}s")
        lines.append(f"  Steps:    {result.total} total | "
                     f"{result.passed} passed | {result.failed} failed | "
                     f"{result.errors} errors | {result.skipped} skipped")
        if result.error_message:
            lines.append(f"  Error:    {result.error_message}")
        lines.append("-" * 60)

        for step in result.steps:
            icon = {
                StepStatus.PASSED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.ERROR: "💥",
                StepStatus.SKIPPED: "⏭",
                StepStatus.PENDING: "⏳",
                StepStatus.RUNNING: "🔄",
            }.get(step.status, "?")

            lines.append(
                f"  {icon} Step {step.step_index:2d}: [{step.action:20s}] "
                f"{step.status.value:8s} {step.duration_ms:7.1f}ms  "
                f"{step.description}"
            )
            if step.message:
                lines.append(f"           → {step.message}")
            for assertion in step.assertions:
                a_icon = "✓" if assertion.get("passed") else "✗"
                lines.append(f"           {a_icon} {assertion.get('message', '')}")

        lines.append("=" * 60)
        return "\n".join(lines)

    # ── JSON ──────────────────────────────────────────────────────

    @staticmethod
    def _to_json(result: TestResult) -> str:
        data = {
            "script": result.script_name,
            "path": result.script_path,
            "status": result.status.value,
            "start_time": result.start_time,
            "end_time": result.end_time,
            "duration_s": result.duration_s,
            "summary": {
                "total": result.total,
                "passed": result.passed,
                "failed": result.failed,
                "errors": result.errors,
                "skipped": result.skipped,
            },
            "steps": [
                {
                    "index": s.step_index,
                    "action": s.action,
                    "description": s.description,
                    "status": s.status.value,
                    "duration_ms": s.duration_ms,
                    "message": s.message,
                    "assertions": s.assertions,
                }
                for s in result.steps
            ],
        }
        if result.error_message:
            data["error_message"] = result.error_message
        return json.dumps(data, indent=2, ensure_ascii=False)

    # ── HTML ──────────────────────────────────────────────────────

    @staticmethod
    def _to_html(result: TestResult) -> str:
        status_color = "#a6e3a1" if result.status == TestStatus.PASSED else "#f38ba8"
        status_bg = "#1e1e2e"

        steps_html = ""
        for step in result.steps:
            icon = {
                StepStatus.PASSED: "✅",
                StepStatus.FAILED: "❌",
                StepStatus.ERROR: "💥",
                StepStatus.SKIPPED: "⏭",
            }.get(step.status, "⏳")
            color = {
                StepStatus.PASSED: "#a6e3a1",
                StepStatus.FAILED: "#f38ba8",
                StepStatus.ERROR: "#fab387",
                StepStatus.SKIPPED: "#a6adc8",
            }.get(step.status, "#cdd6f4")

            assertions_html = ""
            for a in step.assertions:
                a_icon = "✓" if a.get("passed") else "✗"
                a_color = "#a6e3a1" if a.get("passed") else "#f38ba8"
                assertions_html += (
                    f'<div style="margin-left:40px;color:{a_color};font-size:13px">'
                    f'{a_icon} {a.get("message", "")}</div>'
                )

            steps_html += f"""
            <div style="padding:6px 12px;border-bottom:1px solid #313244;">
                <span>{icon}</span>
                <span style="color:#89b4fa;font-weight:bold;">Step {step.step_index}</span>
                <span style="color:{color};">[{step.action}]</span>
                <span style="color:#a6adc8;">{step.duration_ms:.1f}ms</span>
                <span style="color:#cdd6f4;">{step.description}</span>
                {f'<div style="margin-left:30px;color:#a6adc8;">→ {step.message}</div>' if step.message else ""}
                {assertions_html}
            </div>"""

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Test Report: {result.script_name}</title>
    <style>
        body {{ background: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', sans-serif; padding: 20px; }}
        .header {{ text-align: center; padding: 20px; }}
        .status {{ font-size: 48px; }}
        .summary {{ display: flex; gap: 20px; justify-content: center; margin: 20px 0; }}
        .metric {{ background: #313244; padding: 12px 24px; border-radius: 8px; text-align: center; }}
        .metric-value {{ font-size: 24px; font-weight: bold; }}
        .metric-label {{ font-size: 12px; color: #a6adc8; }}
        .steps {{ background: #181825; border-radius: 8px; overflow: hidden; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="status">{'✅' if result.status == TestStatus.PASSED else '❌'}</div>
        <h1>{result.script_name}</h1>
        <p style="color:#a6adc8;">{result.description}</p>
    </div>
    <div class="summary">
        <div class="metric"><div class="metric-value" style="color:{status_color};">{result.status.value.upper()}</div><div class="metric-label">Status</div></div>
        <div class="metric"><div class="metric-value">{result.duration_s:.2f}s</div><div class="metric-label">Duration</div></div>
        <div class="metric"><div class="metric-value">{result.total}</div><div class="metric-label">Total</div></div>
        <div class="metric"><div class="metric-value" style="color:#a6e3a1;">{result.passed}</div><div class="metric-label">Passed</div></div>
        <div class="metric"><div class="metric-value" style="color:#f38ba8;">{result.failed}</div><div class="metric-label">Failed</div></div>
    </div>
    <div class="steps">{steps_html}</div>
</body>
</html>"""

    # ── JUnit XML ─────────────────────────────────────────────────

    @staticmethod
    def _to_junit(result: TestResult) -> str:
        import xml.etree.ElementTree as ET

        testsuites = ET.Element("testsuites")
        testsuite = ET.SubElement(testsuites, "testsuite")
        testsuite.set("name", result.script_name)
        testsuite.set("tests", str(result.total))
        testsuite.set("failures", str(result.failed))
        testsuite.set("errors", str(result.errors))
        testsuite.set("skipped", str(result.skipped))
        testsuite.set("time", f"{result.duration_s:.3f}")

        for step in result.steps:
            testcase = ET.SubElement(testsuite, "testcase")
            testcase.set("name", f"Step {step.step_index}: {step.action}")
            testcase.set("classname", result.script_name)
            testcase.set("time", f"{step.duration_ms / 1000:.3f}")

            if step.status == StepStatus.FAILED:
                failure = ET.SubElement(testcase, "failure")
                failure.set("message", step.message)
                failure.set("type", "AssertionError")
            elif step.status == StepStatus.ERROR:
                error = ET.SubElement(testcase, "error")
                error.set("message", step.message)
                error.set("type", "Error")
            elif step.status == StepStatus.SKIPPED:
                ET.SubElement(testcase, "skipped")

        ET.indent(testsuites, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(testsuites, encoding="unicode")
