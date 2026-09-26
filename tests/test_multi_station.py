"""多站并发模拟测试."""

from __future__ import annotations

import pytest

from core.engine.multi_station import (
    MultiStationConfig,
    MultiStationManager,
    StationConfig,
    StationStatus,
)
from core.engine.slave import SlaveEvent


class TestStationConfig:
    """StationConfig 测试."""

    def test_default_values(self):
        """测试默认值."""
        config = StationConfig()
        assert config.station_id == ""
        assert config.station_name == ""
        assert config.host == "0.0.0.0"
        assert config.port == 2404
        assert config.common_addr == 1
        assert config.max_connections == 16
        assert config.auto_generate is True
        assert config.yx_count == 100
        assert config.yc_count == 50
        assert config.spontaneous_enabled is True
        assert config.simulation_enabled is False

    def test_custom_values(self):
        """测试自定义值."""
        config = StationConfig(
            station_id="test_station",
            station_name="测试站",
            port=2405,
            common_addr=2,
            yx_count=50,
            simulation_enabled=True,
        )
        assert config.station_id == "test_station"
        assert config.station_name == "测试站"
        assert config.port == 2405
        assert config.common_addr == 2
        assert config.yx_count == 50
        assert config.simulation_enabled is True


class TestMultiStationConfig:
    """MultiStationConfig 测试."""

    def test_empty_config(self):
        """测试空配置."""
        config = MultiStationConfig()
        assert len(config.stations) == 0

    def test_with_stations(self):
        """测试带站点的配置."""
        config = MultiStationConfig(
            stations=[
                StationConfig(station_id="s1", port=2404),
                StationConfig(station_id="s2", port=2405),
            ]
        )
        assert len(config.stations) == 2
        assert config.stations[0].station_id == "s1"
        assert config.stations[1].station_id == "s2"


class TestStationStatus:
    """StationStatus 测试."""

    def test_creation(self):
        """测试创建."""
        status = StationStatus(
            station_id="s1",
            station_name="测试站",
            port=2404,
            common_addr=1,
            running=True,
            client_count=3,
            yx_count=100,
            yc_count=50,
        )
        assert status.station_id == "s1"
        assert status.station_name == "测试站"
        assert status.running is True
        assert status.client_count == 3
        assert status.yx_count == 100


class TestMultiStationManager:
    """MultiStationManager 测试."""

    def test_init(self):
        """测试初始化."""
        config = MultiStationConfig()
        manager = MultiStationManager(config)
        assert not manager.is_running
        assert manager.station_count == 0
        assert manager.total_client_count == 0

    def test_get_engine_not_found(self):
        """测试获取不存在的引擎."""
        config = MultiStationConfig()
        manager = MultiStationManager(config)
        assert manager.get_engine("nonexistent") is None

    def test_get_station_status_not_found(self):
        """测试获取不存在的站点状态."""
        config = MultiStationConfig()
        manager = MultiStationManager(config)
        assert manager.get_station_status("nonexistent") is None

    def test_get_all_station_status_empty(self):
        """测试获取空站点状态列表."""
        config = MultiStationConfig()
        manager = MultiStationManager(config)
        assert manager.get_all_station_status() == []

    def test_get_summary_not_running(self):
        """测试获取未运行时的汇总."""
        config = MultiStationConfig()
        manager = MultiStationManager(config)
        summary = manager.get_summary()
        assert summary["running"] is False
        assert summary["station_count"] == 0
        assert summary["total_clients"] == 0

    @pytest.mark.asyncio
    async def test_start_stop_single_station(self):
        """测试启动/停止单个站点."""
        config = MultiStationConfig(
            stations=[
                StationConfig(
                    station_id="s1",
                    station_name="测试站1",
                    port=2404,
                    common_addr=1,
                    auto_generate=True,
                    yx_count=10,
                    yc_count=5,
                )
            ]
        )
        manager = MultiStationManager(config)

        # 启动
        await manager.start_all()
        assert manager.is_running
        assert manager.station_count == 1

        # 获取引擎
        engine = manager.get_engine("s1")
        assert engine is not None

        # 获取状态
        status = manager.get_station_status("s1")
        assert status is not None
        assert status.station_id == "s1"
        assert status.running is True

        # 获取汇总
        summary = manager.get_summary()
        assert summary["running"] is True
        assert summary["station_count"] == 1

        # 停止
        await manager.stop_all()
        assert not manager.is_running
        assert manager.station_count == 0

    @pytest.mark.asyncio
    async def test_start_stop_multiple_stations(self):
        """测试启动/停止多个站点."""
        config = MultiStationConfig(
            stations=[
                StationConfig(
                    station_id=f"s{i}",
                    station_name=f"测试站{i}",
                    port=2403 + i,
                    common_addr=i,
                    auto_generate=True,
                    yx_count=10,
                    yc_count=5,
                )
                for i in range(1, 4)
            ]
        )
        manager = MultiStationManager(config)

        # 启动
        await manager.start_all()
        assert manager.is_running
        assert manager.station_count == 3

        # 获取所有状态
        statuses = manager.get_all_station_status()
        assert len(statuses) == 3

        # 检查端口
        ports = {s.port for s in statuses}
        assert ports == {2404, 2405, 2406}

        # 获取汇总
        summary = manager.get_summary()
        assert summary["station_count"] == 3

        # 停止
        await manager.stop_all()
        assert not manager.is_running

    @pytest.mark.asyncio
    async def test_event_callback(self):
        """测试事件回调."""
        config = MultiStationConfig(
            stations=[
                StationConfig(
                    station_id="s1",
                    station_name="测试站1",
                    port=2404,
                    common_addr=1,
                    auto_generate=True,
                    yx_count=10,
                    yc_count=5,
                )
            ]
        )
        manager = MultiStationManager(config)

        events = []

        def on_event(event, data):
            events.append((event, data))

        manager.set_event_callback(on_event)

        # 启动
        await manager.start_all()

        # 触发事件
        engine = manager.get_engine("s1")
        engine._fire_event(SlaveEvent.STARTDT_RECEIVED, {"client_id": "test"})

        # 检查事件
        assert len(events) > 0
        assert events[0][0] == SlaveEvent.STARTDT_RECEIVED
        assert events[0][1]["station_id"] == "s1"

        # 停止
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """测试重复启动."""
        config = MultiStationConfig(
            stations=[
                StationConfig(
                    station_id="s1",
                    port=2404,
                    common_addr=1,
                    auto_generate=True,
                    yx_count=10,
                    yc_count=5,
                )
            ]
        )
        manager = MultiStationManager(config)

        await manager.start_all()
        assert manager.is_running

        # 重复启动应该不会出错
        await manager.start_all()
        assert manager.is_running

        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        """测试停止未运行的管理器."""
        config = MultiStationConfig()
        manager = MultiStationManager(config)

        # 停止未运行的管理器应该不会出错
        await manager.stop_all()
        assert not manager.is_running


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
