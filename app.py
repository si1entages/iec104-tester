"""IEC 60870-5-104 协议测试工具 — 应用入口."""

import sys
import os
import logging
import argparse
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: str = None) -> None:
    """配置日志."""
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    datefmt = "%H:%M:%S"

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt=datefmt,
        handlers=handlers,
    )


def main():
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 协议测试工具"
    )
    parser.add_argument(
        "--mode", choices=["master", "slave"], default=None,
        help="运行模式: master(主站) 或 slave(子站)"
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="配置文件路径 (YAML)"
    )
    parser.add_argument(
        "--host", type=str, default=None,
        help="连接地址"
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="端口号 (默认 2404)"
    )
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO", help="日志级别"
    )
    parser.add_argument(
        "--log-file", type=str, default=None,
        help="日志文件路径"
    )
    parser.add_argument(
        "--point-table", type=str, default=None,
        help="点表文件路径 (YAML)"
    )
    parser.add_argument(
        "--no-gui", action="store_true",
        help="无GUI模式（仅CLI日志输出）"
    )
    parser.add_argument(
        "--qss-reload", action="store_true",
        help="启用QSS热重载（修改style.qss实时生效）"
    )
    parser.add_argument(
        "--history-db", type=str, default=None,
        help="历史数据库路径 (SQLite)"
    )
    parser.add_argument(
        "--test", type=str, default=None,
        help="运行自动化测试脚本 (YAML 文件或目录)"
    )

    args = parser.parse_args()

    # 确保项目根目录在 sys.path
    project_root = Path(__file__).parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # 日志
    setup_logging(args.log_level, args.log_file)
    logger = logging.getLogger("iec104")
    logger.info("Starting IEC 60870-5-104 Tester...")

    # 配置
    from core.config import load_config, AppConfig

    config_path = args.config
    if config_path and Path(config_path).exists():
        config = load_config(config_path)
        logger.info(f"Loaded config from: {config_path}")
    else:
        config = AppConfig()

    # 命令行参数覆盖
    if args.mode:
        config.mode = args.mode
    if args.host:
        config.connection.host = args.host
    if args.port:
        config.connection.port = args.port
    if args.point_table:
        config.point_table.file = args.point_table

    # 点表
    from core.data.point_table import PointTable
    point_table = PointTable()

    if config.point_table.file and Path(config.point_table.file).exists():
        try:
            point_table.load_yaml(config.point_table.file)
            logger.info(f"Loaded point table: {config.point_table.file}")
        except Exception as e:
            logger.error(f"Failed to load point table: {e}")

    if point_table.yx_count == 0 and config.point_table.auto_generate:
        point_table.generate_demo_points(
            yx_count=config.point_table.yx_count,
            yc_count=config.point_table.yc_count,
            yk_count=config.point_table.yk_count,
            ym_count=config.point_table.ym_count,
        )
        point_table.station_name = "Demo Station"
        point_table.common_addr = config.connection.common_addr

    # 历史数据库
    history_db = None
    if args.history_db:
        from core.data.history import HistoryDB
        history_db = HistoryDB(args.history_db)
        history_db.open()
        logger.info(f"History DB: {args.history_db}")

    # 自动化测试脚本模式
    if args.test:
        logger.info(f"Running test script: {args.test}")
        _run_tests(args.test, logger)
        return

    # 无GUI模式
    if args.no_gui:
        logger.info("Running in CLI mode (no GUI)")
        _run_cli(config, point_table, history_db, logger)
        return

    # Web UI 模式（主站/子站）
    role = "slave" if config.mode == "slave" else "master"
    port = 8766 if role == "slave" else 8765
    logger.info(f"Starting Web UI as {role} on http://127.0.0.1:{port}/")
    from webui.server import run_server
    try:
        run_server(role, "127.0.0.1", port)
    except KeyboardInterrupt:
        pass
    if history_db:
        history_db.close()
    sys.exit(0)


