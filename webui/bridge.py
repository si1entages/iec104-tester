"""Web 后端门面 — 组合 EventBus / PointService / EngineSession，保持旧 API 形状."""

from __future__ import annotations

import logging
from typing import Any

from core.config import AppConfig
from core.data.point_table import PointTable

from .events import EventBus
from .points import PointService
from .session import EngineSession

logger = logging.getLogger("iec104.webui")


class EngineBridge:
    """在独立 asyncio 循环上运行主站或子站引擎，并向 UI 推送事件."""

    def __init__(self, role: str = "master", point_table: PointTable | None = None):
        assert role in ("master", "slave")
        self.role = role
        self.config = AppConfig()
        self.config.mode = role
        self.bus = EventBus()
        self.points = PointService(point_table)
        self.point_table: PointTable = self.points.table
        self.session = EngineSession(
            role, self.config,
            on_event=lambda etype, data: self.bus.publish("event", {"type": etype, "data": data}),
            on_frame=self._on_raw_frame,
        )
        self.loop = None
        self._status: dict[str, Any] = {"role": role, "running": False}

    # ── 兼容旧属性 ────────────────────────────────────────────────

    @property
    def engine(self):
        return self.session.engine

    @engine.setter
    def engine(self, value) -> None:
        self.session.engine = value

    # ── 事件总线（委托）────────────────────────────────────────────

    def subscribe(self):
        return self.bus.subscribe()

    def unsubscribe(self, q) -> None:
        self.bus.unsubscribe(q)

    def _publish(self, kind: str, data: dict) -> None:
        self.bus.publish(kind, data)

    def recent(self, kind: str, limit: int = 100) -> list[dict]:
        return self.bus.recent(kind, limit)

    def _on_raw_frame(self, data: bytes, direction: str, client_id: str = "") -> None:
        self.bus.publish("frame", {
            "direction": direction,
            "len": len(data),
            "hex": data.hex(),
            "client": client_id,
        })

    def ensure_demo_points(self) -> None:
        """点表为空时生成演示点表.

        若 bridge 由外部传入点表（``--point-table`` / 配置文件），
        ``PointService.ensure_demo`` 只在 ``yx_count == 0`` 时才生成，
        因此不会覆盖用户点表。
        """
        n = 50 if self.role == "slave" else 20
        self.points.ensure_demo(
            yx=n, yc=max(10, n // 2), yk=8, ym=5,
            common_addr=self.config.connection.common_addr,
        )

    def snapshot_points(self) -> list[dict]:
        return self.points.snapshot(self.engine)

    def status(self) -> dict:
        st = dict(self._status)
        st.update(self.session.status_fields())
        st["points"] = self.points.count
        st["dropped"] = self.bus.dropped
        return st

    async def start_master(self, host: str, port: int, addr: int, reconnect: bool = True) -> dict:
        self.ensure_demo_points()
        r = await self.session.start_master(host, port, addr, reconnect, self.points)
        if r.get("ok"):
            self._status.update({"running": True, "host": host, "port": port})
            self.bus.publish("event", {"type": "ui", "data": {"msg": f"连接中 {host}:{port}"}})
        return r

    async def stop_master(self) -> dict:
        if not self.session.engine:
            return {"ok": True}
        r = await self.session.stop_master()
        self._status["running"] = False
        self.bus.publish("event", {"type": "ui", "data": {"msg": "已断开"}})
        return r

    async def start_slave(self, host: str, port: int, addr: int) -> dict:
        self.ensure_demo_points()
        r = await self.session.start_slave(host, port, addr, self.points)
        if r.get("ok"):
            self._status.update({"running": True, "host": host, "port": port})
            self.bus.publish("event", {"type": "ui", "data": {"msg": f"监听 {host}:{port}"}})
        return r

    async def stop_slave(self) -> dict:
        if not self.session.engine:
            return {"ok": True}
        r = await self.session.stop_slave()
        self._status["running"] = False
        self.bus.publish("event", {"type": "ui", "data": {"msg": "已停止监听"}})
        return r

    async def general_interrogation(self, qoi: int = 20) -> dict:
        return await self._cmd(self.session.general_interrogation(qoi))

    async def counter_interrogation(self) -> dict:
        return await self._cmd(self.session.counter_interrogation())

    async def clock_sync(self) -> dict:
        return await self._cmd(self.session.clock_sync())

    async def reset_process(self) -> dict:
        return await self._cmd(self.session.reset_process())

    async def test_command(self) -> dict:
        return await self._cmd(self.session.test_command())

    async def read_command(self, ioa: int) -> dict:
        return await self._cmd(self.session.read_command(ioa))

    async def send_yk(self, ioa: int, state: int | bool, select: bool = False, double: bool = False) -> dict:
        return await self._cmd(self.session.send_yk(ioa, state, select, double))

    async def send_setpoint(self, ioa: int, value: float, select: bool = False) -> dict:
        return await self._cmd(self.session.send_setpoint(ioa, value, select))

    async def parameter_command(self, kind: str, ioa: int, value: float, qualifier: int = 1) -> dict:
        return await self._cmd(self.session.parameter_command(kind, ioa, value, qualifier))

    async def file_action(self, action: str, ioa: int = 0, file_name: int = 0) -> dict:
        return await self._cmd(self.session.file_action(action, ioa, file_name))

    async def set_response(self, cfg: dict) -> dict:
        return await self._cmd(self.session.set_response(cfg))

    async def set_simulation(self, enabled: bool, **kwargs) -> dict:
        r = await self._cmd(self.session.set_simulation(enabled, **kwargs))
        if r.get("ok"):
            self._status["simulation"] = bool(enabled)
        return r

    def batch_points(self, ptype: str, ioas: list[int], action: str, group: int | None = None) -> dict:
        return self.points.batch(ptype, ioas, action, group, engine=self.engine)

    async def slave_set_yx(self, ioa: int, value: bool) -> dict:
        return await self._cmd(self.session.slave_set_yx(ioa, value))

    async def slave_set_yc(self, ioa: int, value: float) -> dict:
        return await self._cmd(self.session.slave_set_yc(ioa, value))

    def export_points_csv(self) -> str:
        return self.points.export_csv(self.engine)

    def export_points_yaml(self) -> str:
        return self.points.export_yaml()

    def import_points_yaml(self, text: str) -> dict:
        return self.points.import_yaml(text, engine=self.engine)

    def export_session_json(self) -> dict:
        return self.bus.export_session(self.role, self.status())

    async def shutdown(self) -> None:
        await self.session.shutdown()

    async def _cmd(self, coro) -> dict:
        try:
            return await coro
        except (RuntimeError, ValueError, KeyError, TypeError, ConnectionError) as e:
            return {"ok": False, "error": str(e)}
