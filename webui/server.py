"""本地 Web 服务 — REST + WebSocket，供浏览器加载."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from .bridge import EngineBridge

logger = logging.getLogger("iec104.webui")
STATIC = Path(__file__).parent / "static"
# 项目资源目录（图标等）：webui/ 的上一级 resources/
RESOURCES = Path(__file__).parent.parent / "resources"


def create_app(bridge: EngineBridge) -> web.Application:
    app = web.Application()

    async def index(request: web.Request) -> web.Response:
        page = "master.html" if bridge.role == "master" else "slave.html"
        return web.FileResponse(STATIC / page)

    async def favicon(request: web.Request) -> web.Response:
        """返回项目图标，避免浏览器请求 /favicon.ico 时 404."""
        icon = RESOURCES / "icon.svg"
        if not icon.exists():
            return web.Response(status=404)
        return web.FileResponse(icon, headers={"Content-Type": "image/svg+xml"})

    async def api_status(request: web.Request) -> web.Response:
        return web.json_response(bridge.status())

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
        r = await bridge.start_master(
            host,
            port,
            addr,
            bool(body.get("reconnect", True)),
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
        ))

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

    async def ws_feed(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        q = bridge.subscribe()
        # 先推快照
        await ws.send_json({"kind": "snapshot", "data": {
            "points": bridge.snapshot_points(),
            "status": bridge.status(),
            "frames": bridge.recent("frame", 50),
            "events": bridge.recent("event", 50),
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
                    msg = recv_task.result()
                    if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
                    if msg.type == WSMsgType.TEXT:
                        # 前端可请求刷新
                        if msg.data == "refresh":
                            await ws.send_json({"kind": "snapshot", "data": {
                                "points": bridge.snapshot_points(),
                                "status": bridge.status(),
                            }})
        finally:
            bridge.unsubscribe(q)
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/points", api_points)
    app.router.add_get("/api/recent", api_recent)
    app.router.add_post("/api/master/start", api_master_start)
    app.router.add_post("/api/master/stop", api_master_stop)
    app.router.add_post("/api/master/gi", api_gi)
    app.router.add_post("/api/master/yk", api_yk)
    app.router.add_post("/api/master/setpoint", api_sp)
    app.router.add_post("/api/master/clock", api_clock)
    app.router.add_post("/api/master/ci", api_ci)
    app.router.add_post("/api/master/reset", api_reset)
    app.router.add_post("/api/master/test", api_test)
    app.router.add_post("/api/master/read", api_read)
    app.router.add_post("/api/master/param", api_param)
    app.router.add_post("/api/master/file", api_file)
    app.router.add_get("/api/points/yaml", api_points_yaml_get)
    app.router.add_post("/api/points/yaml", api_points_yaml_put)
    app.router.add_get("/api/export/points.csv", api_export_csv)
    app.router.add_get("/api/export/session.json", api_export_session)
    app.router.add_post("/api/points/batch", api_points_batch)
    app.router.add_post("/api/slave/start", api_slave_start)
    app.router.add_post("/api/slave/stop", api_slave_stop)
    app.router.add_post("/api/slave/yx", api_slave_yx)
    app.router.add_post("/api/slave/yc", api_slave_yc)
    app.router.add_post("/api/slave/response", api_slave_response)
    app.router.add_post("/api/slave/sim", api_slave_sim)
    app.router.add_get("/ws", ws_feed)
    app.router.add_static("/static/", STATIC, show_index=False)
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_get("/favicon.svg", favicon)
    return app


async def _run(role: str, host: str = "127.0.0.1", port: int = 8765,
               point_table=None) -> None:
    bridge = EngineBridge(role, point_table=point_table)
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
               point_table=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(_run(role, host, port, point_table=point_table))
    except KeyboardInterrupt:
        pass
