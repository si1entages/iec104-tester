"""引擎会话：master/slave 启停与协议命令门面."""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from core.config import AppConfig
from core.engine.master import MasterEngine, MasterEvent
from core.engine.multi_station import (
    MultiStationConfig,
    MultiStationManager,
    StationConfig,
    _coerce_tls_config,
)
from core.engine.slave import ResponseBehavior, SlaveEngine, SlaveEvent
from core.transport.connection import TlsConfigError, build_context_from_config

logger = logging.getLogger("iec104.webui")

EventHook = Callable[[str, dict], None]
FrameHook = Callable[[bytes, str, str], None]


def prepare_tls(tls: Any, role: str) -> tuple[ssl.SSLContext | None, str | None]:
    """把可选 ``tls``（dict / ``TlsConfig`` / None）解析为 (ssl_context, server_hostname).

    单站启动与多站 ``StationConfig.tls`` 共用同一配置形态；未传或未启用时返回
    ``(None, None)``（明文，与历史行为一致）。配置无效抛 ``TlsConfigError``。
    """
    cfg = _coerce_tls_config(tls)
    if cfg is None or not cfg.enabled:
        return None, None
    ctx = build_context_from_config(cfg, role)
    return ctx, (cfg.server_hostname or None)


def jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def param_state_to_dict(state: Any) -> dict | None:
    """把主站 ``ParameterState`` 快照序列化为 JSON 友好 dict（``None`` 透传）.

    ``ParameterResult`` 为字符串枚举，取 ``.value``（如 ``"ok"`` / ``"timeout"``）；
    ``*_updated_at`` 为 ``time.monotonic()`` 秒值，供前端算时长而非展示绝对时间。
    ``ioa`` 从未下发过参数命令时返回 ``None``。
    """
    if state is None:
        return None

    def _result(v: Any) -> Any:
        return v.value if hasattr(v, "value") else v

    return {
        "ioa": int(state.ioa),
        "loadResult": _result(state.load_result),
        "loadCot": state.load_cot,
        "loadUpdatedAt": state.load_updated_at,
        "activationResult": _result(state.activation_result),
        "activationCot": state.activation_cot,
        "activationUpdatedAt": state.activation_updated_at,
    }


