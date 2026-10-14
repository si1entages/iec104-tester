"""子站数据模拟层 — 手动 / 随机 / 脚本化数据变化与自发上送.

从 ``core/engine/slave.py`` 抽出的"数据变化"职责：

- 手动触发点变化（``simulate_yx_change`` / ``simulate_yc_change``）
- 随机数据模拟循环（``start_simulation`` / ``stop_simulation`` / ``_simulation_loop``）
- 逐点自动变化循环（``_auto_change_loop``，按 ``is_changing`` 与 ``change_interval``）
- 自发上送（``send_spontaneous_yx`` / ``_yc`` / ``_dp`` / ``_ym`` / ``_step``）
  及测试注入类上送（``send_protection_event`` / ``send_group_single_point``）
- 命令结果联动（``_reflect_command_result``）：遥控/遥调成功后同 IOA 变位并上送

设计：**组合 + 构造期注入**。引擎全部共享状态（``_data_store`` /
``_point_table`` / ``_spontaneous_enabled`` / ``_simulation_*`` / ``_auto_change_*``）
仍由 ``SlaveEngine`` 持有，本类只持有引擎引用并按需读写；类型仅经
``TYPE_CHECKING`` 前置引用，避免反向 import 造成循环依赖。这样测试对引擎实例
属性（如 ``engine._simulation_running`` / ``engine._simulation_task``）的替换
依旧生效，行为零变化。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING

from ..data.point_table import YxType
from ..protocol.asdu import ASDUBuilder
from ..protocol.types import COT, QualityDescriptor

if TYPE_CHECKING:
    from .slave import SlaveEngine

logger = logging.getLogger("iec104.slave")


class SlaveSimulator:
    """子站数据模拟 / 自发上送（由 ``SlaveEngine`` 组合持有）."""

    def __init__(self, engine: SlaveEngine) -> None:
        self._engine = engine

    # ── 手动模拟 ──────────────────────────────────────────────────

    def simulate_yx_change(self, ioa: int, value: bool) -> None:
        """模拟遥信变化."""
        e = self._engine
        e._data_store.update_yx(ioa, value)
        e._spawn(self.send_spontaneous_yx(ioa, value))

    def simulate_yc_change(self, ioa: int, value: float) -> None:
        """模拟遥测变化."""
        e = self._engine
        e._data_store.update_yc(ioa, value)
        e._spawn(self.send_spontaneous_yc(ioa, value))

    # ── 随机模拟循环 ──────────────────────────────────────────────

    async def start_simulation(
        self,
        yx_interval: float = 5.0,
        yc_interval: float = 2.0,
        yx_change_rate: float = 0.1,
        yc_change_range: float = 0.05,
    ) -> None:
        """启动自动数据模拟."""
        e = self._engine
        if e._simulation_running:
            return

        e._simulation_running = True
        e._simulation_task = e._spawn(
            self.simulation_loop(yx_interval, yc_interval, yx_change_rate, yc_change_range)
        )
        logger.info("Simulation started")

    async def stop_simulation(self) -> None:
        """停止模拟."""
        e = self._engine
        e._simulation_running = False
        if e._simulation_task:
            e._simulation_task.cancel()
            try:
                await e._simulation_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("Simulation stopped")

    async def simulation_loop(
        self,
        yx_interval: float,
        yc_interval: float,
        yx_change_rate: float,
        yc_change_range: float,
    ) -> None:
        """模拟数据变化循环（随机变化）."""
        e = self._engine
        yx_tick = 0.0
        yc_tick = 0.0

        while e._simulation_running:
            await asyncio.sleep(0.1)
            now = time.monotonic()

            # 遥信随机变化
            if now - yx_tick >= yx_interval:
                yx_tick = now
                yx_points = e._point_table.get_all_yx()
                for p in yx_points:
                    if random.random() < yx_change_rate:
                        current = e._data_store.get_yx(p.ioa)
                        new_value = not current.value if current else True
                        await self.send_spontaneous_yx(p.ioa, new_value)

            # 遥测随机波动
            if now - yc_tick >= yc_interval:
                yc_tick = now
                yc_points = e._point_table.get_all_yc()
                for p in yc_points:
                    current = e._data_store.get_yc(p.ioa)
                    if current:
                        delta = current.value * yc_change_range * (random.random() * 2 - 1)
                        new_value = current.value + delta
                        new_value = max(p.min_value, min(p.max_value, new_value))
                        await self.send_spontaneous_yc(p.ioa, new_value)

    async def auto_change_loop(self) -> None:
        """逐点自动变化循环 — 标记为 is_changing 的点按 change_interval 周期变化."""
        e = self._engine
        change_ticks: dict[int, float] = {}

        while e._auto_change_running:
            await asyncio.sleep(0.1)
            now = time.monotonic()

            # 遥信自动变化（翻转）
            yx_data = e._data_store._yx
            for ioa, point in list(yx_data.items()):
                if point.is_changing:
                    last_tick = change_ticks.get(ioa, 0)
                    if now - last_tick >= point.change_interval:
                        change_ticks[ioa] = now
                        new_value = not point.value
                        await self.send_spontaneous_yx(ioa, new_value)

            # 遥测自动变化（在最小值最大值范围内随机）
            yc_data = e._data_store._yc
            for ioa, point in list(yc_data.items()):
                if point.is_changing:
                    last_tick = change_ticks.get(f"yc_{ioa}", 0)
                    if now - last_tick >= point.change_interval:
                        change_ticks[f"yc_{ioa}"] = now
                        min_val = point.min_val if point.min_val != float('inf') else 0.0
                        max_val = point.max_val if point.max_val != float('-inf') else 100.0
                        if min_val >= max_val:
                            min_val, max_val = max_val - 100, max_val
                        new_value = min_val + random.random() * (max_val - min_val)
                        await self.send_spontaneous_yc(ioa, new_value)

    # ── 命令结果联动 ──────────────────────────────────────────────

    async def reflect_command_result(self, ioa: int, *,
                                     single: bool | None = None,
                                     double_state: int | None = None,
                                     yc_value: float | None = None,
                                     step_delta: int | None = None) -> bool:
        """把命令执行结果联动到被控点并自发上送（**以真机为准**）.

        真机语义：
        - 遥控执行成功后，同 IOA 的遥信立即变位并带时标上送（COT=3, SOE）；
        - 遥调/设点执行成功后，同 IOA 的遥测更新并上报（COT=3）；
        - 升降命令执行成功后，同 IOA 的**步位置**按步长加减并限幅后上送；
        - 上送类型由**点表声明**决定：单点遥信 → M_SP_TB_1，双点遥信 → M_DP_TB_1，
          步位置 → M_ST_TB_1；
        - 点表没有该点、或值未发生变化（含已到限幅边界）时不上送。

        上送受 ``spontaneous_enabled`` 约束（关闭时仍更新实时库，供召唤使用）。

        Args:
            ioa: 被控点 IOA（与命令 IOA 相同）。
            single: 单命令目标状态（True=合）。
            double_state: 双命令目标状态（1=分, 2=合）。
            yc_value: 设点目标值（工程值）。
            step_delta: 升降步数增量（+1=升一步 / -1=降一步）。

        Returns:
            True 表示已完成联动（值有变化或被更新）。
        """
        e = self._engine
        if step_delta is not None:
            point = e._point_table.get_step(ioa)
            if point is None:
                logger.debug(f"Command feedback: STEP IOA={ioa} 不在点表，跳过联动")
                return False
            current = e._data_store.get_step(ioa)
            cur = int(current.value) if current is not None else int(point.initial_value)
            new_value = cur + int(point.step_size) * int(step_delta)
            # 限幅到点表定义的上下限（升到上限不再增、降到下限不再减）
            new_value = max(int(point.min_value), min(int(point.max_value), new_value))
            if new_value == cur:
                return False
            await self.send_spontaneous_step(ioa, new_value, transient=point.transient)
            return True

        if yc_value is not None:
            if e._point_table.get_yc(ioa) is None:
                logger.debug(f"Command feedback: YC IOA={ioa} 不在点表，跳过联动")
                return False
            current_yc = e._data_store.get_yc(ioa)
            if current_yc is not None and abs(float(current_yc.value) - float(yc_value)) < 1e-9:
                return False
            await self.send_spontaneous_yc(ioa, float(yc_value))
            return True

        point = e._point_table.get_yx(ioa)
        if point is None:
            logger.debug(f"Command feedback: YX IOA={ioa} 不在点表，跳过联动")
            return False
        current = e._data_store.get_yx(ioa)

        if double_state is not None and point.point_type == YxType.DOUBLE:
            if current is not None and current.double_state == int(double_state):
                return False
            await self.send_spontaneous_dp(ioa, int(double_state))
            return True

        value = bool(single) if single is not None else (double_state == 2)
        if current is not None and bool(current.value) == value:
            return False
        await self.send_spontaneous_yx(ioa, value)
        return True

    # ── 自发上送 ──────────────────────────────────────────────────

    async def send_spontaneous_yx(self, ioa: int, value: bool,
                                  quality: int = 0) -> None:
        """自发上送遥信变化.

        若该 IOA 在点表中声明为**双点**，则按真机语义转成双点上送
        （M_DP_TB_1，状态 2=合/1=分），避免双点遥信以单点类型上送造成类型错配。
        """
        e = self._engine
        point = e._point_table.get_yx(ioa)
        if point is not None and point.point_type == YxType.DOUBLE:
            await self.send_spontaneous_dp(ioa, 2 if value else 1)
            return
        e._data_store.update_yx(ioa, value, QualityDescriptor(quality))

        if not e._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_spontaneous_single_point(
            e._common_addr, ioa, value, quality
        )
        await e._session.broadcast_i_frame(asdu_data)

    async def send_spontaneous_yc(self, ioa: int, value: float,
                                  quality: int = 0) -> None:
        """自发上送遥测变化."""
        e = self._engine
        e._data_store.update_yc(ioa, value, QualityDescriptor(quality))

        if not e._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_short_float(
            e._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await e._session.broadcast_i_frame(asdu_data)

    async def send_spontaneous_dp(self, ioa: int, value: int,
                                  quality: int = 0) -> None:
        """自发上送双点遥信变化."""
        e = self._engine
        e._data_store.update_yx(ioa, value == 2, QualityDescriptor(quality), double_state=value)

        if not e._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_double_point(
            e._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await e._session.broadcast_i_frame(asdu_data)

    async def send_spontaneous_ym(self, ioa: int, value: int,
                                  quality: int = 0) -> None:
        """自发上送累计量变化."""
        e = self._engine
        e._data_store.update_ym(ioa, value, QualityDescriptor(quality))

        if not e._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_counter_value(
            e._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await e._session.broadcast_i_frame(asdu_data)

    async def send_spontaneous_step(self, ioa: int, value: int,
                                    quality: int = 0,
                                    transient: bool = False) -> None:
        """自发上送步位置变化 (M_ST_TB_1, COT=3)."""
        e = self._engine
        e._data_store.update_step(ioa, int(value), QualityDescriptor(quality),
                                  transient=transient)

        if not e._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_step_position(
            e._common_addr, ioa, int(value), quality,
            transient=transient, cot=COT.SPONT, with_time=True
        )
        await e._session.broadcast_i_frame(asdu_data)

    async def send_protection_event(self, ioa: int, event_value: int = 1,
                                    with_time: bool = True, quality: int = 0) -> None:
        """模拟继电保护设备事件上送 (M_EP_TD_1 / M_EP_TA_1, COT=3).

        说明：点表未建模继保事件点，本方法为**测试注入**用途——直接广播报文，
        不落实时库（主站侧按 M_EP_* 类型自行处理/展示）。
        """
        e = self._engine
        if not e._spontaneous_enabled:
            return
        asdu_data = ASDUBuilder.build_protection_event(
            e._common_addr, ioa, event_value, quality,
            with_time=with_time, cot=COT.SPONT,
        )
        await e._session.broadcast_i_frame(asdu_data)

    async def send_group_single_point(self, ioa: int,
                                      points: list[tuple[bool, bool]],
                                      with_time: bool = False) -> None:
        """模拟带状态检出的成组单点信息上送 (M_PS_NA_1 / M_PS_TB_1, COT=3).

        同上，属测试注入：每点 (状态, 检出位)，最多 8 点，不落实时库。
        注意：M_PS_* 信息体本身不含品质描述词。
        """
        e = self._engine
        if not e._spontaneous_enabled:
            return
        asdu_data = ASDUBuilder.build_group_single_point(
            e._common_addr, ioa, points,
            cot=COT.SPONT, with_time=with_time,
        )
        await e._session.broadcast_i_frame(asdu_data)
