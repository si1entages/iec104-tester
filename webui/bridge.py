"""Web 后端与引擎桥接 — 复用 core 引擎，供 REST/WebSocket 调用."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from core.config import AppConfig
from core.data.point_table import PointTable
from core.engine.master import MasterEngine, MasterEvent
from core.engine.slave import SlaveEngine, SlaveEvent

logger = logging.getLogger("iec104.webui")


class EngineBridge:
    """在独立 asyncio 循环上运行主站或子站引擎，并向 UI 推送事件."""

    def __init__(self, role: str = "master"):
        assert role in ("master", "slave")
        self.role = role
        self.config = AppConfig()
        self.config.mode = role
        self.point_table = PointTable()
        self.engine: Optional[MasterEngine | SlaveEngine] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: set[asyncio.Queue] = set()
        self._frames: list[dict] = []
        self._events: list[dict] = []
        self._status: dict[str, Any] = {"role": role, "running": False}

    # ── 事件总线 ──────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _publish(self, kind: str, data: dict) -> None:
        msg = {"kind": kind, "ts": time.time(), "data": data}
        if kind == "frame":
            self._frames.append(msg)
            if len(self._frames) > 500:
                self._frames = self._frames[-500:]
        elif kind == "event":
            self._events.append(msg)
            if len(self._events) > 500:
                self._events = self._events[-500:]
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def recent(self, kind: str, limit: int = 100) -> list[dict]:
        src = self._frames if kind == "frame" else self._events
        return src[-limit:]

    # ── 引擎回调（引擎线程）──────────────────────────────────────

    def _on_master_event(self, event: MasterEvent, data: dict) -> None:
        self._publish("event", {"type": event.value, "data": _jsonable(data)})

    def _on_slave_event(self, event: SlaveEvent, data: dict) -> None:
        self._publish("event", {"type": event.value, "data": _jsonable(data)})

    def _on_raw_frame(self, data: bytes, direction: str, client_id: str = "") -> None:
        self._publish("frame", {
            "direction": direction,
            "len": len(data),
            "hex": data.hex(),
            "client": client_id,
        })

    def _on_raw_frame_master(self, data: bytes, direction: str) -> None:
        self._on_raw_frame(data, direction, "")

    # ── 操作 ──────────────────────────────────────────────────────

    def ensure_demo_points(self) -> None:
        if self.point_table.yx_count == 0:
            n = 50 if self.role == "slave" else 20
            self.point_table.generate_demo_points(
                yx_count=n, yc_count=max(10, n // 2),
                yk_count=8, ym_count=5,
            )
            self.point_table.common_addr = self.config.connection.common_addr
            self.point_table.station_name = "WebDemo"

    def snapshot_points(self) -> list[dict]:
        out = []
        for p in self.point_table.get_all_yx():
            out.append({"ioa": p.ioa, "type": "YX", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": "OFF"})
        for p in self.point_table.get_all_yc():
            out.append({"ioa": p.ioa, "type": "YC", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0.0})
        for p in self.point_table.get_all_yk():
            out.append({"ioa": p.ioa, "type": "YK", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": "—"})
        for p in self.point_table.get_all_ym():
            out.append({"ioa": p.ioa, "type": "YM", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0})
        if self.engine:
            store = self.engine.data_store
            for row in out:
                if row["type"] == "YX":
                    d = store.get_yx(row["ioa"])
                    if d:
                        row["value"] = "ON" if d.value else "OFF"
                        row["quality"] = str(d.quality)
                elif row["type"] == "YC":
                    d = store.get_yc(row["ioa"])
                    if d:
                        row["value"] = float(d.value)
                        row["quality"] = str(d.quality)
                elif row["type"] == "YM":
                    d = store.get_ym(row["ioa"])
                    if d:
                        row["value"] = int(d.value)
                        row["quality"] = str(d.quality)
        return out

    def status(self) -> dict:
        st = dict(self._status)
        if self.engine:
            if self.role == "master":
                st["state"] = str(self.engine.state)
                st["running"] = self.engine.is_running
            else:
                st["running"] = self.engine.is_running
                st["clients"] = self.engine.client_count
                st["client_list"] = list(self.engine.client_list)
            stats = getattr(self.engine, "connection_stats", None)
            if stats:
                st["tx"] = stats.frames_sent
                st["rx"] = stats.frames_received
            seq = getattr(self.engine, "sequence_manager", None)
            if seq:
                st["vs"] = seq.send_seq
                st["vr"] = seq.recv_seq
                st["window"] = f"{seq.unconfirmed_count}/{seq.k}"
        st["points"] = len(self.snapshot_points())
        return st

    async def start_master(self, host: str, port: int, addr: int, reconnect: bool = True) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        self.ensure_demo_points()
        eng = MasterEngine(
            host=host, port=port, common_addr=addr,
            auto_start=True, auto_gi=False, reconnect=reconnect,
        )
        eng.set_event_callback(self._on_master_event)
        eng.set_raw_frame_callback(self._on_raw_frame_master)
        self.engine = eng
        self.config.connection.host = host
        self.config.connection.port = port
        self.config.connection.common_addr = addr
        await eng.start()
        self._status.update({"running": True, "host": host, "port": port})
        self._publish("event", {"type": "ui", "data": {"msg": f"连接中 {host}:{port}"}})
        return {"ok": True}

    async def stop_master(self) -> dict:
        if not self.engine:
            return {"ok": True}
        eng = self.engine
        self.engine = None
        try:
            await asyncio.wait_for(eng.stop(), timeout=6)
        except Exception as e:
            logger.warning("master stop: %s", e)
        self._status["running"] = False
        self._publish("event", {"type": "ui", "data": {"msg": "已断开"}})
        return {"ok": True}

    async def start_slave(self, host: str, port: int, addr: int) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        self.ensure_demo_points()
        eng = SlaveEngine(
            host=host, port=port, common_addr=addr,
            point_table=self.point_table, spontaneous_enabled=True,
        )
        eng.data_store.init_from_point_table(self.point_table)
        eng.set_event_callback(self._on_slave_event)
        eng.set_raw_frame_callback(self._on_raw_frame)
        self.engine = eng
        await eng.start()
        self._status.update({"running": True, "host": host, "port": port})
        self._publish("event", {"type": "ui", "data": {"msg": f"监听 {host}:{port}"}})
        return {"ok": True}

    async def stop_slave(self) -> dict:
        if not self.engine:
            return {"ok": True}
        eng = self.engine
        self.engine = None
        try:
            await asyncio.wait_for(eng.stop(), timeout=8)
        except Exception as e:
            logger.warning("slave stop: %s", e)
        self._status["running"] = False
        self._publish("event", {"type": "ui", "data": {"msg": "已停止监听"}})
        return {"ok": True}

    async def general_interrogation(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.general_interrogation()
        return {"ok": True}

    async def send_yk(self, ioa: int, state: int | bool, select: bool = False, double: bool = False) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        if double:
            await self.engine.double_command(ioa, int(state), select, 0)
        else:
            await self.engine.single_command(ioa, bool(state), select, 0)
        return {"ok": True}

    async def send_setpoint(self, ioa: int, value: float) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.setpoint_shortfloat(ioa, float(value), False)
        return {"ok": True}

    async def slave_set_yx(self, ioa: int, value: bool) -> dict:
        if self.role != "slave" or not self.engine:
            return {"ok": False, "error": "not listening"}
        self.engine.data_store.update_yx(ioa, value)
        await self.engine.send_spontaneous_yx(ioa, value)
        return {"ok": True}

    async def slave_set_yc(self, ioa: int, value: float) -> dict:
        if self.role != "slave" or not self.engine:
            return {"ok": False, "error": "not listening"}
        self.engine.data_store.update_yc(ioa, value)
        await self.engine.send_spontaneous_yc(ioa, float(value))
        return {"ok": True}

    async def shutdown(self) -> None:
        if self.role == "master":
            await self.stop_master()
        else:
            await self.stop_slave()


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)
