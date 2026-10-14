"""契约自检接入 pytest 门禁（T18）。

与 ``python -m webui.contract_check`` 等价，但由 pytest 收集，从而自动进入
``pytest tests/`` 全量门禁（CI 的 test job，3.11 / 3.13 双版本都会跑）。

刻意**不使用 skip**：前后端 schemaVersion 不一致、文档与实现漂移、WS 信封缺版本，
都必须是红灯——否则契约门禁形同虚设。
"""

from __future__ import annotations

from webui.contract_check import run_checks


def test_contract_check_entry_is_importable() -> None:
    """自检入口必须可导入可运行（防止被误删/改名后静默失效）。"""
    assert callable(run_checks)


def test_api_contract_matches_implementation() -> None:
    """api_contract.md ↔ 后端实现不得漂移（含前后端 schemaVersion 一致）。"""
    problems = run_checks()
    assert not problems, "契约漂移：\n" + "\n".join(f"  - {p}" for p in problems)
