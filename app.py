"""IEC 60870-5-104 协议测试工具 — 应用入口.

纯 Web 形态：浏览器作为唯一 UI，入口负责启动本地 Web 服务并按需打开浏览器。
单文件发布入口：默认单进程双角色、一个 8765 端口，打开一个工作台（左侧菜单
切换主站/子站）；也支持 `--mode master|slave` 只启动单角色。
透明桥（T73）：`--mode bridge`（真实主站 ↔ 测试器 ↔ 真实子站旁路观察，headless）。
提供三类运行方式：
  - Web UI（默认）：`python app.py`（both）/ `--mode master|slave`
  - headless 引擎 CLI：`python app.py --mode slave --no-gui`
  - YAML 自动化测试：`python app.py --test tests/scripts/`
"""

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from core.version import __version__

# Web UI 默认 HTTP 端口（按角色区分，避免主站/子站同时启动时端口冲突）
_DEFAULT_HTTP_PORT = {"slave": 8766, "master": 8765, "bridge": 8767}

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
            history_db=None, engine_config=None,
            http_host: str = "127.0.0.1", auth_token: str | None = None,
            web_tls_cert: str | None = None,
            web_tls_key: str | None = None,
            history_dbs: dict | None = None) -> None:
    """启动 Web 服务（阻塞）并在就绪后打开浏览器.

    Args:
        role: "master" / "slave" / "both"（both = 单进程双角色、同一端口）.
        http_port: HTTP 端口；为 None 时按角色取默认端口（主站 8765 / 子站 8766）.
        open_browser: True 时在端口就绪后自动打开默认浏览器；False 时仅打印地址.
        point_table: 已加载的 ``PointTable``；为 None 时 Web 层自行生成演示点表.
        connection: CLI 连接参数（host/port/addr）透传给 Web 层——
            否则 UI 的输入框回落到默认 2404，「启动监听/连接」会忽略 --port。
        history_db: 已打开的 ``HistoryDB``；非 None 时 Web 模式会把收发报文
            落盘（此前 Web 模式只建库、不记录）。为 None 则 Web 层不记录。
        engine_config: CLI 解析出的 ``AppConfig``（D3 接线）。经
            run_server → EngineBridge → EngineSession 传入引擎构造，使
            ``--tls*`` / 冗余等 CLI 配置在默认 Web 模式下真实生效；
            为 None 时 Web 层使用默认配置（与改动前行为一致）。
        http_host: Web UI 监听地址（默认 127.0.0.1；0.0.0.0 会暴露到局域网）.
        auth_token: 可选访问令牌；设置后 /api/* 与 /ws 需携带令牌.
    """
    from webui.server import create_web_ssl_context, run_server

    port = http_port if http_port is not None else _DEFAULT_HTTP_PORT.get(
        role, _DEFAULT_HTTP_PORT["master"]
    )
    ssl_context = None
    if web_tls_cert:
        try:
            ssl_context = create_web_ssl_context(web_tls_cert, web_tls_key)
        except (OSError, ValueError) as e:
            print(f"Web UI TLS 配置无效，拒绝启动: {e}", file=sys.stderr, flush=True)
            raise SystemExit(2) from e
    # 0.0.0.0/:: 是监听地址而非可访问地址：本机浏览器仍走回环地址
    browse_host = "127.0.0.1" if http_host in ("0.0.0.0", "::", "") else http_host
    scheme = "https" if ssl_context is not None else "http"
    url = f"{scheme}://{browse_host}:{port}/"

    if http_host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"Web UI 监听 {http_host}:{port}（非本地回环）——"
            + ("已启用访问令牌认证" if auth_token
               else "未启用认证！请使用 --auth-token 或改回 127.0.0.1"),
            flush=True,
        )
    if auth_token:
        print(
            f"Web UI 认证已启用：首次打开会提示输入令牌；也可直接访问 "
            f"{scheme}://{browse_host}:{port}/app/?token=<token>",
            flush=True,
        )
    print(f"Web UI: {url}", flush=True)
    if open_browser:
        _open_browser_when_ready(url, port)
    else:
        print("请用浏览器打开上述地址", flush=True)
    print("关闭此窗口或按 Ctrl+C 停止服务", flush=True)

    try:
        run_server(role, http_host, port, point_table=point_table,
                   connection=connection, history_db=history_db,
                   history_dbs=history_dbs,
                   app_config=engine_config, auth_token=auth_token,
                   ssl_context=ssl_context)
    except KeyboardInterrupt:
        pass


# ═══════════════════════════════════════════════════════════════════
#  一键环回演示（--demo）
# ═══════════════════════════════════════════════════════════════════

