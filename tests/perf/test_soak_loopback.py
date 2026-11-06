"""主站↔子站真 TCP 环回长稳冒烟（默认 5s，可用环境变量拉长）."""

from __future__ import annotations

import asyncio
import gc
import os
import socket
import tracemalloc

import pytest

from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine

pytestmark = pytest.mark.perf

psutil = pytest.importorskip("psutil")  # 句柄统计；缺 dev 依赖时跳过而非收集失败

DEFAULT_SOAK_SECONDS = 5.0
MAX_MEMORY_GROWTH = 8 * 1024 * 1024  # 8 MB
MAX_TASK_GROWTH = 2
MAX_HANDLE_GROWTH = 2


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _handle_count() -> int:
    proc = psutil.Process()
    if hasattr(proc, "num_handles"):       # Windows
        return proc.num_handles()
    return proc.num_fds()                  # Linux/macOS


def _demo_point_table() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=50, yc_count=20, yk_count=5, ym_count=5)
    pt.common_addr = 1
    pt.station_name = "SOAK"
    return pt


async def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def test_loopback_soak_no_leak() -> None:
    """持续总召 N 秒：结束后任务/句柄/内存不得超过基线.

    默认 5s 是 CI/本地冒烟；长稳验证用
    ``IEC104_SOAK_SECONDS=7200 pytest tests/perf -m perf -k soak``。
    """
    duration = float(os.environ.get("IEC104_SOAK_SECONDS", DEFAULT_SOAK_SECONDS))
    assert duration > 0

    port = _free_port()
    points = _demo_point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                        point_table=points)
    slave.data_store.init_from_point_table(points)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)

    tasks_before = len(asyncio.all_tasks())
    handles_before = _handle_count()

    await slave.start()
    try:
        await master.start()
        ready = await _wait_until(lambda engine=master: engine.is_running)
        assert ready, f"master not running, state={master.state}"

        # 预热：让连接/缓冲/事件环达到稳态后再取内存基线
        for _ in range(10):
            await master.general_interrogation()
            await asyncio.sleep(0.05)
        gc.collect()
        tracemalloc.start()
        mem_baseline, _ = tracemalloc.get_traced_memory()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration
        gi_count = 0
        while loop.time() < deadline:
            await master.general_interrogation()
            gi_count += 1
            await asyncio.sleep(0.2)

        current, peak = tracemalloc.get_traced_memory()
        print(f"\n[perf] soak: {duration:.1f}s, {gi_count} GI, "
              f"memory +{(current - mem_baseline) / 1024 / 1024:.2f} MB "
              f"(peak {peak / 1024 / 1024:.2f} MB)")
        assert current - mem_baseline < MAX_MEMORY_GROWTH, (
            f"memory grew {(current - mem_baseline) / 1024 / 1024:.2f} MB "
            f">= {MAX_MEMORY_GROWTH / 1024 / 1024:.0f} MB"
        )
    finally:
        await master.stop()
        await slave.stop()
        tracemalloc.stop()

    # 引擎对象释放后再看任务数/句柄数
    del master, slave, points
    gc.collect()
    await asyncio.sleep(0.2)

    tasks_after = len(asyncio.all_tasks())
    handles_after = _handle_count()
    assert tasks_after <= tasks_before + MAX_TASK_GROWTH, (
        f"asyncio tasks leaked: {tasks_before} -> {tasks_after}"
    )
    assert handles_after <= handles_before + MAX_HANDLE_GROWTH, (
        f"handles leaked: {handles_before} -> {handles_after}"
    )
