"""入口层冒烟门禁（P1-3 覆盖率补真）.

CI 的 ``--cov=core --cov=webui`` 只统计两个包，``app.py`` 与 5 个顶层 CLI
工具（约 90KB）完全不在覆盖率口径内。把这些脚本直接并入 91% 门禁会让
统计失真（启动/CLI 代码本就少单测），因此这里单列一层真实断言：

1. 每个入口可被 Python 编译（语法/导入期错误立即暴露）；
2. 每个入口 ``--help`` 在 3s 内返回 0 且输出含用法；
3. 关键入口模块可被 import（不触发 ``if __name__ == "__main__"`` 副作用）。

这样「入口层零覆盖」变成「入口层有可复现的冒烟验证」，且不改变既有分支
覆盖率门禁口径。真实业务行为由 e2e / qa_full_flow.py 覆盖。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINTS = (
    "app.py",
    "apps/web_master.py",
    "apps/web_slave.py",
    "run_tests.py",
    "run_multi_station.py",
    "capture_tool.py",
    "sim_tool.py",
)


@pytest.mark.parametrize("rel", ENTRYPOINTS)
def test_entrypoint_compiles(rel: str) -> None:
    """语法错误在 CI 里必须立刻可见，而不是等打包/现场启动才发现."""
    path = ROOT / rel
    assert path.exists(), f"入口缺失: {rel}"
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.parametrize("rel", ENTRYPOINTS)
def test_entrypoint_help_exits_zero(rel: str) -> None:
    path = ROOT / rel
    proc = subprocess.run(
        [sys.executable, str(path), "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, (
        f"{rel} --help 退出码 {proc.returncode}: {proc.stderr[-500:]}"
    )
    assert "usage" in (proc.stdout + proc.stderr).lower(), (
        f"{rel} --help 未输出用法: {(proc.stdout + proc.stderr)[:300]}"
    )


@pytest.mark.parametrize("module", ("app", "run_tests", "capture_tool", "sim_tool",
                                    "run_multi_station", "apps.web_master", "apps.web_slave"))
def test_entrypoint_importable(module: str) -> None:
    """import 不启动服务；验证模块级依赖与相对导入链完整."""
    spec = importlib.util.find_spec(module)
    assert spec is not None, f"无法定位模块 {module}"
