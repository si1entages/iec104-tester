"""版本单一真相源校验（D5）.

发布包（PyInstaller）、Python 包元数据、Web 前端 `package.json` 必须同版本；
否则会出现「exe 显示 1.1.0、前端仍是 0.1.0」的漂移。CI 的 pytest 全量会执行本文件。
"""

from __future__ import annotations

import json
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
