"""压测编排测试（T76/T83）：真主站连接群 ↔ 真子站，吞吐差分 + 多连接."""

from __future__ import annotations

import asyncio

import pytest

from core.data.point_table import PointTable
from webui.bridge import EngineBridge
from webui.loadtest import LoadTestService


@pytest.mark.asyncio
async def test_loadtest_end_to_end():
    """1.5s @ 80 事件/秒 × 2 连接：自发事件经真实 104 链路上行，双连接统计可见."""
    pt = PointTable()
    pt.generate_demo_points(yx_count=10, yc_count=10, yk_count=0, ym_count=0)

    slave_bridge = EngineBridge("slave", point_table=pt)
    await slave_bridge.start_slave("127.0.0.1", 0, 1)
    svc = LoadTestService(slave_bridge, publish=lambda k, d: None)
    try:
        r = await svc.start(duration_s=1.5, events_per_s=80, connections=2)
        assert r["ok"] is True, r
        # 等 STARTDT × 2
        for _ in range(50):
            if all(eng.is_running for eng in svc._engines):
                break
            await asyncio.sleep(0.1)
        assert len(svc._engines) == 2

        await asyncio.sleep(2.2)
        st = svc.status()
        assert st["events_sent"] >= 80
        # 子站每次自发事件推给两条连接 → 总帧数 ≈ 事件数 × 2
        assert st["rx_frames"] > 80
        assert len(st["per_connection"]) == 2
        assert all(row["frames_received"] > 20 for row in st["per_connection"])

        summary = await svc.stop()
        assert summary["ok"] is True
        assert summary["connections"] == 2
        assert summary["rx_frames"] >= 80
        assert summary["avg_eps"] > 10
        # 停止后连接全部拆除
        assert svc._engines == []
        assert slave_bridge.session.engine.client_count == 0

        status_after = svc.status()
        assert status_after["running"] is False
        assert status_after["summary"] is not None
    finally:
        await slave_bridge.stop_slave()
        await slave_bridge.shutdown()


@pytest.mark.asyncio
async def test_loadtest_guards():
    """子站未运行时启动被拒；重复启动被拒（幂等保护）."""
    slave_bridge = EngineBridge("slave", point_table=PointTable())
    svc = LoadTestService(slave_bridge, publish=lambda k, d: None)
    r = await svc.start(duration_s=1, events_per_s=10)
    assert r["ok"] is False and "子站" in r["error"]

    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=5, yk_count=0, ym_count=0)
    slave_bridge2 = EngineBridge("slave", point_table=pt)
    await slave_bridge2.start_slave("127.0.0.1", 0, 1)
    svc2 = LoadTestService(slave_bridge2, publish=lambda k, d: None)
    task = asyncio.create_task(svc2.start(duration_s=5, events_per_s=50))
    await asyncio.sleep(0.3)
    r2 = await svc2.start(duration_s=1, events_per_s=10)
    assert r2["ok"] is False and "已在运行" in r2["error"]
    await svc2.stop()
    await task
    await slave_bridge2.shutdown()
