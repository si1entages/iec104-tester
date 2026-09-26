"""IEC 60870-5-104 协议测试工具 — 应用入口.

纯 Web 形态：浏览器作为唯一 UI，入口负责启动本地 Web 服务并按需打开浏览器。
提供三类运行方式：
  - Web UI（默认）：`python app.py --mode master|slave`
  - headless 引擎 CLI：`python app.py --mode slave --no-gui`
  - YAML 自动化测试：`python app.py --test tests/scripts/`
"""

import argparse
import logging
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Web UI 默认 HTTP 端口（按角色区分，避免主站/子站同时启动时端口冲突）
_DEFAULT_HTTP_PORT = {"slave": 8766, "master": 8765}

# 打开浏览器前的端口探测参数
_PROBE_INTERVAL_S = 0.05
_PROBE_TIMEOUT_S = 5.0


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


def _open_browser_when_ready(
    url: str,
    port: int,
    interval: float = _PROBE_INTERVAL_S,
    timeout: float = _PROBE_TIMEOUT_S,
) -> None:
    """后台轮询端口就绪后再打开浏览器（避免固定 sleep 的竞态）.

    在守护线程中以 ``connect_ex`` 探测本地端口，一旦连通立即
    ``webbrowser.open(url)``；超过 ``timeout`` 仍未就绪则打印提示，不抛异常。

    Args:
        url: 要打开的完整 URL.
        port: 本地监听端口.
        interval: 每次探测的间隔秒数.
        timeout: 最长等待秒数.
    """

    def _probe() -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(interval)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    try:
                        webbrowser.open(url)
                    except Exception:  # pragma: no cover - 环境相关
                        print(f"未能自动打开浏览器，请手动访问: {url}", flush=True)
                    return
            time.sleep(interval)
        print(f"服务尚未就绪，请手动访问: {url}", flush=True)

    threading.Thread(target=_probe, daemon=True).start()


def run_web(role: str, http_port: int | None = None, open_browser: bool = True,
            point_table=None, connection: dict | None = None) -> None:
    """启动 Web 服务（阻塞）并在就绪后打开浏览器.

    Args:
        role: 运行角色，"master"（主站）或 "slave"（子站）.
        http_port: HTTP 端口；为 None 时按角色取默认端口（主站 8765 / 子站 8766）.
        open_browser: True 时在端口就绪后自动打开默认浏览器；False 时仅打印地址.
        point_table: 已加载的 ``PointTable``；为 None 时 Web 层自行生成演示点表.
        connection: CLI 连接参数（host/port/addr）透传给 Web 层——
            否则 UI 的输入框回落到默认 2404，「启动监听/连接」会忽略 --port。
    """
    from webui.server import run_server

    port = http_port if http_port is not None else _DEFAULT_HTTP_PORT.get(
        role, _DEFAULT_HTTP_PORT["master"]
    )
    url = f"http://127.0.0.1:{port}/"

    print(f"Web UI: {url}", flush=True)
    if open_browser:
        _open_browser_when_ready(url, port)
    else:
        print("请用浏览器打开上述地址", flush=True)
    print("关闭此窗口或按 Ctrl+C 停止服务", flush=True)

    try:
        run_server(role, "127.0.0.1", port, point_table=point_table,
                   connection=connection)
    except KeyboardInterrupt:
        pass


def cli(default_role: str | None = None) -> int:
    """解析命令行参数并分派到对应的运行模式.

    Args:
        default_role: ``--mode`` 的默认值（供 apps/ 瘦入口注入角色）.

    Returns:
        进程退出码.
    """
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 协议测试工具"
    )
    parser.add_argument(
        "--mode", choices=["master", "slave"], default=default_role,
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
        "--history-db", type=str, default=None,
        help="历史数据库路径 (SQLite)"
    )
    parser.add_argument(
        "--test", type=str, default=None,
        help="运行自动化测试脚本 (YAML 文件或目录)"
    )
    parser.add_argument(
        "--http-port", type=int, default=None,
        help="Web UI HTTP 端口 (默认主站 8765 / 子站 8766)"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="启动 Web 服务时不自动打开浏览器"
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
    from core.config import AppConfig, load_config

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

    try:
        # 自动化测试脚本模式
        if args.test:
            logger.info(f"Running test script: {args.test}")
            return _run_tests(args.test, logger)

        # 无GUI模式
        if args.no_gui:
            logger.info("Running in CLI mode (no GUI)")
            _run_cli(config, point_table, history_db, logger)
            return 0

        # Web UI 模式（主站/子站）
        role = "slave" if config.mode == "slave" else "master"
        connection = {
            "host": config.connection.host,
            "port": config.connection.port,
            "addr": config.connection.common_addr,
        }
        run_web(role, args.http_port, open_browser=not args.no_browser,
                point_table=point_table, connection=connection)
        return 0
    finally:
        # 保证异常路径也会关闭历史数据库
        if history_db:
            history_db.close()


def _run_tests(script_path: str, logger) -> int:
    """运行自动化测试脚本，返回进程退出码."""
    import asyncio

    from core.testing import ReportGenerator, TestRunner

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

        runner.set_callbacks(on_step_complete=on_step, on_test_complete=on_test)

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

    return asyncio.run(run())


def _run_cli(config, point_table, history_db, logger):
    """CLI 无GUI模式 — 纯日志输出."""
    import asyncio

    async def run():
        is_master = config.mode == "master"

        if is_master:
            from core.engine.master import MasterEngine

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
            from core.engine.slave import SlaveEngine

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


def main() -> int:
    """控制台入口（pyproject [project.scripts] iec104-tester = app:main）."""
    return cli()


if __name__ == "__main__":
    raise SystemExit(main())
