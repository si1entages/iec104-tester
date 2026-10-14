"""多站并发模拟管理器.

支持在同一进程中运行多个独立的子站引擎实例，每个实例监听不同端口，
拥有独立的点表和数据存储，用于主站系统压力测试和验收测试。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import FlowControlConfig, TimerConfig
from ..data.point_table import PointTable
from .slave import SlaveEngine, SlaveEvent

logger = logging.getLogger("iec104.multi_station")


@dataclass
class StationConfig:
    """单个子站配置."""
    station_id: str = ""                    # 站唯一标识
    station_name: str = ""                  # 站名称
    host: str = "0.0.0.0"                   # 监听地址
    port: int = 2404                        # 监听端口
    common_addr: int = 1                    # 公共地址
    max_connections: int = 16               # 最大连接数
    point_table_file: str = ""              # 点表文件路径
    auto_generate: bool = True              # 自动生成演示点表
    yx_count: int = 100                     # 自动生成的遥信数量
    yc_count: int = 50                      # 自动生成的遥测数量
    yk_count: int = 20                      # 自动生成的遥控数量
    ym_count: int = 10                      # 自动生成的遥脉数量
    spontaneous_enabled: bool = True        # 是否启用自发上送
    simulation_enabled: bool = False        # 是否启用自动模拟
    yx_interval: float = 5.0               # 遥信变化间隔(秒)
    yc_interval: float = 2.0               # 遥测变化间隔(秒)
    yx_change_rate: float = 0.1            # 遥信变化概率
    yc_change_range: float = 0.05          # 遥测波动范围
    timers: TimerConfig = field(default_factory=TimerConfig)
    flow_control: FlowControlConfig = field(default_factory=FlowControlConfig)


@dataclass
class MultiStationConfig:
    """多站总配置."""
    stations: list[StationConfig] = field(default_factory=list)
    global_timers: TimerConfig = field(default_factory=TimerConfig)
    global_flow_control: FlowControlConfig = field(default_factory=FlowControlConfig)


@dataclass
class StationStatus:
    """站点状态."""
    station_id: str
    station_name: str
    port: int
    common_addr: int
    running: bool = False
    client_count: int = 0
    yx_count: int = 0
    yc_count: int = 0
    yk_count: int = 0
    ym_count: int = 0
    simulation_active: bool = False


class MultiStationManager:
    """多站并发模拟管理器.

    设计要点:
    1. 每站独立的 SlaveEngine 实例(独立端口/独立数据)
    2. 统一生命周期管理(start_all/stop_all)
    3. 全局事件聚合与分发
    4. 站间数据隔离
    5. 共享 asyncio 事件循环
    """

    def __init__(self, config: MultiStationConfig):
        self._config = config
        self._engines: dict[str, SlaveEngine] = {}
        self._station_configs: dict[str, StationConfig] = {}
        self._global_event_callback: Callable | None = None
        self._running = False
        self._start_time: float = 0.0

    @property
    def is_running(self) -> bool:
        """是否正在运行."""
        return self._running

    @property
    def station_count(self) -> int:
        """站点数量."""
        return len(self._engines)

    @property
    def total_client_count(self) -> int:
        """总客户端连接数."""
        return sum(engine.client_count for engine in self._engines.values())

    @property
    def uptime(self) -> float:
        """运行时间(秒)."""
        return time.monotonic() - self._start_time if self._running else 0.0

    def set_event_callback(self, callback: Callable):
        """设置全局事件回调."""
        self._global_event_callback = callback

    async def start_all(self) -> None:
        """启动所有子站引擎."""
        if self._running:
            logger.warning("MultiStationManager is already running")
            return

        logger.info(f"Starting {len(self._config.stations)} stations...")

        for station_cfg in self._config.stations:
            try:
                await self._start_station(station_cfg)
            except Exception as e:
                logger.error(f"Failed to start station {station_cfg.station_id}: {e}")
                # 回滚已启动的站
                await self.stop_all()
                raise

        self._running = True
        self._start_time = time.monotonic()
        logger.info(f"All {len(self._engines)} stations started successfully")

    async def stop_all(self) -> None:
        """停止并**彻底回收**所有子站引擎（幂等）.

        关停加固（T07）：

        - **不再以 ``_running`` 作为提前返回条件**：``start_all()`` 中途失败
          会回滚调用 ``stop_all()``，此时 ``_running`` 仍为 False 但 ``_engines``
          里已有已启动的引擎——旧的提前返回会让这些引擎与其监听端口泄漏。
          现在只要「有引擎实例」或「标记为运行中」就执行回收。
        - 逐站 ``stop()`` 后再回收其**残留后台任务**（``aclose_background_tasks``），
          避免事件循环关闭时出现 "Task was destroyed but it is pending!"。
        - 清空引擎/配置字典与全局事件回调，复位运行标记与计时。
        """
        if not self._engines and not self._running:
            return

        logger.info("Stopping all stations...")

        for station_id, engine in list(self._engines.items()):
            try:
                await engine.stop()
            except Exception as e:
                logger.error(f"Error stopping station {station_id}: {e}")
            # 关停后回收残留后台任务，防 pending 告警与资源泄漏
            aclose = getattr(engine, "aclose_background_tasks", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as e:
                    logger.warning(f"Error reaping station {station_id} tasks: {e}")
            logger.info(f"Station {station_id} stopped")

        self._engines.clear()
        self._station_configs.clear()
        self._global_event_callback = None
        self._running = False
        self._start_time = 0.0
        logger.info("All stations stopped")

    async def _start_station(self, config: StationConfig) -> None:
        """启动单个子站."""
        # 加载点表
        point_table = PointTable()
        if config.point_table_file:
            point_table.load_yaml(config.point_table_file)
            logger.info(f"Loaded point table for {config.station_id}: {config.point_table_file}")
        elif config.auto_generate:
            point_table.generate_demo_points(
                yx_count=config.yx_count,
                yc_count=config.yc_count,
                yk_count=config.yk_count,
                ym_count=config.ym_count,
            )
            point_table.station_name = config.station_name or config.station_id
            point_table.common_addr = config.common_addr
            logger.info(f"Generated demo points for {config.station_id}: "
                       f"YX={config.yx_count}, YC={config.yc_count}")

        # 创建引擎
        engine = SlaveEngine(
            host=config.host,
            port=config.port,
            common_addr=config.common_addr,
            max_connections=config.max_connections,
            point_table=point_table,
            spontaneous_enabled=config.spontaneous_enabled,
            k=config.flow_control.k,
            w=config.flow_control.w,
            t0=config.timers.t0,
            t1=config.timers.t1,
            t2=config.timers.t2,
            t3=config.timers.t3,
        )

        # 设置事件回调
        engine.set_event_callback(
            lambda event, data, sid=config.station_id: self._on_station_event(sid, event, data)
        )

        # 启动引擎
        await engine.start()
        self._engines[config.station_id] = engine
        self._station_configs[config.station_id] = config

        # 启动模拟
        if config.simulation_enabled:
            await engine.start_simulation(
                yx_interval=config.yx_interval,
                yc_interval=config.yc_interval,
                yx_change_rate=config.yx_change_rate,
                yc_change_range=config.yc_change_range,
            )
            logger.info(f"Simulation started for {config.station_id}")

        logger.info(f"Station {config.station_id} started on port {config.port} "
                   f"(common_addr={config.common_addr})")

    def get_engine(self, station_id: str) -> SlaveEngine | None:
        """获取指定站的引擎."""
        return self._engines.get(station_id)

    def get_station_status(self, station_id: str) -> StationStatus | None:
        """获取指定站的状态."""
        engine = self._engines.get(station_id)
        config = self._station_configs.get(station_id)
        if not engine or not config:
            return None

        data_stats = engine.data_store.stats
        return StationStatus(
            station_id=station_id,
            station_name=config.station_name,
            port=config.port,
            common_addr=config.common_addr,
            running=engine.is_running,
            client_count=engine.client_count,
            yx_count=data_stats.get('yx_count', 0),
            yc_count=data_stats.get('yc_count', 0),
            yk_count=data_stats.get('yk_count', 0),
            ym_count=data_stats.get('ym_count', 0),
            simulation_active=config.simulation_enabled,
        )

    def get_all_station_status(self) -> list[StationStatus]:
        """获取所有站的状态."""
        statuses = []
        for station_id in self._engines:
            status = self.get_station_status(station_id)
            if status:
                statuses.append(status)
        return statuses

    def get_summary(self) -> dict[str, Any]:
        """获取汇总信息."""
        statuses = self.get_all_station_status()
        return {
            "running": self._running,
            "station_count": len(statuses),
            "total_clients": sum(s.client_count for s in statuses),
            "total_yx": sum(s.yx_count for s in statuses),
            "total_yc": sum(s.yc_count for s in statuses),
            "total_yk": sum(s.yk_count for s in statuses),
            "total_ym": sum(s.ym_count for s in statuses),
            "uptime": self.uptime,
            "stations": [
                {
                    "id": s.station_id,
                    "name": s.station_name,
                    "port": s.port,
                    "clients": s.client_count,
                }
                for s in statuses
            ],
        }

    async def start_simulation(self, station_id: str = None) -> None:
        """启动指定站或所有站的模拟."""
        if station_id:
            engine = self._engines.get(station_id)
            config = self._station_configs.get(station_id)
            if engine and config:
                await engine.start_simulation(
                    yx_interval=config.yx_interval,
                    yc_interval=config.yc_interval,
                    yx_change_rate=config.yx_change_rate,
                    yc_change_range=config.yc_change_range,
                )
                logger.info(f"Simulation started for {station_id}")
        else:
            for sid, engine in self._engines.items():
                config = self._station_configs.get(sid)
                if config:
                    await engine.start_simulation(
                        yx_interval=config.yx_interval,
                        yc_interval=config.yc_interval,
                        yx_change_rate=config.yx_change_rate,
                        yc_change_range=config.yc_change_range,
                    )
            logger.info("Simulation started for all stations")

    async def stop_simulation(self, station_id: str = None) -> None:
        """停止指定站或所有站的模拟."""
        if station_id:
            engine = self._engines.get(station_id)
            if engine:
                await engine.stop_simulation()
                logger.info(f"Simulation stopped for {station_id}")
        else:
            for engine in self._engines.values():
                await engine.stop_simulation()
            logger.info("Simulation stopped for all stations")

    def _on_station_event(self, station_id: str, event: SlaveEvent, data: dict):
        """聚合站事件到全局回调."""
        data["station_id"] = station_id
        if self._global_event_callback:
            try:
                self._global_event_callback(event, data)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
