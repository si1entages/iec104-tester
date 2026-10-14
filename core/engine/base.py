"""引擎基类 — 主站/子站共用功能."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("iec104.engine.base")


class EngineBase:
    """引擎基类，提供主站和子站共用的通用方法."""

    def __init__(self):
        # 后台任务引用，防止被 GC 回收
        self._background_tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> asyncio.Task | None:
        """安全创建后台任务：保留引用并记录异常.

        将协程包装为 asyncio.Task 并注册到 _background_tasks 集合中，
        防止任务被垃圾回收。异常会被自动记录到日志。
        """
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            # 无运行中的事件循环（如同步测试环境）
            coro.close()
            return None
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        def _log_exc(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("Background task failed: %s", exc, exc_info=exc)

        task.add_done_callback(_log_exc)
        return task

    async def aclose_background_tasks(self, timeout: float = 2.0) -> int:
        """取消并回收全部后台任务（关停加固）.

        引擎 ``stop()`` 只取消其**已知的长驻任务**（定时器 / 模拟 / 轮询 /
        周期总召等）；其余经 ``_spawn()`` 派发的**短驻任务**（如逐帧发送、
        一次性应答）在关停瞬间可能仍处于 pending。若随后事件循环关闭，
        这些任务会触发 "Task was destroyed but it is pending!"，并可能
        泄漏引用/句柄。

        本方法取消 ``_background_tasks`` 中所有未完成任务，并以 ``timeout``
        **有界**等待其结束，最后清空集合。幂等，可重复调用。

        Returns:
            本次被取消的任务数量。
        """
        pending = [t for t in list(self._background_tasks) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            try:
                await asyncio.wait(pending, timeout=timeout)
            except Exception:  # noqa: BLE001 — 关停阶段不允许抛出
                pass
        # 无论是否等待完成，都清空引用；未完成者已被取消，循环关闭时不会告警
        self._background_tasks.clear()
        return len(pending)
