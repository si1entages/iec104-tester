"""`core/engine/scheduler.py` 单元测试.

覆盖：任务增删启停查询、调度循环（同步/异步回调、禁用跳过）、
回调异常（auto_restart 开/关）、循环级异常、start/stop 幂等、
统计与预定义任务模板。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.engine.scheduler import (
    ScheduledTask,
    TaskScheduler,
    create_counter_freeze_task,
    create_periodic_clock_sync_task,
    create_periodic_gi_task,
)


def test_scheduled_task_next_run_and_overdue(monkeypatch):
    task = ScheduledTask(name="t", interval=10.0, callback=lambda: None, last_run=100.0)
    assert task.next_run == 110.0

    # 只替换 scheduler 模块内的 time 引用（直接 patch time.monotonic 会污染
    # asyncio 等共享同一模块对象的代码）
    monkeypatch.setattr("core.engine.scheduler.time",
                        types.SimpleNamespace(monotonic=lambda: 109.9))
    assert task.overdue is False
    monkeypatch.setattr("core.engine.scheduler.time",
                        types.SimpleNamespace(monotonic=lambda: 110.0))
    assert task.overdue is True


def test_task_management_crud():
    s = TaskScheduler()
    assert s.task_count == 0

    s.add_task("a", 1.0, lambda: None, False, False, 1, x=2)
    assert s.task_count == 1
    task = s.get_task("a")
    assert task is not None
    assert task.enabled is False
    assert task.auto_restart is False
    assert task.args == (1,)
    assert task.kwargs == {"x": 2}
    assert s.get_task("missing") is None
    assert [t.name for t in s.get_all_tasks()] == ["a"]

    assert s.enable_task("a") is True
    assert s.get_task("a").enabled is True
    assert s.enable_task("missing") is False

    assert s.disable_task("a") is True
    assert s.get_task("a").enabled is False
    assert s.disable_task("missing") is False

    assert s.remove_task("a") is True
    assert s.remove_task("a") is False
    assert s.task_count == 0


def test_get_stats():
    s = TaskScheduler()
    s.add_task("a", 2.0, lambda: None)
    assert s.get_stats() == {
        "a": {
            "enabled": True,
            "interval": 2.0,
            "run_count": 0,
            "error_count": 0,
            "last_error": "",
            "last_run": 0.0,
        }
    }


async def _run_one_iteration(scheduler: TaskScheduler, monkeypatch) -> None:
    """跑调度循环一轮（用假 sleep 在首轮后置 _running=False，避免真实等待）."""
    async def fake_sleep(_seconds: float) -> None:
        scheduler._running = False

    monkeypatch.setattr("core.engine.scheduler.asyncio.sleep", fake_sleep)
    scheduler._running = True
    await scheduler._run_loop()


@pytest.mark.asyncio
async def test_run_loop_executes_sync_and_async_callbacks(monkeypatch):
    s = TaskScheduler()
    calls = []

    def sync_cb(*args, **kwargs):
        calls.append(("sync", args, kwargs))

    async def async_cb():
        calls.append(("async", (), {}))

    s.add_task("sync", 0.0, sync_cb, True, True, 1, k="v")
    s.add_task("async", 0.0, async_cb)
    s.add_task("disabled", 0.0, lambda: calls.append(("disabled", (), {})), False)

    await _run_one_iteration(s, monkeypatch)

    assert ("sync", (1,), {"k": "v"}) in calls
    assert ("async", (), {}) in calls
    assert all(c[0] != "disabled" for c in calls)
    assert s.get_task("sync").run_count == 1
    assert s.get_task("async").run_count == 1


@pytest.mark.asyncio
async def test_run_loop_error_disables_task_when_no_auto_restart(monkeypatch):
    s = TaskScheduler()

    def boom():
        raise RuntimeError("boom")

    s.add_task("boom", 0.0, boom, True, False)
    await _run_one_iteration(s, monkeypatch)

    task = s.get_task("boom")
    assert task.error_count == 1
    assert task.last_error == "boom"
    assert task.enabled is False
    assert task.run_count == 0


@pytest.mark.asyncio
async def test_run_loop_error_keeps_task_when_auto_restart(monkeypatch):
    s = TaskScheduler()

    def boom():
        raise ValueError("x")

    s.add_task("boom", 0.0, boom, True, True)
    await _run_one_iteration(s, monkeypatch)

    task = s.get_task("boom")
    assert task.error_count == 1
    assert task.enabled is True


@pytest.mark.asyncio
async def test_run_loop_swallows_loop_level_errors(monkeypatch):
    s = TaskScheduler()
    sleeps = {"n": 0}

    def bad_clock():
        raise RuntimeError("clock broken")

    async def fake_sleep(_seconds: float) -> None:
        sleeps["n"] += 1
        s._running = False

    # 同上：只替换 scheduler 模块内的 time 引用，避免破坏 asyncio 内部计时
    monkeypatch.setattr("core.engine.scheduler.time",
                        types.SimpleNamespace(monotonic=bad_clock))
    monkeypatch.setattr("core.engine.scheduler.asyncio.sleep", fake_sleep)

    s._running = True
    await s._run_loop()   # 循环级异常被吞掉，不向外抛
    assert sleeps["n"] == 1


@pytest.mark.asyncio
async def test_start_stop_idempotent():
    s = TaskScheduler()
    await s.start()
    assert s.is_running is True
    loop_task = s._loop_task
    await s.start()                     # 已在运行：不重建
    assert s._loop_task is loop_task

    await s.stop()
    assert s.is_running is False
    assert loop_task.done()

    await s.stop()                      # 幂等
    assert s.is_running is False


@pytest.mark.asyncio
async def test_task_templates_respect_engine_running_state():
    class _Engine:
        def __init__(self):
            self.is_running = True
            self.general_interrogation = AsyncMock()
            self.clock_sync = AsyncMock()
            self.counter_interrogation = AsyncMock()

    eng = _Engine()
    cases = [
        (create_periodic_gi_task, eng.general_interrogation),
        (create_periodic_clock_sync_task, eng.clock_sync),
        (create_counter_freeze_task, eng.counter_interrogation),
    ]
    for factory, method in cases:
        name, interval, callback = factory(eng, 12.0)
        assert name
        assert interval == 12.0
        await callback()
        method.assert_awaited_once()

    # 引擎未运行：模板回调不触发协议动作
    eng.is_running = False
    _, _, callback = create_periodic_gi_task(eng, 5.0)
    await callback()
    assert eng.general_interrogation.await_count == 1
