"""网络异常条件定义."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnomalyType(Enum):
    DELAY = "delay"
    LOSS = "loss"
    DUPLICATE = "duplicate"
    CORRUPT = "corrupt"
    REORDER = "reorder"
    DISCONNECT = "disconnect"
    BANDWIDTH = "bandwidth"
    JITTER = "jitter"


@dataclass
class NetworkCondition:
    """网络异常条件.

    所有概率值范围 0.0~1.0。
    """
    # 延迟 (ms)
    delay_ms: float = 0.0
    delay_variance_ms: float = 0.0  # 抖动范围

    # 丢包率 (0.0~1.0)
    loss_rate: float = 0.0

    # 重复率 (0.0~1.0)
    duplicate_rate: float = 0.0

    # 损坏率 (0.0~1.0)
    corrupt_rate: float = 0.0
    corrupt_bits: int = 1  # 翻转位数

    # 乱序率 (0.0~1.0)
    reorder_rate: float = 0.0
    reorder_window: int = 5  # 乱序窗口(帧数)

    # 断线模拟
    disconnect_rate: float = 0.0  # 每帧触发断线的概率
    disconnect_duration_s: float = 3.0  # 断线持续时间

    # 带宽限制 (bytes/s, 0=不限)
    bandwidth_bps: int = 0

    # 方向过滤: "rx" / "tx" / "both"
    direction: str = "both"

    # 是否激活
    active: bool = True

    def has_any(self) -> bool:
        """是否有任何异常条件."""
        return any([
            self.delay_ms > 0,
            self.loss_rate > 0,
            self.duplicate_rate > 0,
            self.corrupt_rate > 0,
            self.reorder_rate > 0,
            self.disconnect_rate > 0,
            self.bandwidth_bps > 0,
        ])

    def describe(self) -> str:
        parts = []
        if self.delay_ms > 0:
            parts.append(f"delay={self.delay_ms}ms±{self.delay_variance_ms}ms")
        if self.loss_rate > 0:
            parts.append(f"loss={self.loss_rate*100:.0f}%")
        if self.duplicate_rate > 0:
            parts.append(f"dup={self.duplicate_rate*100:.0f}%")
        if self.corrupt_rate > 0:
            parts.append(f"corrupt={self.corrupt_rate*100:.0f}%({self.corrupt_bits}bit)")
        if self.reorder_rate > 0:
            parts.append(f"reorder={self.reorder_rate*100:.0f}%")
        if self.disconnect_rate > 0:
            parts.append(f"disconnect={self.disconnect_rate*100:.0f}%/{self.disconnect_duration_s}s")
        if self.bandwidth_bps > 0:
            parts.append(f"bw={self.bandwidth_bps}B/s")
        return ", ".join(parts) if parts else "(none)"


class ConditionPreset:
    """预设网络条件."""

    @staticmethod
    def clean() -> NetworkCondition:
        """正常网络."""
        return NetworkCondition()

    @staticmethod
    def poor_wifi() -> NetworkCondition:
        """差 WiFi 环境."""
        return NetworkCondition(
            delay_ms=30,
            delay_variance_ms=20,
            loss_rate=0.05,
            reorder_rate=0.02,
        )

    @staticmethod
    def congested() -> NetworkCondition:
        """网络拥塞."""
        return NetworkCondition(
            delay_ms=100,
            delay_variance_ms=50,
            loss_rate=0.1,
            duplicate_rate=0.02,
            reorder_rate=0.05,
        )

    @staticmethod
    def satellite() -> NetworkCondition:
        """卫星链路 (高延迟)."""
        return NetworkCondition(
            delay_ms=500,
            delay_variance_ms=100,
            loss_rate=0.02,
        )

    @staticmethod
    def unreliable() -> NetworkCondition:
        """高丢包."""
        return NetworkCondition(
            loss_rate=0.3,
            corrupt_rate=0.05,
            duplicate_rate=0.03,
        )

    @staticmethod
    def intermittent() -> NetworkCondition:
        """间歇性断线."""
        return NetworkCondition(
            disconnect_rate=0.05,
            disconnect_duration_s=5.0,
        )

    @staticmethod
    def slow_link() -> NetworkCondition:
        """低带宽."""
        return NetworkCondition(
            bandwidth_bps=1024,  # 1KB/s
            delay_ms=50,
        )

    @staticmethod
    def stress_test() -> NetworkCondition:
        """综合压力测试."""
        return NetworkCondition(
            delay_ms=50,
            delay_variance_ms=30,
            loss_rate=0.1,
            duplicate_rate=0.03,
            corrupt_rate=0.02,
            reorder_rate=0.05,
            disconnect_rate=0.01,
            disconnect_duration_s=3.0,
        )

    @staticmethod
    def from_name(name: str) -> NetworkCondition:
        presets = {
            "clean": ConditionPreset.clean,
            "poor_wifi": ConditionPreset.poor_wifi,
            "congested": ConditionPreset.congested,
            "satellite": ConditionPreset.satellite,
            "unreliable": ConditionPreset.unreliable,
            "intermittent": ConditionPreset.intermittent,
            "slow_link": ConditionPreset.slow_link,
            "stress": ConditionPreset.stress_test,
        }
        factory = presets.get(name)
        if not factory:
            raise ValueError(f"Unknown preset: {name}. Available: {list(presets.keys())}")
        return factory()
