"""断言引擎 — 验证测试结果."""

from __future__ import annotations

import logging

from .context import TestContext

logger = logging.getLogger("iec104.testing.assertions")


class AssertionFailed(Exception):
    """断言失败."""
    pass


class AssertionEngine:
    """断言引擎.

    支持的断言类型:
    - state: 检查连接状态
    - frame_count: 检查帧数量
    - asdu_received: 检查是否收到指定 ASDU
    - variable: 检查变量值
    - data_value: 检查实时数据值
    - client_count: 检查客户端连接数
    - always_pass: 总是通过（用于占位）
    - always_fail: 总是失败（用于调试）
    """

    def __init__(self):
        self._assertions: dict[str, callable] = {
            "state": self._assert_state,
            "frame_count": self._assert_frame_count,
            "asdu_received": self._assert_asdu_received,
            "variable": self._assert_variable,
            "data_value": self._assert_data_value,
            "client_count": self._assert_client_count,
            "always_pass": self._assert_always_pass,
            "always_fail": self._assert_always_fail,
        }

    def check(self, assertion_type: str, ctx: TestContext, params: dict) -> dict:
        """执行断言检查.

        Returns:
            {"passed": bool, "message": str, "details": dict}
        """
        handler = self._assertions.get(assertion_type)
        if not handler:
            raise ValueError(
                f"Unknown assertion: {assertion_type}. "
                f"Available: {list(self._assertions.keys())}"
            )

        try:
            result = handler(ctx, params)
            return {
                "passed": result["passed"],
                "message": result.get("message", ""),
                "details": result.get("details", {}),
            }
        except Exception as e:
            return {
                "passed": False,
                "message": f"Assertion error: {e}",
                "details": {"exception": str(e)},
            }

    # ── 断言实现 ──────────────────────────────────────────────────

    def _assert_state(self, ctx: TestContext, params: dict) -> dict:
        """检查连接状态.

        params:
            expected: "connected" / "disconnected" / "running" / "stopped"
        """
        expected = params.get("expected", "running")

        if expected == "connected":
            actual = ctx.connected
        elif expected == "disconnected":
            actual = not ctx.connected
        elif expected == "running":
            actual = ctx.running
        elif expected == "stopped":
            actual = not ctx.running
        else:
            actual = False

        return {
            "passed": actual,
            "message": f"State: expected={expected}, connected={ctx.connected}, running={ctx.running}",
            "details": {
                "expected": expected,
                "connected": ctx.connected,
                "running": ctx.running,
            },
        }

    def _assert_frame_count(self, ctx: TestContext, params: dict) -> dict:
        """检查帧数量.

        params:
            direction: "rx" / "tx"
            frame_type: "I" / "S" / "U" / null (全部)
            min: 最小值 (含)
            max: 最大值 (含)
            exact: 精确值
        """
        direction = params.get("direction", "rx")
        frame_type = params.get("frame_type")
        min_count = params.get("min")
        max_count = params.get("max")
        exact = params.get("exact")

        if direction == "rx":
            actual = ctx.get_rx_frame_count(frame_type)
        else:
            actual = ctx.get_tx_frame_count(frame_type)

        passed = True
        if exact is not None and actual != exact:
            passed = False
        if min_count is not None and actual < min_count:
            passed = False
        if max_count is not None and actual > max_count:
            passed = False

        return {
            "passed": passed,
            "message": (
                f"Frame count ({direction.upper()} {frame_type or 'ALL'}): "
                f"actual={actual}, min={min_count}, max={max_count}, exact={exact}"
            ),
            "details": {
                "direction": direction,
                "frame_type": frame_type,
                "actual": actual,
                "min": min_count,
                "max": max_count,
                "exact": exact,
            },
        }

    def _assert_asdu_received(self, ctx: TestContext, params: dict) -> dict:
        """检查是否收到指定 ASDU.

        params:
            type_id: ASDU 类型标识 (int)
            cot: 传送原因 (int)
            min_count: 最少收到几个
        """
        type_id = params.get("type_id")
        cot = params.get("cot")
        min_count = params.get("min_count", 1)

        matched = 0
        for asdu_info in ctx.received_asdus:
            tid_ok = (type_id is None or asdu_info.get("type_id") == type_id)
            cot_ok = (cot is None or asdu_info.get("cot") == cot)
            if tid_ok and cot_ok:
                matched += 1

        passed = matched >= min_count

        return {
            "passed": passed,
            "message": f"ASDU received: type={type_id} cot={cot}, matched={matched}, required>={min_count}",
            "details": {
                "type_id": type_id,
                "cot": cot,
                "matched": matched,
                "min_count": min_count,
            },
        }

    def _assert_variable(self, ctx: TestContext, params: dict) -> dict:
        """检查变量值.

        params:
            name: 变量名
            expected: 期望值
            operator: "eq" / "ne" / "gt" / "lt" / "gte" / "lte" / "contains"
        """
        name = params["name"]
        expected = params.get("expected")
        operator = params.get("operator", "eq")

        actual = ctx.get_variable(name)

        ops = {
            "eq": lambda a, e: a == e,
            "ne": lambda a, e: a != e,
            "gt": lambda a, e: a > e,
            "lt": lambda a, e: a < e,
            "gte": lambda a, e: a >= e,
            "lte": lambda a, e: a <= e,
            "contains": lambda a, e: e in a if a else False,
        }

        op_func = ops.get(operator, ops["eq"])
        passed = op_func(actual, expected)

        return {
            "passed": passed,
            "message": f"Variable '{name}': {actual} {operator} {expected}",
            "details": {
                "name": name,
                "actual": actual,
                "expected": expected,
                "operator": operator,
            },
        }

    def _assert_data_value(self, ctx: TestContext, params: dict) -> dict:
        """检查实时数据值.

        params:
            point_type: "yx" / "yc" / "ym"
            ioa: 信息对象地址
            expected: 期望值
            tolerance: 浮点容差 (可选)
        """
        point_type = params.get("point_type", "yx")
        ioa = params["ioa"]
        expected = params.get("expected")
        tolerance = params.get("tolerance", 0.0)

        if point_type == "yx":
            actual = ctx.yx_data.get(ioa)
        elif point_type == "yc":
            actual = ctx.yc_data.get(ioa)
        elif point_type == "ym":
            actual = ctx.ym_data.get(ioa)
        else:
            actual = None

        if actual is None:
            return {
                "passed": False,
                "message": f"Data not found: {point_type} IOA={ioa}",
                "details": {"point_type": point_type, "ioa": ioa, "actual": None},
            }

        if tolerance > 0 and isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            passed = abs(actual - expected) <= tolerance
        else:
            passed = actual == expected

        return {
            "passed": passed,
            "message": f"Data {point_type} IOA={ioa}: actual={actual}, expected={expected}",
            "details": {
                "point_type": point_type,
                "ioa": ioa,
                "actual": actual,
                "expected": expected,
                "tolerance": tolerance,
            },
        }

    def _assert_client_count(self, ctx: TestContext, params: dict) -> dict:
        """检查客户端连接数 (子站模式)."""
        expected = params.get("expected", 0)
        min_count = params.get("min")
        actual = ctx.client_count

        if min_count is not None:
            passed = actual >= min_count
        else:
            passed = actual == expected

        return {
            "passed": passed,
            "message": f"Client count: actual={actual}, expected={expected}, min={min_count}",
            "details": {"actual": actual, "expected": expected, "min": min_count},
        }

    def _assert_always_pass(self, ctx: TestContext, params: dict) -> dict:
        return {"passed": True, "message": "Always pass"}

    def _assert_always_fail(self, ctx: TestContext, params: dict) -> dict:
        return {"passed": False, "message": params.get("message", "Always fail")}
