"""本地 Web 服务 — REST + WebSocket，供浏览器加载."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from .bridge import EngineBridge
from .events import SCHEMA_VERSION

logger = logging.getLogger("iec104.webui")
STATIC = Path(__file__).parent / "static"
# 新前端（Vite/React）构建产物目录：webui/static/app/（T10）。
# 与旧原生页（master.html/slave.html/js/css）同级共存，互不干扰。
APP_STATIC = STATIC / "app"
# 项目资源目录（图标等）：webui/ 的上一级 resources/
RESOURCES = Path(__file__).parent.parent / "resources"


@web.middleware
async def no_cache_pages(request: web.Request, handler) -> web.Response:
    """页面与静态资源禁止启发式缓存.

    浏览器对没有 Cache-Control 的静态文件会按 Last-Modified 启发式缓存，
    前端修复（如按钮失效）可能长时间不生效，表现为"改了没用/要手动强刷"。
    本工具只在局域网调试使用，全部走协商缓存（no-cache 表示必须回源校验）。
    """
    resp = await handler(request)
    if (
        request.path == "/"
        or request.path.startswith("/static/")
        or request.path.startswith("/app")
    ):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


def create_app(bridge: EngineBridge) -> web.Application:
    app = web.Application(middlewares=[no_cache_pages])

    def _asset_version() -> str:
        """静态资源版本号 = 关键前端文件的最新 mtime（内容一变，URL 即变）."""
        latest = 0
        for rel in ("js/app.js", "css/app.css", "master.html", "slave.html"):
            p = STATIC / rel
            if p.exists():
                latest = max(latest, int(p.stat().st_mtime))
        return str(latest)

    async def index(request: web.Request) -> web.Response:
        page = "master.html" if bridge.role == "master" else "slave.html"
        html = (STATIC / page).read_text(encoding="utf-8")

        # 缓存击穿：给静态资源引用追加版本号。浏览器即使缓存了旧 HTML，
        # 也会因为 URL 变化而拉取新的 app.js / app.css（配合 no-cache 双保险）。
        v = _asset_version()
        html = html.replace("app.js", f"app.js?v={v}").replace("app.css", f"app.css?v={v}")

        # 构建时间戳：让用户能直接确认跑的是不是新版本前端
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(v)))
        html = html.replace(
            "</body>",
            f'<script>window.IEC104_BUILD = "{stamp}";</script>\n</body>',
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def favicon(request: web.Request) -> web.Response:
        """返回项目图标，避免浏览器请求 /favicon.ico 时 404."""
        icon = RESOURCES / "icon.svg"
        if not icon.exists():
            return web.Response(status=404)
        return web.FileResponse(icon, headers={"Content-Type": "image/svg+xml"})

    # ── 新前端（Vite 产物）托管：/app/ ────────────────────────────────
    # 独立路径，与旧原生页完全并存；产物缺失时优雅 404，不影响旧 UI。

    async def app_redirect(request: web.Request) -> web.Response:
        """`/app` → `/app/`：保证 Vite base 下的相对资源正确解析."""
        return web.HTTPFound("/app/")

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
        return web.json_response({
            "ok": True,
            "schemaVersion": SCHEMA_VERSION,
            "wsKinds": ["snapshot", "frame", "event", "log"],
            "wsSchemaKey": "schemaVersion",
        })

    async def api_points(request: web.Request) -> web.Response:
        return web.json_response({"points": bridge.snapshot_points()})

    async def api_recent(request: web.Request) -> web.Response:
        return web.json_response({
            "frames": bridge.recent("frame", 200),
            "events": bridge.recent("event", 200),
        })

    async def api_master_start(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        host = body.get("host", "127.0.0.1")
        if not isinstance(host, str):
            return web.json_response({"ok": False, "error": "invalid host"}, status=400)
        port = body.get("port", 2404)
        if not isinstance(port, int) or port < 0 or port > 65535:
            return web.json_response({"ok": False, "error": "invalid port"}, status=400)
        addr = body.get("addr", 1)
        if not isinstance(addr, int) or addr < 0:
            return web.json_response({"ok": False, "error": "invalid addr"}, status=400)
        gi_interval = body.get("gi_interval", 0)
        if not isinstance(gi_interval, (int, float)) or gi_interval < 0:
            return web.json_response({"ok": False, "error": "invalid gi_interval"},
                                     status=400)
        r = await bridge.start_master(
            host,
            port,
            addr,
            bool(body.get("reconnect", True)),
            float(gi_interval),
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
        return web.json_response(await bridge.send_yk(
            ioa, body.get("state", 0),
            bool(body.get("select", False)), bool(body.get("double", False)),
            bool(body.get("with_time", False)),
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
        return web.json_response(await bridge.send_setpoint(
            ioa, value, bool(body.get("select", False)),
            str(body.get("kind", "short_float") or "short_float"),
            bool(body.get("with_time", False)),
        ))

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
            return web.Response(text=text, content_type="text/yaml")
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
        return web.Response(text=bridge.export_points_csv(), content_type="text/csv")

    async def api_export_session(request: web.Request) -> web.Response:
        return web.json_response(bridge.export_session_json())

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

    async def api_slave_sim(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"ok": False, "error": "invalid body"}, status=400)
        return web.json_response(await bridge.set_simulation(
            bool(body.get("enabled")),
            **{k: body[k] for k in ("yx_interval", "yc_interval", "yx_change_rate", "yc_change_range") if k in body},
        ))

    async def api_slave_start(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
        host = body.get("host", "0.0.0.0")
        if not isinstance(host, str):
            return web.json_response({"ok": False, "error": "invalid host"}, status=400)
        port = body.get("port", 2404)
        if not isinstance(port, int) or port < 0 or port > 65535:
            return web.json_response({"ok": False, "error": "invalid port"}, status=400)
        addr = body.get("addr", 1)
        if not isinstance(addr, int) or addr < 0:
            return web.json_response({"ok": False, "error": "invalid addr"}, status=400)
        return web.json_response(await bridge.start_slave(host, port, addr))

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
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/points", api_points)
    app.router.add_get("/api/recent", api_recent)
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
    app.router.add_get("/api/points/yaml", api_points_yaml_get)
    app.router.add_post("/api/points/yaml", api_points_yaml_put)
    app.router.add_post("/api/points/import", api_points_import)
    app.router.add_get("/api/export/points.csv", api_export_csv)
    app.router.add_get("/api/export/session.json", api_export_session)
    app.router.add_get("/api/logs", api_logs)
    app.router.add_get("/api/logs/export", api_logs_export)
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
    app.router.add_get("/api/multi/status", api_multi_status)
    app.router.add_get("/api/multi/summary", api_multi_summary)
    app.router.add_get("/ws", ws_feed)
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", app_index)
    app.router.add_get("/app/{tail:.*}", app_asset)
    app.router.add_static("/static/", STATIC, show_index=False)
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_get("/favicon.svg", favicon)
    return app


async def _run(role: str, host: str = "127.0.0.1", port: int = 8765,
               point_table=None, connection: dict | None = None,
               history_db=None) -> None:
    bridge = EngineBridge(role, point_table=point_table, connection=connection,
                          history_db=history_db)
    bridge.ensure_demo_points()
    app = create_app(bridge)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web UI http://%s:%s  role=%s", host, port, role)
    try:
        await asyncio.Event().wait()
    finally:
        await bridge.shutdown()
        await runner.cleanup()


def run_server(role: str, host: str = "127.0.0.1", port: int = 8765,
               point_table=None, connection: dict | None = None,
               history_db=None) -> None:
    """启动 Web 服务（阻塞）.

    Args:
        role: "master" / "slave"。
        point_table: 预加载点表；None 时用演示点表。
        connection: CLI 连接参数透传。
        history_db: 可选的 ``HistoryDB``（已 open）；提供时 Web 模式会把
            收发报文落盘（见 ``EngineBridge._on_raw_frame``）。None 则不记录，
            与改动前行为一致。
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(_run(role, host, port, point_table=point_table,
                         connection=connection, history_db=history_db))
    except KeyboardInterrupt:
        pass
