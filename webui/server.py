"""本地 Web 服务 — REST + WebSocket，供浏览器加载."""

from __future__ import annotations

import asyncio
import copy
import csv
import hmac
import io
import json
import logging
import ssl
import time
from pathlib import Path

import yaml
from aiohttp import WSMsgType, web

from core.data.scd_import import import_scd

from .bridge import EngineBridge
from .events import SCHEMA_VERSION
from .frame_translate import translate_hex

logger = logging.getLogger("iec104.webui")
STATIC = Path(__file__).parent / "static"
# 新前端（Vite/React）构建产物目录：webui/static/app/（T10）。
# 旧原生页（master.html/slave.html/js/css）已于 T19 退役并删除。
APP_STATIC = STATIC / "app"
# 项目资源目录（图标等）：webui/ 的上一级 resources/
RESOURCES = Path(__file__).parent.parent / "resources"

# 历史查询页参数上限：单次查询 1 万行（表格分页足够），CSV 导出 20 万行
# （更大导出请用 CLI capture_tool / 诊断包，避免浏览器内存压力）
HISTORY_QUERY_MAX_LIMIT = 10000
HISTORY_EXPORT_MAX_ROWS = 200000


def _empty_history_stats() -> dict:
    """未启用/无连接时的零值统计，形状与启用时一致（契约 §2.11/§4.9）.

    早期实现返回 ``stats: {}``，前端类型与契约却声明为完整 HistoryStats，
    属于“两侧各自自洽”的契约漂移；统一给零值后响应可被前端 schema 校验。
    """
    return {
        "data_records": 0,
        "frame_records": 0,
        "buffered_data": 0,
        "buffered_frames": 0,
        "oldest_data": 0,
        "newest_data": 0,
        "db_size_bytes": 0,
        "dropped_records": 0,
    }

# 安全响应头（E4）：静态 SPA + REST/WS 同源。
# - CSP 允许 antd CSS-in-JS 注入的 <style>（style-src 'unsafe-inline'），
#   但不允许内联/外部脚本；WS 与 REST 都走同源（localhost/局域网 IP）。
# - frame-ancestors/X-Frame-Options 防点击劫持；nosniff 防 MIME 嗅探。
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@web.middleware
async def security_headers(request: web.Request, handler) -> web.Response:
    """给所有响应补安全头（含 401/404）."""
    resp = await handler(request)
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if request.secure:
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resp


