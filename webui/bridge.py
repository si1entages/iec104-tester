"""Web 后端门面 — 组合 EventBus / PointService / EngineSession，保持旧 API 形状."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.config import AppConfig
from core.data.point_table import PointTable
from core.logging_manager import LogManager

from .events import EventBus
from .points import PointService
from .session import EngineSession

logger = logging.getLogger("iec104.webui")


class EngineBridge:
    """在独立 asyncio 循环上运行主站或子站引擎，并向 UI 推送事件."""

    def __init__(self, role: str = "master", point_table: PointTable | None = None,
                 connection: dict | None = None, history_db=None):
        assert role in ("master", "slave")
        self.role = role
        self.config = AppConfig()
        self.config.mode = role
        # 历史库（T17 决策 1）：Web 模式下把收发报文落盘。
        # 为 None 时不记录，行为与改动前一致。
        self._history = history_db
        # CLI --host/--port/--addr 透传：否则 Web 层用默认 2404，
        # UI 上点「启动监听/连接」会忽略命令行给出的真实端口
        conn = self.config.connection
        for key, value in (connection or {}).items():
            if value is None:
                continue
            if key == "addr":
                conn.common_addr = int(value)
            elif key in ("host",):
                conn.host = str(value)
            elif key == "port":
                conn.port = int(value)
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

        # 结构化日志：内存环形缓冲 + JSONL 会话文件 + WS 推送；
        # 并把既有 iec104.* 引擎日志桥接进来（引擎侧零改动）
        self.logs = LogManager(source=role, log_dir=Path("logs"))
        self.logs.attach_python_logging()
        self.logs.subscribe(self._on_log_entry)

    def _on_log_entry(self, entry) -> None:
        self.bus.publish("log", {
            "ts": entry.ts, "level": entry.level, "source": entry.source,
            "category": entry.category, "message": entry.message,
            "data": entry.data,
        })

    def query_logs(self, *, level_min: str = "DEBUG", source: str | None = None,
                   category: str | None = None, contains: str | None = None,
                   limit: int = 200, newest_first: bool = True) -> list[dict]:
        return [e.to_dict() for e in self.logs.query(
            level_min=level_min, source=source, category=category,
            contains=contains, limit=limit, newest_first=newest_first)]

    def log_stats(self) -> dict:
        st = self.logs.stats()
        st["source"] = self.logs.source
        return st

    def recent_logs(self, limit: int = 50) -> list[dict]:
        return [e.to_dict() for e in self.logs.query(limit=limit, newest_first=False)]

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
        if self._history is not None:
            # HistoryDB.record_frame 只入内存缓冲（批量落盘），异常不外抛
            try:
                self._history.record_frame(direction, data, client_id=client_id)
            except Exception as e:  # noqa: BLE001 — 历史库不得影响报文主路径
                logger.warning(f"history record_frame failed: {e}")

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
        # 引擎未启动时也必须给出配置里的连接参数——否则前端输入框回落到
        # HTML 默认值 2404，用户点「启动监听」会把子站悄悄搬到另一个端口，
        # 主站（按原端口重连）就永远连不上。
        st.setdefault("host", self.config.connection.host)
        st.setdefault("port", self.config.connection.port)
        st.setdefault("addr", self.config.connection.common_addr)
        st["points"] = self.points.count
        st["dropped"] = self.bus.dropped
        return st

    def _notify_ui(self, msg: str) -> None:
        """广播一条 UI 事件.

        前端收到任何 event 都会向服务端要一次状态快照，因此**每个会改变状态的
        分支都必须广播**，包括"本来就已经是该状态"的空操作分支。否则页面会停在
        旧状态上，用户看到的就是「按钮能点，点了没效果」。
        """
        self.bus.publish("event", {"type": "ui", "data": {"msg": msg}})

    async def start_master(self, host: str, port: int, addr: int, reconnect: bool = True,
                           gi_interval: float = 0.0, tls: dict | None = None) -> dict:
        self.ensure_demo_points()
        r = await self.session.start_master(host, port, addr, reconnect, self.points,
                                            gi_interval=gi_interval, tls=tls)
        if r.get("ok"):
            self._status.update({"running": True, "host": host, "port": port})
            self._notify_ui(f"连接中 {host}:{port}")
        else:
            # 例如 already running：也要广播，让页面把按钮对齐到真实状态
            self._notify_ui(r.get("error", "启动失败"))
        return r

    async def stop_master(self) -> dict:
        # 先清标志再停引擎：engine 置 None 之后、stop 完成之前，任何 refresh
        # 快照都不得再报告 running=true（否则前端出现"运行中"+按钮按未启动渲染的矛盾态）
        self._status["running"] = False
        if not self.session.engine:
            # 服务端本来就没在连：仍广播，让"以为还连着"的页面立刻对齐
            self._notify_ui("未连接")
            return {"ok": True}
        r = await self.session.stop_master()
        self._notify_ui("已断开")
        return r

    async def start_slave(self, host: str, port: int, addr: int,
                          tls: dict | None = None) -> dict:
        self.ensure_demo_points()
        r = await self.session.start_slave(host, port, addr, self.points, tls=tls)
        if r.get("ok"):
            self._status.update({"running": True, "host": host, "port": port})
            self._notify_ui(f"监听 {host}:{port}")
        else:
            self._notify_ui(r.get("error", "启动失败"))
        return r

    async def stop_slave(self) -> dict:
        # 同 stop_master：先清标志，杜绝停止过程中的矛盾快照
        self._status["running"] = False
        if not self.session.engine:
            self._notify_ui("未监听")
            return {"ok": True}
        r = await self.session.stop_slave()
        self._notify_ui("已停止监听")
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

    async def send_yk(self, ioa: int, state: int | bool, select: bool = False,
                      double: bool = False, with_time: bool = False) -> dict:
        return await self._cmd(self.session.send_yk(ioa, state, select, double, with_time))

    async def send_step_command(self, ioa: int, state: int, select: bool = False) -> dict:
        return await self._cmd(self.session.send_step_command(ioa, state, select))

    async def send_bitstring(self, ioa: int, value: int) -> dict:
        return await self._cmd(self.session.send_bitstring(ioa, value))

    async def send_delay_request(self, delay_ms: int) -> dict:
        return await self._cmd(self.session.send_delay_request(delay_ms))

    async def send_setpoint(self, ioa: int, value: float, select: bool = False,
                             kind: str = "short_float", with_time: bool = False) -> dict:
        return await self._cmd(self.session.send_setpoint(ioa, value, select, kind, with_time))

    async def parameter_command(self, kind: str, ioa: int, value: float, qualifier: int = 1) -> dict:
        return await self._cmd(self.session.parameter_command(kind, ioa, value, qualifier))

    async def file_action(self, action: str, ioa: int = 0, file_name: int = 0) -> dict:
        return await self._cmd(self.session.file_action(action, ioa, file_name))

    async def set_response(self, cfg: dict) -> dict:
        return await self._cmd(self.session.set_response(cfg))

    def get_response(self) -> dict:
        """只读返回当前 ``ResponseBehavior``（``GET /api/slave/response``）."""
        return self.session.get_response()

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

    async def slave_set_ym(self, ioa: int, value: int) -> dict:
        return await self._cmd(self.session.slave_set_ym(ioa, value))

    async def slave_set_step(self, ioa: int, value: int) -> dict:
        return await self._cmd(self.session.slave_set_step(ioa, value))

    # ── 参数状态查询（T08）────────────────────────────────────────

    def param_state(self, ioa: int) -> dict:
        return self.session.param_state(ioa)

    def param_states(self) -> dict:
        return self.session.param_states()

    # ── 多站（T16）───────────────────────────────────────────────

    async def multi_start(self, stations: list[dict]) -> dict:
        return await self._cmd(self.session.multi_start(stations))

    async def multi_stop(self) -> dict:
        return await self._cmd(self.session.multi_stop())

    def multi_status(self) -> dict:
        return self.session.multi_status()

    def multi_summary(self) -> dict:
        return self.session.multi_summary()

    async def slave_protection_event(self, ioa: int, event_value: int = 1,
                                      with_time: bool = True) -> dict:
        return await self._cmd(self.session.slave_protection_event(ioa, event_value, with_time))

    async def slave_group_single_point(self, ioa: int, states: list) -> dict:
        return await self._cmd(self.session.slave_group_single_point(ioa, states))

    def export_points_csv(self) -> str:
        return self.points.export_csv(self.engine)

    def export_points_yaml(self) -> str:
        return self.points.export_yaml()

    def import_points_yaml(self, text: str) -> dict:
        return self.points.import_yaml(text, engine=self.engine)

    def import_points_csv(self, text: str) -> dict:
        return self.points.import_csv(text, engine=self.engine)

    def export_session_json(self) -> dict:
        return self.bus.export_session(self.role, self.status())

    async def shutdown(self) -> None:
        """关停桥接：停引擎、回收后台任务、清空订阅队列与日志桥接（幂等）.

        必须在事件循环关闭前调用。顺序：

        1. ``session.shutdown()`` —— 停引擎（含 socket ``wait_closed`` 有界等待）
           并回收引擎残留后台任务 / 调度器 / 已登记的多站管理器；
        2. 断开日志桥接订阅，避免关停后仍有回调向已废弃的总线投递；
        3. 清空 WebSocket/订阅队列集合，释放订阅者及其内部缓冲。
        """
        # 1) 引擎与会话资源
        try:
            await self.session.shutdown()
        except Exception as e:
            logger.warning("session shutdown: %s", e)

        # 2) 断开日志 → 总线桥接
        try:
            self.logs.unsubscribe(self._on_log_entry)
        except Exception as e:
            logger.warning("log bridge detach: %s", e)

        # 3) 清空订阅者队列集合（EventBus 无 clear()，经 unsubscribe 逐个移除）
        for q in list(getattr(self.bus, "_subscribers", ())):
            try:
                self.bus.unsubscribe(q)
            except Exception:
                pass

    async def _cmd(self, coro) -> dict:
        try:
            return await coro
        except (RuntimeError, ValueError, KeyError, TypeError, ConnectionError) as e:
            return {"ok": False, "error": str(e)}
