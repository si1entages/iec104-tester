"""版本单一真相源校验（D5）.

发布包（PyInstaller）、Python 包元数据、Web 前端 `package.json` 必须同版本；
否则会出现「exe 显示 1.1.0、前端仍是 0.1.0」的漂移。CI 的 pytest 全量会执行本文件。
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]


def _package_version() -> str:
    text = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "__version__" in text, "__init__.py 未导出 __version__"
    from core.version import __version__

    return __version__


def _frontend_version() -> str:
    data = json.loads((ROOT / "webui" / "frontend" / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def test_versions_are_in_sync() -> None:
    versions = {
        "pyproject.toml": _pyproject_version(),
        "__init__.py": _package_version(),
        "webui/frontend/package.json": _frontend_version(),
    }
    assert len(set(versions.values())) == 1, f"版本漂移: {versions}"


def _badges(name: str) -> dict[str, str]:
    """抽取 README 徽章里的版本号与用例数（缺失的键不出现）."""
    text = (ROOT / name).read_text(encoding="utf-8")
    out: dict[str, str] = {}
    version = re.search(r"badge/version-([0-9][^-]*)-", text)
    tests = re.search(r"badge/Tests-([0-9]+)", text)
    if version:
        out["version"] = version.group(1)
    if tests:
        out["tests"] = tests.group(1)
    return out


def test_release_docs_match_version() -> None:
    """README 徽章与 CHANGELOG 首条必须跟版本源一致.

    2026-11-09 曾出现「v1.8.0 已发布、README 仍写 1.7.0 + 上一版用例数」的漂移，
    本用例把它变成可自动发现的失败。
    """
    from core.version import __version__

    changelog_first = re.search(
        r"^## \[([^\]]+)\]", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M
    )
    assert changelog_first, "CHANGELOG.md 未找到首条版本标题"
    assert changelog_first.group(1) == __version__, (
        f"CHANGELOG 首条版本漂移: {changelog_first.group(1)} != {__version__}"
    )

    zh, en = _badges("README.md"), _badges("README_eng.md")
    assert zh.get("version") == __version__, f"README 版本徽章漂移: {zh}"
    assert en.get("version") == __version__, f"README_eng 版本徽章漂移: {en}"
    assert zh.get("tests"), "README 缺少 Tests 徽章"
    assert zh["tests"] == en.get("tests"), f"双语 README 用例数不一致: {zh} vs {en}"

    # WP11a：用例数不再只比「双语一致」，必须与单一真值源 docs/baseline.json 相等。
    # 旧守卫只断言 zh==en，导致 1711/1667 长期漂移未被发现。
    baseline = json.loads((ROOT / "docs" / "baseline.json").read_text(encoding="utf-8"))
    expected = str(baseline["backend_passed"])
    assert zh["tests"] == expected, (
        f"README Tests 徽章 {zh['tests']} != baseline.json {expected}")
    assert en.get("tests") == expected, (
        f"README_eng Tests 徽章 {en.get('tests')} != baseline.json {expected}")
    for name in ("README.md", "README_eng.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"{expected} passed" in text or f"({expected};" in text, (
            f"{name} 基线行未同步为 {expected} passed")
        # 前端单测数同样纳入单一真值源：v1.11 发版前补 15 例 hook 测试时，
        # 曾出现 README 仍写 164 而 baseline.json 已是 179 的漂移。
        fe = str(baseline["frontend_tests"])
        assert f"{fe} passed" in text or f"**{fe} 单测**" in text, (
            f"{name} 前端基线行未同步为 {fe} passed")


def test_baseline_single_source_covers_all_published_numbers() -> None:
    """P1-5：把「数字单一真值源」从用例数扩到覆盖率/e2e/CI job/安全版本表.

    旧守卫只看后端 + 前端用例数，导致 README 覆盖率 91.1 / 91.11 / 91.49、
    SECURITY.md 支持版本停在 1.2.x、CHANGELOG 宣称「10/10 job」而 ci.yml
    只有 8 个 job 等漂移长期并存。本用例把这些对外可见数字全部钉到
    docs/baseline.json 与代码事实。
    """
    from core.version import __version__

    baseline = json.loads((ROOT / "docs" / "baseline.json").read_text(encoding="utf-8"))

    # 1) 双语 README 的覆盖率与 e2e 数字必须与基线一致
    for name in ("README.md", "README_eng.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"{baseline['coverage_total']}%" in text, (
            f"{name} 覆盖率数字与 baseline.json 不一致")
        assert str(baseline["e2e_tests"]) in text, (
            f"{name} e2e 用例数与 baseline.json 不一致")

    # 2) CI job 数：防止 CHANGELOG 写「10/10」而 workflow 只有 8 个
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # 只取 `jobs:` 之后的内容，避免把 `on:` 下的 push/pull_request 误当 job。
    jobs_block = ci.split("\njobs:\n", 1)[-1]
    jobs = re.findall(r"^  ([a-zA-Z][a-zA-Z0-9_-]*):\s*$", jobs_block, re.M)
    assert len(jobs) == baseline["ci_jobs"], (
        f"ci.yml job 数 {len(jobs)} != baseline.json {baseline['ci_jobs']}: {jobs}")

    # 3) SECURITY.md 受支持版本表必须包含当前主版本
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    major_minor = ".".join(__version__.split(".")[:2])
    assert f"{major_minor}.x" in security, (
        f"SECURITY.md 未列出当前版本 {major_minor}.x")

    # 4) 基线自身自洽：覆盖率必须 ≥ 门禁
    assert baseline["coverage_total"] >= baseline["coverage_gate"]
