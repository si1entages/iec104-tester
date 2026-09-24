"""本地 Web 服务 — REST + WebSocket，供 pywebview/浏览器加载."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiohttp import web, WSMsgType

from .bridge import EngineBridge

logger = logging.getLogger("iec104.webui")
STATIC = Path(__file__).parent / "static"


def create_app(bridge: EngineBridge) -> web.Application:
    app = web.Application()
    app["bridge"] = bridge

    async def index(request: web.Request) -> web.Response:
        page = "master.html" if bridge.role == "master" else "slave.html"
        return web.FileResponse(STATIC / page)

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
        body = await request.json()
        r = await bridge.start_master(
            body.get("host", "127.0.0.1"),
            int(body.get("port", 2404)),
            int(body.get("addr", 1)),
            bool(body.get("reconnect", True)),
        )
        return web.json_response(r)

    async def api_master_stop(request: web.Request) -> web.Response:
        return web.json_response(await bridge.stop_master())

    async def api_gi(request: web.Request) -> web.Response:
        return web.json_response(await bridge.general_interrogation())

    async def api_yk(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(await bridge.send_yk(
            int(body["ioa"]), body.get("state", 0),
            bool(body.get("select", False)), bool(body.get("double", False)),
        ))

    async def api_sp(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(await bridge.send_setpoint(int(body["ioa"]), float(body["value"])))

    async def api_slave_start(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(await bridge.start_slave(
            body.get("host", "0.0.0.0"),
            int(body.get("port", 2404)),
            int(body.get("addr", 1)),
        ))

    async def api_slave_stop(request: web.Request) -> web.Response:
        return web.json_response(await bridge.stop_slave())

    async def api_slave_yx(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(await bridge.slave_set_yx(int(body["ioa"]), bool(body["value"])))

    async def api_slave_yc(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(await bridge.slave_set_yc(int(body["ioa"]), float(body["value"])))

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
    app.router.add_post("/api/slave/start", api_slave_start)
    app.router.add_post("/api/slave/stop", api_slave_stop)
    app.router.add_post("/api/slave/yx", api_slave_yx)
    app.router.add_post("/api/slave/yc", api_slave_yc)
    app.router.add_get("/ws", ws_feed)
    app.router.add_static("/static/", STATIC, show_index=False)
    return app


async def _run(role: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    bridge = EngineBridge(role)
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


def run_server(role: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        asyncio.run(_run(role, host, port))
    except KeyboardInterrupt:
        pass
