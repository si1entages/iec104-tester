"""多站并发模拟：长生命周期事件循环下的稳定性验证."""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.engine.master import MasterEngine
from core.engine.multi_station import MultiStationConfig, MultiStationManager, StationConfig


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _safe_stop(coro_factory, timeout: float = 10.0) -> None:
    try:
        await asyncio.wait_for(coro_factory(), timeout=timeout)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_multi_station_start_stop_on_shared_loop():
    """多站在同一长生命周期 loop 上启动/停止，引擎任务不悬空."""
    ports = [_free_port() for _ in range(3)]
    cfg = MultiStationConfig(stations=[
        StationConfig(
            station_id=f"st{i}",
            station_name=f"站{i}",
            port=ports[i],
            common_addr=i + 1,
            auto_generate=True,
            yx_count=10,
            yc_count=5,
            simulation_enabled=True,
            yx_interval=1.0,
            yc_interval=0.5,
        )
        for i in range(3)
    ])
    manager = MultiStationManager(cfg)

    await manager.start_all()
    try:
        assert manager.is_running
        assert manager.station_count == 3
        assert manager.total_client_count == 0

        master = MasterEngine(
            host="127.0.0.1",
            port=ports[0],
            common_addr=1,
            auto_start=True,
            auto_gi=False,
            reconnect=False,
        )
        await master.start()
        try:
            ok = await _wait_until(
                lambda: master.is_running or str(master.state).lower() == "running",
                timeout=8,
            )
            assert ok, f"cannot connect to multi-station port {ports[0]}, state={master.state}"
            ok = await _wait_until(lambda: manager.total_client_count >= 1, timeout=5)
            assert ok

            statuses = manager.get_all_station_status()
            assert len(statuses) == 3
            running = sum(1 for s in statuses if s.running)
            assert running == 3

            summary = manager.get_summary()
            assert summary.get("station_count", 0) == 3
        finally:
            await _safe_stop(master.stop, timeout=5)
    finally:
        await _safe_stop(manager.stop_all, timeout=10)
        assert not manager.is_running
        assert manager.station_count == 0


@pytest.mark.asyncio
async def test_multi_station_independent_ports():
    """不同端口独立监听，端口不冲突."""
    p1, p2 = _free_port(), _free_port()
    assert p1 != p2
    cfg = MultiStationConfig(stations=[
        StationConfig(station_id="a", port=p1, common_addr=1, auto_generate=True, yx_count=5, yc_count=2),
        StationConfig(station_id="b", port=p2, common_addr=2, auto_generate=True, yx_count=5, yc_count=2),
    ])
    manager = MultiStationManager(cfg)
    await manager.start_all()
    try:
        eng_a = manager.get_engine("a")
        eng_b = manager.get_engine("b")
        assert eng_a is not None and eng_b is not None
        assert eng_a.is_running and eng_b.is_running
        # 数据隔离
        assert eng_a.data_store is not eng_b.data_store
        assert eng_a.data_store.stats["yx_count"] == eng_b.data_store.stats["yx_count"]
    finally:
        await _safe_stop(manager.stop_all, timeout=10)


@pytest.mark.asyncio
async def test_multi_station_task_refs_hold():
    """启动后后台任务集合有引用，停止后清理."""
    port = _free_port()
    cfg = MultiStationConfig(stations=[
        StationConfig(
            station_id="s1", port=port, common_addr=1,
            auto_generate=True, yx_count=5, yc_count=2,
            simulation_enabled=True,
        )
    ])
    manager = MultiStationManager(cfg)
    await manager.start_all()
    try:
        engine = manager.get_engine("s1")
        assert engine is not None
        assert hasattr(engine, "_background_tasks")
        await asyncio.sleep(0.3)
        assert isinstance(engine._background_tasks, set)
    finally:
        await _safe_stop(manager.stop_all, timeout=10)