def create_web_ssl_context(certfile: str, keyfile: str | None = None) -> ssl.SSLContext:
    """构造 Web UI 的 TLS 服务端上下文（E4：HTTPS 监听）.

    仅用于浏览器 ↔ Web 服务；与控制链路 TLS（``core.transport.tls_context``）
    互不影响。最低 TLS 1.2，与 IEC 侧策略一致。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile, keyfile or None)
    return ctx



@web.middleware
async def no_cache_pages(request: web.Request, handler) -> web.Response:
    """页面与静态资源禁止启发式缓存.

    浏览器对没有 Cache-Control 的静态文件会按 Last-Modified 启发式缓存，
    前端修复（如按钮失效）可能长时间不生效，表现为"改了没用/要手动强刷"。
    本工具只在局域网调试使用，全部走协商缓存（no-cache 表示必须回源校验）。
    """
    resp = await handler(request)
    if request.path == "/" or request.path.startswith("/app"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


def _extract_token(request: web.Request) -> str:
    """从请求中提取访问令牌：Bearer 头 > X-Auth-Token 头 > ?token= 查询参数.

    WS 无法自定义请求头，浏览器侧必须用 query 形态；REST 优先用请求头。
    """
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("X-Auth-Token", "") or request.query.get("token", "")


def _validate_redundancy(cfg: dict) -> str | None:
    """校验 Web 端冗余配置字段；返回错误信息（None=通过）."""
    if "enabled" in cfg and not isinstance(cfg["enabled"], bool):
        return "invalid redundancy.enabled"
    if "standby_host" in cfg:
        if not isinstance(cfg["standby_host"], str) or not cfg["standby_host"].strip():
            return "invalid redundancy.standby_host"
    if "standby_port" in cfg:
        port = cfg["standby_port"]
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port <= 65535:
            return "invalid redundancy.standby_port"
    for key, low in (("switch_timeout", 0.0), ("dedup_window", 0.0)):
        if key not in cfg:
            continue
        value = cfg[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"invalid redundancy.{key}"
        if (key == "switch_timeout" and float(value) <= low) or (
            key != "switch_timeout" and float(value) < low
        ):
            return f"invalid redundancy.{key}"
    return None


def create_app(bridge: EngineBridge, auth_token: str | None = None, *,
               path_prefix: str = "",
               available_roles: list[str] | None = None,
               slave_api_prefix: str | None = None) -> web.Application:
    """构造单个角色的 aiohttp 应用.

    单角色模式：``path_prefix=""``，API 在 ``/api/*``。
    合并模式：主站应用前缀为空；子站应用以 ``path_prefix="/slave"`` 挂到
    ``/slave/api/*``、``/slave/ws``（同一端口、同一进程，不再需要 8766）。
    """

    def _local_path(path: str) -> str:
        if path_prefix and path.startswith(path_prefix):
            return path[len(path_prefix):] or "/"
        return path

    @web.middleware
    async def token_auth(request: web.Request, handler) -> web.Response:
        """可选访问令牌（B7）：保护 /api/* 与 /ws；静态页放行供前端令牌提示.

        - 未配置 ``auth_token`` 时整体直通（默认行为，兼容旧用法）；
        - ``GET /api/auth`` 公开，供前端探测「是否需要令牌 / 当前令牌是否有效」；
        - 令牌比较用 ``hmac.compare_digest``（常数时间）。
        """
        if not auth_token:
            return await handler(request)
        path = _local_path(request.path)
        if not (path.startswith("/api/") or path == "/ws"):
            return await handler(request)
        if path == "/api/auth":
            return await handler(request)
        provided = _extract_token(request)
        if provided and hmac.compare_digest(provided, auth_token):
            return await handler(request)
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    app = web.Application(middlewares=[security_headers, no_cache_pages, token_auth])

    async def index(request: web.Request) -> web.Response:
        """旧原生页（master.html/slave.html）已退役（T19）：一律进新前端 /app/."""
        raise web.HTTPFound(f"{path_prefix}/app/")

    async def favicon(request: web.Request) -> web.Response:
        """返回项目图标，避免浏览器请求 /favicon.ico 时 404."""
        icon = RESOURCES / "icon.svg"
        if not icon.exists():
            return web.Response(status=404)
        return web.FileResponse(icon, headers={"Content-Type": "image/svg+xml"})

    # ── 新前端（Vite 产物）托管：/app/ ────────────────────────────────
    # 新前端产物托管；产物缺失时优雅 404 并给出构建提示。

    async def app_redirect(request: web.Request) -> web.Response:
        """`/app` → `/app/`：保证 Vite base 下的相对资源正确解析."""
        return web.HTTPFound(request.path + "/")

    async def app_index(request: web.Request) -> web.Response:
        index_file = APP_STATIC / "index.html"
        if not index_file.is_file():
            return web.Response(
                status=404,
                text=(
                    "前端产物缺失：请先执行 "
                    "`cd webui/frontend && npm ci && npm run build`"
                ),
                content_type="text/plain",
                charset="utf-8",
            )
        return web.FileResponse(index_file)

    async def app_asset(request: web.Request) -> web.Response:
        """托管 /app/ 下产物；未命中真实文件时回落 index.html（支持 SPA 前端路由）."""
        tail = request.match_info.get("tail", "")
        root = APP_STATIC.resolve()
        target = (root / tail).resolve()
        # 路径穿越防护：解析后必须仍在 root 之内
        if target != root and root not in target.parents:
            return web.Response(status=404, text="not found")
        if target.is_file():
            return web.FileResponse(target)
        return await app_index(request)

    async def api_status(request: web.Request) -> web.Response:
        # schemaVersion 供前端做契约版本协商（T18）；对旧消费者是新增键，向后兼容
        st = bridge.status()
        st["schemaVersion"] = SCHEMA_VERSION
        return web.json_response(st)

    async def api_schema(request: web.Request) -> web.Response:
        """契约版本探测入口（T18）：前端可先探测再决定是否降级渲染."""
        body = {
            "ok": True,
            "schemaVersion": SCHEMA_VERSION,
            "wsKinds": ["snapshot", "frame", "event", "log"],
            "wsSchemaKey": "schemaVersion",
            "roles": list(available_roles or [bridge.role]),
        }
        if slave_api_prefix:
            body["slaveApiPrefix"] = slave_api_prefix
        return web.json_response(body)

    async def api_auth(request: web.Request) -> web.Response:
        """认证探测（公开）：是否需要令牌、本次请求携带的令牌是否有效（B7）."""
        required = auth_token is not None
        valid = True
        if required:
            provided = _extract_token(request)
            valid = bool(provided) and hmac.compare_digest(provided, auth_token)
        return web.json_response({"ok": True, "required": required, "valid": valid})

    async def api_points(request: web.Request) -> web.Response:
        return web.json_response({"points": bridge.snapshot_points()})

    async def api_recent(request: web.Request) -> web.Response:
        return web.json_response({
            "frames": bridge.recent("frame", 200),
            "events": bridge.recent("event", 200),
        })

    async def api_frames_decode(request: web.Request) -> web.Response:
        """单帧逐段翻译（第二批体验改造 ④）：?hex=<hex> → {ok, format, segments}."""
        hex_str = request.query.get("hex", "")
        if not hex_str:
            return web.json_response({"ok": False, "error": "missing hex"}, status=400)
        if len(hex_str) > 4096:
            return web.json_response({"ok": False, "error": "hex too long"}, status=400)
        return web.json_response(translate_hex(hex_str))

    async def api_master_start(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        # 同 api_slave_start：缺省回落 config.connection（body 显式优先）
        conn = bridge.config.connection
        host = body.get("host", conn.host)
        if not isinstance(host, str):
            return web.json_response({"ok": False, "error": "invalid host"}, status=400)
        port = body.get("port", conn.port)
        if not isinstance(port, int) or port < 0 or port > 65535:
            return web.json_response({"ok": False, "error": "invalid port"}, status=400)
        addr = body.get("addr", conn.common_addr)
        if not isinstance(addr, int) or addr < 0:
            return web.json_response({"ok": False, "error": "invalid addr"}, status=400)
        gi_interval = body.get("gi_interval", 0)
        if not isinstance(gi_interval, (int, float)) or gi_interval < 0:
            return web.json_response({"ok": False, "error": "invalid gi_interval"},
                                     status=400)
        tls = body.get("tls")
        if tls is not None and not isinstance(tls, dict):
            return web.json_response({"ok": False, "error": "invalid tls"}, status=400)
        redundancy = body.get("redundancy")
        if redundancy is not None:
            if not isinstance(redundancy, dict):
                return web.json_response(
                    {"ok": False, "error": "invalid redundancy"}, status=400)
            err = _validate_redundancy(redundancy)
            if err:
                return web.json_response({"ok": False, "error": err}, status=400)
        r = await bridge.start_master(
            host,
            port,
            addr,
            bool(body.get("reconnect", True)),
            float(gi_interval),
            tls=tls,
            redundancy=redundancy,
        )
        return web.json_response(r)

    async def api_master_stop(request: web.Request) -> web.Response:
        return web.json_response(await bridge.stop_master())

    async def api_gi(request: web.Request) -> web.Response:
        body = {}
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                body = {}
        return web.json_response(await bridge.general_interrogation(int(body.get("qoi", 20))))

    async def api_yk(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        deactivate = body.get("deactivate", False)
        if not isinstance(deactivate, bool):
            return web.json_response({"ok": False, "error": "invalid deactivate"}, status=400)
        return web.json_response(await bridge.send_yk(
            ioa, body.get("state", 0),
            bool(body.get("select", False)), bool(body.get("double", False)),
            bool(body.get("with_time", False)), deactivate,
        ))

    async def api_step(request: web.Request) -> web.Response:
        """升降命令 (C_RC_NA_1)：state 1=降一步, 2=升一步."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        state = body.get("state")
        if not isinstance(ioa, int) or ioa < 0 or state not in (1, 2):
            return web.json_response(
                {"ok": False, "error": "invalid ioa/state (state 须为 1 或 2)"}, status=400)
        return web.json_response(await bridge.send_step_command(
            ioa, state, bool(body.get("select", False))))

    async def api_bitstring(request: web.Request) -> web.Response:
        """32 比特串命令 (C_BO_NA_1)."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa, value = body.get("ioa"), body.get("value")
        if not isinstance(ioa, int) or ioa < 0 or not isinstance(value, int) or value < 0:
            return web.json_response({"ok": False, "error": "invalid ioa/value"}, status=400)
        return web.json_response(await bridge.send_bitstring(ioa, value))

    async def api_delay(request: web.Request) -> web.Response:
        """延时获得命令 (C_CD_NA_1)."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        delay = body.get("delay_ms")
        if not isinstance(delay, int) or delay < 0 or delay > 60000:
            return web.json_response(
                {"ok": False, "error": "invalid delay_ms (0-60000)"}, status=400)
        return web.json_response(await bridge.send_delay_request(delay))

    async def api_sp(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        value = body.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid value"}, status=400)
        deactivate = body.get("deactivate", False)
        if not isinstance(deactivate, bool):
            return web.json_response({"ok": False, "error": "invalid deactivate"}, status=400)
        return web.json_response(await bridge.send_setpoint(
            ioa, value, bool(body.get("select", False)),
            str(body.get("kind", "short_float") or "short_float"),
            bool(body.get("with_time", False)), deactivate,
        ))

    async def api_alarms(request: web.Request) -> web.Response:
        return web.json_response(bridge.alarms.snapshot())

    async def api_alarms_history(request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        return web.json_response(bridge.alarms.history_list(limit))

    async def api_alarms_ack(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        alarm_id = body.get("id") if isinstance(body, dict) else None
        try:
            alarm_id = int(alarm_id)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "需要整数 id"}, status=400)
        return web.json_response({"ok": bridge.alarms.ack(alarm_id)})

    async def api_alarms_config(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        bridge.alarms.configure(**body)
        return web.json_response(bridge.alarms.snapshot())

    async def api_master_doctor(request: web.Request) -> web.Response:
        """连接医生（T94）：分层自检（TCP → STARTDT → 数据流），结论随报告附存."""
        from core.engine.doctor import run_doctor

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        host = str(body.get("host") or "").strip()
        try:
            port = int(body.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not host or not 0 < port < 65536:
            return web.json_response({"ok": False, "error": "需要 host 与有效 port"}, status=400)
        try:
            addr = int(body.get("addr") or 1)
        except (TypeError, ValueError):
            addr = 1
        try:
            observe = float(body.get("observe_seconds") or 3.0)
        except (TypeError, ValueError):
            observe = 3.0
        observe = max(1.0, min(observe, 10.0))
        report = await run_doctor(host, port, addr, observe_seconds=observe)
        payload = report.to_dict()
        # 测试报告附「连接诊断」段（最近一次诊断的证据）
        bridge.last_doctor = payload
        return web.json_response({"ok": payload["ok"], "report": payload})

    async def api_clock(request: web.Request) -> web.Response:
        return web.json_response(await bridge.clock_sync())

    async def api_ci(request: web.Request) -> web.Response:
        return web.json_response(await bridge.counter_interrogation())

    async def api_reset(request: web.Request) -> web.Response:
        return web.json_response(await bridge.reset_process())

    async def api_test(request: web.Request) -> web.Response:
        return web.json_response(await bridge.test_command())

    async def api_read(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        return web.json_response(await bridge.read_command(ioa))

    async def api_param(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        value = body.get("value", 0)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid value"}, status=400)
        return web.json_response(await bridge.parameter_command(
            body.get("kind", "float"), ioa,
            value, int(body.get("qualifier", 1)),
        ))

    async def api_param_state(request: web.Request) -> web.Response:
        """单个参数 IOA 的装载/激活状态快照（T08）: ?ioa=<int>."""
        raw = request.query.get("ioa")
        try:
            ioa = int(raw)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        if ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        return web.json_response(bridge.param_state(ioa))

    async def api_params(request: web.Request) -> web.Response:
        """全部已跟踪参数的状态快照列表（T08）."""
        return web.json_response(bridge.param_states())

    async def api_file(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        action = body.get("action", "")
        if not isinstance(action, str):
            return web.json_response({"ok": False, "error": "invalid action"}, status=400)
        ioa = body.get("ioa", 0)
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        file_name = body.get("file_name", 0)
        if not isinstance(file_name, int) or file_name < 0:
            return web.json_response({"ok": False, "error": "invalid file_name"}, status=400)
        return web.json_response(await bridge.file_action(action, ioa, file_name))

    async def api_points_yaml_get(request: web.Request) -> web.Response:
        try:
            text = bridge.export_points_yaml()
            # 前端「导出 YAML」用 window.open 直开：必须带 attachment，
            # 否则浏览器会内联展示文本而不是下载文件。
            return web.Response(
                text=text, content_type="text/yaml",
                headers={
                    "Content-Disposition":
                        f'attachment; filename="iec104_{bridge.role}_points.yaml"',
                })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})

    async def api_points_yaml_put(request: web.Request) -> web.Response:
        try:
            text = await request.text()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(bridge.import_points_yaml(text))

    async def api_points_import(request: web.Request) -> web.Response:
        """点表导入: ?format=csv|yaml|json|auto（auto 按内容嗅探）.

        约定 body 为原始文本；CSV 列格式见 ``PointService.export_csv``。
        """
        try:
            text = await request.text()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        fmt = (request.query.get("format") or "auto").lower()
        if fmt == "auto":
            first_line = text.splitlines()[0].strip().lower() if text.strip() else ""
            if text.lstrip().startswith("{"):
                fmt = "json"
            elif "," in first_line and "type" in first_line:
                fmt = "csv"
            else:
                fmt = "yaml"
        if fmt == "csv":
            return web.json_response(bridge.import_points_csv(text))
        if fmt == "json":
            try:
                data = json.loads(text)
            except Exception as e:
                return web.json_response({"ok": False, "error": f"JSON 解析失败: {e}"},
                                         status=400)
            # JSON 顶层键结构与 YAML 一致，序列化后复用 YAML 导入
            return web.json_response(bridge.import_points_yaml(json.dumps(data)))
        return web.json_response(bridge.import_points_yaml(text))

    async def api_export_csv(request: web.Request) -> web.Response:
        return web.Response(
            text=bridge.export_points_csv(), content_type="text/csv",
            headers={
                "Content-Disposition":
                    f'attachment; filename="iec104_{bridge.role}_points.csv"',
            })

    # ── T95：Excel(xlsx) 点表 + 设计基准 vs 实测比对 ───────────────────

    async def api_points_xlsx_get(request: web.Request) -> web.Response:
        try:
            data = bridge.export_points_xlsx()
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})
        return web.Response(
            body=data, content_type="application/octet-stream",
            headers={
                "Content-Disposition":
                    f'attachment; filename="iec104_{bridge.role}_points.xlsx"',
            })

    async def _read_xlsx_body(request: web.Request) -> bytes | None:
        try:
            data = await request.read()
        except Exception:
            return None
        return data if data else None

    async def api_points_xlsx_preview(request: web.Request) -> web.Response:
        """解析 xlsx（无副作用）：返回类型计数/行级错误/前 100 行摘要."""
        data = await _read_xlsx_body(request)
        if data is None:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(bridge.preview_points_xlsx(data))

    async def api_points_xlsx_import(request: web.Request) -> web.Response:
        """导入 xlsx（整表替换）并把导入结果快照为设计基准."""
        data = await _read_xlsx_body(request)
        if data is None:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(bridge.import_points_xlsx(data))

    async def api_points_design(request: web.Request) -> web.Response:
        """设计基准管理：{action: "set"|"clear"}——set 把当前点表快照为基准."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        action = str(body.get("action") or "")
        return web.json_response(bridge.set_design_baseline(action))

    async def api_points_design_diff(request: web.Request) -> web.Response:
        return web.json_response(bridge.design_points_diff())

    async def api_master_clock_offset(request: web.Request) -> web.Response:
        """时钟偏差测量（T80）：连发 N 次时钟同步，按子站确认时标计算偏差（ms）."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        samples = body.get("samples") or 5
        try:
            samples = max(1, min(int(samples), 20))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "samples 必须是整数"}, status=400)
        return web.json_response(await bridge.measure_clock_offset(samples))

    async def api_export_report(request: web.Request) -> web.Response:
        """会话测试报告（T75/T87）：自包含单文件 HTML，浏览器打印即 PDF 归档.

        GET: ``?title=&notes=&limit=&conclusion=&conclusion_kind=``；
        POST: JSON ``{title?, notes?, conclusion?, conclusion_kind?,
        chart_images?: [dataURL]}``（T87 曲线快照 base64 放 GET query 会超长）。
        数据源为当前缓冲（recent frames/events），不落盘、不改状态。
        """
        from .report import build_session_report_html

        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                return web.json_response({"ok": False, "error": "invalid body"}, status=400)
            title = body.get("title") or ""
            notes = body.get("notes") or ""
            conclusion = body.get("conclusion") or ""
            conclusion_kind = body.get("conclusion_kind") or ""
            limit = body.get("limit") or 300
            chart_images = body.get("chart_images") or []
        else:
            title = request.query.get("title") or ""
            notes = request.query.get("notes") or ""
            conclusion = request.query.get("conclusion") or ""
            conclusion_kind = request.query.get("conclusion_kind") or ""
            limit = request.query.get("limit") or 300
            chart_images = []
        try:
            limit = max(1, min(int(limit), 5000))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "limit 必须是整数"}, status=400)
        if not isinstance(chart_images, list):
            chart_images = []
        # 只接受 data:image/png;base64 前缀（防注入任意 HTML 属性内容）
        chart_images = [str(x) for x in chart_images
                        if isinstance(x, str) and x.startswith("data:image/png;base64,")][:4]
        lt = getattr(bridge, "loadtest", None)
        lt_summary = lt.last_summary() if lt is not None else None
        injection = None
        condition = ""
        if bridge.role == "bridge" and bridge.tcp_bridge is not None:
            injection = bridge.tcp_bridge.injection_stats()
            cond = bridge.tcp_bridge.config.condition
            condition = cond.describe() if cond is not None else ""
        comp = getattr(bridge, "compliance", None)
        comp_violations = comp.violation_list(50) if comp is not None else None
        timeline = (getattr(bridge, "timeline", None).last_result
                    if bridge.role == "bridge"
                    and getattr(bridge, "timeline", None) is not None else None)
        html_text = build_session_report_html(
            bridge.role, bridge.status(),
            bridge.recent("frame", 5000), bridge.recent("event", 2000),
            title=title, notes=notes, max_frames=limit,
            loadtest_summary=lt_summary, compliance_violations=comp_violations,
            conclusion=conclusion, conclusion_kind=conclusion_kind,
            injection=injection, condition=condition,
            chart_images=chart_images,
            doctor=getattr(bridge, "last_doctor", None),
            alarms=(bridge.alarms.history_records(100)
                    if getattr(bridge, "alarms", None) is not None else None),
            timeline=timeline)
        fname = time.strftime("iec104_report_%Y%m%d_%H%M%S.html")
        return web.Response(
            text=html_text, content_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    async def api_export_session(request: web.Request) -> web.Response:
        return web.json_response(
            bridge.export_session_json(),
            headers={
                "Content-Disposition":
                    f'attachment; filename="iec104_{bridge.role}_session.json"',
            })

    async def api_scd_preview(request: web.Request) -> web.Response:
        """SCD/CID/ICD（IEC 61850-6 SCL + 80-1 映射）→ 104 点表预览（无副作用）.

        body 为 SCL 原始 XML 文本；``?common_addr=`` 显式指定公共地址（缺省取
        SCD 中出现最多的 casdu）；``?station=`` 覆盖站名。返回生成的点表 YAML
        文本（可直接投给 ``/api/points/import?format=yaml``），**不修改当前点表**。
        """
        try:
            text = await request.text()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        kwargs: dict = {}
        common_addr = request.query.get("common_addr")
        if common_addr:
            try:
                kwargs["common_addr"] = int(common_addr)
            except ValueError:
                return web.json_response(
                    {"ok": False, "error": "common_addr 必须是整数"}, status=400)
        station = request.query.get("station")
        if station:
            kwargs["station_name"] = station
        try:
            result = import_scd(text, **kwargs)
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        return web.json_response({
            "ok": True,
            "yaml": yaml.safe_dump(result.points, allow_unicode=True, sort_keys=True),
            "station_name": result.station_name,
            "common_addr": result.common_addr,
            "stats": result.stats,
            "warnings": result.warnings,
        })

    async def api_bridge_start(request: web.Request) -> web.Response:
        """启动透明桥（T74）.

        body JSON: ``{listen_host?, listen_port?, upstream_host?, upstream_port?}``；
        缺省回填 0.0.0.0:2404 与 status 的 host/port（CLI ``--upstream-*`` 预填）。
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        listen_host = str(body.get("listen_host") or "0.0.0.0")
        if bridge.role != "bridge":
            return web.json_response(
                {"ok": False, "error": "仅 bridge 角色支持该操作"})
        upstream_host = str(body.get("upstream_host")
                            or bridge.config.connection.host or "127.0.0.1")
        try:
            listen_port = int(body.get("listen_port") or 2404)
            upstream_port = int(body.get("upstream_port")
                                or bridge.config.connection.port or 2404)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "端口必须是整数"}, status=400)
        if not (0 < listen_port < 65536 and 0 < upstream_port < 65536):
            return web.json_response({"ok": False, "error": "端口超出范围 1-65535"}, status=400)
        return web.json_response(await bridge.start_bridge(
            listen_host, listen_port, upstream_host, upstream_port))

    async def api_bridge_stop(request: web.Request) -> web.Response:
        if bridge.role != "bridge":
            return web.json_response(
                {"ok": False, "error": "仅 bridge 角色支持该操作"})
        return web.json_response(await bridge.stop_bridge())

    # ── T97：桥注入时间线 + 自动判定（仅 bridge 角色业务可用） ─────────

    async def api_bridge_timeline_get(request: web.Request) -> web.Response:
        return web.json_response(bridge.timeline_get())

    async def api_bridge_timeline_set(request: web.Request) -> web.Response:
        if bridge.role != "bridge":
            return web.json_response({"ok": False, "error": "仅 bridge 角色支持该操作"})
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        steps = body.get("steps") if isinstance(body, dict) else None
        return web.json_response(bridge.timeline_configure(steps))

    async def api_bridge_timeline_run(request: web.Request) -> web.Response:
        if bridge.role != "bridge":
            return web.json_response({"ok": False, "error": "仅 bridge 角色支持该操作"})
        return web.json_response(await bridge.timeline_run())

    async def api_bridge_timeline_stop(request: web.Request) -> web.Response:
        if bridge.role != "bridge":
            return web.json_response({"ok": False, "error": "仅 bridge 角色支持该操作"})
        return web.json_response(bridge.timeline_stop())

    async def api_bridge_condition_set(request: web.Request) -> web.Response:
        """设置桥网络条件（T85，仅 bridge 角色）：body 为 NetworkCondition 字段."""
        if bridge.role != "bridge":
            return web.json_response(
                {"ok": False, "error": "仅 bridge 角色支持该操作"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(bridge.set_bridge_condition(body))

    async def api_loadtest_start(request: web.Request) -> web.Response:
        """启动压测（T76；仅挂载了 LoadTestService 的 both 模式应用）.

        body JSON: ``{duration_s?, events_per_s?}``。
        """
        loadtest = getattr(bridge, "loadtest", None)
        if loadtest is None:
            # 200 + ok:false（业务拒绝语义）：巡检门禁把 4xx/5xx 一律计失败请求
            return web.json_response(
                {"ok": False, "error": "压测仅支持单进程双角色（both）模式"})
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        try:
            duration_s = float(body.get("duration_s") or 60.0)
            events_per_s = float(body.get("events_per_s") or 100.0)
            connections = int(body.get("connections") or 1)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "参数必须是数字"}, status=400)
        return web.json_response(await loadtest.start(duration_s, events_per_s, connections))

    async def api_loadtest_stop(request: web.Request) -> web.Response:
        loadtest = getattr(bridge, "loadtest", None)
        if loadtest is None:
            return web.json_response(
                {"ok": False, "error": "压测仅支持单进程双角色（both）模式"})
        return web.json_response(await loadtest.stop())

    async def api_loadtest_status(request: web.Request) -> web.Response:
        loadtest = getattr(bridge, "loadtest", None)
        if loadtest is None:
            return web.json_response(
                {"ok": False, "error": "压测仅支持单进程双角色（both）模式"})
        return web.json_response({"ok": True, **loadtest.status()})

    async def api_points_batch(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ptype = body.get("type", "")
        if not isinstance(ptype, str):
            return web.json_response({"ok": False, "error": "invalid type"}, status=400)
        ioas = body.get("ioas") or []
        if not isinstance(ioas, list) or not all(isinstance(i, int) for i in ioas):
            return web.json_response({"ok": False, "error": "invalid ioas"}, status=400)
        action = body.get("action", "")
        if not isinstance(action, str):
            return web.json_response({"ok": False, "error": "invalid action"}, status=400)
        group = body.get("group")
        if group is not None and not isinstance(group, int):
            return web.json_response({"ok": False, "error": "invalid group"}, status=400)
        r = bridge.batch_points(ptype, ioas, action, group)
        return web.json_response(r)

    async def api_slave_response(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(await bridge.set_response(body))

    async def api_slave_response_get(request: web.Request) -> web.Response:
        """读取当前子站应答行为（``ResponseBehavior``），供页面刷新后回填.

        返回与 ``POST /api/slave/response`` **请求体同构**的分组 dict
        （``delays``/``errors``/``quality``/``connection``），未启动时返回暂存/默认值。
        """
        return web.json_response(bridge.get_response())

    async def api_slave_ym(request: web.Request) -> web.Response:
        """累计量置数并自发上送 (M_IT_TB_1, COT=3)."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa, value = body.get("ioa"), body.get("value")
        if not isinstance(ioa, int) or ioa < 0 or not isinstance(value, int):
            return web.json_response({"ok": False, "error": "invalid ioa/value"}, status=400)
        return web.json_response(await bridge.slave_set_ym(ioa, value))

    async def api_slave_ep(request: web.Request) -> web.Response:
        """模拟继电保护设备事件上送 (M_EP_TD_1 / M_EP_TA_1, COT=3)."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        event_value = body.get("event_value", 1)
        if not isinstance(event_value, int) or not (0 <= event_value <= 0xFFFF):
            return web.json_response({"ok": False, "error": "invalid event_value"}, status=400)
        return web.json_response(await bridge.slave_protection_event(
            ioa, event_value, bool(body.get("with_time", True))))

    async def api_slave_ps(request: web.Request) -> web.Response:
        """模拟带状态检出的成组单点信息上送 (M_PS_NA_1, COT=3).

        states: 长度 1-8 的 0/1 数组，[状态, 检出位] 各占一个字节。
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        states = body.get("states")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        if (not isinstance(states, list) or not states
                or len(states) > 8 or not all(isinstance(v, int) and v in (0, 1) for v in states)):
            return web.json_response(
                {"ok": False, "error": "invalid states (须为 1-8 个 0/1)"}, status=400)
        return web.json_response(await bridge.slave_group_single_point(ioa, states))

    async def api_logs(request: web.Request) -> web.Response:
        """结构化日志查询: ?level_min=WARNING&category=connection&q=xxx&limit=200."""
        rows = bridge.query_logs(
            level_min=request.query.get("level_min", "DEBUG"),
            source=request.query.get("source") or None,
            category=request.query.get("category") or None,
            contains=request.query.get("q") or None,
            limit=min(int(request.query.get("limit", 200) or 200), 2000),
        )
        return web.json_response({"ok": True, "logs": rows,
                                  "stats": bridge.log_stats()})

    async def api_logs_export(request: web.Request) -> web.Response:
        """导出全部内存日志为 JSONL 下载."""
        rows = bridge.query_logs(limit=100000, newest_first=False)
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        name = f"iec104_{bridge.role}_logs.jsonl"
        return web.Response(
            body=payload, content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ── 历史库查询（历史查询页，api_contract.md §2.11）─────────────────

    def _parse_history_query(request: web.Request, max_limit: int) -> tuple[dict, str | None]:
        """解析历史查询公共参数（start/end/limit）；返回 (kwargs, 错误信息)."""
        kwargs: dict = {"limit": 500}
        for key, field in (("start", "start_time"), ("end", "end_time")):
            raw = request.query.get(key, "")
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                return {}, f"invalid {key}"
            if value < 0:
                return {}, f"invalid {key}"
            kwargs[field] = value
        raw_limit = request.query.get("limit", "")
        if raw_limit:
            try:
                limit = int(raw_limit)
            except ValueError:
                return {}, "invalid limit"
            if limit <= 0:
                return {}, "invalid limit"
            kwargs["limit"] = min(limit, max_limit)
        return kwargs, None

    def _parse_history_ioa(request: web.Request) -> tuple[int, web.Response | None]:
        """解析可选 ioa 参数；返回 (ioa, 错误响应)（无参数时 ioa=-1 表示不过滤）."""
        raw = request.query.get("ioa", "")
        if not raw:
            return -1, None
        try:
            ioa = int(raw)
        except ValueError:
            return -1, web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        if ioa < 0:
            return -1, web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        return ioa, None

    async def api_history_stats(request: web.Request) -> web.Response:
        """历史库统计（未启用时 enabled=false）."""
        db = bridge.history_db
        if db is None:
            return web.json_response({"ok": True, "enabled": False, "stats": _empty_history_stats()})
        try:
            stats = db.get_stats() or _empty_history_stats()
        except Exception as e:
            return web.json_response(
                {"ok": False, "error": f"history stats failed: {e}"}, status=500)
        return web.json_response({"ok": True, "enabled": True, "stats": stats})

    async def api_history_data(request: web.Request) -> web.Response:
        """数据历史查询: ?point_type=yx&ioa=100&start=<epoch秒>&end=<epoch秒>&limit=500."""
        db = bridge.history_db
        if db is None:
            return web.json_response({"ok": True, "enabled": False, "rows": []})
        kwargs, err = _parse_history_query(request, HISTORY_QUERY_MAX_LIMIT)
        if err:
            return web.json_response({"ok": False, "error": err}, status=400)
        ioa, err_resp = _parse_history_ioa(request)
        if err_resp is not None:
            return err_resp
        rows = db.query_data(
            point_type=request.query.get("point_type") or "",
            ioa=ioa,
            **kwargs,
        )
        return web.json_response({"ok": True, "enabled": True, "rows": [
            {"id": r.id, "ts": r.timestamp, "point_type": r.point_type,
             "ioa": r.ioa, "value": r.value, "quality": r.quality, "source": r.source}
            for r in rows
        ]})

    async def api_history_frames(request: web.Request) -> web.Response:
        """报文历史查询: ?direction=rx&start=<epoch秒>&end=<epoch秒>&limit=500."""
        db = bridge.history_db
        if db is None:
            return web.json_response({"ok": True, "enabled": False, "rows": []})
        kwargs, err = _parse_history_query(request, HISTORY_QUERY_MAX_LIMIT)
        if err:
            return web.json_response({"ok": False, "error": err}, status=400)
        rows = db.query_frames(
            direction=request.query.get("direction") or "",
            **kwargs,
        )
        return web.json_response({"ok": True, "enabled": True, "rows": [
            {"id": r.id, "ts": r.timestamp, "direction": r.direction,
             "frame_type": r.frame_type, "hex": r.hex_data, "parsed": r.parsed,
             "client": r.client_id}
            for r in rows
        ]})

    async def api_history_export(request: web.Request) -> web.Response:
        """历史记录导出 CSV 下载: ?type=data|frames&（同查询过滤参数）."""
        db = bridge.history_db
        if db is None:
            return web.json_response(
                {"ok": False, "error": "history disabled (--no-history)"}, status=400)
        kind = request.query.get("type", "data")
        if kind not in ("data", "frames"):
            return web.json_response({"ok": False, "error": "invalid type"}, status=400)
        kwargs, err = _parse_history_query(request, HISTORY_EXPORT_MAX_ROWS)
        if err:
            return web.json_response({"ok": False, "error": err}, status=400)

        buf = io.StringIO()
        writer = csv.writer(buf)
        if kind == "data":
            ioa, err_resp = _parse_history_ioa(request)
            if err_resp is not None:
                return err_resp
            rows = db.query_data(
                point_type=request.query.get("point_type") or "",
                ioa=ioa,
                **kwargs,
            )
            writer.writerow(["时间戳", "类型", "IOA", "值", "品质", "来源"])
            for r in rows:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp)),
                    r.point_type, r.ioa, r.value, r.quality, r.source,
                ])
        else:
            rows = db.query_frames(
                direction=request.query.get("direction") or "",
                **kwargs,
            )
            writer.writerow(["时间戳", "方向", "帧类型", "HEX数据", "解析", "客户端"])
            for r in rows:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp)),
                    r.direction, r.frame_type, r.hex_data, r.parsed, r.client_id,
                ])
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"iec104_{bridge.role}_history_{kind}_{stamp}.csv"
        return web.Response(
            body=buf.getvalue(), content_type="text/csv", charset="utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def api_diagnostics_export(request: web.Request) -> web.Response:
        """一键诊断包：状态/配置/日志/报文/事件/点表/历史库统计打包下载."""
        from .diagnostics import build_diagnostics_zip

        body = build_diagnostics_zip(bridge)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"iec104_{bridge.role}_diagnostics_{stamp}.zip"
        return web.Response(
            body=body, content_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ── 网络异常模拟（B6，api_contract.md §2.12）────────────────────────

    async def api_network_simulation_get(request: web.Request) -> web.Response:
        """网络异常模拟状态（条件/安装态/统计/预设名）."""
        return web.json_response(bridge.network_simulation_status())

    async def api_network_simulation_set(request: web.Request) -> web.Response:
        """启用/停用网络异常模拟，可携带 preset 或自定义 condition."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            return web.json_response({"ok": False, "error": "invalid enabled"}, status=400)
        preset = body.get("preset")
        if preset is not None and not isinstance(preset, str):
            return web.json_response({"ok": False, "error": "invalid preset"}, status=400)
        condition = body.get("condition")
        if condition is not None and not isinstance(condition, dict):
            return web.json_response(
                {"ok": False, "error": "invalid condition"}, status=400)
        result = await bridge.set_network_simulation(
            enabled, preset=preset, condition=condition)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_network_simulation_reset(request: web.Request) -> web.Response:
        """重置网络模拟统计计数."""
        return web.json_response(bridge.reset_network_simulation_stats())

    async def api_network_simulation_disconnect(request: web.Request) -> web.Response:
        """手动触发一次断线（时长秒，默认 5）."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        duration = body.get("duration", 5.0)
        result = bridge.network_simulation_disconnect(duration)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_slave_sim(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(await bridge.set_simulation(
            bool(body.get("enabled")),
            **{
                k: body[k]
                for k in (
                    "yx_interval", "yc_interval", "yx_change_rate", "yc_change_range",
                    # 第二批改造⑤：范围模式（YX/YC 独立）——scope + 选中点集
                    "yx_scope", "yc_scope", "yx_ioas", "yc_ioas",
                    # 模拟类型开关（只模拟遥信 / 只模拟遥测）
                    "yx_enabled", "yc_enabled",
                )
                if k in body
            },
        ))

    async def api_slave_start(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        # 端口/地址缺省回落 CLI --port 与 --config（接线审计补漏，同 D3 类）：
        # body 显式传入 > config.connection（app.py 已把 --port/--host 写入）
        conn = bridge.config.connection
        host = body.get("host", "0.0.0.0")
        if not isinstance(host, str):
            return web.json_response({"ok": False, "error": "invalid host"}, status=400)
        port = body.get("port", conn.port)
        if not isinstance(port, int) or port < 0 or port > 65535:
            return web.json_response({"ok": False, "error": "invalid port"}, status=400)
        addr = body.get("addr", conn.common_addr)
        if not isinstance(addr, int) or addr < 0:
            return web.json_response({"ok": False, "error": "invalid addr"}, status=400)
        tls = body.get("tls")
        if tls is not None and not isinstance(tls, dict):
            return web.json_response({"ok": False, "error": "invalid tls"}, status=400)
        return web.json_response(await bridge.start_slave(host, port, addr, tls=tls))

    async def api_slave_stop(request: web.Request) -> web.Response:
        return web.json_response(await bridge.stop_slave())

    async def api_slave_yx(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        value = body.get("value")
        if not isinstance(value, bool):
            return web.json_response({"ok": False, "error": "invalid value"}, status=400)
        return web.json_response(await bridge.slave_set_yx(ioa, value))

    async def api_slave_yc(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        value = body.get("value")
        try:
            value = float(value)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid value"}, status=400)
        return web.json_response(await bridge.slave_set_yc(ioa, value))

    async def api_slave_step(request: web.Request) -> web.Response:
        """步位置置数并自发上送 (M_ST_TB_1, COT=3)（T09）."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        ioa = body.get("ioa")
        if not isinstance(ioa, int) or ioa < 0:
            return web.json_response({"ok": False, "error": "invalid ioa"}, status=400)
        value = body.get("value")
        if not isinstance(value, int) or not (-64 <= value <= 63):
            return web.json_response(
                {"ok": False, "error": "invalid value (须为 -64..63 的整数)"}, status=400)
        return web.json_response(await bridge.slave_set_step(ioa, value))

    # ── 多站（T16）────────────────────────────────────────────────

    async def api_multi_start(request: web.Request) -> web.Response:
        """创建并启动多站管理器: body {stations: [StationConfig, ...]}."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        stations = body.get("stations")
        if not isinstance(stations, list) or not stations:
            return web.json_response(
                {"ok": False, "error": "invalid stations (须为非空数组)"}, status=400)
        for s in stations:
            if not isinstance(s, dict):
                return web.json_response(
                    {"ok": False, "error": "invalid station entry"}, status=400)
            if not isinstance(s.get("station_id"), str) or not s.get("station_id"):
                return web.json_response(
                    {"ok": False, "error": "station_id required"}, status=400)
            port = s.get("port", 2404)
            if not isinstance(port, int) or port < 0 or port > 65535:
                return web.json_response(
                    {"ok": False, "error": "invalid port"}, status=400)
        return web.json_response(await bridge.multi_start(stations))

    async def api_multi_stop(request: web.Request) -> web.Response:
        return web.json_response(await bridge.multi_stop())

    async def api_multi_status(request: web.Request) -> web.Response:
        return web.json_response(bridge.multi_status())

    async def api_multi_summary(request: web.Request) -> web.Response:
        return web.json_response(bridge.multi_summary())

    # ── 报文录制/回放（E2）───────────────────────────────────────────

    async def api_capture_status(request: web.Request) -> web.Response:
        return web.json_response(bridge.captures.status())

    async def api_capture_start(request: web.Request) -> web.Response:
        body = {}
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        name = body.get("name")
        if name is not None and not isinstance(name, str):
            return web.json_response({"ok": False, "error": "invalid name"}, status=400)
        result = bridge.captures.start(name)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_stop(request: web.Request) -> web.Response:
        result = bridge.captures.stop()
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_pause(request: web.Request) -> web.Response:
        result = bridge.captures.pause()
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_resume(request: web.Request) -> web.Response:
        result = bridge.captures.resume()
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_files(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "files": bridge.captures.list_files()})

    async def api_capture_download(request: web.Request) -> web.Response:
        name = request.match_info.get("name", "")
        path = bridge.captures.download_path(name)
        if path is None:
            return web.json_response({"ok": False, "error": "file not found"}, status=404)
        return web.FileResponse(path, headers={
            "Content-Disposition": f'attachment; filename="{path.name}"'})

    async def api_capture_export(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        name, fmt = body.get("name"), body.get("format")
        if not isinstance(name, str) or not isinstance(fmt, str):
            return web.json_response({"ok": False, "error": "invalid name/format"}, status=400)
        result = bridge.captures.export(name, fmt)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_load(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str):
            return web.json_response({"ok": False, "error": "invalid name"}, status=400)
        result = bridge.captures.load(name)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_frames(request: web.Request) -> web.Response:
        try:
            offset = int(request.query.get("offset", 0) or 0)
            limit = int(request.query.get("limit", 200) or 200)
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid offset/limit"}, status=400)
        result = bridge.captures.frames(offset, limit)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_diff(request: web.Request) -> web.Response:
        """两段录制对比（T96）：body {a, b, max_entries?}——签名级多重集 diff."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        name_a = body.get("a") if isinstance(body, dict) else None
        name_b = body.get("b") if isinstance(body, dict) else None
        if not isinstance(name_a, str) or not isinstance(name_b, str) or not name_a or not name_b:
            return web.json_response({"ok": False, "error": "invalid a/b"}, status=400)
        try:
            max_entries = int(body.get("max_entries") or 200)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid max_entries"}, status=400)
        result = bridge.captures.diff_files(
            name_a, name_b, max_entries=min(500, max(1, max_entries)))
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_play(request: web.Request) -> web.Response:
        body = {}
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        try:
            speed = float(body.get("speed", 1.0))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "invalid speed"}, status=400)
        result = bridge.captures.play(speed)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_playback_stop(request: web.Request) -> web.Response:
        return web.json_response(bridge.captures.stop_playback())

    async def api_capture_playback_pause(request: web.Request) -> web.Response:
        result = bridge.captures.pause_playback()
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_capture_step(request: web.Request) -> web.Response:
        body = {}
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                body = {}
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        result = bridge.captures.step(str(body.get("direction", "forward")))
        return web.json_response(result, status=200 if result.get("ok") else 400)

    # ── 自动化测试中心（E1）─────────────────────────────────────────

    async def api_tests_scripts(request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "scripts": bridge.testcenter.list_scripts()})

    async def api_tests_run(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        scripts = body.get("scripts") if isinstance(body, dict) else None
        if not isinstance(scripts, list) or not all(isinstance(s, str) for s in scripts):
            return web.json_response(
                {"ok": False, "error": "scripts 须为字符串数组"}, status=400)
        result = bridge.testcenter.start(scripts)
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_tests_stop(request: web.Request) -> web.Response:
        result = bridge.testcenter.stop()
        return web.json_response(result, status=200 if result.get("ok") else 400)

    async def api_tests_status(request: web.Request) -> web.Response:
        return web.json_response(bridge.testcenter.status())

    async def api_tests_report(request: web.Request) -> web.Response:
        run_id = request.match_info.get("run_id", "")
        name = request.match_info.get("name", "")
        path = bridge.testcenter.report_path(run_id, name)
        if path is None:
            return web.json_response({"ok": False, "error": "report not found"}, status=404)
        return web.FileResponse(path, headers={
            "Content-Disposition": f'attachment; filename="{path.name}"'})

    async def ws_feed(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        q = bridge.subscribe()
        # 先推快照（snapshot 必须先行：前端据此对齐后再生效增量）
        await ws.send_json({"kind": "snapshot", "schemaVersion": SCHEMA_VERSION, "data": {
            "schemaVersion": SCHEMA_VERSION,
            "points": bridge.snapshot_points(),
            "status": {**bridge.status(), "schemaVersion": SCHEMA_VERSION},
            "frames": bridge.recent("frame", 50),
            "events": bridge.recent("event", 50),
            "logs": bridge.recent_logs(80),
        }})
        try:
            while True:
                get_task = asyncio.create_task(q.get())
                recv_task = asyncio.create_task(ws.receive())
                done, pending = await asyncio.wait(
                    {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
                if get_task in done:
                    try:
                        await ws.send_json(get_task.result())
                    except Exception:
                        break
                if recv_task in done:
                    try:
                        msg = recv_task.result()
                    except Exception:
                        # 客户端断开（含浏览器直接关标签页）属正常退出，
                        # 不能让 RuntimeError 冒泡成 500 日志噪音
                        break
                    if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
                    if msg.type == WSMsgType.TEXT:
                        # 前端可请求刷新
                        if msg.data == "refresh":
                            await ws.send_json({
                                "kind": "snapshot",
                                "schemaVersion": SCHEMA_VERSION,
                                "data": {
                                    "schemaVersion": SCHEMA_VERSION,
                                    "points": bridge.snapshot_points(),
                                    "status": {**bridge.status(),
                                               "schemaVersion": SCHEMA_VERSION},
                                },
                            })
        finally:
            bridge.unsubscribe(q)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/api/schema", api_schema)
    app.router.add_get("/api/auth", api_auth)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/points", api_points)
    app.router.add_get("/api/recent", api_recent)
    app.router.add_get("/api/frames/decode", api_frames_decode)
    # 桥启停端点在所有角色应用上注册（契约单一表）；非 bridge 角色在
    # handler 层业务拒绝。桥应用则跳过引擎专属路由（见 else 分支注释）。
    app.router.add_post("/api/bridge/start", api_bridge_start)
    app.router.add_post("/api/bridge/stop", api_bridge_stop)
    app.router.add_post("/api/bridge/condition", api_bridge_condition_set)
    app.router.add_get("/api/bridge/timeline", api_bridge_timeline_get)
    app.router.add_post("/api/bridge/timeline", api_bridge_timeline_set)
    app.router.add_post("/api/bridge/timeline/run", api_bridge_timeline_run)
    app.router.add_post("/api/bridge/timeline/stop", api_bridge_timeline_stop)
    if bridge.role != "bridge":
        app.router.add_post("/api/master/start", api_master_start)
        app.router.add_post("/api/master/stop", api_master_stop)
        app.router.add_post("/api/master/gi", api_gi)
        app.router.add_post("/api/master/yk", api_yk)
        app.router.add_post("/api/master/setpoint", api_sp)
        app.router.add_post("/api/master/step", api_step)
        app.router.add_post("/api/master/bitstring", api_bitstring)
        app.router.add_post("/api/master/delay", api_delay)
        app.router.add_post("/api/master/clock", api_clock)
        app.router.add_post("/api/master/ci", api_ci)
        app.router.add_post("/api/master/reset", api_reset)
        app.router.add_post("/api/master/test", api_test)
        app.router.add_post("/api/master/read", api_read)
        app.router.add_post("/api/master/param", api_param)
        app.router.add_get("/api/master/param_state", api_param_state)
        app.router.add_get("/api/master/params", api_params)
        app.router.add_post("/api/master/file", api_file)
        app.router.add_post("/api/master/clock_offset", api_master_clock_offset)
        app.router.add_post("/api/master/doctor", api_master_doctor)
        # 值守告警（T93）：master/slave 角色各一个服务（bridge 角色无引擎不评估）
        app.router.add_get("/api/alarms", api_alarms)
        app.router.add_get("/api/alarms/history", api_alarms_history)
        app.router.add_post("/api/alarms/ack", api_alarms_ack)
        app.router.add_post("/api/alarms/config", api_alarms_config)
        app.router.add_post("/api/points/yaml", api_points_yaml_put)
        app.router.add_post("/api/points/import", api_points_import)
        app.router.add_post("/api/points/xlsx/preview", api_points_xlsx_preview)
        app.router.add_post("/api/points/xlsx/import", api_points_xlsx_import)
        app.router.add_post("/api/points/design", api_points_design)
        app.router.add_get("/api/points/design-diff", api_points_design_diff)
        app.router.add_post("/api/points/batch", api_points_batch)
        app.router.add_post("/api/slave/start", api_slave_start)
        app.router.add_post("/api/slave/stop", api_slave_stop)
        app.router.add_post("/api/slave/yx", api_slave_yx)
        app.router.add_post("/api/slave/yc", api_slave_yc)
        app.router.add_post("/api/slave/ym", api_slave_ym)
        app.router.add_post("/api/slave/step", api_slave_step)
        app.router.add_post("/api/slave/ep", api_slave_ep)
        app.router.add_post("/api/slave/ps", api_slave_ps)
        app.router.add_post("/api/slave/response", api_slave_response)
        app.router.add_get("/api/slave/response", api_slave_response_get)
        app.router.add_post("/api/slave/sim", api_slave_sim)
        app.router.add_post("/api/multi/start", api_multi_start)
        app.router.add_post("/api/multi/stop", api_multi_stop)
    app.router.add_get("/api/points/yaml", api_points_yaml_get)
    app.router.add_get("/api/points/xlsx", api_points_xlsx_get)
    app.router.add_post("/api/scd/preview", api_scd_preview)
    app.router.add_get("/api/export/points.csv", api_export_csv)
    app.router.add_get("/api/export/session.json", api_export_session)
    app.router.add_get("/api/export/report.html", api_export_report)
    app.router.add_post("/api/export/report.html", api_export_report)
    app.router.add_get("/api/logs", api_logs)
    app.router.add_get("/api/logs/export", api_logs_export)
    app.router.add_get("/api/diagnostics/export", api_diagnostics_export)
    app.router.add_get("/api/history/stats", api_history_stats)
    app.router.add_get("/api/history/data", api_history_data)
    app.router.add_get("/api/history/frames", api_history_frames)
    app.router.add_get("/api/history/export", api_history_export)
    app.router.add_get("/api/tests/scripts", api_tests_scripts)
    app.router.add_post("/api/tests/run", api_tests_run)
    app.router.add_post("/api/tests/stop", api_tests_stop)
    app.router.add_get("/api/tests/status", api_tests_status)
    app.router.add_get("/api/tests/reports/{run_id}/{name}", api_tests_report)
    app.router.add_get("/api/capture/status", api_capture_status)
    app.router.add_post("/api/capture/start", api_capture_start)
    app.router.add_post("/api/capture/stop", api_capture_stop)
    app.router.add_post("/api/capture/pause", api_capture_pause)
    app.router.add_post("/api/capture/resume", api_capture_resume)
    app.router.add_get("/api/capture/files", api_capture_files)
    app.router.add_get("/api/capture/download/{name}", api_capture_download)
    app.router.add_post("/api/capture/export", api_capture_export)
    app.router.add_post("/api/capture/load", api_capture_load)
    app.router.add_get("/api/capture/frames", api_capture_frames)
    app.router.add_post("/api/capture/diff", api_capture_diff)
    app.router.add_post("/api/capture/play", api_capture_play)
    app.router.add_post("/api/capture/playback/stop", api_capture_playback_stop)
    app.router.add_post("/api/capture/playback/pause", api_capture_playback_pause)
    app.router.add_post("/api/capture/step", api_capture_step)
    if bridge.role != "bridge":
        app.router.add_get("/api/simulation", api_network_simulation_get)
        app.router.add_post("/api/simulation", api_network_simulation_set)
        app.router.add_post("/api/simulation/reset", api_network_simulation_reset)
        app.router.add_post("/api/simulation/disconnect", api_network_simulation_disconnect)
    # 压测端点在所有角色应用上注册（契约单一表）；非 both 部署无编排服务，
    # handler 返回 404 JSON（见 §2.4b 注）
    app.router.add_post("/api/loadtest/start", api_loadtest_start)
    app.router.add_post("/api/loadtest/stop", api_loadtest_stop)
    app.router.add_get("/api/loadtest/status", api_loadtest_status)
    app.router.add_get("/api/multi/status", api_multi_status)
    app.router.add_get("/api/multi/summary", api_multi_summary)
    app.router.add_get("/ws", ws_feed)
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", app_index)
    app.router.add_get("/app/{tail:.*}", app_asset)
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_get("/favicon.svg", favicon)

    if bridge.role != "bridge":
        from .alarms import AlarmService

        bridge.alarms = AlarmService(bridge)

        async def _start_alarms(app: web.Application) -> None:
            app["alarms_task"] = asyncio.ensure_future(bridge.alarms.loop())

        async def _stop_alarms(app: web.Application) -> None:
            task = app.get("alarms_task")
            if task is not None:
                task.cancel()

        app.on_startup.append(_start_alarms)
        app.on_cleanup.append(_stop_alarms)

    return app


async def _run(role: str, host: str = "127.0.0.1", port: int = 8765,
               point_table=None, connection: dict | None = None,
               history_db=None, app_config=None,
               auth_token: str | None = None,
               ssl_context: ssl.SSLContext | None = None) -> None:
    if auth_token is None and host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Web UI 监听 %s 且未启用访问令牌：局域网内任何主机都可能调用 REST/WS"
            "（含遥控、点表下发）。请用 --auth-token <token> 启用认证，"
            "或改回 --http-host 127.0.0.1。", host)
    bridge = EngineBridge(role, point_table=point_table, connection=connection,
                          history_db=history_db, app_config=app_config)
    if role != "bridge":
        bridge.ensure_demo_points()
    app = create_app(bridge, auth_token=auth_token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
    await site.start()
    logger.info("Web UI http://%s:%s  role=%s", host, port, role)
    try:
        await asyncio.Event().wait()
    finally:
        await bridge.shutdown()
        await runner.cleanup()


async def _run_dual(host: str = "127.0.0.1", port: int = 8765,
                    point_table=None, connection: dict | None = None,
                    history_dbs: dict | None = None, app_config=None,
                    auth_token: str | None = None,
                    ssl_context: ssl.SSLContext | None = None) -> None:
    """单进程双角色：同一端口托管主站 + 子站（子站 API/WS 在 /slave 前缀）.

    两个角色的引擎、历史库、日志仍相互独立；普通用户只接触一个 HTTP 端口。
    """
    if auth_token is None and host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Web UI 监听 %s 且未启用访问令牌：局域网内任何主机都可能调用 REST/WS"
            "（含遥控、点表下发）。请用 --auth-token <token> 启用认证，"
            "或改回 --http-host 127.0.0.1。", host)
    dbs = history_dbs or {}
    master_bridge = EngineBridge(
        "master",
        point_table=point_table.clone() if point_table is not None else None,
        connection=connection,
        history_db=dbs.get("master"),
        app_config=copy.deepcopy(app_config) if app_config is not None else None,
    )
    slave_bridge = EngineBridge(
        "slave",
        point_table=point_table.clone() if point_table is not None else None,
        connection=connection,
        history_db=dbs.get("slave"),
        app_config=copy.deepcopy(app_config) if app_config is not None else None,
    )
    master_bridge.ensure_demo_points()
    slave_bridge.ensure_demo_points()

    # 压测编排（T76）：both 模式独有——双桥都在本进程，挂在主站桥上供路由发现
    from .loadtest import LoadTestService

    master_bridge.loadtest = LoadTestService(
        slave_bridge,
        publish=lambda kind, data: master_bridge.bus.publish(kind, data))

    schema_roles = ["master", "slave"]
    master_app = create_app(
        master_bridge, auth_token=auth_token,
        available_roles=schema_roles, slave_api_prefix="/slave",
    )
    slave_app = create_app(
        slave_bridge, auth_token=auth_token, path_prefix="/slave",
        available_roles=schema_roles, slave_api_prefix="/slave",
    )
    master_app.add_subapp("/slave", slave_app)

    runner = web.AppRunner(master_app)
    await runner.setup()
    site = web.TCPSite(runner, host, port, ssl_context=ssl_context)
    await site.start()
    logger.info("Web UI http://%s:%s  roles=master+slave", host, port)
    try:
        await asyncio.Event().wait()
    finally:
        await master_bridge.shutdown()
        await slave_bridge.shutdown()
        await runner.cleanup()


def run_server(role: str, host: str = "127.0.0.1", port: int = 8765,
               point_table=None, connection: dict | None = None,
               history_db=None, app_config=None,
               auth_token: str | None = None,
               ssl_context: ssl.SSLContext | None = None,
               history_dbs: dict | None = None) -> None:
    """启动 Web 服务（阻塞）.

    Args:
        role: "master" / "slave"。
        point_table: 预加载点表；None 时用演示点表。
        connection: CLI 连接参数透传。
        history_db: 可选的 ``HistoryDB``（已 open）；提供时 Web 模式会把
            收发报文落盘（见 ``EngineBridge._on_raw_frame``）。None 则不记录，
            与改动前行为一致。
        app_config: CLI / ``--config`` 解析出的 ``AppConfig``（D3 接线）；
            提供 TLS、冗余等配置经 EngineBridge → EngineSession 生效。
            None 时使用默认配置（与改动前行为一致）。
        auth_token: 可选访问令牌；设置后 /api/* 与 /ws 需携带
            ``Authorization: Bearer <token>`` / ``X-Auth-Token`` / ``?token=``。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        if role == "both":
            asyncio.run(_run_dual(
                host, port, point_table=point_table, connection=connection,
                history_dbs=history_dbs, app_config=app_config,
                auth_token=auth_token, ssl_context=ssl_context,
            ))
        else:
            asyncio.run(_run(role, host, port, point_table=point_table,
                             connection=connection, history_db=history_db,
                             app_config=app_config, auth_token=auth_token,
                             ssl_context=ssl_context))
    except KeyboardInterrupt:
        pass
