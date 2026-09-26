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
