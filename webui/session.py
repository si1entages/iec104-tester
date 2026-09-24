"""引擎会话：master/slave 启停与协议命令门面."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from core.config import AppConfig
from core.engine.master import MasterEngine, MasterEvent
from core.engine.slave import SlaveEngine, SlaveEvent

logger = logging.getLogger("iec104.webui")

EventHook = Callable[[str, dict], None]
FrameHook = Callable[[bytes, str, str], None]


def jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


class EngineSession:
    """持有当前 MasterEngine 或 SlaveEngine，并转发命令."""

    def __init__(
        self,
        role: str,
        config: AppConfig,
        on_event: EventHook,
        on_frame: FrameHook,
    ):
        assert role in ("master", "slave")
        self.role = role
        self.config = config
        self.engine: Optional[MasterEngine | SlaveEngine] = None
        self.pending_response: dict = {}
        self.simulation = False
        self._on_event = on_event
        self._on_frame = on_frame

    def _hook_master(self, event: MasterEvent, data: dict) -> None:
        self._on_event(event.value, jsonable(data))

    def _hook_slave(self, event: SlaveEvent, data: dict) -> None:
        self._on_event(event.value, jsonable(data))

    def _hook_frame(self, data: bytes, direction: str, client_id: str = "") -> None:
        self._on_frame(data, direction, client_id)

    def _hook_frame_master(self, data: bytes, direction: str) -> None:
        self._on_frame(data, direction, "")

    def require_master(self) -> MasterEngine:
        if self.role != "master" or not self.engine:
            raise RuntimeError("not connected")
        return self.engine  # type: ignore[return-value]

    def require_slave(self) -> SlaveEngine:
        if self.role != "slave" or not self.engine:
            raise RuntimeError("not listening")
        return self.engine  # type: ignore[return-value]

    async def start_master(self, host: str, port: int, addr: int,
                           reconnect: bool, points: Any) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        eng = MasterEngine(
            host=host, port=port, common_addr=addr,
            auto_start=True, auto_gi=False, reconnect=reconnect,
            reconnect_interval=5.0,
        )
        eng.set_event_callback(self._hook_master)
        eng.set_raw_frame_callback(self._hook_frame_master)
        self.engine = eng
        self.config.connection.host = host
        self.config.connection.port = port
        self.config.connection.common_addr = addr
        await eng.start()
        return {"ok": True}

    async def stop_master(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": True}
        eng = self.engine
        self.engine = None
        try:
            await asyncio.wait_for(eng.stop(), timeout=6)
        except Exception as e:
            logger.warning("master stop: %s", e)
        return {"ok": True}

    async def start_slave(self, host: str, port: int, addr: int,
                          points: Any, spontaneous: bool = True) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        eng = SlaveEngine(
            host=host, port=port, common_addr=addr,
            point_table=points.table, spontaneous_enabled=spontaneous,
        )
        eng.data_store.init_from_point_table(points.table)
        eng.set_event_callback(self._hook_slave)
        eng.set_raw_frame_callback(self._hook_frame)
        if self.pending_response:
            eng.set_response_behavior(self.pending_response)
        self.engine = eng
        await eng.start()
        return {"ok": True}

    async def stop_slave(self) -> dict:
        if self.role != "slave" or not self.engine:
            return {"ok": True}
        eng = self.engine
        self.engine = None
        self.simulation = False
        try:
            await asyncio.wait_for(eng.stop(), timeout=8)
        except Exception as e:
            logger.warning("slave stop: %s", e)
        return {"ok": True}

    async def shutdown(self) -> None:
        if self.role == "master":
            await self.stop_master()
        else:
            await self.stop_slave()

    def status_fields(self) -> dict:
        st: dict[str, Any] = {}
        if not self.engine:
            return st
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
        return st

    # ── 命令 ──────────────────────────────────────────────────────

    async def general_interrogation(self, qoi: int = 20) -> dict:
        await self.require_master().general_interrogation(int(qoi))
        return {"ok": True}

    async def counter_interrogation(self) -> dict:
        await self.require_master().counter_interrogation()
        return {"ok": True}

    async def clock_sync(self) -> dict:
        await self.require_master().clock_sync()
        return {"ok": True}

    async def reset_process(self) -> dict:
        await self.require_master().reset_process()
        return {"ok": True}

    async def test_command(self) -> dict:
        await self.require_master().send_test_command()
        return {"ok": True}

    async def read_command(self, ioa: int) -> dict:
        await self.require_master().read_command(int(ioa))
        return {"ok": True}

    async def send_yk(self, ioa: int, state: Any, select: bool = False, double: bool = False) -> dict:
        eng = self.require_master()
        if double:
            await eng.double_command(int(ioa), int(state), select, 0)
        else:
            await eng.single_command(int(ioa), bool(state), select, 0)
        return {"ok": True}

    async def send_setpoint(self, ioa: int, value: float) -> dict:
        await self.require_master().setpoint_shortfloat(int(ioa), float(value), False)
        return {"ok": True}

    async def parameter_command(self, kind: str, ioa: int, value: float, qualifier: int = 1) -> dict:
        eng = self.require_master()
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
        eng = self.require_master()
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

    async def set_response(self, cfg: dict) -> dict:
        if self.role != "slave":
            return {"ok": False, "error": "not slave"}
        self.pending_response = dict(cfg or {})
        if self.engine:
            self.engine.set_response_behavior(self.pending_response)
        return {"ok": True}

    async def set_simulation(self, enabled: bool, **kwargs: float) -> dict:
        eng = self.require_slave()
        if enabled:
            await eng.start_simulation(
                yx_interval=float(kwargs.get("yx_interval", 5.0)),
                yc_interval=float(kwargs.get("yc_interval", 2.0)),
                yx_change_rate=float(kwargs.get("yx_change_rate", 0.1)),
                yc_change_range=float(kwargs.get("yc_change_range", 0.05)),
            )
        else:
            await eng.stop_simulation()
        self.simulation = bool(enabled)
        return {"ok": True}

    async def slave_set_yx(self, ioa: int, value: bool) -> dict:
        eng = self.require_slave()
        eng.data_store.update_yx(int(ioa), value)
        await eng.send_spontaneous_yx(int(ioa), value)
        return {"ok": True}

    async def slave_set_yc(self, ioa: int, value: float) -> dict:
        eng = self.require_slave()
        eng.data_store.update_yc(int(ioa), value)
        await eng.send_spontaneous_yc(int(ioa), float(value))
        return {"ok": True}
