"""主站参数命令状态跟踪 — 装载/激活结果快照与应答等待（T08）.

从 ``core/engine/master.py`` 抽出的参数命令可观测性逻辑：

- ``ParameterResult`` / ``ParameterState``：单个参数的单一维度结果与状态快照
  （供 Web UI / REST 查询）
- ``MasterParameterTracker.send_tracked_parameter``：下发参数命令并**非阻塞**
  地跟踪结果（下发失败回退 ``UNKNOWN``，不把"从未发出"误记为超时）
- ``wait_parameter_ack``：等待激活确认（ACTCON），超时记 ``TIMEOUT``
- ``record_ack`` / ``record_timeout``：应答/超时的状态写入（含竞态防护）

设计：**组合 + 构造期注入**。状态容器（``_parameter_states`` /
``_pending_parameter_acks``）与超时值（``_t1``）仍由 ``MasterEngine`` 持有——
测试与 REST 接线会直接访问 ``engine._pending_parameter_acks`` /
``engine.get_parameter_state()``，故本类只持有引擎引用并按需读写，避免子模块
反向 ``import`` ``master.py`` 造成循环依赖（类型仅经 ``TYPE_CHECKING`` 前置引用）。

``ParameterResult`` / ``ParameterState`` 定义在本模块，并由 ``master.py`` 再导出
（``from core.engine.master import ParameterState, ParameterResult`` 保持兼容）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING

from ..protocol.types import COT

if TYPE_CHECKING:
    from .master import MasterEngine

logger = logging.getLogger("iec104.master")


class ParameterResult(Enum):
    """参数命令在主站侧的单一维度（装载 / 激活）结果."""

    UNKNOWN = "unknown"        # 未下发过，或下发失败后回退
    PENDING = "pending"        # 已下发，等待应答
    OK = "ok"                  # 收到激活确认 (ACTCON, PN=0)
    TERMINATED = "terminated"  # 收到激活终止 (ACTTERM)
    REJECTED = "rejected"      # 收到否定确认 (ACTCON, PN=1)
    TIMEOUT = "timeout"        # t1 内未收到任何应答


@dataclass
class ParameterState:
    """单个参数的主站侧状态快照（装载 + 激活，供 Web UI / REST 查询）.

    - **装载 (load)**：``P_ME_NA_1`` / ``P_ME_NB_1`` / ``P_ME_NC_1``（参数值下发）
    - **激活 (activation)**：``P_AC_NA_1``（参数激活 / 去激活）

    ``*_updated_at`` 为 ``time.monotonic()`` 时间戳（与 ``_last_clock_sync_sent_time``
    一致，适合算时长/间隔，不用于向用户展示绝对时间）。
    """

    ioa: int
    load_result: ParameterResult = ParameterResult.UNKNOWN
    load_cot: int | None = None
    load_updated_at: float | None = None
    activation_result: ParameterResult = ParameterResult.UNKNOWN
    activation_cot: int | None = None
    activation_updated_at: float | None = None


class MasterParameterTracker:
    """参数命令装载/激活结果跟踪（由 ``MasterEngine`` 组合持有）."""

    def __init__(self, engine: MasterEngine) -> None:
        self._engine = engine

    # ── 查询接口（公开 API 的实现，门面见 ``MasterEngine``）─────────

    def get_state(self, ioa: int) -> ParameterState | None:
        """查询单个参数的装载/激活状态快照（**快照副本**；未知 IOA 返回 None）."""
        state = self._engine._parameter_states.get(ioa)
        return replace(state) if state is not None else None

    def all_states(self) -> dict[int, ParameterState]:
        """返回全部已跟踪参数的状态快照（键 = IOA，值为快照副本）."""
        return {
            ioa: replace(state)
            for ioa, state in self._engine._parameter_states.items()
        }

    # ── 下发与应答等待（与 SBO 同一机制与超时语义）─────────────────

    async def send_tracked_parameter(self, kind: str, ioa: int,
                                      sender: Callable, *args) -> None:
        """下发参数命令并跟踪结果；**不阻塞调用方**（既有非阻塞语义不变）.

        与 SBO 的 ``_wait_select_ack`` 使用同一套机制与超时语义：登记 Future →
        ``asyncio.wait_for(t1)`` → 超时记 ``TIMEOUT``。区别仅在于等待放在后台
        任务中执行，故调用方的延迟与异常行为与改动前完全一致（参数命令应答
        属可观测性信息，不应把设备是否应答变成调用方的阻塞点）。
        """
        e = self._engine
        self.set_result(ioa, kind, ParameterResult.PENDING, None)
        waiter = e._spawn(self.wait_parameter_ack(ioa, kind, e._t1))
        try:
            await sender(*args)
        except Exception:
            # 下发失败：撤销等待并回退状态，避免把"从未发出"误记为超时
            if waiter is not None:
                waiter.cancel()
            self.set_result(ioa, kind, ParameterResult.UNKNOWN, None)
            raise

    async def wait_parameter_ack(self, ioa: int, kind: str, timeout: float) -> bool:
        """等待参数命令的激活确认 (ACTCON) — 与 ``_wait_select_ack`` 同语义.

        并发安全同 SBO：同一 (IOA, 类型) 上已有未完成等待时先取消旧的；清理时
        只删除属于自己的 Future（``is fut`` 判定），不误删他人登记。

        Returns:
            True=收到肯定确认 (PN=0)；False=否定确认或超时（状态已由
            ``record_ack`` / ``record_timeout`` 记录）。
        """
        e = self._engine
        key = (ioa, kind)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        old = e._pending_parameter_acks.get(key)
        if old is not None and not old.done():
            logger.warning(
                f"Parameter: concurrent wait on IOA={ioa} kind={kind}, "
                f"cancelling stale waiter"
            )
            old.cancel()
        e._pending_parameter_acks[key] = fut
        try:
            pn, cot = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self.record_timeout(ioa, kind)
            return False
        except asyncio.CancelledError:
            return False
        finally:
            if e._pending_parameter_acks.get(key) is fut:
                e._pending_parameter_acks.pop(key, None)
        return not pn

    # ── 状态写入 ──────────────────────────────────────────────────

    def set_result(self, ioa: int, kind: str,
                    result: ParameterResult, cot: int | None) -> None:
        """写入某参数某一维（load/activation）的结果与时间戳."""
        states = self._engine._parameter_states
        state = states.get(ioa)
        if state is None:
            state = ParameterState(ioa=ioa)
            states[ioa] = state
        now = time.monotonic()
        if kind == "activation":
            state.activation_result = result
            state.activation_cot = cot
            state.activation_updated_at = now
        else:
            state.load_result = result
            state.load_cot = cot
            state.load_updated_at = now

    def record_ack(self, ioa: int, kind: str, cot: int, pn: bool) -> None:
        """记录参数命令应答（由 ``MasterProtocolHandler.process_parameter_ack`` 调用）.

        与 SBO 一致：**仅 ACTCON 唤醒等待者**——ACTTERM 可能是上一条命令的滞后帧，
        若用它唤醒本次等待会把"肯定确认"误判为超时（SBO 侧同类竞态的修复经验）。
        ACTTERM/DEACTCON 仅更新已记录的状态。
        """
        if cot == COT.ACTCON:
            fut = self._engine._pending_parameter_acks.get((ioa, kind))
            if fut is not None and not fut.done():
                fut.set_result((pn, cot))
            result = ParameterResult.REJECTED if pn else ParameterResult.OK
        elif cot == COT.ACTTERM:
            result = ParameterResult.TERMINATED
        elif cot == COT.DEACTCON:
            # 参数去激活确认：调用方要求去激活（qualifier=2）时的正常完成
            result = ParameterResult.OK
        else:
            # 其它 COT（如 SPONT/INTROGEN）不是参数命令应答语义，只记日志
            logger.debug(f"Parameter ACK with unexpected COT={cot}: IOA={ioa}")
            return
        self.set_result(ioa, kind, result, cot)

    def record_timeout(self, ioa: int, kind: str) -> None:
        """t1 内未收到应答 → 记 TIMEOUT；已有终态（OK/REJECTED/TERMINATED）不被覆盖."""
        state = self._engine._parameter_states.get(ioa)
        if state is None:
            return
        current = state.activation_result if kind == "activation" else state.load_result
        if current is not ParameterResult.PENDING:
            return
        self.set_result(ioa, kind, ParameterResult.TIMEOUT, None)
