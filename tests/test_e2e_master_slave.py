"""真 TCP 端到端联调：MasterEngine ↔ SlaveEngine.

在同一进程内启动子站与主站，验证:
- TCP 连接建立
- STARTDT / 数据传输
- 总召唤往返
- 自发上送
- 响应行为配置生效
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import PointTable
from core.engine.master import MasterEngine, MasterEvent
from core.engine.slave import SlaveEngine, SlaveEvent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_point_table() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=20, yc_count=10, yk_count=5, ym_count=5)
    pt.common_addr = 1
    pt.station_name = "E2E"
    return pt


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _wait_master_ready(master: MasterEngine, timeout: float = 8.0) -> bool:
    return await _wait_until(
        lambda: master.is_running or str(master.state).lower() == "running",
        timeout=timeout,
    )


@pytest.mark.asyncio
async def test_master_slave_connect_and_gi():
    """真连接：连接 + 总召唤收到数据."""
    port = _free_port()
    points = _demo_point_table()

    slave = SlaveEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        point_table=points,
    )
    slave.data_store.init_from_point_table(points)

    master_events: list[tuple[MasterEvent, dict]] = []
    slave_events: list[tuple[SlaveEvent, dict]] = []

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )
    master.set_event_callback(lambda e, d: master_events.append((e, d)))
    slave.set_event_callback(lambda e, d: slave_events.append((e, d)))

    await slave.start()
    try:
        await master.start()
        try:
            # 等待进入数据传输状态
            ok = await _wait_master_ready(master, timeout=8)
            assert ok, f"master not running, state={master.state}"

            # 等待至少一个客户端连上子站
            ok = await _wait_until(lambda: slave.client_count > 0, timeout=5)
            assert ok, "slave got no clients"

            # 总召唤
            await master.general_interrogation()
            ok = await _wait_until(
                lambda: (
                    master.data_store.stats.get("yx_count", 0) > 0
                    or master.data_store.stats.get("yc_count", 0) > 0
                ),
                timeout=8,
            )
            stats = master.data_store.stats
            assert ok and (stats.get("yx_count", 0) > 0 or stats.get("yc_count", 0) > 0), (
                f"GI produced no data: stats={stats}, events={[e.value for e,_ in master_events]}"
            )

            # 子站应收到过 GI
            assert any(e == SlaveEvent.GI_RECEIVED for e, _ in slave_events), (
                f"slave events={[e.value for e,_ in slave_events]}"
            )
        finally:
            try:
                await asyncio.wait_for(master.stop(), timeout=5)
            except Exception:
                pass
    finally:
        try:
            await asyncio.wait_for(slave.stop(), timeout=5)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_spontaneous_yx_reaches_master():
    """子站自发上送到主站."""
    port = _free_port()
    points = _demo_point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_master_ready(master, timeout=8)
            assert ok

            ioa = 1
            original = None
            yx = master.data_store.get_yx(ioa)
            if yx:
                original = yx.value

            await slave.send_spontaneous_yx(ioa, not original if original is not None else True)
            ok = await _wait_until(
                lambda: (
                    (m := master.data_store.get_yx(ioa)) is not None
                    and m.value != original
                ),
                timeout=8,
            )
            assert ok, "spontaneous YX did not update master data store"
        finally:
            try:
                await asyncio.wait_for(master.stop(), timeout=5)
            except Exception:
                pass
    finally:
        try:
            await asyncio.wait_for(slave.stop(), timeout=5)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_response_behavior_no_response_blocks_gi():
    """配置 no_response 后，主站总召唤拿不到数据."""
    port = _free_port()
    points = _demo_point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave.set_response_behavior({"errors": {"no_response": True}})

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_master_ready(master, timeout=8)
            assert ok

            # 清空主站数据后发 GI
            before = master.data_store.stats.get("yx_count", 0)
            await master.general_interrogation()
            await asyncio.sleep(1.0)
            after = master.data_store.stats.get("yx_count", 0)
            # no_response 应阻止数据上送（允许已有的连接初始化数据）
            assert after <= before + 1
        finally:
            try:
                await asyncio.wait_for(master.stop(), timeout=5)
            except Exception:
                pass
    finally:
        try:
            await asyncio.wait_for(slave.stop(), timeout=5)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_response_behavior_gi_delay():
    """GI 延迟配置应拉长响应时间."""
    port = _free_port()
    points = PointTable()
    points.generate_demo_points(yx_count=5, yc_count=2)
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave.set_response_behavior({"delays": {"gi": 0.8}})

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_master_ready(master, timeout=8)
            assert ok
            t0 = asyncio.get_event_loop().time()
            await master.general_interrogation()
            ok = await _wait_until(
                lambda: master.data_store.stats.get("yx_count", 0) > 0,
                timeout=8,
            )
            elapsed = asyncio.get_event_loop().time() - t0
            assert ok
            assert elapsed >= 0.7, f"GI delay not applied, elapsed={elapsed:.3f}s"
        finally:
            try:
                await asyncio.wait_for(master.stop(), timeout=5)
            except Exception:
                pass
    finally:
        try:
            await asyncio.wait_for(slave.stop(), timeout=5)
        except Exception:
            pass