def response_behavior_to_dict(rb: Any) -> dict:
    """把 ``ResponseBehavior`` 序列化为 ``POST /api/slave/response`` 接受的**同一分组形态**.

    输出与 ``ResponseBehavior.from_dict`` 严格互逆（``delays``/``errors``/``quality``/
    ``connection`` 四组），使前端可「GET 回填 → 修改 → POST」原样往返，不会因两侧
    命名不同而丢配置。``None`` 返回空 dict（调用方另行兜底默认值）。
    """
    if rb is None:
        return {}
    return {
        "delays": {
            "gi": rb.gi_delay,
            "command": rb.command_delay,
            "data": rb.data_delay,
        },
        "errors": {
            "drop_frames": rb.drop_frames,
            "drop_rate": rb.drop_rate,
            "corrupt": rb.corrupt,
            "no_response": rb.no_response,
            "wrong_cot": rb.wrong_cot,
        },
        "quality": {
            "invalid": rb.force_invalid,
            "blocked": rb.force_blocked,
            "not_topical": rb.force_not_topical,
            "overflow": rb.force_overflow,
        },
        "connection": {
            "reject_startdt": rb.reject_startdt,
            "auto_stopdt": rb.auto_stopdt,
            "send_testfr": rb.send_testfr,
            "testfr_interval": rb.testfr_interval,
        },
    }


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

    # ── 多站（T16）───────────────────────────────────────────────

    @property
    def multi_station(self) -> MultiStationManager | None:
        return self._multi_station

    @staticmethod
    def _failed_list(failed: dict[str, str]) -> list[dict]:
        """把逐站启动失败快照序列化为稳定形态（station_id/ok/error）."""
        return [{"station_id": sid, "ok": False, "error": msg}
                for sid, msg in failed.items()]

    async def multi_start(self, stations: list[dict]) -> dict:
        """创建并启动多站管理器（子站侧压力测试）.

        每个元素为 ``StationConfig`` 的字段字典（``station_id`` / ``port`` 等）。
        已存在运行中的管理器时返回业务失败（``ok=False``）。

        TLS 配置无效的站**不启动也不降级明文**（T20 策略与单站一致）：
        - 全部站都失败 → ``ok=False`` 并回收管理器；
        - 部分失败 → ``ok=True`` + ``stations`` 为成功数 + ``failed`` 逐站报错。
        """
        if self._multi_station is not None:
            return {"ok": False, "error": "multi already running"}
        try:
            cfgs = [StationConfig(**s) for s in stations]
        except TypeError as e:
            return {"ok": False, "error": f"invalid station config: {e}"}
        if not cfgs:
            return {"ok": False, "error": "no stations"}
        ids = [c.station_id for c in cfgs]
        if len(set(ids)) != len(ids):
            return {"ok": False, "error": "duplicate station_id"}
        mgr = MultiStationManager(MultiStationConfig(stations=cfgs))
        try:
            await mgr.start_all()
        except Exception as e:
            await mgr.stop_all()
            logger.warning("multi start failed: %s", e)
            return {"ok": False, "error": str(e)}
        failed = mgr.start_errors
        if mgr.station_count == 0:
            # 没有任何站启动成功（如全部 TLS 配置无效）：整体失败并回收
            await mgr.stop_all()
            logger.warning("multi start: all stations failed (%s)", list(failed))
            return {
                "ok": False,
                "error": "；".join(f"{sid}: {msg}" for sid, msg in failed.items()),
                "failed": self._failed_list(failed),
            }
        self._multi_station = mgr
        return {
            "ok": True,
            "stations": mgr.station_count,
            "failed": self._failed_list(failed),
        }

    async def multi_stop(self) -> dict:
        mgr = self._multi_station
        if mgr is None:
            return {"ok": True}
        await mgr.stop_all()
        self._multi_station = None
        return {"ok": True}

    def multi_status(self) -> dict:
        mgr = self._multi_station
        if mgr is None:
            return {"ok": True, "running": False, "stations": [], "failed": []}
        return {
            "ok": True,
            "running": mgr.is_running,
            "stations": [asdict(s) for s in mgr.get_all_station_status()],
            "failed": self._failed_list(mgr.start_errors),
        }

    def multi_summary(self) -> dict:
        mgr = self._multi_station
        if mgr is None:
            return {"ok": True, "running": False, "station_count": 0,
                    "total_clients": 0, "uptime": 0.0, "stations": [], "failed": []}
        return {"ok": True, **mgr.get_summary(),
                "failed": self._failed_list(mgr.start_errors)}

    # ── 主站参数状态查询（T08）───────────────────────────────────

    def param_state(self, ioa: int) -> dict:
        eng = self.engine
        if self.role != "master" or eng is None or not hasattr(eng, "get_parameter_state"):
            return {"ok": False, "error": "not connected"}
        return {
            "ok": True,
            "ioa": int(ioa),
            "state": param_state_to_dict(eng.get_parameter_state(int(ioa))),
        }

    def param_states(self) -> dict:
        eng = self.engine
        if self.role != "master" or eng is None or not hasattr(eng, "parameter_states"):
            return {"ok": False, "error": "not connected"}
        rows = [param_state_to_dict(s) for s in eng.parameter_states().values()]
        rows = [r for r in rows if r is not None]
        rows.sort(key=lambda r: r["ioa"])
        return {"ok": True, "params": rows}

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
                           gi_interval: float = 0.0,
                           tls: Any = None) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        # TLS 来源优先级（D3 修复）：HTTP body 显式传入 > 会话配置
        # （CLI --tls* / --config 经 app.py 传入的 config.tls）。
        # body 未带 tls 时回落 config.tls，使 CLI 入口声明的 TLS 真实生效；
        # body 显式传入时仍以 body 为准（既有路径行为不变）。
        effective_tls = tls if tls is not None else self.config.tls
        try:
            ssl_context, server_hostname = prepare_tls(effective_tls, "master")
        except TlsConfigError as e:
            return {"ok": False, "error": f"TLS 配置无效: {e}"}
        if ssl_context is not None:
            logger.info("TLS enabled (master, verify=%s, source=%s)",
                        getattr(effective_tls, "verify", True),
                        "request body" if tls is not None else "CLI/config")
        eng = MasterEngine(
            host=host, port=port, common_addr=addr,
            auto_start=True, auto_gi=False, reconnect=reconnect,
            reconnect_interval=5.0,
            point_table=getattr(points, "table", None),
            gi_interval=float(gi_interval or 0.0),
            ssl_context=ssl_context, server_hostname=server_hostname,
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
                          points: Any, spontaneous: bool = True,
                          tls: Any = None) -> dict:
        if self.engine:
            return {"ok": False, "error": "already running"}
        # TLS 来源优先级（D3 修复）：HTTP body 显式传入 > 会话配置
        # （CLI --tls* / --config 经 app.py 传入的 config.tls）。
        effective_tls = tls if tls is not None else self.config.tls
        try:
            ssl_context, _ = prepare_tls(effective_tls, "slave")
        except TlsConfigError as e:
            return {"ok": False, "error": f"TLS 配置无效: {e}"}
        if ssl_context is not None:
            logger.info("TLS enabled (slave, verify_client=%s, source=%s)",
                        getattr(effective_tls, "verify_client", False),
                        "request body" if tls is not None else "CLI/config")
        eng = SlaveEngine(
            host=host, port=port, common_addr=addr,
            point_table=points.table, spontaneous_enabled=spontaneous,
            ssl_context=ssl_context,
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

    def get_response(self) -> dict:
        """返回**当前生效**的 ``ResponseBehavior``（只读，供前端刷新后回填）.

        - 子站已启动：读引擎实际持有的 ``response_behavior``（权威值）。
        - 未启动：由 ``pending_response`` 暂存项构造（与启动时应用的值一致）；
          从未配置过则为全默认值。二者都会补齐缺失分组/键，故返回结构恒定。
        """
        if self.role != "slave":
            return {"ok": False, "error": "not slave"}
        eng = self.engine
        if eng is not None:
            rb = eng.response_behavior
        else:
            rb = ResponseBehavior.from_dict(self.pending_response)
        return {"ok": True, "response": response_behavior_to_dict(rb)}

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

    async def slave_set_step(self, ioa: int, value: int) -> dict:
        """步位置置数并自发上送 (M_ST_TB_1, COT=3)."""
        eng = self.require_slave()
        await eng.send_spontaneous_step(int(ioa), int(value))
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
