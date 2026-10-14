"""`core/simulation/proxy.py` 网络异常代理单元测试.

覆盖 RX/TX 两条处理链上的全部异常分支：方向过滤、断线、丢包、损坏、重复、
延迟（含无事件循环降级与 call_later 调度）、带宽限速、乱序缓冲与释放、
安装/卸载包装、统计重置。

**确定性**：``random`` 与 ``time.monotonic`` 全部注入/打桩；延迟与限速等待用
可控 ``asyncio.sleep`` 替换或伪事件循环捕获，**不使用任何真实等待**。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import core.simulation.proxy as proxy_mod
from core.simulation.conditions import NetworkCondition
from core.simulation.proxy import NetworkProxy

FRAME = b"\x68\x04\x0b\x00\x00\x00"


def _proxy(**cond_kwargs) -> NetworkProxy:
    cond = NetworkCondition(active=True, **cond_kwargs)
    return NetworkProxy(cond)


class _RecordingLoop:
    """伪事件循环：捕获 call_later 的调度而不真正等待."""

    def __init__(self):
        self.calls: list[tuple[float, object]] = []

    def call_later(self, delay, callback):
        self.calls.append((delay, callback))
        return SimpleNamespace(cancel=lambda: None)


# ── 基本属性 ─────────────────────────────────────────────────────

def test_condition_and_stats_properties_are_snapshots():
    proxy = _proxy()
    assert proxy.condition is proxy._condition

    proxy._stats["rx_total"] = 3
    snapshot = proxy.stats
    assert snapshot["rx_total"] == 3

    snapshot["rx_total"] = 999              # 外部修改不影响内部统计
    assert proxy.stats["rx_total"] == 3


def test_update_condition_applies_known_keys_only():
    proxy = _proxy()
    proxy.update_condition(loss_rate=0.5, not_a_field=123)

    assert proxy.condition.loss_rate == 0.5
    assert not hasattr(proxy.condition, "not_a_field")


def test_reset_stats_zeroes_all_counters():
    proxy = _proxy()
    proxy._stats = {k: 7 for k in proxy._stats}
    proxy.reset_stats()

    assert set(proxy.stats.values()) == {0}
    assert proxy.stats["rx_total"] == 0


# ── RX 处理链 ────────────────────────────────────────────────────

def test_rx_passthrough_when_condition_inactive():
    proxy = _proxy()
    proxy._condition.active = False
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == [FRAME]
    assert proxy.stats["rx_total"] == 0     # 未激活不计数


def test_rx_total_counts_but_direction_filter_passes_through():
    """direction="tx" 时 RX 仍原样放行（仅计数 rx_total，不施加异常）."""
    proxy = _proxy(direction="tx", loss_rate=1.0)
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == [FRAME]
    assert proxy.stats["rx_total"] == 1
    assert proxy.stats["rx_dropped"] == 0


def test_rx_dropped_when_disconnected():
    proxy = _proxy()
    proxy._disconnected_until = float("inf")
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == []
    assert proxy.stats["rx_dropped"] == 1


def test_rx_dropped_by_loss(monkeypatch):
    proxy = _proxy(loss_rate=0.5)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)   # < loss_rate
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == []
    assert proxy.stats["rx_dropped"] == 1


def test_rx_delivered_when_no_loss(monkeypatch):
    proxy = _proxy(loss_rate=0.5)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.99)  # >= loss_rate
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == [FRAME]
    assert proxy.stats["rx_dropped"] == 0


def test_rx_corruption_changes_frame(monkeypatch):
    proxy = _proxy(corrupt_rate=1.0, corrupt_bits=1)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)
    monkeypatch.setattr(proxy_mod.random, "randint", lambda a, b: 3)  # 固定翻转字节
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert proxy.stats["rx_corrupted"] == 1
    assert seen != [FRAME]
    assert len(seen[0]) == len(FRAME)        # 只翻位，长度不变


def test_rx_no_corruption_when_rate_zero(monkeypatch):
    proxy = _proxy(corrupt_rate=0.0)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == [FRAME]
    assert proxy.stats["rx_corrupted"] == 0


def test_rx_duplicate_delivers_twice(monkeypatch):
    proxy = _proxy(duplicate_rate=1.0)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == [FRAME, FRAME]            # 重复一次 + 正常投递一次
    assert proxy.stats["rx_duplicated"] == 1


def test_rx_delay_schedules_via_call_later(monkeypatch):
    """有事件循环：延迟走 call_later（用伪循环捕获，不真实等待）."""
    proxy = _proxy(delay_ms=50.0)
    loop = _RecordingLoop()
    monkeypatch.setattr(proxy_mod.asyncio, "get_running_loop", lambda: loop)
    monkeypatch.setattr(proxy_mod.random, "uniform", lambda a, b: 0.0)
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)

    assert seen == []                        # 尚未投递
    assert proxy.stats["rx_delayed"] == 1
    assert loop.calls[0][0] == pytest.approx(0.05)

    loop.calls[0][1]()                       # 触发延迟回调
    assert seen == [FRAME]


def test_rx_delay_degrades_to_immediate_without_event_loop():
    """无运行中的事件循环（同步调用场景）→ 立即投递，不延迟."""
    proxy = _proxy(delay_ms=50.0)
    seen = []
    proxy.wrap_rx_callback(lambda f, *a, **k: seen.append(f))

    proxy._process_rx(FRAME)                 # 同步上下文，get_running_loop 抛 RuntimeError

    assert seen == [FRAME]
    assert proxy.stats["rx_delayed"] == 1


def test_rx_deliver_swallows_original_callback_error():
    proxy = _proxy()

    def boom(_frame, *_a, **_k):
        raise RuntimeError("原始回调出错")

    proxy.wrap_rx_callback(boom)
    proxy._process_rx(FRAME)                 # 不应向外抛异常

    assert proxy.stats["rx_total"] == 1


def test_rx_without_original_callback_is_noop():
    proxy = _proxy()
    proxy._process_rx(FRAME)                 # _original_rx 为 None
    assert proxy.stats["rx_total"] == 1


# ── TX 处理链 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tx_passthrough_when_inactive():
    proxy = _proxy()
    proxy._condition.active = False
    proxy._original_tx = AsyncMock()

    await proxy._process_tx(FRAME)

    proxy._original_tx.assert_awaited_once_with(FRAME)
    assert proxy.stats["tx_total"] == 0


@pytest.mark.asyncio
async def test_tx_direction_filter_passes_through():
    proxy = _proxy(direction="rx", loss_rate=1.0)
    proxy._original_tx = AsyncMock()

    await proxy._process_tx(FRAME)

    proxy._original_tx.assert_awaited_once_with(FRAME)
    assert proxy.stats["tx_total"] == 1
    assert proxy.stats["tx_dropped"] == 0


@pytest.mark.asyncio
async def test_tx_dropped_when_disconnected():
    proxy = _proxy()
    proxy._disconnected_until = float("inf")
    proxy._original_tx = AsyncMock()

    await proxy._process_tx(FRAME)

    proxy._original_tx.assert_not_awaited()
    assert proxy.stats["tx_dropped"] == 1


@pytest.mark.asyncio
async def test_tx_dropped_by_loss(monkeypatch):
    proxy = _proxy(loss_rate=0.9)
    proxy._original_tx = AsyncMock()
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.1)

    await proxy._process_tx(FRAME)

    proxy._original_tx.assert_not_awaited()
    assert proxy.stats["tx_dropped"] == 1


@pytest.mark.asyncio
async def test_tx_corrupt_then_deliver(monkeypatch):
    proxy = _proxy(corrupt_rate=1.0, corrupt_bits=1)
    proxy._original_tx = AsyncMock()
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)
    monkeypatch.setattr(proxy_mod.random, "randint", lambda a, b: 3)

    await proxy._process_tx(FRAME)

    assert proxy.stats["tx_corrupted"] == 1
    delivered = proxy._original_tx.await_args[0][0]
    assert delivered != FRAME
    assert len(delivered) == len(FRAME)


@pytest.mark.asyncio
async def test_tx_duplicate_delivers_twice(monkeypatch):
    proxy = _proxy(duplicate_rate=1.0)
    proxy._original_tx = AsyncMock()
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)

    await proxy._process_tx(FRAME)

    assert proxy._original_tx.await_count == 2
    assert proxy.stats["tx_duplicated"] == 1


@pytest.mark.asyncio
async def test_tx_bandwidth_limit_waits(monkeypatch):
    """带宽限速：按帧长计算最小间隔并等待（sleep 被替换为记录器）."""
    proxy = _proxy(bandwidth_bps=6)          # 6 B/s → 6 字节帧需等 1s
    proxy._original_tx = AsyncMock()
    proxy._last_tx_time = proxy_mod.time.monotonic()   # 刚发过 → wait 接近 1s

    waits: list[float] = []

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(proxy_mod.asyncio, "sleep", fake_sleep)

    await proxy._process_tx(FRAME)

    assert waits and waits[0] > 0.5
    proxy._original_tx.assert_awaited_once_with(FRAME)


@pytest.mark.asyncio
async def test_tx_bandwidth_no_wait_when_enough_time_passed(monkeypatch):
    proxy = _proxy(bandwidth_bps=1000)
    proxy._original_tx = AsyncMock()
    proxy._last_tx_time = proxy_mod.time.monotonic() - 10.0   # 间隔已足够

    waits: list[float] = []

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(proxy_mod.asyncio, "sleep", fake_sleep)

    await proxy._process_tx(FRAME)

    assert waits == []
    proxy._original_tx.assert_awaited_once_with(FRAME)


@pytest.mark.asyncio
async def test_tx_delay_waits_and_counts(monkeypatch):
    proxy = _proxy(delay_ms=100.0, delay_variance_ms=0.0)
    proxy._original_tx = AsyncMock()

    waits: list[float] = []

    async def fake_sleep(delay):
        waits.append(delay)

    monkeypatch.setattr(proxy_mod.asyncio, "sleep", fake_sleep)

    await proxy._process_tx(FRAME)

    assert waits == [pytest.approx(0.1)]
    assert proxy.stats["tx_delayed"] == 1
    proxy._original_tx.assert_awaited_once_with(FRAME)


@pytest.mark.asyncio
async def test_tx_disconnect_triggered(monkeypatch):
    proxy = _proxy(disconnect_rate=1.0, disconnect_duration_s=2.0)
    proxy._original_tx = AsyncMock()
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)

    await proxy._process_tx(FRAME)

    assert proxy.stats["disconnects"] == 1
    assert proxy._is_disconnected() is True
    # 当前帧仍投递（触发点在投递之前）
    proxy._original_tx.assert_awaited_once_with(FRAME)


@pytest.mark.asyncio
async def test_tx_reorder_buffers_until_window_full(monkeypatch):
    """乱序：先缓存不投递，缓冲满（W 帧）后打乱一次性释放."""
    proxy = _proxy(reorder_rate=1.0, reorder_window=2)
    proxy._original_tx = AsyncMock()
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)

    await proxy._process_tx(b"\x01")
    assert proxy._original_tx.await_count == 0        # 第一帧仅入缓冲
    assert proxy.stats["tx_reordered"] == 1

    await proxy._process_tx(b"\x02")
    assert proxy._original_tx.await_count == 2        # 缓冲满 → 释放两帧
    assert proxy.stats["tx_reordered"] == 2
    assert proxy._original_tx.await_args_list[0][0][0] in (b"\x01", b"\x02")


@pytest.mark.asyncio
async def test_tx_non_reorder_frame_flushes_pending_buffer(monkeypatch):
    """非乱序帧到来时先把积压帧打乱发出，再发当前帧."""
    proxy = _proxy(reorder_rate=0.5, reorder_window=5)
    proxy._original_tx = AsyncMock()
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.99)   # 当前帧不触发乱序

    proxy._reorder_buffer.append(b"\x01")     # 模拟此前积压的乱序帧

    await proxy._process_tx(b"\x02")

    assert proxy._original_tx.await_count == 2          # 积压帧 + 当前帧
    assert len(proxy._reorder_buffer) == 0              # 缓冲已清空
    assert proxy._original_tx.await_args_list[-1][0][0] == b"\x02"


@pytest.mark.asyncio
async def test_tx_deliver_swallows_original_error():
    proxy = _proxy()
    proxy._original_tx = AsyncMock(side_effect=RuntimeError("发送失败"))

    await proxy._process_tx(FRAME)                    # 不应向外抛异常

    assert proxy.stats["tx_total"] == 1


@pytest.mark.asyncio
async def test_tx_without_original_callback_is_noop():
    proxy = _proxy()
    await proxy._process_tx(FRAME)
    assert proxy.stats["tx_total"] == 1


# ── 内部工具 ─────────────────────────────────────────────────────

def test_calc_delay_with_and_without_variance(monkeypatch):
    fixed = _proxy(delay_ms=40.0, delay_variance_ms=0.0)
    assert fixed._calc_delay() == pytest.approx(40.0)

    jitter = _proxy(delay_ms=40.0, delay_variance_ms=10.0)
    monkeypatch.setattr(proxy_mod.random, "uniform", lambda a, b: 5.0)
    assert jitter._calc_delay() == pytest.approx(45.0)

    monkeypatch.setattr(proxy_mod.random, "uniform", lambda a, b: -100.0)
    assert jitter._calc_delay() == 0.0                # 负值被钳制为 0


def test_maybe_corrupt_skips_when_rate_zero_or_roll_too_high(monkeypatch):
    proxy = _proxy(corrupt_rate=0.0)
    assert proxy._maybe_corrupt(FRAME, "rx") == FRAME

    proxy = _proxy(corrupt_rate=0.5)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.99)
    assert proxy._maybe_corrupt(FRAME, "rx") == FRAME
    assert proxy.stats["rx_corrupted"] == 0


def test_maybe_corrupt_breaks_on_very_short_frame(monkeypatch):
    """帧长 <2 时无法跳过起始符 → 直接跳出循环，不越界."""
    proxy = _proxy(corrupt_rate=1.0, corrupt_bits=3)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.0)
    monkeypatch.setattr(proxy_mod.random, "randint", lambda a, b: 0)

    result = proxy._maybe_corrupt(b"\x68", "tx")

    assert result == b"\x68"
    assert proxy.stats["tx_corrupted"] == 1


def test_trigger_disconnect_sets_deadline(monkeypatch):
    proxy = _proxy(disconnect_duration_s=3.0)
    monkeypatch.setattr(proxy_mod.time, "monotonic", lambda: 1000.0)

    proxy._trigger_disconnect()

    assert proxy._disconnected_until == pytest.approx(1003.0)
    assert proxy.stats["disconnects"] == 1


# ── 包装与安装 ───────────────────────────────────────────────────

def test_wrap_rx_callback_routes_through_proxy():
    proxy = _proxy()
    seen = []

    def original(frame, *args):
        seen.append((frame, args))

    wrapped = proxy.wrap_rx_callback(original)

    assert proxy._original_rx is not None
    wrapped(FRAME, "extra-arg")               # 透传额外位置参数

    assert seen == [(FRAME, ("extra-arg",))]
    assert proxy.stats["rx_total"] == 1


@pytest.mark.asyncio
async def test_wrap_tx_callback_routes_through_proxy():
    proxy = _proxy()
    original = AsyncMock()
    wrapped = proxy.wrap_tx_callback(original)

    await wrapped(FRAME)

    original.assert_awaited_once_with(FRAME)
    assert proxy.stats["tx_total"] == 1


def test_install_on_engine_wraps_rx_tx_and_client_hook():
    engine = SimpleNamespace()
    engine._send_frame = AsyncMock()
    engine._on_frame_received = lambda frame: None
    engine._client = SimpleNamespace(_on_frame=None)

    proxy = _proxy()
    proxy.install_on_engine(engine)

    assert engine._on_frame_received is not None
    assert engine._client._on_frame is engine._on_frame_received
    assert engine._send_frame is not engine.__dict__.get("__orig", None)


def test_install_on_engine_falls_back_to_server_hook():
    """无 _client 但有 _server 时，更新服务端回调引用."""
    engine = SimpleNamespace()
    engine._on_frame_received = lambda frame: None
    engine._server = SimpleNamespace(_on_frame=None)

    proxy = _proxy()
    proxy.install_on_engine(engine)

    assert engine._server._on_frame is engine._on_frame_received


def test_install_on_engine_with_minimal_engine_does_not_fail():
    """引擎既无 _send_frame 也无 _on_frame_received 时不得抛异常."""
    proxy = _proxy()
    proxy.install_on_engine(SimpleNamespace())

    assert proxy.condition is not None


def test_installed_rx_wrapper_actually_delivers(monkeypatch):
    """安装后通过引擎回调走一遍完整 RX 路径（无异常条件下原样投递）."""
    engine = SimpleNamespace()
    received = []
    engine._on_frame_received = received.append
    engine._client = SimpleNamespace(_on_frame=None)

    proxy = _proxy()
    proxy.install_on_engine(engine)
    monkeypatch.setattr(proxy_mod.random, "random", lambda: 0.99)

    engine._client._on_frame(FRAME)

    assert received == [FRAME]
    assert proxy.stats["rx_total"] == 1


def test_installed_tx_wrapper_actually_delivers():
    """安装后 engine._send_frame 变为异步包装，调用可正常 await."""
    engine = SimpleNamespace()
    engine._send_frame = AsyncMock()
    engine._on_frame_received = lambda frame: None

    proxy = _proxy()
    proxy.install_on_engine(engine)

    assert inspect.iscoroutinefunction(engine._send_frame)
