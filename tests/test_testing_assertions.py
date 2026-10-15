"""`core/testing/assertions.py` 断言引擎单元测试。

覆盖全部内置断言类型（状态/帧数/ASDU/变量/实时数据/客户端数/恒真/恒假）的
通过与失败路径、未知断言类型报错、以及处理器内部异常被转为失败结果（不外抛）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.testing.assertions import AssertionEngine, AssertionFailed
from core.testing.context import TestContext as ScriptContext

U_FRAME = b"\x68\x04\x0b\x00\x00\x00"
I_FRAME = b"\x68\x0e\x00\x00\x00\x00" + b"\x00" * 8


@pytest.fixture
def engine() -> AssertionEngine:
    return AssertionEngine()


@pytest.fixture
def ctx() -> ScriptContext:
    return ScriptContext()


def test_assertion_failed_is_exception_subclass():
    assert issubclass(AssertionFailed, Exception)


def test_unknown_assertion_type_raises_with_available_list(engine, ctx):
    with pytest.raises(ValueError, match="Unknown assertion: nope"):
        engine.check("nope", ctx, {})


def test_handler_exception_is_converted_to_failed_result(engine, ctx):
    """处理器抛异常（如缺少必填参数）→ 返回 passed=False 而非向外抛."""
    result = engine.check("variable", ctx, {})      # 缺 name → KeyError

    assert result["passed"] is False
    assert result["message"].startswith("Assertion error:")
    assert "exception" in result["details"]


# ── state ────────────────────────────────────────────────────────

@pytest.mark.parametrize("flags,expected,passed", [
    ({"connected": True}, "connected", True),
    ({"connected": False}, "connected", False),
    ({"connected": False}, "disconnected", True),
    ({"connected": True}, "disconnected", False),
    ({"running": True}, "running", True),
    ({"running": False}, "running", False),
    ({"running": False}, "stopped", True),
    ({"running": True}, "stopped", False),
    ({}, "bogus", False),          # 未知期望值 → 一律失败
])
def test_assert_state(engine, ctx, flags, expected, passed):
    for key, value in flags.items():
        setattr(ctx, key, value)

    result = engine.check("state", ctx, {"expected": expected})

    assert result["passed"] is passed
    assert f"expected={expected}" in result["message"]
    assert result["details"]["expected"] == expected


def test_assert_state_defaults_to_running(engine, ctx):
    ctx.running = True
    assert engine.check("state", ctx, {})["passed"] is True


# ── frame_count ──────────────────────────────────────────────────

def test_assert_frame_count_exact_min_max(engine, ctx):
    ctx.add_rx_frame(U_FRAME)
    ctx.add_rx_frame(I_FRAME)
    ctx.add_tx_frame(U_FRAME)

    assert engine.check("frame_count", ctx, {"exact": 2})["passed"] is True
    assert engine.check("frame_count", ctx, {"exact": 3})["passed"] is False
    assert engine.check("frame_count", ctx, {"min": 1, "max": 3})["passed"] is True
    assert engine.check("frame_count", ctx, {"min": 3})["passed"] is False
    assert engine.check("frame_count", ctx, {"max": 1})["passed"] is False
    assert engine.check("frame_count", ctx, {"frame_type": "I", "exact": 1})["passed"] is True
    assert engine.check("frame_count", ctx,
                        {"direction": "tx", "exact": 1})["passed"] is True


def test_assert_frame_count_details_and_message(engine, ctx):
    ctx.add_rx_frame(U_FRAME)
    result = engine.check("frame_count", ctx, {"direction": "rx", "min": 1})

    assert result["details"]["actual"] == 1
    assert "Frame count (RX ALL)" in result["message"]


# ── asdu_received ────────────────────────────────────────────────

def test_assert_asdu_received_filters_and_min_count(engine, ctx):
    ctx.received_asdus.extend([
        {"type_id": 1, "cot": 3},
        {"type_id": 100, "cot": 7},
        {"type_id": 100, "cot": 10},
    ])

    assert engine.check("asdu_received", ctx, {"type_id": 100})["passed"] is True
    assert engine.check("asdu_received", ctx,
                        {"type_id": 100, "cot": 7})["passed"] is True
    result = engine.check("asdu_received", ctx, {"type_id": 100, "min_count": 3})
    assert result["passed"] is False
    assert result["details"]["matched"] == 2

    assert engine.check("asdu_received", ctx, {})["passed"] is True    # 不限条件


# ── variable ─────────────────────────────────────────────────────

@pytest.mark.parametrize("operator,actual,expected,passed", [
    ("eq", 5, 5, True),
    ("eq", 5, 6, False),
    ("ne", 5, 6, True),
    ("ne", 5, 5, False),
    ("gt", 5, 4, True),
    ("gt", 5, 5, False),
    ("lt", 4, 5, True),
    ("lte", 5, 5, True),
    ("gte", 5, 5, True),
    ("contains", "abcdef", "cde", True),
    ("contains", "abcdef", "xyz", False),
    ("contains", "", "x", False),
    ("unknown-op", 7, 7, True),      # 未知算子回落到 eq
])
def test_assert_variable_operators(engine, ctx, operator, actual, expected, passed):
    ctx.set_variable("v", actual)
    result = engine.check("variable", ctx,
                          {"name": "v", "expected": expected, "operator": operator})

    assert result["passed"] is passed


def test_assert_variable_missing_defaults_to_none(engine, ctx):
    result = engine.check("variable", ctx, {"name": "absent", "expected": None})
    assert result["passed"] is True
    assert result["details"]["actual"] is None


# ── data_value ───────────────────────────────────────────────────

def test_assert_data_value_exact_match(engine, ctx):
    ctx.yx_data[100] = True
    ctx.yc_data[300] = 220.5
    ctx.ym_data[400] = 12345

    assert engine.check("data_value", ctx,
                        {"point_type": "yx", "ioa": 100, "expected": True})["passed"] is True
    assert engine.check("data_value", ctx,
                        {"point_type": "yc", "ioa": 300, "expected": 220.5})["passed"] is True
    assert engine.check("data_value", ctx,
                        {"point_type": "ym", "ioa": 400, "expected": 12345})["passed"] is True


def test_assert_data_value_tolerance_for_numbers(engine, ctx):
    ctx.yc_data[1] = 220.54

    assert engine.check("data_value", ctx,
                        {"point_type": "yc", "ioa": 1, "expected": 220.5,
                         "tolerance": 0.1})["passed"] is True
    assert engine.check("data_value", ctx,
                        {"point_type": "yc", "ioa": 1, "expected": 220.5,
                         "tolerance": 0.001})["passed"] is False


def test_assert_data_value_tolerance_ignored_for_non_numbers(engine, ctx):
    ctx.yx_data[1] = True
    assert engine.check("data_value", ctx,
                        {"point_type": "yx", "ioa": 1, "expected": True,
                         "tolerance": 0.5})["passed"] is True


def test_assert_data_value_missing_point_is_failure(engine, ctx):
    result = engine.check("data_value", ctx, {"point_type": "yx", "ioa": 999})

    assert result["passed"] is False
    assert "Data not found" in result["message"]


def test_assert_data_value_unknown_point_type_is_not_found(engine, ctx):
    result = engine.check("data_value", ctx, {"point_type": "zz", "ioa": 1})
    assert result["passed"] is False
    assert result["details"]["actual"] is None


# ── client_count ─────────────────────────────────────────────────

def test_assert_client_count_exact_and_min(engine, ctx):
    ctx.client_count = 2

    assert engine.check("client_count", ctx, {"expected": 2})["passed"] is True
    assert engine.check("client_count", ctx, {"expected": 3})["passed"] is False
    assert engine.check("client_count", ctx, {"min": 1})["passed"] is True
    assert engine.check("client_count", ctx, {"min": 5})["passed"] is False


def test_assert_client_count_defaults_to_zero(engine, ctx):
    assert engine.check("client_count", ctx, {})["passed"] is True


# ── 恒真 / 恒假 ──────────────────────────────────────────────────

def test_assert_always_pass_and_fail(engine, ctx):
    assert engine.check("always_pass", ctx, {})["passed"] is True

    assert engine.check("always_fail", ctx, {})["passed"] is False
    assert engine.check("always_fail", ctx, {})["message"] == "Always fail"

    custom = engine.check("always_fail", ctx, {"message": "调试用失败"})
    assert custom["message"] == "调试用失败"


def test_available_assertions_listed(engine):
    assert set(engine._assertions) == {
        "state", "frame_count", "asdu_received", "variable",
        "data_value", "client_count", "always_pass", "always_fail",
    }
