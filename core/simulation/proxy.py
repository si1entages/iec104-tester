"""网络代理 — 在帧传输路径上注入异常.

拦截引擎的收发回调，对帧施加条件后再传递给原始处理器。
"""

from __future__ import annotations

import asyncio
import logging
import random
import struct
import time
import threading
from collections import deque
from typing import Callable, Optional

from .conditions import NetworkCondition

logger = logging.getLogger("iec104.simulation.proxy")


class NetworkProxy:
    """网络异常代理.

    工作原理:
    - 拦截 TX: 引擎发送帧 → proxy → 条件处理 → TCP 发送
    - 拦截 RX: TCP 收帧 → proxy → 条件处理 → 引擎处理

    用法:
        proxy = NetworkProxy(condition)
        proxy.set_original_tx_callback(engine._send_frame)
        proxy.set_original_rx_callback(engine._on_frame_received)
        proxy.install(engine)
    """

    def __init__(self, condition: NetworkCondition):
        self._condition = condition
        self._lock = threading.Lock()

        # 原始回调
        self._original_rx: Optional[Callable] = None
        self._original_tx: Optional[Callable] = None

        # 乱序缓冲
        self._reorder_buffer: deque = deque(maxlen=condition.reorder_window)

        # 断线状态
        self._disconnected_until: float = 0.0

        # 带宽限速
        self._last_tx_time: float = 0.0

        # 统计
        self._stats = {
            "rx_total": 0, "tx_total": 0,
            "rx_dropped": 0, "tx_dropped": 0,
            "rx_corrupted": 0, "tx_corrupted": 0,
            "rx_duplicated": 0, "tx_duplicated": 0,
            "rx_delayed": 0, "tx_delayed": 0,
            "rx_reordered": 0, "tx_reordered": 0,
            "disconnects": 0,
        }

    @property
    def condition(self) -> NetworkCondition:
        return self._condition

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def update_condition(self, **kwargs) -> None:
        """动态更新条件参数."""
        for k, v in kwargs.items():
            if hasattr(self._condition, k):
                setattr(self._condition, k, v)
        logger.info(f"Condition updated: {self._condition.describe()}")

    # ── 安装/卸载 ─────────────────────────────────────────────────

    def wrap_rx_callback(self, original: Callable) -> Callable:
        """包装 RX 回调."""
        self._original_rx = original

        def wrapped_rx(frame: bytes, *args, **kwargs):
            return self._process_rx(frame, *args, **kwargs)

        return wrapped_rx

    def wrap_tx_callback(self, original: Callable) -> Callable:
        """包装 TX 回调."""
        self._original_tx = original

        async def wrapped_tx(frame: bytes, *args, **kwargs):
            return await self._process_tx(frame, *args, **kwargs)

        return wrapped_tx

    def install_on_engine(self, engine) -> None:
        """在引擎上安装代理.

        自动包装引擎的 frame_callback，不需要手动设置。
        """
        # 保存引擎引用，用于后续发送
        self._engine = engine
        logger.info(f"Network proxy installed: {self._condition.describe()}")

    # ── 帧处理 ────────────────────────────────────────────────────

    def _process_rx(self, frame: bytes, *args, **kwargs) -> None:
        """处理接收帧."""
        if not self._condition.active:
            if self._original_rx:
                self._original_rx(frame, *args, **kwargs)
            return

        self._stats["rx_total"] += 1
        direction_ok = self._condition.direction in ("rx", "both")

        if not direction_ok:
            if self._original_rx:
                self._original_rx(frame, *args, **kwargs)
            return

        # 断线检查
        if self._is_disconnected():
            self._stats["rx_dropped"] += 1
            return

        # 丢包
        if random.random() < self._condition.loss_rate:
            self._stats["rx_dropped"] += 1
            logger.debug(f"RX frame dropped (loss)")
            return

        # 损坏
        frame = self._maybe_corrupt(frame, "rx")

        # 重复
        if random.random() < self._condition.duplicate_rate:
            self._stats["rx_duplicated"] += 1
            self._deliver_rx(frame, *args, **kwargs)

        # 延迟
        if self._condition.delay_ms > 0:
            delay = self._calc_delay()
            self._stats["rx_delayed"] += 1
            asyncio.get_event_loop().call_later(
                delay / 1000.0,
                lambda: self._deliver_rx(frame, *args, **kwargs),
            )
        else:
            self._deliver_rx(frame, *args, **kwargs)

    async def _process_tx(self, frame: bytes, *args, **kwargs) -> None:
        """处理发送帧."""
        if not self._condition.active:
            if self._original_tx:
                await self._original_tx(frame, *args, **kwargs)
            return

        self._stats["tx_total"] += 1
        direction_ok = self._condition.direction in ("tx", "both")

        if not direction_ok:
            if self._original_tx:
                await self._original_tx(frame, *args, **kwargs)
            return

        # 断线检查
        if self._is_disconnected():
            self._stats["tx_dropped"] += 1
            return

        # 丢包
        if random.random() < self._condition.loss_rate:
            self._stats["tx_dropped"] += 1
            logger.debug(f"TX frame dropped (loss)")
            return

        # 损坏
        frame = self._maybe_corrupt(frame, "tx")

        # 重复
        if random.random() < self._condition.duplicate_rate:
            self._stats["tx_duplicated"] += 1
            await self._deliver_tx(frame, *args, **kwargs)

        # 带宽限制
        if self._condition.bandwidth_bps > 0:
            frame_len = len(frame)
            min_interval = frame_len / self._condition.bandwidth_bps
            now = time.monotonic()
            wait = min_interval - (now - self._last_tx_time)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_tx_time = time.monotonic()

        # 延迟
        if self._condition.delay_ms > 0:
            delay = self._calc_delay()
            self._stats["tx_delayed"] += 1
            await asyncio.sleep(delay / 1000.0)

        # 断线触发
        if self._condition.disconnect_rate > 0:
            if random.random() < self._condition.disconnect_rate:
                self._trigger_disconnect()

        await self._deliver_tx(frame, *args, **kwargs)

    # ── 内部方法 ──────────────────────────────────────────────────

    def _deliver_rx(self, frame: bytes, *args, **kwargs) -> None:
        if self._original_rx:
            try:
                self._original_rx(frame, *args, **kwargs)
            except Exception as e:
                logger.error(f"RX deliver error: {e}")

    async def _deliver_tx(self, frame: bytes, *args, **kwargs) -> None:
        if self._original_tx:
            try:
                await self._original_tx(frame, *args, **kwargs)
            except Exception as e:
                logger.error(f"TX deliver error: {e}")

    def _calc_delay(self) -> float:
        """计算延迟 (ms)."""
        base = self._condition.delay_ms
        variance = self._condition.delay_variance_ms
        if variance > 0:
            return max(0, base + random.uniform(-variance, variance))
        return base

    def _maybe_corrupt(self, frame: bytes, direction: str) -> bytes:
        """可能损坏帧."""
        if self._condition.corrupt_rate <= 0:
            return frame
        if random.random() >= self._condition.corrupt_rate:
            return frame

        self._stats[f"{direction}_corrupted"] += 1

        # 翻转随机位
        frame = bytearray(frame)
        for _ in range(self._condition.corrupt_bits):
            if len(frame) < 2:
                break
            byte_idx = random.randint(2, len(frame) - 1)  # 跳过起始符和长度
            bit_idx = random.randint(0, 7)
            frame[byte_idx] ^= (1 << bit_idx)

        logger.debug(f"{direction.upper()} frame corrupted ({self._condition.corrupt_bits} bits)")
        return bytes(frame)

    def _is_disconnected(self) -> bool:
        """是否处于断线状态."""
        return time.monotonic() < self._disconnected_until

    def _trigger_disconnect(self) -> None:
        """触发断线."""
        self._disconnected_until = time.monotonic() + self._condition.disconnect_duration_s
        self._stats["disconnects"] += 1
        logger.warning(
            f"Network disconnect triggered for {self._condition.disconnect_duration_s}s"
        )

    def reset_stats(self) -> None:
        self._stats = {k: 0 for k in self._stats}
