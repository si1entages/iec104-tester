"""多站并发模拟启动脚本.

用法:
    python run_multi_station.py                          # 使用默认配置启动3个站
    python run_multi_station.py --config configs/multi_station.yaml  # 使用自定义配置
    python run_multi_station.py --stations 5             # 快速启动5个演示站
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from core.engine.multi_station import MultiStationConfig, MultiStationManager, StationConfig

logger = logging.getLogger("iec104.multi_station")


def create_demo_config(station_count: int = 3) -> MultiStationConfig:
    """创建演示配置."""
    config = MultiStationConfig()

    for i in range(1, station_count + 1):
        station = StationConfig(
            station_id=f"station_{i}",
            station_name=f"演示变电站{i}",
            host="0.0.0.0",
            port=2403 + i,  # 2404, 2405, 2406, ...
            common_addr=i,
            max_connections=8,
            auto_generate=True,
            yx_count=50 + i * 10,
            yc_count=25 + i * 5,
            yk_count=10 + i * 2,
            ym_count=5 + i,
            spontaneous_enabled=True,
            simulation_enabled=True,
            yx_interval=3.0 + i,
            yc_interval=1.5 + i * 0.5,
            yx_change_rate=0.1,
            yc_change_range=0.05,
        )
        config.stations.append(station)

    return config


def load_multi_station_config(config_path: str) -> MultiStationConfig:
    """从YAML文件加载多站配置."""
    import yaml

    with open(config_path, encoding='utf-8') as f:
        data = yaml.safe_load(f)

    config = MultiStationConfig()

    # 加载全局配置
    if 'global_timers' in data:
        from core.config import TimerConfig
        config.global_timers = TimerConfig(**data['global_timers'])

    if 'global_flow_control' in data:
        from core.config import FlowControlConfig
        config.global_flow_control = FlowControlConfig(**data['global_flow_control'])

    # 加载站点配置
    for station_data in data.get('stations', []):
        station = StationConfig(
            station_id=station_data.get('station_id', ''),
            station_name=station_data.get('station_name', ''),
            host=station_data.get('host', '0.0.0.0'),
            port=station_data.get('port', 2404),
            common_addr=station_data.get('common_addr', 1),
            max_connections=station_data.get('max_connections', 16),
            point_table_file=station_data.get('point_table_file', ''),
            auto_generate=station_data.get('auto_generate', True),
            yx_count=station_data.get('yx_count', 100),
            yc_count=station_data.get('yc_count', 50),
            yk_count=station_data.get('yk_count', 20),
            ym_count=station_data.get('ym_count', 10),
            spontaneous_enabled=station_data.get('spontaneous_enabled', True),
            simulation_enabled=station_data.get('simulation_enabled', False),
            yx_interval=station_data.get('yx_interval', 5.0),
            yc_interval=station_data.get('yc_interval', 2.0),
            yx_change_rate=station_data.get('yx_change_rate', 0.1),
            yc_change_range=station_data.get('yc_change_range', 0.05),
        )

        # 加载站点定时器配置
        if 'timers' in station_data:
            from core.config import TimerConfig
            station.timers = TimerConfig(**station_data['timers'])
        else:
            station.timers = config.global_timers

        # 加载站点流控配置
        if 'flow_control' in station_data:
            from core.config import FlowControlConfig
            station.flow_control = FlowControlConfig(**station_data['flow_control'])
        else:
            station.flow_control = config.global_flow_control

        config.stations.append(station)

    return config


def setup_logging(level: str = "INFO"):
    """设置日志."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event
) -> str:
    """注册 SIGINT/SIGTERM → 优雅停止，返回实际使用的机制（"loop" / "signal"）.

    - Unix：``loop.add_signal_handler``（asyncio 原生途径）；
    - Windows：ProactorEventLoop **未实现**该方法（``NotImplementedError``），
      回退到 ``signal.signal`` + ``loop.call_soon_threadsafe``——Ctrl+C 触发
      自定义处理器，线程安全地置位 ``stop_event``，语义与 Unix 一致
      （优雅停止；再按一次 Ctrl+C 走 Python 默认 KeyboardInterrupt 强退）。
    """
    def request_stop():
        logger.info("Received stop signal")
        stop_event.set()

    used = "loop"
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:
            used = "signal"

            def _win_handler(signum, _frame, _loop=loop, _request=request_stop):
                try:
                    _loop.call_soon_threadsafe(_request)
                except RuntimeError:  # 事件循环已关闭，静默退出
                    pass

            signal.signal(sig, _win_handler)
    return used


async def run_multi_station(config: MultiStationConfig):
    """运行多站模拟."""
    manager = MultiStationManager(config)

    # 设置事件回调
    def on_event(event, data):
        station_id = data.get('station_id', 'unknown')
        logger.info(f"[{station_id}] Event: {event.value}")

    manager.set_event_callback(on_event)

    # 处理信号（跨平台：Unix 用 loop API，Windows 回退 signal.signal）
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()
    used = install_signal_handlers(loop, stop_event)
    logger.info(f"Stop signal handler installed via: {used}")

    try:
        # 启动所有站
        await manager.start_all()

        # 打印状态
        summary = manager.get_summary()
        logger.info("=" * 60)
        logger.info("多站并发模拟已启动")
        logger.info("=" * 60)
        logger.info(f"站点数量: {summary['station_count']}")
        logger.info(f"总遥信数: {summary['total_yx']}")
        logger.info(f"总遥测数: {summary['total_yc']}")
        logger.info(f"总遥控数: {summary['total_yk']}")
        logger.info(f"总遥脉数: {summary['total_ym']}")
        logger.info("-" * 60)
        for station in summary['stations']:
            logger.info(f"  {station['name']}: 端口 {station['port']}, "
                       f"客户端 {station['clients']}")
        logger.info("=" * 60)
        logger.info("按 Ctrl+C 停止")

        # 等待停止信号
        await stop_event.wait()

    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        # 停止所有站
        await manager.stop_all()
        logger.info("多站并发模拟已停止")


def main():
    """主函数."""
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 多站并发模拟"
    )
    parser.add_argument(
        '--config', '-c',
        help='多站配置文件路径 (YAML格式)'
    )
    parser.add_argument(
        '--stations', '-n',
        type=int,
        default=3,
        help='快速启动演示站数量 (默认: 3)'
    )
    parser.add_argument(
        '--log-level', '-l',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='日志级别 (默认: INFO)'
    )

    args = parser.parse_args()

    # 设置日志
    setup_logging(args.log_level)

    # 加载配置
    if args.config:
        logger.info(f"Loading config from {args.config}")
        config = load_multi_station_config(args.config)
    else:
        logger.info(f"Creating demo config with {args.stations} stations")
        config = create_demo_config(args.stations)

    # 运行
    asyncio.run(run_multi_station(config))


if __name__ == "__main__":
    main()
