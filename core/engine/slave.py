"""子站引擎 — IEC 60870-5-104 Slave Station.

实现:
- TCP 服务端（监听连接）
- 响应总召唤/组召唤
- 响应时钟同步
- 响应遥控/遥调命令
- 自动上送变化数据（突发）
- SOE 事件上送
- 数据模拟

本模块保留 ``SlaveEngine`` 的编排与**公开 API**（薄门面）以及全部共享状态；
具体职责经组合拆分为三个子模块：

- ``slave_response.SlaveResponseBuilder`` — 品质 / COT / 应答 ASDU 构建与无状态请求处理
- ``slave_session.SlaveSession`` — 每客户端连接 / 帧接收 / SBO 命令会话 / 定时器 / 发送
- ``slave_sim.SlaveSimulator`` — 手动 / 随机 / 脚本化数据模拟与自发上送

共享状态仍由 ``SlaveEngine`` 持有，子模块以构造期注入的引擎引用动态读写，
公开/私有方法签名与行为保持不变（``SlaveEvent`` / ``ResponseBehavior`` /
``_split_contiguous`` 仍可从本模块导入）。
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections import deque
from collections.abc import Callable
from typing import Any

from ..data.data_store import RealtimeDB
from ..data.history import HistoryDB
from ..data.point_table import PointTable
from ..protocol.apci import APCI
from ..protocol.asdu import ASDU, InformationObject
from ..protocol.file_transfer import FileTransferSlave
from ..protocol.types import COT, TypeID
from ..transport.connection import TCPConnection, TCPServer
from .base import EngineBase
from .slave_response import (
    EventCallback,
    ResponseBehavior,
    SlaveEvent,
    SlaveResponseBuilder,
    _split_contiguous,
)
from .slave_session import SlaveSession, _ClientState
from .slave_sim import SlaveSimulator

logger = logging.getLogger("iec104.slave")

# 兼容旧导入路径
__all__ = ["SlaveEngine", "SlaveEvent", "ResponseBehavior", "_split_contiguous"]

# 标准已定义的传送原因取值集合（用于识别"未知传送原因"）。
_VALID_COTS: frozenset[int] = frozenset(int(member) for member in COT)


class SlaveEngine(EngineBase):
    """IEC 104 子站引擎.

    典型使用:
        engine = SlaveEngine(port=2404, point_table=my_points)
        engine.set_event_callback(my_handler)
        await engine.start()
        # 模拟数据变化
        engine.simulate_yx_change(ioa=1, value=True)
        ...
        await engine.stop()

    批量打包限制（考虑 APDU 253 字节上限）:
        _MAX_SP_PER_FRAME = 120   # 单点遥信: 每对象1字节
        _MAX_MV_PER_FRAME = 45    # 短浮点遥测: 每对象5字节
        _MAX_DP_PER_FRAME = 120   # 双点遥信: 每对象1字节
        _MAX_IT_PER_FRAME = 50    # 累计量: 每对象5字节
    """

    _MAX_SP_PER_FRAME: int = 120
    _MAX_MV_PER_FRAME: int = 45
    _MAX_DP_PER_FRAME: int = 120
    _MAX_IT_PER_FRAME: int = 50

    # 错误 COT 注入的偏移量（确定性，便于断言）
    _WRONG_COT_OFFSET: int = 1

    # 延时获得命令 (C_CD_NA_1) 允许的最大延时应答时间，防止恶意/异常值长时间挂起连接
    _MAX_DELAY_MS: int = 10_000

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2404,
        common_addr: int = 1,
        k: int = 12,
        w: int = 8,
        t0: float = 30,
        t1: float = 15,
        t2: float = 10,
        t3: float = 20,
        max_connections: int = 16,
        point_table: PointTable | None = None,
        spontaneous_enabled: bool = True,
        event_buffer_size: int = 10000,
        history_db: HistoryDB | None = None,
        ssl_context: ssl.SSLContext | None = None,
        file_semantics: Any = None,  # WP3a: FileSemantics | None
    ):
        super().__init__()

        # 组合组件（构造期注入引擎引用；仅保存引用，不读取尚未初始化的状态）
        self._response = SlaveResponseBuilder(self)
        self._session = SlaveSession(self)
        self._sim = SlaveSimulator(self)

        self._host = host
        self._port = port
        self._common_addr = common_addr
        self._spontaneous_enabled = spontaneous_enabled

        # 数据
        self._point_table = point_table or PointTable()
        self._data_store = RealtimeDB(event_buffer_size=event_buffer_size)

        # 历史数据库
        self._history_db = history_db

        # 每个客户端连接的状态
        self._client_states: dict[str, _ClientState] = {}

        # TCP 服务端（ssl_context 非空时启用 TLS / IEC 62351 传输加密）
        self._server = TCPServer(
            host=host,
            port=port,
            max_connections=max_connections,
            on_connection=self._on_client_connected,
            on_frame=self._on_frame_received,
            on_disconnected=self._on_client_disconnected,
            ssl_context=ssl_context,
        )

        # 协议参数
        self._k = k
        self._w = w
        self._t0 = t0
        self._t1 = t1
        self._t2 = t2
        self._t3 = t3

        # 响应行为配置
        self._response_behavior = ResponseBehavior()
        self._auto_stopdt_timer = 0.0
        self._testfr_timer = 0.0

        # 回调
        self._event_callback: EventCallback | None = None
        self._raw_frame_callback: Callable[[bytes, str, str], None] | None = None

        # 报文录制器
        self._recorder = None

        # 模拟任务
        self._simulation_task: asyncio.Task | None = None
        self._simulation_running = False

        # 逐点自动变化任务
        self._auto_change_task: asyncio.Task | None = None
        self._auto_change_running = False

        # 报文缓冲
        self._rx_buffer: deque = deque(maxlen=1000)
        self._tx_buffer: deque = deque(maxlen=1000)

        # 通信统计
        self._frames_sent = 0
        self._frames_received = 0
        self._bytes_sent = 0
        self._bytes_received = 0
        self._errors = 0

        # 文件传输管理器
        # WP3a：文件传输语义档位（None=ed1，历史单节行为）
        from ..protocol.file_semantics import ED1

        self._file_semantics = file_semantics if file_semantics is not None else ED1
        self._file_transfer = FileTransferSlave(
            common_addr, semantics=self._file_semantics)
        self._file_transfer.set_callbacks(
            on_send_asdu=lambda data: self._spawn(self._broadcast_i_frame(data)),
        )

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._server.is_running

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def data_store(self) -> RealtimeDB:
        return self._data_store

    @property
    def point_table(self) -> PointTable:
        return self._point_table

    @property
    def client_count(self) -> int:
        return self._server.connection_count

    @property
    def client_list(self) -> list[str]:
        """获取已连接客户端列表。"""
        return list(self._server.connections.keys())

    @property
    def connection_stats(self):
        """获取通信统计。"""
        from ..transport.connection import ConnectionStats
        stats = ConnectionStats()
        stats.frames_sent = self._frames_sent
        stats.frames_received = self._frames_received
        stats.bytes_sent = self._bytes_sent
        stats.bytes_received = self._bytes_received
        stats.errors = self._errors
        return stats

    @property
    def sequence_manager(self):
        """获取第一个客户端的序列号管理器（用于显示）。"""
        if self._client_states:
            first_client = next(iter(self._client_states.values()))
            return first_client.seq
        return None

    def link_snapshot(self) -> dict:
        """链路可观测快照（WP6）：子站侧取**首个客户端的**状态机与序列.

        子站可同时接受多个客户端，逐连接指标不适合塞进单一 status 快照；
        这里给出首条连接的视图，并附 ``clients`` 计数，多连接场景下
        精确定位请用桥接观察页或历史报文。
        """
        snap: dict = {"role": "slave", "clients": self.client_count}
        first = next(iter(self._client_states.values()), None)
        snap["client_id"] = next(iter(self._client_states.keys()), "")
        if first is None:
            snap["state"] = None
            snap["sequence"] = None
            snap["transport"] = None
            return snap
        try:
            snap["state"] = first.state_machine.snapshot()
        except Exception:  # noqa: BLE001 — 观测不得影响状态上报
            snap["state"] = None
        try:
            snap["sequence"] = first.seq.snapshot()
        except Exception:  # noqa: BLE001
            snap["sequence"] = None
        try:
            snap["transport"] = _conn_transport_snapshot(first.conn)
        except Exception:  # noqa: BLE001
            snap["transport"] = None
        return snap

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_event_callback(self, callback: EventCallback) -> None:
        self._event_callback = callback

    def set_raw_frame_callback(self, callback: Callable[[bytes, str, str], None]) -> None:
        """设置原始帧回调 (data, direction, client_id)."""
        self._raw_frame_callback = callback

    def get_raw_frame_callback(self) -> Callable | None:
        """获取当前原始帧回调（供外部模块安全访问，避免直接访问私有属性）."""
        return self._raw_frame_callback

    def set_response_behavior(self, config: dict | ResponseBehavior) -> None:
        """应用响应行为配置（来自 GUI 响应配置面板）。"""
        if isinstance(config, ResponseBehavior):
            self._response_behavior = config
        else:
            self._response_behavior = ResponseBehavior.from_dict(config)
        logger.info(
            "Response behavior updated: gi_delay=%.2f cmd_delay=%.2f "
            "drop=%s rate=%.2f no_response=%s reject_startdt=%s",
            self._response_behavior.gi_delay,
            self._response_behavior.command_delay,
            self._response_behavior.drop_frames,
            self._response_behavior.drop_rate,
            self._response_behavior.no_response,
            self._response_behavior.reject_startdt,
        )

    @property
    def response_behavior(self) -> ResponseBehavior:
        return self._response_behavior

    def set_packet_recorder(self, recorder) -> None:
        """设置报文录制器."""
        self._recorder = recorder

    def set_ssl_context(self, ssl_context: ssl.SSLContext | None) -> None:
        """注入/清除 TLS 上下文（须在 ``start()`` 之前调用；None 表示明文）.

        推荐在构造时直接传 ``ssl_context`` 参数；本方法供兼容入口
        ``configure_engine_tls`` 使用，内部走同一条 ``TCPServer.set_ssl_context``
        路径，行为与构造参数完全一致。
        """
        self._server.set_ssl_context(ssl_context)

    # ── 生命周期 ──────────────────────────────────────────────────

    async def start(self) -> None:
        """启动子站引擎."""
        # 初始化实时数据库
        self._data_store.init_from_point_table(self._point_table)

        await self._server.start()

        # 启动命令超时检查任务
        self._timeout_check_task = self._spawn(self._timeout_check_loop())

        # 启动逐点自动变化任务
        self._auto_change_running = True
        self._auto_change_task = self._spawn(self._auto_change_loop())

        logger.info(
            f"Slave engine started on {self._host}:{self._port} "
            f"(YX={self._point_table.yx_count}, YC={self._point_table.yc_count})"
        )

    async def stop(self) -> None:
        """停止子站引擎."""
        await self.stop_simulation()
        self._reset_change_counts()

        # 停止逐点自动变化任务
        self._auto_change_running = False
        if self._auto_change_task:
            self._auto_change_task.cancel()
            try:
                await asyncio.wait_for(self._auto_change_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        # 停止超时检查任务
        if hasattr(self, '_timeout_check_task') and self._timeout_check_task:
            self._timeout_check_task.cancel()
            try:
                await asyncio.wait_for(self._timeout_check_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        if self._history_db:
            await asyncio.to_thread(self._history_db.flush)
        await self._server.stop()
        logger.info("Slave engine stopped")

    def _reset_change_counts(self) -> None:
        """重置所有点的变化次数。"""
        with self._data_store._lock:
            for point in self._data_store._yx.values():
                point.change_count = 0
            for point in self._data_store._yc.values():
                point.change_count = 0
            for point in self._data_store._ym.values():
                point.change_count = 0
            for point in self._data_store._step.values():
                point.change_count = 0
        logger.info("Change counts reset")

    # ── ASDU 处理（分发）─────────────────────────────────────────

    def _process_asdu(self, state: _ClientState, asdu: ASDU) -> None:
        """处理收到的 ASDU."""
        rb = self._response_behavior

        # 公共地址校验（广播地址255不检查）
        # 标准: 无法识别的公共地址 → 回送 COT=44（未知公共地址），保持连接。
        if asdu.common_addr != 255 and asdu.common_addr != self._common_addr:
            logger.warning(
                f"Common addr mismatch: expected={self._common_addr}, got={asdu.common_addr}"
            )
            if not rb.no_response:
                self._spawn(self._send_standard_error(
                    state, asdu.type_id, COT.UNKNOWN_CA, asdu.common_addr
                ))
            return

        type_id = asdu.type_id
        cot = asdu.cot

        # 故意不响应命令（测试异常场景）
        if rb.no_response and type_id not in (
            TypeID.F_FR_NA_1, TypeID.F_SR_NA_1, TypeID.F_SC_NA_1,
            TypeID.F_LS_NA_1, TypeID.F_AF_NA_1, TypeID.F_SG_NA_1,
            TypeID.F_DR_TA_1,
        ):
            logger.warning(
                f"Response suppressed by config: type={type_id} cot={cot}"
            )
            return

        # 未知传送原因 → 回送 COT=43（未知传送原因），保持连接
        if not self._is_known_cot(cot):
            logger.warning(f"Unknown COT received: cot={cot}, type={type_id}")
            self._spawn(self._send_standard_error(
                state, type_id, COT.UNKNOWN_COT, asdu.common_addr
            ))
            return

        # 总召唤
        if type_id == TypeID.C_IC_NA_1 and cot == COT.ACT:
            self._spawn(self._handle_interrogation(state, asdu))

        # 累计量召唤
        elif type_id == TypeID.C_CI_NA_1 and cot == COT.ACT:
            self._spawn(self._handle_counter_interrogation(state, asdu))

        # 时钟同步
        elif type_id == TypeID.C_CS_NA_1 and cot == COT.ACT:
            self._spawn(self._handle_clock_sync(state, asdu))

        # 读命令
        elif type_id == TypeID.C_RD_NA_1 and cot == COT.REQ:
            self._spawn(self._handle_read_command(state, asdu))

        # 复位进程
        elif type_id == TypeID.C_RP_NA_1 and cot == COT.ACT:
            self._spawn(self._handle_reset_process(state, asdu))

        # 测试命令
        elif type_id in (TypeID.C_TS_NA_1, TypeID.C_TS_TA_1, TypeID.C_TS_NB_1) and cot == COT.ACT:
            self._spawn(self._handle_test_command(state, asdu))

        # 单命令 (含带时标 C_SC_TA_1)
        elif type_id in (TypeID.C_SC_NA_1, TypeID.C_SC_TA_1):
            self._spawn(self._handle_single_command(state, asdu))

        # 双命令 (含带时标 C_DC_TA_1)
        elif type_id in (TypeID.C_DC_NA_1, TypeID.C_DC_TA_1):
            self._spawn(self._handle_double_command(state, asdu))

        # 升降命令 (含带时标 C_RC_TA_1)
        elif type_id in (TypeID.C_RC_NA_1, TypeID.C_RC_TA_1):
            self._spawn(self._handle_regulating_command(state, asdu))

        # 设点命令 (含带时标 C_SE_TA_1/TB_1/TC_1)
        elif type_id in (TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1,
                          TypeID.C_SE_TA_1, TypeID.C_SE_TB_1, TypeID.C_SE_TC_1):
            self._spawn(self._handle_setpoint_command(state, asdu))

        # 比特串命令 (含带时标 C_BO_TA_1)
        elif type_id in (TypeID.C_BO_NA_1, TypeID.C_BO_TA_1):
            self._spawn(self._handle_bitstring_command(state, asdu))

        # 延时获得
        elif type_id == TypeID.C_CD_NA_1:
            self._spawn(self._handle_delay_command(state, asdu))

        # 参数命令
        elif type_id in (TypeID.P_ME_NA_1, TypeID.P_ME_NB_1, TypeID.P_ME_NC_1,
                          TypeID.P_ME_ND_1, TypeID.P_AC_NA_1):
            self._spawn(self._handle_parameter_command(state, asdu))

        # 文件传输
        elif type_id in (TypeID.F_FR_NA_1, TypeID.F_SR_NA_1, TypeID.F_SC_NA_1,
                          TypeID.F_LS_NA_1, TypeID.F_AF_NA_1, TypeID.F_SG_NA_1,
                          TypeID.F_DR_TA_1, TypeID.F_SC_NB_1,
                          TypeID.F_FR_NB_1, TypeID.F_SR_NB_1):
            self._spawn(self._handle_file_transfer(state, asdu))

        else:
            logger.warning(f"Unhandled ASDU: type={type_id}, cot={cot}")

    @staticmethod
    def _is_known_cot(cot: int) -> bool:
        """判断传送原因是否为标准已定义值 (COT 枚举成员)."""
        return int(cot) in _VALID_COTS

    # ── 事件分发 ──────────────────────────────────────────────────

    def _fire_event(self, event: SlaveEvent, data: dict = None) -> None:
        if self._event_callback:
            try:
                self._event_callback(event, data or {})
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    # ── 报文缓冲 ──────────────────────────────────────────────────

    def get_rx_buffer(self, count: int = 100) -> list[tuple[float, bytes, str]]:
        return list(self._rx_buffer)[-count:]

    def get_tx_buffer(self, count: int = 100) -> list[tuple[float, bytes, str]]:
        return list(self._tx_buffer)[-count:]

    # ── 门面 → SlaveResponseBuilder ──────────────────────────────

    def _apply_quality(self, quality: int) -> int:
        """按配置强制注入品质位（门面 → SlaveResponseBuilder）."""
        return self._response._apply_quality(quality)

    def _reply_cot(self, cot: int) -> int:
        """应答传送原因（可注入错误 COT）（门面 → SlaveResponseBuilder）."""
        return self._response._reply_cot(cot)

    def _maybe_drop_frame(self) -> bool:
        """按配置决定是否丢帧（门面 → SlaveResponseBuilder）."""
        return self._response._maybe_drop_frame()

    async def _apply_command_delay(self) -> None:
        """命令延时（门面 → SlaveResponseBuilder）."""
        await self._response._apply_command_delay()

    async def _send_standard_error(self, state: _ClientState, type_id: Any,
                                   cot: int, common_addr: int) -> None:
        """按标准回送错误应答 COT=42/43/44（门面 → SlaveResponseBuilder）."""
        await self._response._send_standard_error(state, type_id, cot, common_addr)

    async def _send_unknown_type_response(self, state: _ClientState,
                                          asdu_data: bytes) -> None:
        """未知类型标识应答 COT=42（门面 → SlaveResponseBuilder）."""
        await self._response._send_unknown_type_response(state, asdu_data)

    async def _send_initialization_end(self, state: _ClientState) -> None:
        """发送初始化结束报文（门面 → SlaveSession）."""
        await self._session.send_initialization_end(state)

    async def _auto_stopdt_after_start(self, state: _ClientState) -> None:
        """STARTDT 后自动 STOPDT（门面 → SlaveSession）."""
        await self._session.auto_stopdt_after_start(state)

    def _build_command_ack(self, type_id: TypeID, cot: int,
                           obj: InformationObject, pn: bool = False) -> bytes:
        """构造命令确认/终止 ASDU（门面 → SlaveResponseBuilder）."""
        return self._response._build_command_ack(type_id, cot, obj, pn)

    async def _handle_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理总召唤（门面 → SlaveResponseBuilder）."""
        await self._response._handle_interrogation(state, asdu)

    async def _send_interrogation_data(self, state: _ClientState, qoi: int) -> None:
        """发送总召唤数据（门面 → SlaveResponseBuilder）."""
        await self._response._send_interrogation_data(state, qoi)

    async def _handle_counter_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理累计量召唤（门面 → SlaveResponseBuilder）."""
        await self._response._handle_counter_interrogation(state, asdu)

    async def _handle_clock_sync(self, state: _ClientState, asdu: ASDU) -> None:
        """处理时钟同步（门面 → SlaveResponseBuilder）."""
        await self._response._handle_clock_sync(state, asdu)

    async def _handle_read_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理读命令（门面 → SlaveResponseBuilder）."""
        await self._response._handle_read_command(state, asdu)

    async def _handle_reset_process(self, state: _ClientState, asdu: ASDU) -> None:
        """处理复位进程（门面 → SlaveResponseBuilder）."""
        await self._response._handle_reset_process(state, asdu)

    async def _handle_test_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理测试命令（门面 → SlaveResponseBuilder）."""
        await self._response._handle_test_command(state, asdu)

    async def _handle_bitstring_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理比特串命令（门面 → SlaveResponseBuilder）."""
        await self._response._handle_bitstring_command(state, asdu)

    async def _handle_delay_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理延时获得命令（门面 → SlaveResponseBuilder）."""
        await self._response._handle_delay_command(state, asdu)

    async def _handle_parameter_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理参数命令（门面 → SlaveResponseBuilder）."""
        await self._response._handle_parameter_command(state, asdu)

    async def _handle_file_transfer(self, state: _ClientState, asdu: ASDU) -> None:
        """处理文件传输（门面 → SlaveResponseBuilder）."""
        await self._response._handle_file_transfer(state, asdu)

    # ── 门面 → SlaveSession ──────────────────────────────────────

    def _on_client_connected(self, conn: TCPConnection) -> None:
        """新客户端连接（门面 → SlaveSession）."""
        self._session.on_client_connected(conn)

    def _on_client_disconnected(self, conn: TCPConnection) -> None:
        """客户端断开（门面 → SlaveSession）."""
        self._session.on_client_disconnected(conn)

    def _on_frame_received(self, conn: TCPConnection, frame: bytes) -> None:
        """收到帧（门面 → SlaveSession）."""
        self._session.on_frame_received(conn, frame)

    def _handle_i_frame(self, state: _ClientState, apci: APCI, frame: bytes) -> None:
        """处理 I 帧（门面 → SlaveSession）."""
        self._session.handle_i_frame(state, apci, frame)

    def _handle_s_frame(self, state: _ClientState, apci: APCI) -> None:
        """处理 S 帧（门面 → SlaveSession）."""
        self._session.handle_s_frame(state, apci)

    def _handle_u_frame(self, state: _ClientState, apci: APCI) -> None:
        """处理 U 帧（门面 → SlaveSession）."""
        self._session.handle_u_frame(state, apci)

    async def _handle_single_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理单命令（门面 → SlaveSession）."""
        await self._session.handle_single_command(state, asdu)

    async def _handle_double_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理双命令（门面 → SlaveSession）."""
        await self._session.handle_double_command(state, asdu)

    async def _handle_setpoint_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理设点命令（门面 → SlaveSession）."""
        await self._session.handle_setpoint_command(state, asdu)

    async def _handle_regulating_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理升降命令（门面 → SlaveSession）."""
        await self._session.handle_regulating_command(state, asdu)

    def _command_requires_sbo(self, ioa: int, *, is_setpoint: bool = False) -> bool:
        """判定命令是否需要 SBO（门面 → SlaveSession）."""
        return self._session.command_requires_sbo(ioa, is_setpoint=is_setpoint)

    async def _timeout_check_loop(self) -> None:
        """命令选择/协议定时器检查循环（门面 → SlaveSession）."""
        await self._session.timeout_check_loop()

    def _on_s_frame_needed(self, state: _ClientState, rx_seq: int) -> None:
        """发送 S 帧（门面 → SlaveSession）."""
        self._session.on_s_frame_needed(state, rx_seq)

    async def _send_i_frame(self, state: _ClientState, asdu_data: bytes) -> None:
        """向指定客户端发送 I 帧（门面 → SlaveSession）."""
        await self._session.send_i_frame(state, asdu_data)

    async def _send_to_client(self, state: _ClientState, frame: bytes) -> None:
        """发送帧到指定客户端（门面 → SlaveSession）."""
        await self._session.send_to_client(state, frame)

    async def _broadcast_i_frame(self, asdu_data: bytes) -> None:
        """向所有已启动客户端广播 I 帧（门面 → SlaveSession）."""
        await self._session.broadcast_i_frame(asdu_data)

    # ── 门面 → SlaveSimulator ────────────────────────────────────

    def simulate_yx_change(self, ioa: int, value: bool) -> None:
        """模拟遥信变化（门面 → SlaveSimulator）."""
        self._sim.simulate_yx_change(ioa, value)

    def simulate_yc_change(self, ioa: int, value: float) -> None:
        """模拟遥测变化（门面 → SlaveSimulator）."""
        self._sim.simulate_yc_change(ioa, value)

    async def start_simulation(
        self,
        yx_interval: float = 5.0,
        yc_interval: float = 2.0,
        yx_change_rate: float = 0.1,
        yc_change_range: float = 0.05,
        yx_scope: str = "all",
        yc_scope: str = "all",
        yx_ioas: list[int] | None = None,
        yc_ioas: list[int] | None = None,
        yx_enabled: bool = True,
        yc_enabled: bool = True,
    ) -> None:
        """启动自动数据模拟（门面 → SlaveSimulator）."""
        await self._sim.start_simulation(
            yx_interval, yc_interval, yx_change_rate, yc_change_range,
            yx_scope=yx_scope, yc_scope=yc_scope,
            yx_ioas=yx_ioas, yc_ioas=yc_ioas,
            yx_enabled=yx_enabled, yc_enabled=yc_enabled,
        )

    async def stop_simulation(self) -> None:
        """停止模拟（门面 → SlaveSimulator）."""
        await self._sim.stop_simulation()

    async def _simulation_loop(
        self,
        yx_interval: float,
        yc_interval: float,
        yx_change_rate: float,
        yc_change_range: float,
        yx_scope: str = "all",
        yc_scope: str = "all",
        yx_ioas: list[int] | None = None,
        yc_ioas: list[int] | None = None,
        yx_enabled: bool = True,
        yc_enabled: bool = True,
    ) -> None:
        """随机模拟循环（门面 → SlaveSimulator）."""
        await self._sim.simulation_loop(
            yx_interval, yc_interval, yx_change_rate, yc_change_range,
            yx_scope=yx_scope, yc_scope=yc_scope,
            yx_ioas=yx_ioas, yc_ioas=yc_ioas,
            yx_enabled=yx_enabled, yc_enabled=yc_enabled,
        )

    async def _auto_change_loop(self) -> None:
        """逐点自动变化循环（门面 → SlaveSimulator）."""
        await self._sim.auto_change_loop()

    async def _reflect_command_result(self, ioa: int, *,
                                      single: bool | None = None,
                                      double_state: int | None = None,
                                      yc_value: float | None = None,
                                      step_delta: int | None = None) -> bool:
        """命令结果联动并自发上送（门面 → SlaveSimulator）."""
        return await self._sim.reflect_command_result(
            ioa, single=single, double_state=double_state, yc_value=yc_value,
            step_delta=step_delta,
        )

    async def send_spontaneous_yx(self, ioa: int, value: bool,
                                  quality: int = 0) -> None:
        """自发上送遥信变化（门面 → SlaveSimulator）."""
        await self._sim.send_spontaneous_yx(ioa, value, quality)

    async def send_spontaneous_yc(self, ioa: int, value: float,
                                  quality: int = 0) -> None:
        """自发上送遥测变化（门面 → SlaveSimulator）."""
        await self._sim.send_spontaneous_yc(ioa, value, quality)

    async def send_spontaneous_dp(self, ioa: int, value: int,
                                  quality: int = 0) -> None:
        """自发上送双点遥信变化（门面 → SlaveSimulator）."""
        await self._sim.send_spontaneous_dp(ioa, value, quality)

    async def send_spontaneous_ym(self, ioa: int, value: int,
                                  quality: int = 0) -> None:
        """自发上送累计量变化（门面 → SlaveSimulator）."""
        await self._sim.send_spontaneous_ym(ioa, value, quality)

    async def send_spontaneous_step(self, ioa: int, value: int,
                                    quality: int = 0,
                                    transient: bool = False) -> None:
        """自发上送步位置变化（门面 → SlaveSimulator）."""
        await self._sim.send_spontaneous_step(ioa, value, quality, transient)

    async def send_protection_event(self, ioa: int, event_value: int = 1,
                                    with_time: bool = True, quality: int = 0) -> None:
        """继保事件上送（门面 → SlaveSimulator）."""
        await self._sim.send_protection_event(ioa, event_value, with_time, quality)

    async def send_group_single_point(self, ioa: int,
                                      points: list[tuple[bool, bool]],
                                      with_time: bool = False) -> None:
        """成组单点上送（门面 → SlaveSimulator）."""
        await self._sim.send_group_single_point(ioa, points, with_time)


def _conn_transport_snapshot(conn) -> dict | None:
    """子站侧链路传输快照（WP6）：与主站 ``TCPClient.link_stats()`` 同形.

    子站是被动接受连接，没有重连循环，因此 ``reconnect_*`` 恒为 0/None；
    ``connected``/``last_error`` 取自连接自身统计，保证前端一套字段两处可用。
    """
    if conn is None:
        return None
    stats = getattr(conn, "stats", None)
    return {
        "target": getattr(conn, "name", "") or getattr(conn, "_remote_addr", ""),
        "connected": bool(conn.is_connected),
        "tls": False,
        "reconnect_count": 0,
        "max_reconnects": 0,
        "reconnect_interval": 0.0,
        "reconnect_in_seconds": None,
        "ever_connected": True,
        "last_error": getattr(stats, "last_error", "") if stats else "",
        "last_error_at": getattr(stats, "last_error_at", 0.0) if stats else 0.0,
    }