def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _pick_port(preferred: int | None = None,
               exclude: set[int] | None = None) -> int:
    """优先用 preferred；被占用时退回系统分配的空闲端口."""
    exclude = exclude or set()
    if preferred and preferred not in exclude and _port_free(preferred):
        return preferred
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in exclude:
            return port
    raise RuntimeError("无法分配空闲端口")


def _http_json(port: int, path: str = "/api/status", timeout: float = 1.0,
               token: str | None = None, scheme: str = "http"):
    """GET 一个本地 Web 端点；不可达时返回 None."""
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(
            f"{scheme}://127.0.0.1:{port}{path}", headers=headers
        )
        context = None
        if scheme == "https":
            import ssl
            # 本地就绪探测不校验证书（与 --web-tls 自签场景一致）
            context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return None


def _post_json(port: int, path: str, payload: dict | None = None) -> dict:
    """POST JSON；失败时返回 ``{ok: False, error}`` 而不是抛异常."""
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _wait_http(ports: list[int], timeout: float = 45.0,
               token: str | None = None, scheme: str = "http") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(_http_json(port, token=token, scheme=scheme) is not None for port in ports):
            return True
        time.sleep(0.2)
    return False


def _wait_master_running(port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _http_json(port)
        if status and status.get("started") and status.get("running"):
            return True
        time.sleep(0.2)
    return False


def _demo_commands(args, http_port: int, iec_port: int) -> list[str]:
    """构造演示子进程命令（一个进程、单端口双角色）."""
    root = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False):
        base = [sys.executable]
    else:
        base = [sys.executable, str(root / "app.py")]
    cmd = base + [
        "--mode", "both", "--host", "127.0.0.1",
        "--http-port", str(http_port), "--port", str(iec_port),
        "--no-browser", "--no-history", "--log-level", args.log_level,
    ]
    if args.config:
        cmd += ["--config", args.config]
    if args.point_table:
        cmd += ["--point-table", args.point_table]
    return cmd


