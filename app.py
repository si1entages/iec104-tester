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

# 历史库默认文件名（目录见 HistoryConfig.dir / --history-db）
_HISTORY_DB_NAME = "history.db"


def resolve_history_path(cfg_dir: str, override: str | None = None,
                         role: str | None = None) -> Path:
    """解析历史库文件路径.

    Args:
        cfg_dir: ``HistoryConfig.dir``；空字符串表示项目根目录下的 ``data/``。
        override: ``--history-db`` 显式路径；非空时直接采用（目录自动创建）。
        role: 运行角色（"master"/"slave"）；给出时默认文件名带角色后缀
            （``history_master.db`` / ``history_slave.db``）。

    Returns:
        历史库的绝对/相对路径（不保证文件已存在）。

    Notes:
        主站（HTTP 8765）与子站（HTTP 8766）按本 README 的用法可**同时运行**
        且共用同一默认目录。若两者写同一个库文件，报文记录表没有角色列，
        两边的帧会混在一起无法区分；且任一进程的保留期/容量清理会把
        对方的记录当"最旧数据"删掉。故默认按角色分文件
        （显式 ``--history-db`` 时以用户指定为准，不做后缀）。
    """
    if override:
        return Path(override)
    base = Path(cfg_dir) if cfg_dir else Path(__file__).parent / "data"
    name = f"history_{role}.db" if role in ("master", "slave") else _HISTORY_DB_NAME
    return base / name


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
            point_table=None, connection: dict | None = None,
            history_db=None) -> None:
    """启动 Web 服务（阻塞）并在就绪后打开浏览器.

    Args:
        role: 运行角色，"master"（主站）或 "slave"（子站）.
        http_port: HTTP 端口；为 None 时按角色取默认端口（主站 8765 / 子站 8766）.
        open_browser: True 时在端口就绪后自动打开默认浏览器；False 时仅打印地址.
        point_table: 已加载的 ``PointTable``；为 None 时 Web 层自行生成演示点表.
        connection: CLI 连接参数（host/port/addr）透传给 Web 层——
            否则 UI 的输入框回落到默认 2404，「启动监听/连接」会忽略 --port。
        history_db: 已打开的 ``HistoryDB``；非 None 时 Web 模式会把收发报文
            落盘（此前 Web 模式只建库、不记录）。为 None 则 Web 层不记录。
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
                   connection=connection, history_db=history_db)
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
        "--no-history", action="store_true",
        help="关闭历史库（默认开启，落盘到 <数据目录>/history.db）"
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
    parser.add_argument(
        "--tls", action="store_true",
        help="启用 TLS 传输层加密（IEC 62351 的传输层部分）"
    )
    parser.add_argument(
        "--tls-cert", type=str, default=None,
        help="TLS 本端证书 (PEM)；子站必填"
    )
    parser.add_argument(
        "--tls-key", type=str, default=None,
        help="TLS 本端私钥 (PEM)；缺省时假定与证书同文件"
    )
    parser.add_argument(
        "--tls-ca", type=str, default=None,
        help="TLS 受信 CA (PEM)；主站校验服务端、子站校验客户端时使用"
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="主站跳过服务端证书校验（仅自签联调用，生产禁用）"
    )
    parser.add_argument(
        "--verify-client", action="store_true",
        help="子站要求并校验客户端证书（双向认证 / mTLS）"
    )
    parser.add_argument(
        "--tls-hostname", type=str, default=None,
        help="主站 TLS 主机名校验用域名（按 IP 连接而证书只签域名时必填）"
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

    # TLS 命令行覆盖（T20）。优先级：命令行 > 配置文件。
    if args.tls:
        config.tls.enabled = True
    if args.tls_cert:
        config.tls.certfile = args.tls_cert
    if args.tls_key:
        config.tls.keyfile = args.tls_key
    if args.tls_ca:
        config.tls.cafile = args.tls_ca
    if args.no_verify:
        config.tls.verify = False
    if args.verify_client:
        config.tls.verify_client = True
    if args.tls_hostname:
        config.tls.server_hostname = args.tls_hostname

    # 自定义（非标准厂商私有）TypeID 注册（T22）。
    # 未配置时注册表为空 → 未知 TypeID 行为与既有一致（仍回 COT=42）。
    if config.custom_types:
        from core.protocol.asdu import CUSTOM_TYPES
        try:
            count = CUSTOM_TYPES.load_dict({"custom_types": config.custom_types})
            logger.info(f"Registered {count} custom TypeID(s): {CUSTOM_TYPES.ids()}")
        except Exception as e:
            logger.error(f"Failed to register custom TypeIDs: {e}")

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

    # 历史数据库（T17：默认开启，落盘到 <数据目录>/history_<role>.db）
    # 优先级：--no-history > --history-db > config.history.enabled
    role = "slave" if config.mode == "slave" else "master"
    history_db = None
    if args.no_history:
        logger.info("History DB disabled by --no-history")
    elif config.history.enabled or args.history_db:
        from core.data.history import HistoryDB

        db_path = resolve_history_path(config.history.dir, args.history_db, role)
        try:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            history_db = HistoryDB(
                db_path,
                retention_days=config.history.retention_days,
                max_size_mb=config.history.max_size_mb,
                flush_interval=config.history.flush_interval,
                auto_flush=True,
            )
            history_db.open()
            logger.info(
                f"History DB: {db_path} (retention={config.history.retention_days}d, "
                f"max_size={config.history.max_size_mb}MB, "
                f"flush_interval={config.history.flush_interval}s)"
            )
        except Exception as e:
            logger.error(f"Failed to open history DB: {e}")
            history_db = None

    try:
        # 自动化测试脚本模式
        if args.test:
            logger.info(f"Running test script: {args.test}")
            return _run_tests(args.test, logger)

        # 无GUI模式
        if args.no_gui:
            logger.info("Running in CLI mode (no GUI)")
            from core.transport.connection import TlsConfigError

            try:
                _run_cli(config, point_table, history_db, logger)
            except TlsConfigError as e:
                # TLS 失败策略与 Web 单站/多站一致（T20 统一）：拒绝明文降级
                logger.error(f"TLS 配置无效，拒绝启动（不降级明文）: {e}")
                return 2
            return 0

        # Web UI 模式（主站/子站）—— role 已在上方历史库接线处解析
        connection = {
            "host": config.connection.host,
            "port": config.connection.port,
            "addr": config.connection.common_addr,
        }
        run_web(role, args.http_port, open_browser=not args.no_browser,
                point_table=point_table, connection=connection,
                history_db=history_db)
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


def _enable_tls(engine, role: str, config, logger) -> None:
    """按配置为引擎注入 TLS 上下文（T20）；未启用时不做任何事.

    TLS 配置无效（证书/密钥/CA 路径不存在、格式错误等）→ 直接抛
    ``TlsConfigError``，由 CLI 启动流程捕获并**以非零退出码终止**——
    与 Web 单站 ``ok=false``、多站「该站不启动」的失败策略完全一致
    （T20 统一）：**绝不静默降级为明文**，否则用户以为在测 TLS 实际是
    明文，测试结论不可信。
    """
    if not config.tls.enabled:
        return
    from core.transport.connection import configure_engine_tls

    configure_engine_tls(engine, role, config.tls)
    logger.info(
        f"TLS enabled ({role}, verify={config.tls.verify}, "
        f"verify_client={config.tls.verify_client})"
    )


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
            _enable_tls(engine, "master", config, logger)

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
            _enable_tls(engine, "slave", config, logger)

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
