"""桥上网络条件注入器（T85）——帧级弱网模拟（混沌验收）.

与 ``core/simulation/proxy.py`` 的回调包装式不同：桥转发路径没有引擎回调，
本注入器工作在 **APCI 完整帧** 层（``FrameSplitter.feed`` 的输出）——
``process(frame, direction)`` 返回一串「投递动作」：立即投递、延迟投递、
复制投递、丢弃。``TcpBridge._pump`` 消费动作序列写 ``peer_writer``。

关键约束：**注入只作用于转发数据路径，旁路观察（on_frame/合规监视/录制）
永远看原始帧**——干扰前先观察，审计证据不被污染，且观察者异常不影响转发。

断线模拟按整连接（每客户端连接一条注入器）；带宽限速在桥处以每帧间隔近似。
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass

from core.simulation.conditions import NetworkCondition


@dataclass
class DeliverAction:
    """一条投递动作：``delay_s=0`` 立即写；>0 由桥调度延迟写."""
    data: bytes
    delay_s: float = 0.0


@dataclass
class InjectionStats:
    """注入统计（只增，进桥状态页与测试报告）."""
    total: int = 0
    dropped: int = 0
    duplicated: int = 0
    corrupted: int = 0
    delayed: int = 0
    reordered: int = 0
    disconnects: int = 0

    def as_dict(self) -> dict:
        return {"total": self.total, "dropped": self.dropped,
                "duplicated": self.duplicated, "corrupted": self.corrupted,
                "delayed": self.delayed, "reordered": self.reordered,
                "disconnects": self.disconnects}


class ConditionInjector:
    """帧级条件注入器（每条客户端连接一个实例，线程内 asyncio 单线程使用）."""

    def __init__(self, condition: NetworkCondition | None = None):
        self.condition = condition or NetworkCondition()
        self.stats = InjectionStats()
        self._disconnected_until = 0.0
        self._reorder_buffer: deque[DeliverAction] = deque()
        self._last_tx_time = 0.0
        self._closed = False

    def update(self, condition: NetworkCondition | None) -> None:
        """动态更新条件（``None`` / ``active=False`` = 直通模式）."""
        self.condition = condition or NetworkCondition()
        if self.condition.reorder_window > 0:
            self._reorder_buffer = deque(maxlen=self.condition.reorder_window)

    @property
    def active(self) -> bool:
        return bool(self.condition.active and self.condition.has_any())

    def is_disconnected(self) -> bool:
        return time.monotonic() < self._disconnected_until

    def process(self, frame: bytes, direction: str) -> list[DeliverAction]:
        """处理一帧 → 投递动作序列（按条件概率决策）.

        ``direction``: ``tx``=主站→子站 / ``rx``=子站→主站；条件器的
        ``direction`` 字段（rx/tx/both）按**被干扰的流向**过滤。
        """
        self.stats.total += 1
        if not self.condition.active or not self.condition.has_any():
            return [DeliverAction(frame)]

        # 方向过滤：条件 direction 用"接收/发送"语义，这里 tx/rx 直接对齐
        cond_dir = self.condition.direction
        if (direction == "tx" and cond_dir == "rx") or \
           (direction == "rx" and cond_dir == "tx"):
            return [DeliverAction(frame)]

        # 断线：整连接静默期（丢弃该方向所有帧，直到恢复）
        if self.is_disconnected():
            self.stats.dropped += 1
            return []
        if random.random() < self.condition.disconnect_rate:
            self.stats.disconnects += 1
            self._disconnected_until = time.monotonic() + self.condition.disconnect_duration_s
            return []

        # 丢包
        if random.random() < self.condition.loss_rate:
            self.stats.dropped += 1
            return []

        # 损坏（翻转随机字节的位）
        out = self._maybe_corrupt(frame)

        # 延迟
        delay_s = 0.0
        if self.condition.delay_ms > 0:
            variance = self.condition.delay_variance_ms * (random.random() * 2 - 1)
            delay_s = max(0.0, (self.condition.delay_ms + variance) / 1000.0)
            self.stats.delayed += 1

        actions = [DeliverAction(out, delay_s)]

        # 重复（复制一份立即或同延迟投递）
        if random.random() < self.condition.duplicate_rate:
            self.stats.duplicated += 1
            actions.append(DeliverAction(out, max(delay_s, 0.0)))

        # 乱序（T85）：本帧附加一个小延迟 → 上一帧先到、本帧后到，
        # 用「后发先至」模拟乱序。不缓存帧（避免窗口滞留导致字节流缺口），
        # 帧数守恒；窗口大小映射为延迟上限（每窗口 5ms，最多 50ms）。
        if self.condition.reorder_rate > 0 and random.random() < self.condition.reorder_rate:
            self.stats.reordered += 1
            extra = min(self.condition.reorder_window * 5, 50) / 1000.0
            actions = [DeliverAction(a.data, a.delay_s + extra) for a in actions]

        return actions

    def _maybe_corrupt(self, frame: bytes) -> bytes:
        if random.random() >= self.condition.corrupt_rate or not frame:
            return frame
        data = bytearray(frame)
        idx = random.randrange(len(data))
        # 翻转 corrupt_bits 个位（同一字节内）
        for b in range(min(self.condition.corrupt_bits, 8)):
            data[idx] ^= 1 << b
        self.stats.corrupted += 1
        return bytes(data)


async def emit_actions(actions: list[DeliverAction],
                       write: asyncio.StreamWriter) -> None:
    """把动作序列投递到对端（延迟动作由事件循环调度，不阻塞转发主循环）."""
    loop = asyncio.get_running_loop()
    for action in actions:
        if action.delay_s > 0:
            loop.call_later(action.delay_s, _delayed_write, write, action.data)
        else:
            try:
                write.write(action.data)
                await write.drain()
            except Exception:  # noqa: BLE001 — 对端写失败由 _pump 收口
                raise


def _delayed_write(writer: asyncio.StreamWriter, data: bytes) -> None:
    try:
        if not writer.is_closing():
            writer.write(data)
            # drain 在回调里不可 await；transport 会缓冲，由下一次 drain 刷出
    except Exception:  # noqa: BLE001 — 延迟投递时连接可能已关闭
        pass
