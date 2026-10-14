"""引擎会话：master/slave 启停与协议命令门面."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

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
        self.engine: MasterEngine | SlaveEngine | None = None
        self.pending_response: dict = {}
        self.simulation = False
        self._on_event = on_event
        self._on_frame = on_frame
        # 可选：随 Web 会话关停一并回收的多站管理器（T07 显式回收路径）
        self._multi_station: Any | None = None

    def attach_multi_station(self, manager: Any) -> None:
        """登记多站管理器，使其随 Web 会话关停被彻底回收.

        由 Web 侧在启用多站并发模拟时调用；``shutdown()`` 会 await 其
        ``stop_all()``，释放各子站引擎、监听端口与后台任务。
        """
        self._multi_station = manager

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
                           reconnect: bool, points: Any,
                           gi_interval: float = 0.0) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        eng = MasterEngine(
            host=host, port=port, common_addr=addr,
            auto_start=True, auto_gi=False, reconnect=reconnect,
            reconnect_interval=5.0,
            point_table=getattr(points, "table", None),
            gi_interval=float(gi_interval or 0.0),
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
        await self._reap_engine(eng)
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
        await self._reap_engine(eng)
        return {"ok": True}

    async def _reap_engine(self, eng: Any) -> None:
        """引擎关停后的彻底回收：停调度器 + 取消并等待残留后台任务.

        ``eng.stop()`` 只取消其已知长驻任务；本方法补齐对调度器与
        ``_background_tasks`` 中短驻任务的回收，避免事件循环关闭时出现
        "Task was destroyed but it is pending!" 与资源泄漏。幂等。
        """
        scheduler = getattr(eng, "_scheduler", None)
        if scheduler is not None and getattr(scheduler, "is_running", False):
            try:
                await scheduler.stop()
            except Exception as e:
                logger.warning("scheduler stop: %s", e)
        aclose = getattr(eng, "aclose_background_tasks", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception as e:
                logger.warning("background task reap: %s", e)

    async def shutdown(self) -> None:
        if self.role == "master":
            await self.stop_master()
        else:
            await self.stop_slave()
        # 多站管理器（若已登记）：释放各子站引擎、监听端口与后台任务
        if self._multi_station is not None:
            try:
                await self._multi_station.stop_all()
            except Exception as e:
                logger.warning("multi-station shutdown: %s", e)
            self._multi_station = None

    def status_fields(self) -> dict:
        """状态字段.

        ``started`` 表示会话是否已有引擎（连接中/已连接/监听中/连接失败都算），
        前端据此同步「连接/断开」「启动监听/停止」按钮的可用状态 ——
        只用 ``running`` 会导致"引擎还在、按钮却禁用"，用户无法断开。
        """
        st: dict[str, Any] = {"started": self.engine is not None}
        if not self.engine:
            # 引擎已不存在：必须显式 running=False。
            # 否则会回落到 bridge._status 里残留的 running=True，
            # 产生 running=true + started=false 的矛盾快照——
            # 前端状态栏显示"运行中"，按钮却按"未启动"渲染。
            st["running"] = False
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

    async def send_yk(self, ioa: int, state: Any, select: bool = False,
                      double: bool = False, with_time: bool = False) -> dict:
        """遥控：单命令 (C_SC) / 双命令 (C_DC)，可选带时标变体 (C_SC_TA_1 / C_DC_TA_1)."""
        eng = self.require_master()
        ioa, state = int(ioa), int(state)
        if double:
            if with_time:
                await eng.double_command_with_time(ioa, state, select, 0)
            else:
                await eng.double_command(ioa, state, select, 0)
        else:
            if with_time:
                await eng.single_command_with_time(ioa, bool(state), select)
            else:
                await eng.single_command(ioa, bool(state), select, 0)
        return {"ok": True}

    async def send_step_command(self, ioa: int, state: int, select: bool = False) -> dict:
        """升降命令 (C_RC_NA_1)：state 1=降一步, 2=升一步."""
        await self.require_master().regulating_step_command(int(ioa), int(state), select, 0)
        return {"ok": True}

    async def send_bitstring(self, ioa: int, value: int) -> dict:
        """32 比特串命令 (C_BO_NA_1)."""
        await self.require_master().bitstring_command(int(ioa), int(value))
        return {"ok": True}

    async def send_delay_request(self, delay_ms: int) -> dict:
        """延时获得命令 (C_CD_NA_1)."""
        await self.require_master().delay_command(int(delay_ms))
        return {"ok": True}

    async def send_setpoint(self, ioa: int, value: float, select: bool = False,
                             kind: str = "short_float", with_time: bool = False) -> dict:
        """发送设点命令.

        Args:
            kind: short_float(C_SE_NC_1) / normalized(C_SE_NA_1) / scaled(C_SE_NB_1)
            with_time: True → 带时标变体 (C_SE_TC_1 / C_SE_TD? → 归一化无此组合时回落)
            select: True=只发选择帧；False=按点表 SBO 配置决定是否两段式
        """
        eng = self.require_master()
        ioa, value = int(ioa), float(value)
        kind = (kind or "short_float").lower()
        if kind in ("normalized", "na"):
            if with_time:
                await eng.setpoint_normalized_with_time(ioa, value, select)
            else:
                await eng.setpoint_normalized(ioa, value, select)
        elif kind in ("scaled", "nb"):
            if with_time:
                await eng.setpoint_scaled_with_time(ioa, int(value), select)
            else:
                await eng.setpoint_scaled(ioa, int(value), select)
        else:
            if with_time:
                await eng.setpoint_shortfloat_with_time(ioa, value, select)
            else:
                await eng.setpoint_shortfloat(ioa, value, select)
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
        await eng.send_spontaneous_yx(int(ioa), value)
        return {"ok": True}

    async def slave_set_yc(self, ioa: int, value: float) -> dict:
        eng = self.require_slave()
        eng.data_store.update_yc(int(ioa), value)
        await eng.send_spontaneous_yc(int(ioa), float(value))
        return {"ok": True}

    async def slave_set_ym(self, ioa: int, value: int) -> dict:
        """累计量置数并自发上送 (M_IT_TB_1, COT=3)."""
        eng = self.require_slave()
        await eng.send_spontaneous_ym(int(ioa), int(value))
        return {"ok": True}

    async def slave_protection_event(self, ioa: int, event_value: int = 1,
                                      with_time: bool = True) -> dict:
        """模拟继电保护设备事件上送 (M_EP_TD_1 / M_EP_TA_1, COT=3)."""
        eng = self.require_slave()
        await eng.send_protection_event(int(ioa), int(event_value), with_time=with_time)
        return {"ok": True}

    async def slave_group_single_point(self, ioa: int, states: list) -> dict:
        """模拟带状态检出的成组单点信息上送 (M_PS_NA_1, COT=3)."""
        eng = self.require_slave()
        points = [(bool(int(v)), True) for v in (states or [])][:8]
        if not points:
            return {"ok": False, "error": "states 为空"}
        await eng.send_group_single_point(int(ioa), points)
        return {"ok": True}