def _demo_connect(http_port: int, iec_port: int) -> tuple[bool, str]:
    """让演示子站监听、主站连接并总召；返回 (成功, 错误信息)."""
    slave = _post_json(http_port, "/slave/api/slave/start",
                       {"host": "127.0.0.1", "port": iec_port, "addr": 1})
    if not slave.get("ok"):
        return False, f"子站监听失败：{slave.get('error', '未知错误')}"

    master = _post_json(http_port, "/api/master/start",
                        {"host": "127.0.0.1", "port": iec_port, "addr": 1})
    if not master.get("ok"):
        return False, f"主站连接失败：{master.get('error', '未知错误')}"
    if not _wait_master_running(http_port):
        return False, "主站未进入运行态"
    _post_json(http_port, "/api/master/gi", {"qoi": 20})
    return True, ""


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    """终止子进程及其子进程树（PyInstaller onefile 是 bootloader + app 两进程）.

    Windows 上只 ``terminate()`` 父 bootloader 会留下真正的 app 子进程继续占用
    端口；``taskkill /T`` 才能把整棵树回收。POSIX 侧直接 terminate 即可。
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True, check=False,
        )
    else:
        proc.terminate()


def _run_demo(args) -> int:
    """一键演示：一个进程双角色（单端口），自动监听/连接/总召，打开单页工作台."""
    http_port = _pick_port(args.http_port or _DEFAULT_HTTP_PORT["master"])
    iec_port = _pick_port(args.port or 2404, exclude={http_port})
    cmd = _demo_commands(args, http_port, iec_port)
    ui_url = f"http://127.0.0.1:{http_port}/app/"

    # 演示模式仅监听 127.0.0.1，且 _demo_connect 不带令牌；
    # 为保证一键演示可用，--auth-token/--http-host 在演示模式下不生效。
    if args.auth_token or args.http_host not in ("127.0.0.1", "localhost", "::1"):
        print("提示：演示模式仅监听 127.0.0.1，不启用访问令牌"
              "（--auth-token / --http-host 已忽略）", flush=True)

    print("启动演示环境（单进程：主站 + 子站）...", flush=True)
    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(cmd)
        if not _wait_http([http_port]):
            print("演示启动超时：请检查端口/依赖是否正常", flush=True)
            return 1
        if proc.poll() is not None:
            print(f"演示进程提前退出（退出码 {proc.returncode}）", flush=True)
            return 1

        # 端口检查与实际 bind 之间存在竞态；失败时换一个 IEC 端口重试一次，
        # 避免演示因本机临时端口占用而永久停在"未连接"。
        connected = False
        last_error = ""
        for attempt in range(2):
            connected, last_error = _demo_connect(http_port, iec_port)
            if connected:
                break
            print(f"演示连接失败（第 {attempt + 1} 次）：{last_error}", flush=True)
            _post_json(http_port, "/api/master/stop")
            _post_json(http_port, "/slave/api/slave/stop")
            time.sleep(0.5)
            iec_port = _pick_port(None, exclude={http_port})

        if not connected:
            print(f"自动连接失败：{last_error}（可在页面手动连接）", flush=True)

        banner = "演示环境已就绪：" if connected else "演示环境已启动（自动连接失败）："
        print(f"\n{banner}", flush=True)
        print(f"  工作台（主站/子站同一页面）: {ui_url}", flush=True)
        print(f"  IEC 104: 127.0.0.1:{iec_port}（公共地址 1）", flush=True)
        print("按 Ctrl+C 停止演示", flush=True)
        if not args.no_browser:
            webbrowser.open(ui_url)

        deadline = (time.monotonic() + args.demo_seconds
                    if args.demo_seconds > 0 else None)
        while proc.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                print(f"演示时间到（{args.demo_seconds:.0f}s），停止 ...", flush=True)
                break
            time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        print("正在停止演示环境 ...", flush=True)
        return 0
    finally:
        if proc is not None:
            _terminate_process_tree(proc)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


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
        "--version", action="version",
        version=f"iec104-tester {__version__}",
        help="打印版本号并退出"
    )
    parser.add_argument(
        "--mode", choices=["master", "slave", "both", "bridge"], default=default_role,
        help="运行模式: master(主站) / slave(子站) / both(默认；单页工作台) / "
             "bridge(透明桥：主站↔测试器↔子站旁路观察，headless)"
    )
    parser.add_argument(
        "--listen-host", type=str, default=None,
        help="[bridge] 监听地址（面向真实主站，默认 0.0.0.0）"
    )
    parser.add_argument(
        "--listen-port", type=int, default=None,
        help="[bridge] 监听端口（主站改连此口；默认 2404）"
    )
    parser.add_argument(
        "--upstream-host", type=str, default=None,
        help="[bridge] 上游子站地址（必填）"
    )
    parser.add_argument(
        "--upstream-port", type=int, default=None,
        help="[bridge] 上游子站端口（默认 2404）"
    )
    parser.add_argument(
        "--capture-file", type=str, default=None,
        help="[bridge] 旁路帧录制文件（按扩展名分派格式：.bin/.json/.pcap；可选）"
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
        "--report-dir", type=str, default="test_reports",
        help="自动化测试报告输出目录（默认 test_reports）"
    )
    parser.add_argument(
        "--http-port", type=int, default=None,
        help="Web UI HTTP 端口 (默认主站 8765 / 子站 8766)"
    )
    parser.add_argument(
        "--http-host", type=str, default="127.0.0.1",
        help="Web UI 监听地址 (默认 127.0.0.1；0.0.0.0 会暴露到局域网)"
    )
    parser.add_argument(
        "--auth-token", type=str,
        default=os.environ.get("IEC104_AUTH_TOKEN") or None,
        help="Web API 访问令牌（可选）；设置后 REST/WS 需携带令牌；"
             "默认读环境变量 IEC104_AUTH_TOKEN"
    )
    parser.add_argument(
        "--web-tls-cert", type=str, default=None,
        help="Web UI HTTPS 证书 (PEM)；设置后 Web 服务以 HTTPS 监听"
    )
    parser.add_argument(
        "--web-tls-key", type=str, default=None,
        help="Web UI HTTPS 私钥 (PEM)；缺省时假定与证书同文件"
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="启动 Web 服务时不自动打开浏览器"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="一键环回演示：本机同时启动子站+主站并自动连接（Ctrl+C 停止全部）"
    )
    parser.add_argument(
        "--demo-seconds", type=float, default=0.0,
        help="演示运行 N 秒后自动停止（默认 0=一直运行到 Ctrl+C；CI/演示录制用）"
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

    # 单文件发布（一个 exe）：无 --mode 时默认同时启动主站+子站（单进程双角色、
    # 一个 8765 端口），不再交互选择。--mode master|slave 仍可用于单角色。
    if args.mode is None and not args.demo and not args.test and not args.config:
        args.mode = "master" if args.no_gui else "both"
    if args.mode == "both" and args.no_gui:
        print("--mode both 仅支持 Web 模式（请去掉 --no-gui）", flush=True)
        return 2

    # 日志
    setup_logging(args.log_level, args.log_file)
    logger = logging.getLogger("iec104")
    logger.info("Starting IEC 60870-5-104 Tester...")

    # 透明桥（T73/T74）：--no-gui 时 headless 旁路观察器（不加载点表/历史库/Web UI）；
    # 否则 Web 桥模式（role="bridge"），桥在 UI 上配置启停（T74）。
    if args.mode == "bridge" and args.no_gui:
        if not args.upstream_host:
            print("--mode bridge --no-gui 需要 --upstream-host（真实子站地址）", flush=True)
            return 2
        return _run_bridge(args, logger)

    # 配置
    from core.config import AppConfig, load_config

    config_path = args.config
    if config_path and Path(config_path).exists():
        config = load_config(config_path)
        logger.info(f"Loaded config from: {config_path}")
    else:
        config = AppConfig()

    # 命令行参数覆盖（both 不是 AppConfig 的合法 mode；引擎按角色单独设置）
    if args.mode and args.mode != "both":
        config.mode = args.mode
    if args.host:
        config.connection.host = args.host
    if args.port:
        config.connection.port = args.port
    if args.point_table:
        config.point_table.file = args.point_table
    if args.upstream_host:
        config.connection.host = args.upstream_host
    if args.upstream_port:
        config.connection.port = args.upstream_port

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

    # 一键环回演示：父进程只做编排，两个 Web 角色各起独立子进程，
    # 避免共享事件循环/全局日志/端口状态；Ctrl+C 时统一回收。
    if args.demo:
        return _run_demo(args)

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
    mode = args.mode or config.mode
    role = ("slave" if mode == "slave" else "bridge" if mode == "bridge" else "master")
    roles = ["master", "slave"] if mode == "both" else [role]
    history_db = None
    history_dbs: dict = {}
    if args.no_history:
        logger.info("History DB disabled by --no-history")
    elif config.history.enabled or args.history_db:
        from core.data.history import HistoryDB

        for db_role in roles:
            if mode == "both" and args.history_db:
                # 双角色共用一个 --history-db 时必须拆文件，避免两个 SQLite 互踩
                p = Path(args.history_db)
                db_path = str(p.with_name(f"{p.stem}_{db_role}{p.suffix or '.db'}"))
            else:
                db_path = resolve_history_path(config.history.dir, args.history_db, db_role)
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                db = HistoryDB(
                    db_path,
                    retention_days=config.history.retention_days,
                    max_size_mb=config.history.max_size_mb,
                    flush_interval=config.history.flush_interval,
                    auto_flush=True,
                )
                db.open()
                history_dbs[db_role] = db
                logger.info(
                    f"History DB({db_role}): {db_path} "
                    f"(retention={config.history.retention_days}d, "
                    f"max_size={config.history.max_size_mb}MB, "
                    f"flush_interval={config.history.flush_interval}s)"
                )
            except Exception as e:
                logger.error(f"Failed to open history DB({db_role}): {e}")
        history_db = history_dbs.get(role) if mode != "both" else None

    try:
        # 自动化测试脚本模式
        if args.test:
            logger.info(f"Running test script: {args.test}")
            return _run_tests(args.test, logger, args.report_dir)

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

        # TLS 失败策略（T20 统一，D3 修复延伸到默认 Web 模式）：
        # 配置显式启用 TLS 但配置无效（证书/密钥/CA 缺失等）→ 启动前即拒绝，
        # **非零退出并给出原因**，绝不静默降级为明文。纯 --no-gui 路径由
        # _run_cli → _enable_tls 在引擎启动前执行同一校验（既有行为不变）。
        if config.tls.enabled and not args.no_gui:
            from core.transport.connection import (
                TlsConfigError,
                build_context_from_config,
            )

            try:
                build_context_from_config(config.tls, role)
            except TlsConfigError as e:
                logger.error(f"TLS 配置无效，拒绝启动（不降级明文）: {e}")
                return 2

        # Web UI 模式（主站/子站）—— role 已在上方历史库接线处解析
        connection = {
            "host": config.connection.host,
            "port": config.connection.port,
            "addr": config.connection.common_addr,
        }
        run_web(mode, args.http_port, open_browser=not args.no_browser,
                point_table=point_table, connection=connection,
                history_db=history_db, history_dbs=history_dbs, engine_config=config,
                http_host=args.http_host, auth_token=args.auth_token,
                web_tls_cert=args.web_tls_cert, web_tls_key=args.web_tls_key)
        return 0
    finally:
        # 保证异常路径也会关闭历史数据库（合并模式两个角色各一个）
        for db in set(history_dbs.values()):
            db.close()
        if history_db is not None and history_db not in history_dbs.values():
            history_db.close()


def _run_bridge(args, logger) -> int:
    """透明桥模式（T73）：真实主站 ↔ 测试器 ↔ 真实子站.

    字节级透传 + 旁路观察（每帧打点日志：方向 + APCI/ASDU 摘要）；
    ``--capture-file`` 可选旁路录制（复用 CaptureRecorder，按扩展名分派格式）。
    现场排障用法：子站地址不动，主站改连桥监听口::

        python app.py --mode bridge --listen-port 2404 \\
            --upstream-host 192.168.1.9 --upstream-port 2404 \\
            --capture-file bridge.pcap
    """
    import asyncio

    from core.engine.tcp_bridge import BridgeConfig, TcpBridge, describe_frame

    cfg = BridgeConfig(
        listen_host=args.listen_host or "0.0.0.0",
        listen_port=args.listen_port or 2404,
        upstream_host=args.upstream_host,
        upstream_port=args.upstream_port or 2404,
    )

    async def run():
        recorder = None  # PacketRecorder（可选 --capture-file）

        def on_frame(data: bytes, direction: str, client_id: str) -> None:
            tag = "主站→子站" if direction == "tx" else "子站→主站"
            logger.info("[%s] %s %s (%dB)", client_id, tag, describe_frame(data), len(data))
            if recorder is not None:
                recorder.record_frame(data, direction, metadata={"client_id": client_id})

        bridge = TcpBridge(cfg, on_frame=on_frame)
        try:
            await bridge.start()
        except OSError as e:
            # 监听端口被占等绑定失败：给一行人话，不甩 traceback
            logger.error(
                "桥接监听失败 %s:%d: %s（端口被占用或无权限）",
                cfg.listen_host, cfg.listen_port, e)
            return 1
        print(
            f"桥接已启动: 主站 → {cfg.listen_host}:{bridge.listen_port} "
            f"→ 子站 {cfg.upstream_host}:{cfg.upstream_port}（Ctrl+C 停止）",
            flush=True,
        )
        if args.capture_file:
            from core.capture.recorder import PacketRecorder

            recorder = PacketRecorder()
            recorder.start(
                args.capture_file,
                description=f"bridge {cfg.listen_port}→{cfg.upstream_host}:{cfg.upstream_port}",
            )
            print(f"旁路录制: {args.capture_file}", flush=True)
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await bridge.stop()
            if recorder is not None:
                recorder.stop()

    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Bridge stopped by user")
        return 0


def _run_tests(script_path: str, logger, report_dir: str = "test_reports") -> int:
    """运行自动化测试脚本，返回进程退出码."""
    import asyncio

    from core.testing import ReportGenerator, TestRunner

    async def run():
        out_dir = Path(report_dir)
        runner = TestRunner(report_dir=str(out_dir))

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
        out_dir.mkdir(parents=True, exist_ok=True)
        for script in scripts:
            result = await runner.run(script)
            results.append(result)
            ReportGenerator.save(result, out_dir / f"{script.name}.txt", format="text")
            ReportGenerator.save(result, out_dir / f"{script.name}.json", format="json")
            ReportGenerator.save(result, out_dir / f"{script.name}.html", format="html")

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
                reconnect_interval=config.connection.reconnect_interval,
                # D4 修复：冗余双通道配置（--config YAML 的 redundancy 节）
                # 必须传入引擎，否则 enabled=True 被静默忽略（QA C8/D4）
                redundancy=config.redundancy,
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
                max_connections=config.connection.max_connections,
                point_table=point_table,
                spontaneous_enabled=config.slave.spontaneous_enabled,
            )
            engine.set_event_callback(on_event)
            engine.set_raw_frame_callback(on_frame)

            # 初始化数据
            engine.data_store.init_from_point_table(point_table)
            _enable_tls(engine, "slave", config, logger)

            await engine.start()

            # 数据模拟（收尾清理）：Web 模式经 /api/slave/sim 运行时设置，
            # CLI no-gui 此前完全不吃 config.slave.simulation_*——现接线：
            # simulation_enabled=true 时按配置间隔启动自动模拟。
            if config.slave.simulation_enabled:
                await engine.start_simulation(
                    yx_interval=config.slave.yx_interval,
                    yc_interval=config.slave.yc_interval,
                    yx_change_rate=config.slave.yx_change_rate,
                    yc_change_range=config.slave.yc_change_range,
                )
                logger.info(
                    "Slave simulation started "
                    f"(yx={config.slave.yx_interval}s, yc={config.slave.yc_interval}s, "
                    f"yx_rate={config.slave.yx_change_rate}, yc_range={config.slave.yc_change_range})"
                )

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
