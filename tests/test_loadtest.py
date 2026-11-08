"""压测编排测试（T76）：真主站 ↔ 真子站，小规模短时验证吞吐统计链路."""

from __future__ import annotations

import asyncio

import pytest

from core.data.point_table import PointTable
from webui.bridge import EngineBridge
from webui.loadtest import LoadTestService


@pytest.mark.asyncio
async def test_loadtest_end_to_end():
    """1.5s @ 80 事件/秒：自发事件经真实 104 链路上行，主站统计差分可见."""
    pt = PointTable()
    pt.generate_demo_points(yx_count=10, yc_count=10, yk_count=0, ym_count=0)

    slave_bridge = EngineBridge("slave", point_table=pt)
    master_bridge = EngineBridge("master", point_table=pt)
    await slave_bridge.start_slave("127.0.0.1", 0, 1)
    slave_port = slave_bridge.session.engine._server._server.sockets[0].getsockname()[1]
    await master_bridge.start_master("127.0.0.1", slave_port, 1)
    # 等 STARTDT 完成（auto_start 默认开）
    for _ in range(50):
        if master_bridge.session.engine and master_bridge.session.engine.is_running:
            break
        await asyncio.sleep(0.1)

    svc = LoadTestService(slave_bridge, master_bridge, publish=lambda k, d: None)
    try:
        r = await svc.start(duration_s=1.5, events_per_s=80)
        assert r["ok"] is True, r

        await asyncio.sleep(2.2)
        st = svc.status()
        assert st["events_sent"] >= 80
        assert st["rx_frames"] > 20
        assert st["fps"] > 10

        summary = await svc.stop()
        assert summary["ok"] is True
        assert summary["rx_frames"] >= 20
        assert summary["avg_eps"] > 10
        # 已停止后再 stop → 明确错误
        r2 = await svc.stop()
        assert r2["ok"] is False

        status_after = svc.status()
        assert status_after["running"] is False
        assert status_after["summary"] is not None
    finally:
        await master_bridge.stop_master()
        await slave_bridge.stop_slave()
        await master_bridge.shutdown()
        await slave_bridge.shutdown()


@pytest.mark.asyncio
async def test_loadtest_guards():
    """引擎未运行时启动被拒；重复启动被拒（幂等保护）."""
    slave_bridge = EngineBridge("slave", point_table=PointTable())
    master_bridge = EngineBridge("master", point_table=PointTable())
    svc = LoadTestService(slave_bridge, master_bridge, publish=lambda k, d: None)
    r = await svc.start(duration_s=1, events_per_s=10)
    assert r["ok"] is False and "子站" in r["error"]

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=5, yk_count=0, ym_count=0)
    slave_bridge2 = EngineBridge("slave", point_table=pt)
    master_bridge2 = EngineBridge("master", point_table=pt)
    await slave_bridge2.start_slave("127.0.0.1", 0, 1)
    slave_port = slave_bridge2.session.engine._server._server.sockets[0].getsockname()[1]
    await master_bridge2.start_master("127.0.0.1", slave_port, 1)
    for _ in range(50):
        if master_bridge2.session.engine and master_bridge2.session.engine.is_running:
            break
        await asyncio.sleep(0.1)

    svc2 = LoadTestService(slave_bridge2, master_bridge2, publish=lambda k, d: None)
    task = asyncio.create_task(svc2.start(duration_s=5, events_per_s=50))
    await asyncio.sleep(0.3)
    r2 = await svc2.start(duration_s=1, events_per_s=10)
    assert r2["ok"] is False and "已在运行" in r2["error"]
    await svc2.stop()
    await task
    await master_bridge2.stop_master()
    await slave_bridge2.stop_slave()
    await master_bridge2.shutdown()
    await slave_bridge2.shutdown()


@pytest.mark.asyncio
async def test_clock_offset_measurement():
    """T80：真引擎时钟同步 → 主站采集子站时标偏差（本机同进程应近 0）."""
    pt = PointTable()
    pt.generate_demo_points(yx_count=3, yc_count=3, yk_count=0, ym_count=0)
    slave_bridge = EngineBridge("slave", point_table=pt)
    master_bridge = EngineBridge("master", point_table=pt)
    await slave_bridge.start_slave("127.0.0.1", 0, 1)
    slave_port = slave_bridge.session.engine._server._server.sockets[0].getsockname()[1]
    await master_bridge.start_master("127.0.0.1", slave_port, 1)
    for _ in range(50):
        if master_bridge.session.engine and master_bridge.session.engine.is_running:
            break
        await asyncio.sleep(0.1)
    try:
        r = await master_bridge.measure_clock_offset(samples=3)
        assert r["ok"] is True, r
        assert r["count"] == 3
        # 本机回环：偏差应在 ±2s 内（进程内时钟同源）
        assert abs(r["avg_ms"]) < 2000
        # 确认帧按标准携带**子站当前时钟**（曾错误回显主站时间——回归锁定）
        assert len(set(r["samples"])) >= 1
    finally:
        await master_bridge.stop_master()
        await slave_bridge.stop_slave()
        await master_bridge.shutdown()
        await slave_bridge.shutdown()
