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
        self._dropped = 0
        self._point_count = 0
        self._pending_response: dict = {}

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
                # 背压：丢最旧再塞，保证 UI 能跟上
                self._dropped += 1
                try:
                    q.get_nowait()
                except Exception:
                    pass
                try:
                    q.put_nowait(msg)
                except Exception:
                    self._dropped += 1

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
        self._point_count = (
            len(self.point_table.get_all_yx())
            + len(self.point_table.get_all_yc())
            + len(self.point_table.get_all_yk())
            + len(self.point_table.get_all_ym())
        )

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
        # 热路径避免全表 snapshot_points
        st["points"] = self._point_count
        st["dropped"] = self._dropped
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
        pending = getattr(self, "_pending_response", None)
        if pending:
            eng.set_response_behavior(pending)
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

    async def general_interrogation(self, qoi: int = 20) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.general_interrogation(int(qoi))
        return {"ok": True}

    async def reset_process(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.reset_process()
        return {"ok": True}

    async def test_command(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.send_test_command()
        return {"ok": True}

    async def read_command(self, ioa: int) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.read_command(int(ioa))
        return {"ok": True}

    async def parameter_command(self, kind: str, ioa: int, value: float, qualifier: int = 1) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        eng = self.engine
        kind = (kind or "").lower()
        if kind in ("normalized", "na"):
            await eng.parameter_normalized(int(ioa), float(value))
        elif kind in ("scaled", "nb"):
            await eng.parameter_scaled(int(ioa), int(value))
        elif kind in ("float", "nc"):
            await eng.parameter_float(int(ioa), float(value))
        elif kind in ("activation", "act"):
            await eng.parameter_activation(int(ioa), int(qualifier))
        else:
            return {"ok": False, "error": "bad kind"}
        return {"ok": True}

    async def file_action(self, action: str, ioa: int = 0, file_name: int = 0) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        eng = self.engine
        action = (action or "").lower()
        if action in ("directory", "dir"):
            await eng.file_call_directory(int(ioa))
        elif action == "select":
            await eng.file_select(int(ioa), int(file_name))
        elif action in ("request", "call"):
            await eng.file_request(int(ioa), int(file_name))
        else:
            return {"ok": False, "error": "bad action"}
        return {"ok": True}

    def export_points_csv(self) -> str:
        def esc(v: str) -> str:
            s = "" if v is None else str(v)
            if any(c in s for c in (',', '"', '\n', '\r')):
                return '"' + s.replace('"', '""') + '"'
            return s
        lines = ["type,ioa,name,group,enabled,value,quality"]
        for p in self.snapshot_points():
            val = p.get("value", "")
            if isinstance(val, float):
                val = f"{val:.6g}"
            lines.append(",".join(esc(x) for x in (
                p["type"], p["ioa"], p.get("name", ""), p.get("group", ""),
                int(bool(p.get("enabled", True))), val, p.get("quality", ""),
            )))
        return "\n".join(lines) + "\n"

    def export_session_json(self) -> dict:
        return {
            "role": self.role,
            "status": self.status(),
            "frames": self.recent("frame", 500),
            "events": self.recent("event", 500),
        }

    def export_points_yaml(self) -> str:
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "points.yaml"
            self.point_table.save_yaml(str(path))
            return path.read_text(encoding="utf-8")

    def import_points_yaml(self, text: str) -> dict:
        import tempfile
        from pathlib import Path
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "points.yaml"
                path.write_text(text, encoding="utf-8")
                self.point_table.load_yaml(str(path))
            self.ensure_demo_points()  # 刷新计数（已有点表时 no-op 生成）
            self._point_count = (
                len(self.point_table.get_all_yx())
                + len(self.point_table.get_all_yc())
                + len(self.point_table.get_all_yk())
                + len(self.point_table.get_all_ym())
            )
            return {"ok": True, "points": self._point_count}
        except Exception as e:
            return {"ok": False, "error": str(e)}

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

    async def clock_sync(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.clock_sync()
        return {"ok": True}

    async def counter_interrogation(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": False, "error": "not connected"}
        await self.engine.counter_interrogation()
        return {"ok": True}

    async def set_response(self, cfg: dict) -> dict:
        """子站 ResponseBehavior（可未启动时暂存，启动后应用）."""
        if self.role != "slave":
            return {"ok": False, "error": "not slave"}
        self._pending_response = dict(cfg or {})
        if self.engine:
            self.engine.set_response_behavior(self._pending_response)
        return {"ok": True}

    async def set_simulation(self, enabled: bool, **kwargs) -> dict:
        if self.role != "slave" or not self.engine:
            return {"ok": False, "error": "not listening"}
        if enabled:
            await self.engine.start_simulation(
                yx_interval=float(kwargs.get("yx_interval", 5.0)),
                yc_interval=float(kwargs.get("yc_interval", 2.0)),
                yx_change_rate=float(kwargs.get("yx_change_rate", 0.1)),
                yc_change_range=float(kwargs.get("yc_change_range", 0.05)),
            )
        else:
            await self.engine.stop_simulation()
        self._status["simulation"] = bool(enabled)
        return {"ok": True}

    def batch_points(self, ptype: str, ioas: list[int], action: str, group: int | None = None) -> dict:
        """批量启用/禁用/改组（只改点表定义，引擎点表同步）."""
        ptype = (ptype or "").upper()
        if ptype not in ("YX", "YC", "YK", "YM"):
            return {"ok": False, "error": "bad type"}
        action = (action or "").lower()
        if action not in ("enable", "disable", "group"):
            return {"ok": False, "error": "bad action"}
        if action == "group" and group is None:
            return {"ok": False, "error": "group required"}
        want = set(int(x) for x in (ioas or []))
        if not want:
            return {"ok": False, "error": "empty ioas"}
        getters = {
            "YX": self.point_table.get_all_yx,
            "YC": self.point_table.get_all_yc,
            "YK": self.point_table.get_all_yk,
            "YM": self.point_table.get_all_ym,
        }
        changed = 0
        for p in getters[ptype]():
            if p.ioa not in want:
                continue
            if action == "enable":
                p.enabled = True
            elif action == "disable":
                p.enabled = False
            else:
                p.group = int(group)
            changed += 1
        return {"ok": True, "changed": changed}

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
