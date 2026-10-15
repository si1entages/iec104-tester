"""run_multi_station.py 信号处理跨平台守卫测试（Windows 回退路径）.

背景：``loop.add_signal_handler`` 是 Unix-only API；Windows（ProactorEventLoop）
上抛 ``NotImplementedError``，曾使 CLI 多站脚本在主平台直接崩溃（M5 打包冒烟发现）。

修复：``install_signal_handlers()`` 捕获 NotImplementedError 后回退到
``signal.signal`` + ``loop.call_soon_threadsafe``——Ctrl+C 置位 stop_event，
优雅停止语义与 Unix 一致。本文件用**假事件循环**分别驱动两条平台路径，
不依赖真实信号。
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_multi_station  # noqa: E402

_SIGS = (signal.SIGINT, signal.SIGTERM)


class _UnixLikeLoop:
    """模拟支持 add_signal_handler 的事件循环（Unix 真实行为）."""

    def __init__(self):
        self.installed: list[tuple[int, object]] = []

    def add_signal_handler(self, sig, callback):
        self.installed.append((sig, callback))


class _WindowsLikeLoop:
    """模拟 ProactorEventLoop：add_signal_handler 未实现；线程安全投递委托真实循环."""

    def __init__(self):
        self._real = asyncio.new_event_loop()

    def add_signal_handler(self, sig, callback):
        raise NotImplementedError

    def call_soon_threadsafe(self, callback, *args):
        return self._real.call_soon_threadsafe(callback, *args)

    def run_until_stop(self, stop: asyncio.Event, timeout: float = 2.0):
        try:
            self._real.run_until_complete(asyncio.wait_for(stop.wait(), timeout=timeout))
        finally:
            self._real.close()


def _with_restored_handlers(fn):
    """临时替换 SIGINT/SIGTERM 处理器，测试后恢复（避免污染 pytest 进程）."""
    saved = {sig: signal.getsignal(sig) for sig in _SIGS}
    try:
        return fn()
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def test_unix_platform_uses_loop_api():
    """支持 add_signal_handler 的平台：走 loop API，注册 SIGINT+SIGTERM."""

    def run():
        loop = _UnixLikeLoop()
        stop = asyncio.Event()
        mode = run_multi_station.install_signal_handlers(loop, stop)
        assert mode == "loop"
        assert [sig for sig, _ in loop.installed] == list(_SIGS)
        # 回调即 request_stop：调用后 stop_event 置位
        loop.installed[0][1]()
        assert stop.is_set()

    _with_restored_handlers(run)


def test_windows_fallback_registers_signal_handlers():
    """Windows 平台（add_signal_handler 抛 NotImplementedError）：回退 signal.signal."""

    def run():
        loop = _WindowsLikeLoop()
        stop = asyncio.Event()
        mode = run_multi_station.install_signal_handlers(loop, stop)
        assert mode == "signal"
        # 两个信号都已注册自定义处理器（非 SIG_DFL/None）
        for sig in _SIGS:
            assert signal.getsignal(sig) not in (signal.SIG_DFL, None)

    _with_restored_handlers(run)


def test_fallback_handler_sets_stop_event_threadsafe():
    """回退处理器被触发（模拟 Ctrl+C 到达）→ call_soon_threadsafe 置位 stop_event."""

    def run():
        loop = _WindowsLikeLoop()
        stop = asyncio.Event()
        run_multi_station.install_signal_handlers(loop, stop)

        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)

        # 与真实场景一致：信号处理器在线程中被调用，经 call_soon_threadsafe
        # 投递到事件循环内执行 → stop_event 置位 → 优雅停止
        handler(signal.SIGINT, None)
        loop.run_until_stop(stop)

    _with_restored_handlers(run)
