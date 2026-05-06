"""模拟管理器 — 简化网络异常模拟的使用.

用法:
    from core.simulation import SimulationManager

    sim = SimulationManager()

    # 应用预设
    sim.apply_preset("congested")

    # 或自定义条件
    sim.apply_condition(loss_rate=0.1, delay_ms=50)

    # 安装到引擎
    sim.install(master_engine)

    # 查看统计
    print(sim.stats())

    # 移除
    sim.remove()
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .conditions import NetworkCondition, ConditionPreset
from .proxy import NetworkProxy

logger = logging.getLogger("iec104.simulation.manager")


class SimulationManager:
    """网络异常模拟管理器.

    简化 NetworkProxy 的使用，提供一站式 API。
    """

    def __init__(self):
        self._condition = NetworkCondition()
        self._proxy: Optional[NetworkProxy] = None
        self._engine: Any = None
        self._installed = False

    @property
    def is_active(self) -> bool:
        return self._installed and self._condition.active

    @property
    def condition(self) -> NetworkCondition:
        return self._condition

    @property
    def proxy(self) -> Optional[NetworkProxy]:
        return self._proxy

    # ── 配置 ──────────────────────────────────────────────────────

    def apply_preset(self, name: str) -> None:
        """应用预设条件."""
        self._condition = ConditionPreset.from_name(name)
        if self._proxy:
            self._proxy._condition = self._condition
        logger.info(f"Applied preset '{name}': {self._condition.describe()}")

    def apply_condition(self, **kwargs) -> None:
        """设置自定义条件参数."""
        for k, v in kwargs.items():
            if hasattr(self._condition, k):
                setattr(self._condition, k, v)
            else:
                logger.warning(f"Unknown condition parameter: {k}")
        if self._proxy:
            self._proxy._condition = self._condition
        logger.info(f"Condition: {self._condition.describe()}")

    def set_active(self, active: bool) -> None:
        """启用/禁用异常注入."""
        self._condition.active = active
        logger.info(f"Simulation {'enabled' if active else 'disabled'}")

    # ── 安装/卸载 ─────────────────────────────────────────────────

    def install(self, engine) -> None:
        """安装到引擎.

        自动拦截引擎的帧回调，注入网络异常。
        """
        if self._installed:
            self.remove()

        self._engine = engine
        self._proxy = NetworkProxy(self._condition)
        self._proxy.install_on_engine(engine)

        # 替换引擎的 raw_frame_callback
        original_callback = getattr(engine, '_raw_frame_callback', None)
        if original_callback:
            wrapped = self._proxy.wrap_rx_callback(original_callback)
            engine.set_raw_frame_callback(wrapped)

        self._installed = True
        logger.info(f"Simulation installed on engine: {self._condition.describe()}")

    def remove(self) -> None:
        """从引擎移除模拟."""
        if not self._installed or not self._engine:
            return

        # 恢复原始回调
        if self._proxy and self._proxy._original_rx:
            self._engine.set_raw_frame_callback(self._proxy._original_rx)

        self._proxy = None
        self._installed = False
        logger.info("Simulation removed")

    # ── 统计 ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        """获取统计信息."""
        if self._proxy:
            return self._proxy.stats
        return {}

    def stats_summary(self) -> str:
        """统计摘要."""
        s = self.stats()
        if not s:
            return "Simulation not active"

        lines = [
            f"🔧 Network Simulation",
            f"   Condition: {self._condition.describe()}",
            f"   Active: {self._condition.active}",
            f"   RX: {s.get('rx_total', 0)} total, "
            f"{s.get('rx_dropped', 0)} dropped, "
            f"{s.get('rx_corrupted', 0)} corrupted",
            f"   TX: {s.get('tx_total', 0)} total, "
            f"{s.get('tx_dropped', 0)} dropped, "
            f"{s.get('tx_corrupted', 0)} corrupted",
        ]
        if s.get("disconnects", 0) > 0:
            lines.append(f"   Disconnects: {s['disconnects']}")
        if s.get("rx_duplicated", 0) > 0 or s.get("tx_duplicated", 0) > 0:
            lines.append(f"   Duplicated: RX={s.get('rx_duplicated', 0)}, TX={s.get('tx_duplicated', 0)}")
        return "\n".join(lines)

    def reset_stats(self) -> None:
        if self._proxy:
            self._proxy.reset_stats()

    # ── 便捷方法 ──────────────────────────────────────────────────

    def set_loss(self, rate: float) -> None:
        """快速设置丢包率."""
        self.apply_condition(loss_rate=rate)

    def set_delay(self, ms: float, variance: float = 0) -> None:
        """快速设置延迟."""
        self.apply_condition(delay_ms=ms, delay_variance_ms=variance)

    def set_corrupt(self, rate: float, bits: int = 1) -> None:
        """快速设置损坏率."""
        self.apply_condition(corrupt_rate=rate, corrupt_bits=bits)

    def disconnect(self, duration: float = 5.0) -> None:
        """手动触发断线."""
        if self._proxy:
            self._proxy._disconnected_until = (
                __import__('time').monotonic() + duration
            )
            self._proxy._stats["disconnects"] += 1
            logger.warning(f"Manual disconnect for {duration}s")
