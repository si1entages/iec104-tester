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
