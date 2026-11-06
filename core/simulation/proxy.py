"""网络代理 — 在帧传输路径上注入异常.

拦截引擎的收发回调，对帧施加条件后再传递给原始处理器。
"""

from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections import deque
from collections.abc import Callable

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
        self._original_rx: Callable | None = None
        self._original_tx: Callable | None = None

        # 安装目标（卸载时精确恢复）：RX 为 (持有者, 属性名)，TX 为引擎对象
        self._engine = None
        self._rx_target: tuple[object, str] | None = None
        self._tx_target: object | None = None

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

        优先替换**传输层实际持有的回调引用**（TCP 客户端/服务端的 ``_on_frame``），
        使帧在进入引擎协议处理**之前**被拦截；只有两者都不存在时才退回替换引擎
        实例方法。引擎的 ``raw_frame_callback``（UI 观测点）不被改动——注入后的
        帧到达引擎时照常上报，被丢弃的帧不会出现在 UI。
        """
        self._engine = engine

        # 安装 TX 拦截：引擎发送统一走 self._send_frame（会话层动态读取）
        if hasattr(engine, '_send_frame'):
            self._tx_target = engine
            engine._send_frame = self.wrap_tx_callback(engine._send_frame)

        # 安装 RX 拦截：找传输层动态读取的回调引用
        owner: object | None = None
        attr = ""
        if hasattr(engine, '_client') and hasattr(engine._client, '_on_frame'):
            owner, attr = engine._client, '_on_frame'
        elif hasattr(engine, '_server') and hasattr(engine._server, '_on_frame'):
            owner, attr = engine._server, '_on_frame'
        elif hasattr(engine, '_on_frame_received'):
            owner, attr = engine, '_on_frame_received'
        if owner is not None:
            self._rx_target = (owner, attr)
            setattr(owner, attr, self.wrap_rx_callback(getattr(owner, attr)))

        logger.info(f"Network proxy installed: {self._condition.describe()}")

    def uninstall_from_engine(self, engine=None) -> None:
        """撤销安装：把 TX/RX 回调恢复为安装前对象（幂等）.

        ``remove()`` 后代理不再位于帧路径上；条件对象由管理器保留，重新
        ``install_on_engine()`` 可再次生效。
        """
        if self._tx_target is not None and self._original_tx is not None:
            try:
                self._tx_target._send_frame = self._original_tx
            except Exception as e:  # noqa: BLE001 — 卸载失败不阻断关停
                logger.warning(f"TX uninstall failed: {e}")
        if self._rx_target is not None and self._original_rx is not None:
            owner, attr = self._rx_target
            try:
                setattr(owner, attr, self._original_rx)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"RX uninstall failed: {e}")
        self._rx_target = None
        self._tx_target = None
        self._original_rx = None
        self._original_tx = None

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
            logger.debug("RX frame dropped (loss)")
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
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(
                    delay / 1000.0,
                    lambda: self._deliver_rx(frame, *args, **kwargs),
                )
            except RuntimeError:
                # 无运行中的事件循环（同步调用场景）— 降级为立即投递，不延迟
                self._deliver_rx(frame, *args, **kwargs)
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
            logger.debug("TX frame dropped (loss)")
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

        # 乱序处理
        if self._condition.reorder_rate > 0 and random.random() < self._condition.reorder_rate:
            self._reorder_buffer.append(frame)
            self._stats["tx_reordered"] += 1
            logger.debug(f"TX frame buffered for reorder ({len(self._reorder_buffer)}/{self._condition.reorder_window})")
            # 缓冲区满时，打乱顺序释放所有帧
            if len(self._reorder_buffer) >= self._condition.reorder_window:
                frames = list(self._reorder_buffer)
                random.shuffle(frames)
                self._reorder_buffer.clear()
                for f in frames:
                    await self._deliver_tx(f, *args, **kwargs)
            return

        # 非乱序帧：先刷新缓冲区中积压的帧（打乱后发送），再发送当前帧
        if self._reorder_buffer:
            frames = list(self._reorder_buffer)
            random.shuffle(frames)
            self._reorder_buffer.clear()
            for f in frames:
                await self._deliver_tx(f, *args, **kwargs)

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
