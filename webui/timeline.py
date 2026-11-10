"""桥场景化注入时间线 + 自动判定（T97，C 采纳）.

把「运行中手动设条件 + 自己盯违规列表」变成编排好的闭环：按时间线逐步施加
网络条件（复用 T85 的 ``NetworkCondition``/注入器），每步在一个**时间窗**内
采集注入统计增量与合规违规（按 ts 归窗），逐步自动判定是否符合预期。

判定口径（防误报的核心，测试锁死）：
- 窗口外证据一律不参与——违规按 ``ts > 游标`` 归入当前窗，丢包/断链按增量归窗；
- ``none`` 要求窗口内零丢帧、零断链、零违规；
- ``loss`` 只看 dropped 增量；``k-exceed``/``t1`` 只看窗口内对应 kind 违规；
- ``disconnect`` 看断链（disconnects 增量或客户端数下降）。

运行以 asyncio task 进行（HTTP 端点只负责启动），逐步发 ``timeline`` 事件，
结束后 ``last_result`` 供 UI 轮询与测试报告（report.py 新段）引用。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from core.simulation.conditions import NetworkCondition

_ALLOWED_EXPECT = ("none", "loss", "k-exceed", "t1", "disconnect")
_COND_FIELDS = (
    "delay_ms", "delay_variance_ms", "loss_rate", "duplicate_rate",
    "corrupt_rate", "corrupt_bits", "reorder_rate", "reorder_window",
    "disconnect_rate", "disconnect_duration_s", "bandwidth_bps", "direction",
)
_MAX_STEPS = 50
_MIN_DURATION = 0.5
_MAX_DURATION = 600.0


class TimelineService:
    """步骤编排 + 逐窗采集判定；判定逻辑为纯函数，合成序列单测锁死."""

    def __init__(self, bridge: Any):
        self.bridge = bridge
        self.steps: list[dict] = []
        self.last_result: dict | None = None
        self.running = False
        self.tick_s = 0.5  # 采集粒度；测试可注入小值
        self._sleep = asyncio.sleep  # 可注入（测试用假时钟加速）
        self._task: asyncio.Task | None = None
        self._stop_requested = False

    # ── 编排 ─────────────────────────────────────────────────────

    def configure(self, raw_steps: list[dict]) -> dict:
        """校验并保存步骤序列；覆盖旧编排."""
        if not isinstance(raw_steps, list) or not raw_steps:
            return {"ok": False, "error": "steps 须为非空数组"}
        if len(raw_steps) > _MAX_STEPS:
            return {"ok": False, "error": f"步骤数超限（最多 {_MAX_STEPS}）"}
        cleaned: list[dict] = []
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                return {"ok": False, "error": f"第 {i + 1} 步须为对象"}
            label = str(raw.get("label") or f"步骤{i + 1}")[:80]
            try:
                duration = float(raw.get("duration_s", 0))
            except (TypeError, ValueError):
                return {"ok": False, "error": f"第 {i + 1} 步 duration_s 非法"}
            if not (_MIN_DURATION <= duration <= _MAX_DURATION):
                return {"ok": False,
                        "error": f"第 {i + 1} 步 duration_s 须在 {_MIN_DURATION}~{_MAX_DURATION}s"}
            expect = str(raw.get("expect") or "none").lower()
            if expect not in _ALLOWED_EXPECT:
                return {"ok": False,
                        "error": f"第 {i + 1} 步 expect 须为 {'/'.join(_ALLOWED_EXPECT)}"}
            cond_raw = raw.get("condition") or {}
            cond: dict = {}
            if isinstance(cond_raw, dict):
                for k, v in cond_raw.items():
                    if k in _COND_FIELDS and v is not None:
                        if k == "direction":
                            cond[k] = str(v) if str(v) in ("rx", "tx", "both") else "both"
                        else:
                            try:
                                cond[k] = max(0.0, float(v))
                            except (TypeError, ValueError):
                                return {"ok": False, "error": f"第 {i + 1} 步 {k} 须为数值"}
            cleaned.append({"label": label, "duration_s": duration,
                            "condition": cond, "expect": expect})
        self.steps = cleaned
        return {"ok": True, "steps": len(cleaned)}

    def to_dict(self) -> dict:
        return {"ok": True, "running": self.running,
                "steps": self.steps, "last_result": self.last_result}

    # ── 判定（纯函数，合成证据单测锁死） ─────────────────────────

    @staticmethod
    def judge(expect: str, *, dropped_delta: int, disconnect_delta: int,
              kinds: list[str]) -> tuple[bool, str]:
        """单步判定：只吃窗口内证据."""
        if expect == "none":
            ok = dropped_delta == 0 and disconnect_delta == 0 and not kinds
            detail = "窗口内零丢帧/零断链/零违规" if ok else \
                f"窗口内出现异常（丢帧 {dropped_delta}，断链 {disconnect_delta}，违规 {kinds or '无'}）"
            return ok, detail
        if expect == "loss":
            ok = dropped_delta > 0
            return ok, f"窗口内丢帧 {dropped_delta}" + ("" if ok else "（预期应发生丢帧）")
        if expect in ("k-exceed", "t1"):
            ok = expect in kinds
            return ok, (f"窗口内违规 kinds={kinds}" if ok else
                        f"窗口内未观察到 {expect}（违规 {kinds or '无'}，丢帧 {dropped_delta}）")
        if expect == "disconnect":
            ok = disconnect_delta > 0
            return ok, f"窗口内断链 {disconnect_delta}" + ("" if ok else "（预期应断链）")
        return False, f"未知 expect: {expect}"

    # ── 执行 ─────────────────────────────────────────────────────

    async def run(self) -> dict:
        """启动时间线（asyncio task）；运行中重复启动与未启动桥被拒绝."""
        if self.running:
            return {"ok": False, "error": "时间线运行中"}
        tcp = getattr(self.bridge, "tcp_bridge", None)
        if tcp is None:
            return {"ok": False, "error": "桥未启动（先启动桥接再运行时间线）"}
        if not self.steps:
            return {"ok": False, "error": "未编排步骤（先 POST /api/bridge/timeline）"}
        self._stop_requested = False
        self.running = True  # 同步置位：双击/重复 POST 立即被拒
        self._task = asyncio.ensure_future(self._run_impl())
        return {"ok": True, "running": True, "steps": len(self.steps)}

    def stop(self) -> dict:
        if not self.running:
            return {"ok": False, "error": "时间线未在运行"}
        self._stop_requested = True
        return {"ok": True, "stopping": True}

    def _latest_violation_ts(self) -> float:
        """运行起点游标：历史违规（上次运行/运行前流量）不参与本次判定."""
        comp = getattr(self.bridge, "compliance", None)
        if comp is None:
            return 0.0
        try:
            latest = comp.violation_list(1)
        except Exception:  # noqa: BLE001
            return 0.0
        return max([v.get("ts", 0) for v in latest] or [0.0])

    def _window_violations(self, cursor: float) -> tuple[list[dict], float]:
        comp = getattr(self.bridge, "compliance", None)
        if comp is None:
            return [], cursor
        try:
            comp.poll(time.time())
            latest = comp.violation_list(100)
        except Exception:  # noqa: BLE001 — 判定不得拖垮桥
            return [], cursor
        fresh = [v for v in latest if v.get("ts", 0) > cursor]
        new_cursor = max([v.get("ts", 0) for v in latest] + [cursor])
        return fresh, new_cursor

    async def _run_impl(self) -> None:
        tcp = self.bridge.tcp_bridge
        started = time.time()
        results: list[dict] = []
        cursor = self._latest_violation_ts()
        try:
            for step in self.steps:
                if self._stop_requested:
                    results.append({"label": step["label"], "skipped": True,
                                    "detail": "已手动停止"})
                    continue
                try:
                    result, cursor = await self._run_step(step, cursor)
                    results.append(result)
                except Exception as e:  # noqa: BLE001 — 单步异常不拖垮整条时间线
                    results.append({"label": step["label"], "expect": step["expect"],
                                    "ok": False, "detail": f"步骤执行异常: {e}"})
                self._publish(step, results[-1])
        finally:
            try:
                tcp.set_condition(NetworkCondition())  # 复位干净链路
            except Exception:  # noqa: BLE001
                pass
            self.running = False
            self.last_result = {
                "ok": all(r.get("ok") for r in results if not r.get("skipped")),
                "steps": results,
                "started_at": started,
                "duration_s": round(time.time() - started, 2),
                "stopped": self._stop_requested,
            }
            self._publish(None, self.last_result)

    async def _run_step(self, step: dict, cursor: float) -> tuple[dict, float]:
        """执行单步：设条件 → 窗口采集 → 判定；返回 (结果, 新违规游标)."""
        tcp = self.bridge.tcp_bridge
        cond = NetworkCondition()
        for k, v in step["condition"].items():
            setattr(cond, k, v)
        cond.active = bool(step["condition"])
        tcp.set_condition(cond)
        inj_before = dict(tcp.injection_stats())
        clients_before = tcp.stats.clients_total
        window_start = time.time()
        ticks = max(1, int(step["duration_s"] / self.tick_s))
        for _ in range(ticks):
            await self._sleep(self.tick_s)
            if self._stop_requested:
                break
        fresh, cursor = self._window_violations(cursor)
        inj_after = dict(tcp.injection_stats())
        clients_after = tcp.stats.clients_total
        dropped = inj_after.get("dropped", 0) - inj_before.get("dropped", 0)
        disconnects = inj_after.get("disconnects", 0) - inj_before.get("disconnects", 0)
        client_delta = clients_after - clients_before
        # 超时类证据（t1/t2/t3 来自 poll 的持久状态 + 真实时钟）：陈旧会话状态
        # 与空闲桥都会在首个窗口误触发，不是「注入扰动」的证据——
        # · t3（链路静默）与注入行为无关，一律排除；
        # · t1/t2 仅在显式 expect=t1 时作为正面证据；none 判定不把超时当反证
        #   （防误报：none 只看帧级瞬时违规 + 窗口增量）。
        all_kinds = [v.get("kind", "") for v in fresh]
        if step["expect"] == "none":
            kinds = [k for k in all_kinds if k not in ("t1", "t2", "t3")]
        else:
            kinds = [k for k in all_kinds if k != "t3"]
        ok, detail = self.judge(
            step["expect"], dropped_delta=dropped,
            disconnect_delta=disconnects + max(0, -client_delta),
            kinds=kinds)
        return ({
            "label": step["label"], "expect": step["expect"], "ok": ok,
            "detail": detail,
            "condition": cond.describe() if cond.has_any() else "(clean)",
            "observed": {"dropped": dropped, "disconnects": disconnects,
                         "clients": clients_after,
                         "violations": fresh[:10]},
            "window_s": round(time.time() - window_start, 2),
        }, cursor)

    def _publish(self, step: dict | None, payload: dict) -> None:
        bus = getattr(self.bridge, "bus", None)
        if bus is None:
            return
        try:
            bus.publish("timeline", {"step": (step or {}).get("label", ""),
                                     "running": self.running,
                                     **payload})
        except Exception:  # noqa: BLE001 — 事件不得影响主流程
            pass
