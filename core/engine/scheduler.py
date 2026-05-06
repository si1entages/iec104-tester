"""定时任务调度器 — 周期上送、电度冻结、定期总召.

提供:
- 周期性数据上送 (循环遥测/遥信)
- 电度定时冻结
- 周期总召
- 自定义定时任务
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger("iec104.scheduler")


@dataclass
class ScheduledTask:
    """定时任务定义."""
    name: str
    interval: float                 # 执行间隔（秒）
    callback: Callable              # 异步回调函数
    enabled: bool = True
    auto_restart: bool = True       # 执行异常后是否自动重启
    last_run: float = 0.0
    last_error: str = ""
    run_count: int = 0
    error_count: int = 0
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)

    @property
    def next_run(self) -> float:
        return self.last_run + self.interval

    @property
    def overdue(self) -> bool:
        return time.monotonic() >= self.next_run


class TaskScheduler:
    """定时任务调度器.

    基于 asyncio 的轻量级调度器，支持:
    - 多任务并发执行
    - 可配置执行间隔
    - 错误统计与自动重启
    - 运行时动态添加/删除/启用/禁用任务
    """

    def __init__(self):
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    # ── 任务管理 ──────────────────────────────────────────────────

    def add_task(
        self,
        name: str,
        interval: float,
        callback: Callable,
        enabled: bool = True,
        auto_restart: bool = True,
        *args,
        **kwargs,
    ) -> None:
        """添加定时任务."""
        self._tasks[name] = ScheduledTask(
            name=name,
            interval=interval,
            callback=callback,
            enabled=enabled,
            auto_restart=auto_restart,
            args=args,
            kwargs=kwargs,
        )
        logger.info(f"Task added: {name} (interval={interval}s)")

    def remove_task(self, name: str) -> bool:
        """移除定时任务."""
        if name in self._tasks:
            del self._tasks[name]
            logger.info(f"Task removed: {name}")
            return True
        return False

    def enable_task(self, name: str) -> bool:
        """启用任务."""
        task = self._tasks.get(name)
        if task:
            task.enabled = True
            return True
        return False

    def disable_task(self, name: str) -> bool:
        """禁用任务."""
        task = self._tasks.get(name)
        if task:
            task.enabled = False
            return True
        return False

    def get_task(self, name: str) -> Optional[ScheduledTask]:
        return self._tasks.get(name)

    def get_all_tasks(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    # ── 调度控制 ──────────────────────────────────────────────────

    async def start(self) -> None:
        """启动调度器."""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info(f"Scheduler started with {len(self._tasks)} tasks")

    async def stop(self) -> None:
        """停止调度器."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("Scheduler stopped")

    async def _run_loop(self) -> None:
        """主调度循环."""
        while self._running:
            try:
                now = time.monotonic()

                for task in self._tasks.values():
                    if not task.enabled:
                        continue

                    if now >= task.next_run:
                        try:
                            if asyncio.iscoroutinefunction(task.callback):
                                await task.callback(*task.args, **task.kwargs)
                            else:
                                task.callback(*task.args, **task.kwargs)

                            task.last_run = now
                            task.run_count += 1

                        except Exception as e:
                            task.error_count += 1
                            task.last_error = str(e)
                            logger.error(f"Task '{task.name}' error: {e}")

                            if not task.auto_restart:
                                task.enabled = False
                                logger.warning(f"Task '{task.name}' disabled due to error")

                await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}")
                await asyncio.sleep(1)

    def get_stats(self) -> dict[str, dict]:
        """获取所有任务统计."""
        return {
            name: {
                "enabled": t.enabled,
                "interval": t.interval,
                "run_count": t.run_count,
                "error_count": t.error_count,
                "last_error": t.last_error,
                "last_run": t.last_run,
            }
            for name, t in self._tasks.items()
        }


# ═══════════════════════════════════════════════════════════════════
#  预定义调度任务模板
# ═══════════════════════════════════════════════════════════════════

def create_periodic_gi_task(
    engine,
    interval: float = 300.0,
) -> tuple[str, float, Callable]:
    """创建周期总召任务.

    Args:
        engine: MasterEngine 实例
        interval: 周期间隔（秒），默认5分钟
    """
    async def periodic_gi():
        if engine.is_running:
            await engine.general_interrogation()

    return ("periodic_gi", interval, periodic_gi)


def create_periodic_clock_sync_task(
    engine,
    interval: float = 600.0,
) -> tuple[str, float, Callable]:
    """创建周期时钟同步任务.

    Args:
        engine: MasterEngine 实例
        interval: 周期间隔（秒），默认10分钟
    """
    async def periodic_clock_sync():
        if engine.is_running:
            await engine.clock_sync()

    return ("periodic_clock_sync", interval, periodic_clock_sync)


def create_counter_freeze_task(
    engine,
    interval: float = 3600.0,
) -> tuple[str, float, Callable]:
    """创建电度冻结任务.

    Args:
        engine: MasterEngine 实例
        interval: 冻结周期（秒），默认1小时
    """
    async def counter_freeze():
        if engine.is_running:
            await engine.counter_interrogation()

    return ("counter_freeze", interval, counter_freeze)