def _run_tests(script_path: str, logger):
    """运行自动化测试脚本."""
    import asyncio
    from core.testing import TestRunner, ReportGenerator

    async def run():
        runner = TestRunner(report_dir="test_reports")

        target = Path(script_path)
        if target.is_dir():
            scripts = runner.load_directory(target)
            logger.info(f"Loaded {len(scripts)} scripts from {target}")
        elif target.is_file():
            scripts = [runner.load_script(target)]
        else:
            logger.error(f"Not found: {script_path}")
            return 2

        def on_step(step_result):
            icon = {"passed": "✅", "failed": "❌", "error": "💥", "skipped": "⏭"}.get(step_result.status.value, "?")
            logger.info(f"  {icon} Step {step_result.step_index}: [{step_result.action}] {step_result.description}")
            for a in step_result.assertions:
                a_icon = "✓" if a.get("passed") else "✗"
                logger.info(f"           {a_icon} {a.get('message', '')}")

        def on_test(test_result):
            icon = "✅" if test_result.status.value == "passed" else "❌"
            logger.info(f"{icon} {test_result.script_name}: {test_result.status.value.upper()} ({test_result.duration_s:.2f}s)")

        runner._on_step_complete = on_step
        runner._on_test_complete = on_test

        results = []
        for script in scripts:
            result = await runner.run(script)
            results.append(result)
            ReportGenerator.save(result, f"test_reports/{script.name}.txt", format="text")
            ReportGenerator.save(result, f"test_reports/{script.name}.json", format="json")
            ReportGenerator.save(result, f"test_reports/{script.name}.html", format="html")

        passed = sum(1 for r in results if r.status.value == "passed")
        failed = len(results) - passed
        logger.info(f"\nSummary: {len(results)} scripts, {passed} passed, {failed} failed")
        return 0 if failed == 0 else 1

    exit_code = asyncio.run(run())
    sys.exit(exit_code)


def _run_cli(config, point_table, history_db, logger):
    """CLI 无GUI模式 — 纯日志输出."""
    import asyncio

    async def run():
        is_master = config.mode == "master"

        if is_master:
            from core.engine.master import MasterEngine, MasterEvent

            def on_event(event, data):
                logger.info(f"[EVENT] {event.value}: {data}")

            def on_frame(data, direction):
                hex_str = " ".join(f"{b:02X}" for b in data[:40])
                logger.debug(f"[{direction.upper()}] {hex_str}")
                if history_db:
                    history_db.record_frame(direction, data)

            engine = MasterEngine(
                host=config.connection.host,
                port=config.connection.port,
                common_addr=config.connection.common_addr,
                k=config.flow_control.k,
                w=config.flow_control.w,
                t0=config.timers.t0,
                t1=config.timers.t1,
                t2=config.timers.t2,
                t3=config.timers.t3,
                auto_start=config.master.auto_start,
                auto_gi=config.master.auto_gi,
                reconnect=config.connection.reconnect,
            )
            engine.set_event_callback(on_event)
            engine.set_raw_frame_callback(on_frame)

            await engine.start()
            logger.info("Master engine started. Press Ctrl+C to stop.")

            try:
                while True:
                    if history_db:
                        history_db.flush()
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            finally:
                await engine.stop()

        else:
            from core.engine.slave import SlaveEngine, SlaveEvent

            def on_event(event, data):
                logger.info(f"[EVENT] {event.value}: {data}")

            def on_frame(data, direction, client_id=""):
                hex_str = " ".join(f"{b:02X}" for b in data[:40])
                logger.debug(f"[{direction.upper()}] {client_id}: {hex_str}")
                if history_db:
                    history_db.record_frame(direction, data, client_id=client_id)

            engine = SlaveEngine(
                port=config.connection.port,
                common_addr=config.connection.common_addr,
                point_table=point_table,
            )
            engine.set_event_callback(on_event)
            engine.set_raw_frame_callback(on_frame)

            # 初始化数据
            engine.data_store.init_from_point_table(point_table)

            await engine.start()
            logger.info("Slave engine started. Press Ctrl+C to stop.")

            try:
                while True:
                    if history_db:
                        history_db.flush()
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass
            finally:
                await engine.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
