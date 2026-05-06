#!/usr/bin/env python3
"""IEC 60870-5-104 自动化测试脚本运行器.

用法:
    # 运行单个脚本
    python run_tests.py tests/scripts/basic_connection_gi.yaml

    # 运行目录下所有脚本
    python run_tests.py tests/scripts/

    # 指定报告输出目录和格式
    python run_tests.py tests/scripts/ --report-dir reports --format text

    # 详细输出
    python run_tests.py tests/scripts/ -v
"""

import sys
import os
import asyncio
import argparse
import logging
from pathlib import Path

# 确保项目根目录在 sys.path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt="%H:%M:%S",
    )


async def run_scripts(args) -> int:
    """执行测试脚本，返回退出码 (0=全部通过, 1=有失败)."""
    from core.testing import TestRunner, ReportGenerator

    runner = TestRunner(report_dir=args.report_dir)

    # 加载脚本
    target = Path(args.script)
    if target.is_dir():
        scripts = runner.load_directory(target)
        print(f"📂 Loaded {len(scripts)} scripts from {target}")
    elif target.is_file():
        scripts = [runner.load_script(target)]
        print(f"📄 Loaded script: {target}")
    else:
        print(f"❌ Not found: {target}")
        return 2

    if not scripts:
        print("❌ No scripts found")
        return 2

    # 回调
    def on_step(step_result):
        icon = {
            "passed": "✅", "failed": "❌", "error": "💥",
            "skipped": "⏭", "running": "🔄", "pending": "⏳",
        }.get(step_result.status.value, "?")
        print(f"  {icon} Step {step_result.step_index}: [{step_result.action:20s}] "
              f"{step_result.description}")
        if step_result.message and args.verbose:
            print(f"           → {step_result.message}")
        for a in step_result.assertions:
            a_icon = "✓" if a.get("passed") else "✗"
            print(f"           {a_icon} {a.get('message', '')}")

    def on_test(test_result):
        status_icon = "✅" if test_result.status.value == "passed" else "❌"
        print(f"\n{status_icon} {test_result.script_name}: "
              f"{test_result.status.value.upper()} "
              f"({test_result.duration_s:.2f}s, "
              f"{test_result.passed}/{test_result.total} passed)")

    runner._on_step_complete = on_step
    runner._on_test_complete = on_test

    # 执行
    print(f"\n{'=' * 60}")

    results = []
    for script in scripts:
        print(f"\n▶ Running: {script.name}")
        print(f"  {script.description}")
        print(f"  Role: {script.role} | Steps: {len(script.steps)}")
        print("-" * 40)

        result = await runner.run(script)
        results.append(result)

        # 保存报告
        os.makedirs(args.report_dir, exist_ok=True)

        # Text 报告
        txt_path = Path(args.report_dir) / f"{script.name}.txt"
        ReportGenerator.save(result, txt_path, format="text")

        # JSON 报告
        json_path = Path(args.report_dir) / f"{script.name}.json"
        ReportGenerator.save(result, json_path, format="json")

        # HTML 报告
        html_path = Path(args.report_dir) / f"{script.name}.html"
        ReportGenerator.save(result, html_path, format="html")

        if args.verbose:
            print(f"\n  Reports: {txt_path}, {json_path}, {html_path}")

    # 汇总
    print(f"\n{'=' * 60}")
    total = len(results)
    passed = sum(1 for r in results if r.status.value == "passed")
    failed = total - passed

    print(f"\n📊 Summary: {total} scripts, {passed} passed, {failed} failed")
    print(f"📁 Reports saved to: {args.report_dir}/")

    for r in results:
        icon = "✅" if r.status.value == "passed" else "❌"
        print(f"  {icon} {r.script_name} ({r.duration_s:.2f}s)")

    return 0 if failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 自动化测试脚本运行器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_tests.py tests/scripts/basic_connection_gi.yaml
  python run_tests.py tests/scripts/
  python run_tests.py tests/scripts/ -v --report-dir reports
        """,
    )
    parser.add_argument(
        "script",
        help="测试脚本文件或目录",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出",
    )
    parser.add_argument(
        "--report-dir",
        default="test_reports",
        help="报告输出目录 (默认: test_reports)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别",
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    exit_code = asyncio.run(run_scripts(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
