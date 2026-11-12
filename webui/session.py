"""引擎会话：master/slave 启停与协议命令门面."""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from core.config import AppConfig, RedundancyConfig
from core.engine.master import MasterEngine, MasterEvent
from core.engine.multi_station import (
    MultiStationConfig,
    MultiStationManager,
    StationConfig,
    _coerce_tls_config,
)
from core.engine.slave import ResponseBehavior, SlaveEngine, SlaveEvent
from core.simulation import NetworkCondition, SimulationManager
from core.simulation.conditions import PRESET_NAMES
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
            "substituted": rb.force_substituted,
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
        # 网络异常模拟（与子站数据模拟 self.simulation 无关）：
        # enabled 在引擎未启动时也保持，start_master/start_slave 会自动安装
        self._net_sim = SimulationManager()
        self._net_sim_enabled = False
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
        except asyncio.CancelledError:
            # Web 会话在启动过程中被取消：先回收已启动的站，再传播取消
            await mgr.stop_all()
            raise
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
        self.attach_multi_station(mgr)
        return {
            "ok": True,
            "stations": mgr.station_count,
            "failed": self._failed_list(failed),
        }

    async def multi_stop(self) -> dict:
        mgr, self._multi_station = self._multi_station, None
        if mgr is None:
            return {"ok": True}
        try:
            await mgr.stop_all()
        except Exception as e:
            logger.warning("multi stop: %s", e)
            return {"ok": False, "error": str(e)}
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
                           tls: Any = None,
                           redundancy: Any = None) -> dict:
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
        # 冗余双通道（E3）：body 显式传入 > CLI/config；未传时沿用配置。
        red_cfg = self.config.redundancy
        if redundancy is not None:
            fields = {k: redundancy[k] for k in (
                "enabled", "standby_host", "standby_port",
                "switch_timeout", "dedup_window") if k in redundancy}
            try:
                red_cfg = RedundancyConfig(**fields)
            except TypeError as e:
                return {"ok": False, "error": f"冗余配置无效: {e}"}
        if red_cfg.enabled:
            if not red_cfg.standby_host:
                return {"ok": False, "error": "冗余配置无效: standby_host 必填"}
            if not 0 < int(red_cfg.standby_port) <= 65535:
                return {"ok": False, "error": "冗余配置无效: standby_port 非法"}
            if red_cfg.standby_host == host and int(red_cfg.standby_port) == int(port):
                return {"ok": False, "error": "冗余配置无效: 备用地址不能与主用相同"}
        eng = MasterEngine(
            host=host, port=port, common_addr=addr,
            auto_start=True, auto_gi=False, reconnect=reconnect,
            auto_clock_sync=self.config.master.auto_clock_sync,
            # 计时器/流控/重连间隔来自会话配置（CLI --config / config.tls 同源），
            # 默认值与引擎构造默认一致（k=12,w=8,t0=30,t1=15,t2=10,t3=20,ri=5.0）
            reconnect_interval=self.config.connection.reconnect_interval,
            k=self.config.flow_control.k,
            w=self.config.flow_control.w,
            t0=self.config.timers.t0,
            t1=self.config.timers.t1,
            t2=self.config.timers.t2,
            t3=self.config.timers.t3,
            point_table=getattr(points, "table", None),
            gi_interval=float(gi_interval or 0.0),
            ssl_context=ssl_context, server_hostname=server_hostname,
            # D4 修复：CLI/--config 启用的冗余双通道配置经会话配置传入；
            # 默认 enabled=False 时引擎行为与单通道完全一致（无回归）。
            redundancy=red_cfg,
            # WP3a：文件传输语义档位（默认 ed1，历史行为逐字节不变）
            file_semantics=self.config.file_transfer.resolve(),
        )
        eng.set_event_callback(self._hook_master)
        eng.set_raw_frame_callback(self._hook_frame_master)
        self._install_network_simulation(eng)
        self.engine = eng
        try:
            await eng.start()
        except Exception as e:  # noqa: BLE001 — 启动失败必须回滚会话状态
            self.engine = None
            self._remove_network_simulation()
            logger.warning("master start failed: %s", e)
            return {"ok": False, "error": str(e)}
        self.config.connection.host = host
        self.config.connection.port = port
        self.config.connection.common_addr = addr
        return {"ok": True}

    async def stop_master(self) -> dict:
        if self.role != "master" or not self.engine:
            return {"ok": True}
        self._remove_network_simulation()
        eng = self.engine
        self.engine = None
        try:
            await asyncio.wait_for(eng.stop(), timeout=6)
        except Exception as e:
            logger.warning("master stop: %s", e)
        await self._reap_engine(eng)
        return {"ok": True}

    async def start_slave(self, host: str, port: int, addr: int,
                          points: Any, spontaneous: bool | None = None,
                          tls: Any = None) -> dict:
        """启动子站监听.

        ``spontaneous`` 为 ``None``（默认，Web 入口不传）时回落会话配置
        ``config.slave.spontaneous_enabled``；显式传入时以调用方为准。
        """
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
            point_table=points.table,
            spontaneous_enabled=(self.config.slave.spontaneous_enabled
                                 if spontaneous is None else spontaneous),
            ssl_context=ssl_context,
            # WP3a：从站多节分包与语义档位
            file_semantics=self.config.file_transfer.resolve(),
        )
        eng.data_store.init_from_point_table(points.table)
        eng.set_event_callback(self._hook_slave)
        eng.set_raw_frame_callback(self._hook_frame)
        self._install_network_simulation(eng)
        if self.pending_response:
            eng.set_response_behavior(self.pending_response)
        self.engine = eng
        try:
            await eng.start()
        except Exception as e:  # noqa: BLE001 — 端口占用等启动失败必须回滚
            self.engine = None
            self._remove_network_simulation()
            logger.warning("slave start failed: %s", e)
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    async def stop_slave(self) -> dict:
        if self.role != "slave" or not self.engine:
            return {"ok": True}
        self._remove_network_simulation()
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

    async def _shutdown_multi_station(self) -> None:
        """注销并回收已登记的多站管理器（幂等；关停阶段异常不外抛）."""
        mgr, self._multi_station = self._multi_station, None
        if mgr is None:
            return
        try:
            await mgr.stop_all()
        except Exception as e:
            logger.warning("multi-station shutdown: %s", e)

    async def shutdown(self) -> None:
        """关停会话持有的全部资源.

        单站引擎 stop 失败时也必须继续回收多站管理器（``finally`` 兜底），
        否则多站监听端口、连接与后台任务会随 Web 会话关停而残留。
        """
        try:
            if self.role == "master":
                await self.stop_master()
            else:
                await self.stop_slave()
        except Exception as e:
            logger.warning("session engine shutdown: %s", e)
        finally:
            await self._shutdown_multi_station()

    def link_fields(self) -> dict | None:
        """链路可观测字段（WP6）：引擎聚合快照；无引擎/不支持时返回 None.

        只读、叠在既有键之外（``status`` 只增键，见 `webui/api_contract.md` §1.3）。
        """
        eng = self.engine
        if eng is None:
            # WP6：没有引擎时也要能回答"链路为什么起不来"。给出与
            # EngineBridge.status() 一致的连接目标（配置值），避免界面出现空白面板。
            return {
                "role": self.role,
                "state": None,
                "sequence": None,
                "transport": {
                    "target": f"{self.config.connection.host}:{self.config.connection.port}",
                    "connected": False,
                    "tls": bool(getattr(self.config.tls, "enabled", False)),
                    "reconnect_count": 0,
                    "max_reconnects": 0,
                    "reconnect_interval": float(
                        getattr(self.config.connection, "reconnect_interval", 0.0)),
                    "reconnect_in_seconds": None,
                    "ever_connected": False,
                    "last_error": "",
                    "last_error_at": 0.0,
                },
            }
        fn = getattr(eng, "link_snapshot", None)
        if not callable(fn):
            return None
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — 观测失败不得影响状态上报
            logger.warning("link snapshot failed: %s", e)
            return None

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
            # WP6：没有引擎时也给链路段（配置目标 + 未连接），否则"为什么连不上"
            # 恰恰在最需要看的时候没有面板。
            link = self.link_fields()
            if link is not None:
                st["link"] = link
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
        if self.role == "master":
            status_fn = getattr(self.engine, "redundancy_status", None)
            red = status_fn() if callable(status_fn) else None
            if red is None and self.config.redundancy.enabled:
                cfg = self.config.redundancy
                red = {
                    "enabled": True, "active": None,
                    "primary_connected": False, "standby_connected": False,
                    "standby_host": cfg.standby_host,
                    "standby_port": int(cfg.standby_port),
                    "switch_timeout": float(cfg.switch_timeout),
                    "dedup_window": float(cfg.dedup_window),
                    "failovers": 0,
                }
            if red is not None:
                st["redundancy"] = red
        # WP6：链路可观测（未确认 I 帧 / t1 剩余 / 重连原因 / 状态时间线）
        link = self.link_fields()
        if link is not None:
            st["link"] = link
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
                      double: bool = False, with_time: bool = False,
                      deactivate: bool = False) -> dict:
        """遥控：单命令 (C_SC) / 双命令 (C_DC)，可选带时标变体与撤销 (COT=8 DEACT，D1)."""
        eng = self.require_master()
        ioa, state = int(ioa), int(state)
        if double:
            if with_time:
                await eng.double_command_with_time(ioa, state, select, 0,
                                                   deactivate=deactivate)
            else:
                await eng.double_command(ioa, state, select, 0,
                                         deactivate=deactivate)
        else:
            if with_time:
                await eng.single_command_with_time(ioa, bool(state), select,
                                                   deactivate=deactivate)
            else:
                await eng.single_command(ioa, bool(state), select, 0,
                                         deactivate=deactivate)
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
                             kind: str = "short_float", with_time: bool = False,
                             deactivate: bool = False) -> dict:
        """发送设点命令.

        Args:
            kind: short_float(C_SE_NC_1) / normalized(C_SE_NA_1) / scaled(C_SE_NB_1)
            with_time: True → 带时标变体 (C_SE_TC_1 / C_SE_TD? → 归一化无此组合时回落)
            select: True=只发选择帧；False=按点表 SBO 配置决定是否两段式
            deactivate: True=发送撤销帧 (COT=8 DEACT，D1；标准允许设点命令停止激活)
        """
        eng = self.require_master()
        ioa, value = int(ioa), float(value)
        kind = (kind or "short_float").lower()
        if kind in ("normalized", "na"):
            if with_time:
                await eng.setpoint_normalized_with_time(ioa, value, select,
                                                        deactivate=deactivate)
            else:
                await eng.setpoint_normalized(ioa, value, select,
                                              deactivate=deactivate)
        elif kind in ("scaled", "nb"):
            if with_time:
                await eng.setpoint_scaled_with_time(ioa, int(value), select,
                                                    deactivate=deactivate)
            else:
                await eng.setpoint_scaled(ioa, int(value), select,
                                          deactivate=deactivate)
        else:
            if with_time:
                await eng.setpoint_shortfloat_with_time(ioa, value, select,
                                                        deactivate=deactivate)
            else:
                await eng.setpoint_shortfloat(ioa, value, select,
                                              deactivate=deactivate)
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

    async def file_action(self, action: str, ioa: int = 0, file_name: int = 0,
                          cot: int | None = None, qualifier: int | None = None,
                          data: str = "", segment_size: int = 200) -> dict:
        action = (action or "").lower()
        # WP3c：upload 的参数校验放在 require_master() 之前——参数错误应精确报出，
        # 不要被「未连接」掩盖。
        payload = b""
        seg = 200
        if action == "upload":
            import binascii

            if not isinstance(data, str) or not data:
                return {"ok": False, "error": "upload 需要 data(hex)"}
            if len(data) > 131072:
                return {"ok": False, "error": "data 过长（上限 64 KiB）"}
            try:
                payload = binascii.unhexlify(data.replace(" ", ""))
            except (binascii.Error, ValueError) as e:
                return {"ok": False, "error": f"data 非法 hex: {e}"}
            if not payload:
                return {"ok": False, "error": "data 不能为空"}
            try:
                seg = max(1, min(int(segment_size), 255))
            except (TypeError, ValueError):
                return {"ok": False, "error": "segment_size 须为 1~255"}

        eng = self.require_master()
        if action in ("directory", "dir"):
            # cot/qualifier 为可选覆盖（T50/C4 §2 组合矩阵探测用）；默认值 = 项目约定
            if cot is not None and int(cot) not in (5, 6, 13):
                return {"ok": False, "error": "cot 须为 5(REQ)/6(ACT)/13(FILE)"}
            if qualifier is not None and not (0 <= int(qualifier) <= 7):
                return {"ok": False, "error": "qualifier(SCQ) 须为 0~7"}
            await eng.file_call_directory(int(ioa), cot=cot, qualifier=qualifier)
        elif action == "select":
            await eng.file_select(int(ioa), int(file_name))
        elif action in ("request", "call"):
            await eng.file_request(int(ioa), int(file_name))
        elif action == "upload":
            # WP3c：上传方向（主站→子站），data 为 hex（与报文查看器一致）
            await eng.upload_file(int(ioa), int(file_name), payload, seg)
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

    async def set_simulation(self, enabled: bool, **kwargs) -> dict:
        eng = self.require_slave()
        if enabled:
            # YX / YC 可独立开启（只模拟遥信或只模拟遥测），至少选一类
            yx_enabled = bool(kwargs.get("yx_enabled", True))
            yc_enabled = bool(kwargs.get("yc_enabled", True))
            if not yx_enabled and not yc_enabled:
                return {"ok": False, "error": "yx_enabled / yc_enabled 至少启用一项"}

            # 第二批改造⑤：范围模式 scope（YX/YC 独立）——"all" 全部点 / "selected" 仅指定 IOA
            def _scope(key: str) -> str | None:
                v = kwargs.get(key, "all")
                return v if v in ("selected", "all") else None

            yx_scope = _scope("yx_scope")
            yc_scope = _scope("yc_scope")
            if yx_scope is None or yc_scope is None:
                return {"ok": False, "error": "scope 须为 selected|all"}

            def _ioas(key: str) -> list[int] | None:
                v = kwargs.get(key)
                if v is None:
                    return None
                if isinstance(v, list) and v and all(
                    isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v
                ):
                    return [int(x) for x in v]
                return None

            yx_ioas = _ioas("yx_ioas")
            yc_ioas = _ioas("yc_ioas")
            # 只有启用的那一类才要求 selected 模式带点集
            if (yx_enabled and yx_scope == "selected" and not yx_ioas) or (
                yc_enabled and yc_scope == "selected" and not yc_ioas
            ):
                return {"ok": False, "error": "scope=selected 须提供非空 ioas 列表"}

            await eng.start_simulation(
                yx_interval=float(kwargs.get("yx_interval", 5.0)),
                yc_interval=float(kwargs.get("yc_interval", 2.0)),
                yx_change_rate=float(kwargs.get("yx_change_rate", 0.1)),
                yc_change_range=float(kwargs.get("yc_change_range", 0.05)),
                yx_scope=yx_scope,
                yc_scope=yc_scope,
                yx_ioas=yx_ioas,
                yc_ioas=yc_ioas,
                yx_enabled=yx_enabled,
                yc_enabled=yc_enabled,
            )
        else:
            await eng.stop_simulation()
        self.simulation = bool(enabled)
        return {"ok": True}

    # ── 网络异常模拟（B6：Web 接入；与子站数据模拟 self.simulation 无关）──

    @staticmethod
    def _validate_sim_condition(condition: dict) -> str | None:
        """校验自定义网络条件字典；返回错误信息（None=通过）."""
        fields = NetworkCondition.__dataclass_fields__
        prob_fields = {"loss_rate", "duplicate_rate", "corrupt_rate",
                       "reorder_rate", "disconnect_rate"}
        nonneg_fields = {"delay_ms", "delay_variance_ms",
                         "disconnect_duration_s", "bandwidth_bps"}
        int_fields = {"corrupt_bits", "reorder_window"}
        for key, value in condition.items():
            if key not in fields:
                return f"unknown condition field: {key}"
            if key == "direction":
                if value not in ("rx", "tx", "both"):
                    return "direction 须为 rx|tx|both"
            elif key == "active":
                if not isinstance(value, bool):
                    return "active 须为 bool"
            elif key in prob_fields:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return f"{key} 须为数字"
                if not 0 <= float(value) <= 1:
                    return f"{key} 须在 0..1"
            elif key in nonneg_fields:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return f"{key} 须为数字"
                if float(value) < 0:
                    return f"{key} 须 >= 0"
            elif key in int_fields:
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    return f"{key} 须为 >=1 的整数"
        return None

    def network_simulation_status(self) -> dict:
        """网络异常模拟状态（条件 / 安装态 / 统计 / 预设名）."""
        cond = self._net_sim.condition
        return {
            "enabled": self._net_sim_enabled,
            "installed": self._net_sim.installed,
            "active": self._net_sim.is_active,
            "describe": cond.describe(),
            "condition": asdict(cond),
            "stats": self._net_sim.stats(),
            "presets": list(PRESET_NAMES),
        }

    async def set_network_simulation(self, enabled: bool, preset: str | None = None,
                                     condition: dict | None = None) -> dict:
        """启用/停用网络异常模拟；可在引擎未启动时预设（启动时自动安装）.

        停用不卸载代理（仅 ``active=False`` 直通），避免反复启用造成包装叠加；
        引擎停止时才真正卸载，重启后按 enabled 自动重装。
        """
        if preset:
            try:
                self._net_sim.apply_preset(preset)
            except ValueError as e:
                return {"ok": False, "error": str(e)}
        if condition is not None:
            if not isinstance(condition, dict):
                return {"ok": False, "error": "invalid condition"}
            err = self._validate_sim_condition(condition)
            if err:
                return {"ok": False, "error": err}
            self._net_sim.apply_condition(**condition)
        self._net_sim_enabled = bool(enabled)
        self._net_sim.set_active(bool(enabled))
        if enabled and self.engine is not None and not self._net_sim.installed:
            try:
                self._net_sim.install(self.engine)
            except Exception as e:  # noqa: BLE001 — 模拟失败不拖垮引擎
                logger.warning("network simulation install failed: %s", e)
                return {"ok": False, "error": f"install failed: {e}"}
        return {"ok": True}

    def reset_network_simulation_stats(self) -> dict:
        self._net_sim.reset_stats()
        return {"ok": True}

    def network_simulation_disconnect(self, duration: float = 5.0) -> dict:
        """手动触发一次断线（仅已安装时有效）."""
        if not self._net_sim.installed or self.engine is None:
            return {"ok": False, "error": "simulation not installed（先启用并启动引擎）"}
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) \
                or not 0 < float(duration) <= 600:
            return {"ok": False, "error": "duration 须在 (0, 600] 秒"}
        self._net_sim.disconnect(float(duration))
        return {"ok": True}

    def _install_network_simulation(self, eng: Any) -> None:
        """引擎启动后按 enabled 自动安装网络异常模拟."""
        if not self._net_sim_enabled:
            return
        try:
            self._net_sim.install(eng)
        except Exception as e:  # noqa: BLE001
            logger.warning("network simulation install failed: %s", e)

    def _remove_network_simulation(self) -> None:
        """引擎停止前卸载模拟（恢复原始回调；引擎对象随后丢弃）."""
        if self._net_sim.installed:
            try:
                self._net_sim.remove()
            except Exception as e:  # noqa: BLE001
                logger.warning("network simulation remove failed: %s", e)

    async def measure_clock_offset(self, samples: int = 5) -> dict:
        """时钟偏差测量（T80）：连发 N 次 C_CS_NA_1，收集子站时标偏移（ms）.

        每次：发送 → 等待确认帧入账（_clock_offsets_ms 增长）→ 下一发。
        """
        eng = self.require_master()
        total = max(1, min(int(samples), 20))
        offsets: list[float] = []
        for _ in range(total):
            before = len(eng._clock_offsets_ms)
            await eng.clock_sync()
            for _ in range(40):  # 最长 2s 等确认入账
                await asyncio.sleep(0.05)
                if len(eng._clock_offsets_ms) > before:
                    break
            if len(eng._clock_offsets_ms) > before:
                offsets.append(eng._clock_offsets_ms[-1])
        if not offsets:
            return {"ok": False, "error": "未收到时钟同步确认（连接是否正常？）"}
        return {"ok": True, "samples": offsets, "count": len(offsets),
                "avg_ms": round(sum(offsets) / len(offsets), 1),
                "min_ms": min(offsets), "max_ms": max(offsets)}

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
