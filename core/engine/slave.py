"""子站引擎 — IEC 60870-5-104 Slave Station.

实现:
- TCP 服务端（监听连接）
- 响应总召唤/组召唤
- 响应时钟同步
- 响应遥控/遥调命令
- 自动上送变化数据（突发）
- SOE 事件上送
- 数据模拟
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Any
from enum import Enum

from ..protocol.apci import APCICodec, APCI
from ..protocol.asdu import ASDU, ASDUBuilder, InformationObject
from ..protocol.types import (
    TypeID, COT, ConnState,
    SinglePoint, DoublePoint, NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, QualityDescriptor, CP56Time2a,
    SingleCommand, DoubleCommand, RegulatingStepCommand,
    SetpointCommandN, SetpointCommandS, SetpointCommandScaled,
    BitString32Command,
    QualifierOfInterrogation,
    FileReady, SectionReady, CallDirectory, LastSection, AckFileSection,
    FileSegment, DirectoryEntry, FileSelectCallGet, FileReadyAck, SectionReadyAck,
    InitializationEnd,
)
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..transport.connection import TCPServer, TCPConnection
from ..data.data_store import RealtimeDB
from ..data.point_table import PointTable
from ..data.history import HistoryDB
from ..protocol.file_transfer import FileTransferSlave, FileTransferState

logger = logging.getLogger("iec104.slave")


class SlaveEvent(Enum):
    """子站事件类型."""
    CLIENT_CONNECTED = "client_connected"
    CLIENT_DISCONNECTED = "client_disconnected"
    STARTDT_RECEIVED = "startdt"
    STOPDT_RECEIVED = "stopdt"
    GI_RECEIVED = "gi"
    COMMAND_RECEIVED = "command"
    CLOCK_SYNC_RECEIVED = "clock_sync"
    DATA_CHANGED = "data_changed"
    ERROR = "error"


EventCallback = Callable[[SlaveEvent, dict[str, Any]], None]


@dataclass
class ResponseBehavior:
    """子站响应行为配置（GUI 响应配置面板可写入）。"""

    # 延迟（秒）
    gi_delay: float = 0.0
    command_delay: float = 0.0
    data_delay: float = 0.0

    # 错误注入
    drop_frames: bool = False
    drop_rate: float = 0.0
    corrupt: bool = False
    no_response: bool = False
    wrong_cot: bool = False

    # 品质注入
    force_invalid: bool = False
    force_blocked: bool = False
    force_not_topical: bool = False
    force_overflow: bool = False

    # 连接行为
    reject_startdt: bool = False
    auto_stopdt: bool = False
    send_testfr: bool = False
    testfr_interval: float = 20.0

    @classmethod
    def from_dict(cls, config: dict) -> "ResponseBehavior":
        delays = config.get("delays", {}) or {}
        errors = config.get("errors", {}) or {}
        quality = config.get("quality", {}) or {}
        conn = config.get("connection", {}) or {}
        return cls(
            gi_delay=float(delays.get("gi", 0) or 0),
            command_delay=float(delays.get("command", 0) or 0),
            data_delay=float(delays.get("data", 0) or 0),
            drop_frames=bool(errors.get("drop_frames", False)),
            drop_rate=float(errors.get("drop_rate", 0) or 0),
            corrupt=bool(errors.get("corrupt", False)),
            no_response=bool(errors.get("no_response", False)),
            wrong_cot=bool(errors.get("wrong_cot", False)),
            force_invalid=bool(quality.get("invalid", False)),
            force_blocked=bool(quality.get("blocked", False)),
            force_not_topical=bool(quality.get("not_topical", False)),
            force_overflow=bool(quality.get("overflow", False)),
            reject_startdt=bool(conn.get("reject_startdt", False)),
            auto_stopdt=bool(conn.get("auto_stopdt", False)),
            send_testfr=bool(conn.get("send_testfr", False)),
            testfr_interval=float(conn.get("testfr_interval", 20) or 20),
        )

    def quality_mask(self) -> int:
        """合并品质描述词位（IV=0x80, NT=0x40, SB=0x10, OV=0x04）。"""
        mask = 0
        if self.force_invalid:
            mask |= 0x80
        if self.force_not_topical:
            mask |= 0x40
        if self.force_blocked:
            mask |= 0x10
        if self.force_overflow:
            mask |= 0x04
        return mask

    def has_delay(self) -> bool:
        return self.gi_delay > 0 or self.command_delay > 0 or self.data_delay > 0


class SlaveEngine:
    """IEC 104 子站引擎.

    典型使用:
        engine = SlaveEngine(port=2404, point_table=my_points)
        engine.set_event_callback(my_handler)
        await engine.start()
        # 模拟数据变化
        engine.simulate_yx_change(ioa=1, value=True)
        ...
        await engine.stop()
    """

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
        point_table: Optional[PointTable] = None,
        spontaneous_enabled: bool = True,
        event_buffer_size: int = 10000,
        history_db: Optional[HistoryDB] = None,
    ):
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

        # TCP 服务端
        self._server = TCPServer(
            host=host,
            port=port,
            max_connections=max_connections,
            on_connection=self._on_client_connected,
            on_frame=self._on_frame_received,
            on_disconnected=self._on_client_disconnected,
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
        self._event_callback: Optional[EventCallback] = None
        self._raw_frame_callback: Optional[Callable[[bytes, str, str], None]] = None

        # 报文录制器
        self._recorder = None

        # 模拟任务
        self._simulation_task: Optional[asyncio.Task] = None
        self._simulation_running = False

        # 逐点自动变化任务
        self._auto_change_task: Optional[asyncio.Task] = None
        self._auto_change_running = False

        # 报文缓冲
        self._rx_buffer: list[tuple[float, bytes, str]] = []
        self._tx_buffer: list[tuple[float, bytes, str]] = []

        # 通信统计
        self._frames_sent = 0
        self._frames_received = 0
        self._bytes_sent = 0
        self._bytes_received = 0
        self._errors = 0

        # 文件传输管理器
        self._file_transfer = FileTransferSlave(common_addr)
        self._file_transfer.set_callbacks(
            on_send_asdu=lambda data: self._spawn(self._broadcast_i_frame(data)),
        )
        # 后台任务引用，防止被 GC 回收
        self._background_tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> Optional[asyncio.Task]:
        """安全创建后台任务：保留引用并记录异常."""
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            # 无运行中的事件循环（如同步测试环境）
            coro.close()
            return None
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        def _log_exc(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error("Background task failed: %s", exc, exc_info=exc)

        task.add_done_callback(_log_exc)
        return task

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._server.is_running

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

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_event_callback(self, callback: EventCallback) -> None:
        self._event_callback = callback

    def set_raw_frame_callback(self, callback: Callable[[bytes, str, str], None]) -> None:
        """设置原始帧回调 (data, direction, client_id)."""
        self._raw_frame_callback = callback

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

    def _apply_quality(self, quality: int) -> int:
        """按配置强制注入品质位。"""
        mask = self._response_behavior.quality_mask()
        if mask:
            return quality | mask
        return quality

    def _maybe_drop_frame(self) -> bool:
        """按配置决定是否丢弃当前发送帧。"""
        rb = self._response_behavior
        if not rb.drop_frames:
            return False
        rate = max(0.0, min(1.0, rb.drop_rate))
        if rate <= 0:
            return True
        return random.random() < rate

    async def _apply_command_delay(self) -> None:
        delay = self._response_behavior.command_delay
        if delay > 0:
            await asyncio.sleep(delay)

    def set_packet_recorder(self, recorder) -> None:
        """设置报文录制器."""
        self._recorder = recorder

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
            self._history_db.flush()
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
        logger.info("Change counts reset")

    # ── 客户端连接管理 ────────────────────────────────────────────

    def _on_client_connected(self, conn: TCPConnection) -> None:
        """新客户端连接."""
        conn_id = conn.name
        seq = SequenceManager(k=self._k, w=self._w)
        state = _ClientState(
            conn=conn,
            seq=seq,
            state_machine=ConnectionStateMachine(
                t0=self._t0, t1=self._t1, t2=self._t2, t3=self._t3,
            ),
        )
        seq.set_s_frame_callback(lambda rx_seq: self._on_s_frame_needed(state, rx_seq))
        self._client_states[conn_id] = state
        state.state_machine.on_connected()
        logger.info(f"Client connected: {conn_id}")
        self._fire_event(SlaveEvent.CLIENT_CONNECTED, {"client_id": conn_id})

    def _on_client_disconnected(self, conn: TCPConnection) -> None:
        """客户端断开."""
        conn_id = conn.name
        if conn_id in self._client_states:
            del self._client_states[conn_id]
        logger.info(f"Client disconnected: {conn_id}")
        self._fire_event(SlaveEvent.CLIENT_DISCONNECTED, {"client_id": conn_id})

    def _on_frame_received(self, conn: TCPConnection, frame: bytes) -> None:
        """收到帧。"""
        conn_id = conn.name

        # 更新统计
        self._frames_received += 1
        self._bytes_received += len(frame)

        if self._raw_frame_callback:
            try:
                self._raw_frame_callback(frame, "rx", conn_id)
            except Exception:
                pass

        # 报文录制
        if self._recorder:
            self._recorder.record_frame(frame, direction="rx", metadata={"client_id": conn_id})

        self._rx_buffer.append((time.monotonic(), frame, conn_id))

        # 记录到历史数据库
        if self._history_db:
            frame_type = "I" if len(frame) >= 6 and (frame[2] & 0x01) == 0 else (
                "S" if len(frame) >= 6 and (frame[2] & 0x03) == 0x01 else "U"
            )
            self._history_db.record_frame("rx", frame, frame_type=frame_type, client_id=conn_id)

        state = self._client_states.get(conn_id)
        if not state:
            return

        try:
            apci, _ = APCICodec.decode(frame)

            if apci.is_i_frame:
                self._handle_i_frame(state, apci, frame)
            elif apci.is_s_frame:
                self._handle_s_frame(state, apci)
            elif apci.is_u_frame:
                self._handle_u_frame(state, apci)

            state.state_machine.on_any_frame_received()

        except Exception as e:
            logger.error(f"Frame decode error from {conn_id}: {e}")

    def _handle_i_frame(self, state: _ClientState, apci: APCI, frame: bytes) -> None:
        """处理 I 帧."""
        # 无论STOPDT还是RUNNING状态，都处理序列号
        seq_ok = state.seq.process_rx_i_frame(apci.tx_seq)
        if not seq_ok:
            logger.error(f"Sequence mismatch from {state.conn.name}, disconnecting")
            self._spawn(state.conn.stop())
            return

        # I帧的rx_seq是隐式确认，等效于S帧
        old_unconfirmed = state.seq.unconfirmed_count
        state.seq.process_rx_i_frame_ack(apci.rx_seq)
        # 如果隐式确认释放了窗口空间，通知等待的协程
        if state.seq.unconfirmed_count < old_unconfirmed:
            state.window_available.set()

        # 只在数据传输启用时处理ASDU
        if not state.data_transfer_enabled:
            logger.warning(f"I-Frame ASDU ignored in STOPDT state from {state.conn.name}")
            state.state_machine.on_i_frame_received()
            return

        asdu_data = frame[6:6 + apci.asdu_length]
        try:
            asdu = ASDU.decode(asdu_data)
            self._process_asdu(state, asdu)
        except Exception as e:
            logger.error(f"ASDU decode error: {e}")

        state.state_machine.on_i_frame_received()

    def _handle_s_frame(self, state: _ClientState, apci: APCI) -> None:
        """处理 S 帧."""
        state.seq.process_rx_s_frame(apci.rx_seq)
        state.state_machine.on_ack_received()
        # 通知等待窗口空间的协程
        state.window_available.set()

    def _handle_u_frame(self, state: _ClientState, apci: APCI) -> None:
        """处理 U 帧."""
        if apci.is_startdt_act:
            if self._response_behavior.reject_startdt:
                logger.warning(
                    f"STARTDT ACT rejected by response config from {state.conn.name}"
                )
                self._fire_event(SlaveEvent.ERROR, {
                    "client_id": state.conn.name,
                    "error": "startdt_rejected",
                })
                return

            # 回复 STARTDT CON
            self._spawn(
                self._send_to_client(state, APCICodec.startdt_con())
            )
            state.state_machine.on_startdt_con()
            state.seq.process_rx_u_frame_startdt_con()
            state.data_transfer_enabled = True
            state.window_available.set()  # 序列号重置，窗口可用
            logger.info(f"STARTDT ACT from {state.conn.name}, CON sent")
            self._fire_event(SlaveEvent.STARTDT_RECEIVED, {
                "client_id": state.conn.name
            })

            # 发送初始化结束报文 M_EI_NA_1
            self._spawn(self._send_initialization_end(state))

            # 可选：自动 STOPDT
            if self._response_behavior.auto_stopdt:
                self._spawn(self._auto_stopdt_after_start(state))

        elif apci.is_stopdt_act:
            self._spawn(
                self._send_to_client(state, APCICodec.stopdt_con())
            )
            state.state_machine.on_stopdt_con()
            state.data_transfer_enabled = False
            logger.info(f"STOPDT ACT from {state.conn.name}, CON sent")
            self._fire_event(SlaveEvent.STOPDT_RECEIVED, {
                "client_id": state.conn.name
            })

        elif apci.is_testfr_act:
            self._spawn(
                self._send_to_client(state, APCICodec.testfr_con())
            )
            state.state_machine.on_testfr_act_received()

        elif apci.is_testfr_con:
            state.state_machine.on_ack_received()

    # ── ASDU 处理 ──────────────────────────────────────────────────

    async def _send_initialization_end(self, state: _ClientState) -> None:
        """发送初始化结束报文 (M_EI_NA_1)."""
        asdu = ASDU(
            type_id=TypeID.M_EI_NA_1, sq=False, num=1,
            cot=COT.INIT, common_addr=self._common_addr,
        )
        init_end = InitializationEnd(cause=2)  # 远方复位
        asdu.objects.append(InformationObject(ioa=0, data=init_end))
        await self._send_i_frame(state, asdu.encode())
        logger.info(f"Initialization End sent to {state.conn.name}")

    def _process_asdu(self, state: _ClientState, asdu: ASDU) -> None:
        """处理收到的 ASDU."""
        # 公共地址校验（广播地址255不检查）
        if asdu.common_addr != 255 and asdu.common_addr != self._common_addr:
            logger.warning(
                f"Common addr mismatch: expected={self._common_addr}, got={asdu.common_addr}"
            )
            return

        rb = self._response_behavior
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

        # 单命令
        elif type_id == TypeID.C_SC_NA_1:
            self._spawn(self._handle_single_command(state, asdu))

        # 双命令
        elif type_id == TypeID.C_DC_NA_1:
            self._spawn(self._handle_double_command(state, asdu))

        # 升降命令
        elif type_id == TypeID.C_RC_NA_1:
            self._spawn(self._handle_regulating_command(state, asdu))

        # 设点命令
        elif type_id in (TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1):
            self._spawn(self._handle_setpoint_command(state, asdu))

        # 比特串命令
        elif type_id == TypeID.C_BO_NA_1:
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

    async def _auto_stopdt_after_start(self, state: _ClientState) -> None:
        """STARTDT 后按配置自动发送 STOPDT."""
        await asyncio.sleep(0.2)
        try:
            await self._send_to_client(state, APCICodec.stopdt_act())
            state.state_machine.on_stopdt_con()
            state.data_transfer_enabled = False
            logger.info(f"Auto STOPDT sent to {state.conn.name}")
            self._fire_event(SlaveEvent.STOPDT_RECEIVED, {
                "client_id": state.conn.name
            })
        except Exception as e:
            logger.error(f"Auto STOPDT failed: {e}")

    async def _handle_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理总召唤."""
        if self._response_behavior.gi_delay > 0:
            await asyncio.sleep(self._response_behavior.gi_delay)

        qoi = 20
        if asdu.objects:
            qoi = asdu.objects[0].data[0] if isinstance(asdu.objects[0].data, bytes) else 20

        logger.info(f"Interrogation from {state.conn.name}: QOI={qoi}")

        # 发送激活确认
        ack = ASDUBuilder.build_general_interrogation_ack(self._common_addr, qoi)
        await self._send_i_frame(state, ack)

        # 发送所有数据
        await self._send_interrogation_data(state, qoi)

        # 发送激活结束
        term = ASDUBuilder.build_general_interrogation_end(self._common_addr, qoi)
        await self._send_i_frame(state, term)

        self._fire_event(SlaveEvent.GI_RECEIVED, {
            "client_id": state.conn.name, "qoi": qoi
        })

    async def _send_interrogation_data(self, state: _ClientState, qoi: int) -> None:
        """发送总召唤数据（批量打包，SQ=1，分批发送）."""
        cot = COT.INTROGEN if qoi == 20 else COT.group_response(qoi)

        # IEC 104 限制: VSQ 低7位最大127，APDU最大253字节
        # 实际安全批次大小（考虑APDU长度限制）
        MAX_SP_PER_FRAME = 120   # 单点遥信: 每对象1字节, 120+3+6=129B
        MAX_MV_PER_FRAME = 45    # 短浮点遥测: 每对象5字节, 225+3+6=234B
        MAX_DP_PER_FRAME = 120   # 双点遥信: 每对象1字节
        MAX_IT_PER_FRAME = 50    # 累计量: 每对象5字节

        # ── 单点遥信打包发送 ──
        yx_points = self._point_table.get_all_yx()
        if qoi != 20:
            yx_points = self._point_table.get_yx_by_group(qoi)

        yx_batch = []
        for p in yx_points:
            if not p.enabled:
                continue
            yx_data = self._data_store.get_yx(p.ioa)
            if yx_data:
                yx_batch.append((p.ioa, yx_data.value, self._apply_quality(yx_data.quality.to_int())))

        for i in range(0, len(yx_batch), MAX_SP_PER_FRAME):
            chunk = yx_batch[i:i + MAX_SP_PER_FRAME]
            asdu_data = ASDUBuilder.build_single_point_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # ── 双点遥信打包发送 ──
        dp_batch = []
        for p in yx_points:
            if not p.enabled:
                continue
            yx_data = self._data_store.get_yx(p.ioa)
            if yx_data and yx_data.double_state:
                dp_batch.append((p.ioa, yx_data.double_state, yx_data.quality.to_int()))

        for i in range(0, len(dp_batch), MAX_DP_PER_FRAME):
            chunk = dp_batch[i:i + MAX_DP_PER_FRAME]
            # 使用ASDUBuilder构建双点遥信序列
            asdu = ASDU(
                type_id=TypeID.M_DP_NA_1,
                sq=True,
                num=len(chunk),
                cot=cot,
                common_addr=self._common_addr,
            )
            for ioa, value, quality in chunk:
                dp = DoublePoint(value=value, quality=QualityDescriptor(quality))
                asdu.objects.append(InformationObject(ioa=ioa, data=dp))
            await self._send_i_frame(state, asdu.encode())

        # ── 遥测打包发送 ──
        yc_points = self._point_table.get_all_yc()
        if qoi != 20:
            yc_points = self._point_table.get_yc_by_group(qoi)

        yc_batch = []
        for p in yc_points:
            if not p.enabled:
                continue
            yc_data = self._data_store.get_yc(p.ioa)
            if yc_data:
                yc_batch.append((p.ioa, yc_data.value, self._apply_quality(yc_data.quality.to_int())))

        for i in range(0, len(yc_batch), MAX_MV_PER_FRAME):
            chunk = yc_batch[i:i + MAX_MV_PER_FRAME]
            asdu_data = ASDUBuilder.build_short_float_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # ── 累计量打包发送 ──
        ym_points = self._point_table.get_all_ym()
        if qoi != 20:
            ym_points = self._point_table.get_ym_by_group(qoi) if hasattr(self._point_table, 'get_ym_by_group') else []

        ym_batch = []
        for p in ym_points:
            if not p.enabled:
                continue
            ym_data = self._data_store.get_ym(p.ioa)
            if ym_data:
                ym_batch.append((p.ioa, ym_data.value, ym_data.quality.to_int(), 0))

        for i in range(0, len(ym_batch), MAX_IT_PER_FRAME):
            chunk = ym_batch[i:i + MAX_IT_PER_FRAME]
            asdu_data = ASDUBuilder.build_counter_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # ── 带时标的单点遥信 (SOE) 发送 ──
        MAX_SP_TB_PER_FRAME = 30  # 带时标单点: 每对象1+7=8字节

        soe_batch = []
        for p in yx_points:
            if not p.enabled:
                continue
            yx_data = self._data_store.get_yx(p.ioa)
            if yx_data and yx_data.change_count > 0:
                soe_batch.append((p.ioa, yx_data.value, self._apply_quality(yx_data.quality.to_int())))

        for i in range(0, len(soe_batch), MAX_SP_TB_PER_FRAME):
            chunk = soe_batch[i:i + MAX_SP_TB_PER_FRAME]
            asdu_data = ASDUBuilder.build_single_point_sequence(
                self._common_addr, chunk, cot=cot
            )
            # 注意：这里需要使用带时标的类型，但ASDUBuilder.build_single_point_sequence不支持
            # 实际实现中需要创建新的Builder方法或手动构建
            await self._send_i_frame(state, asdu_data)

    async def _handle_counter_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理累计量召唤."""
        qcc = asdu.objects[0].data[0] if asdu.objects else 0
        logger.info(f"Counter Interrogation from {state.conn.name}: QCC={qcc}")

        # 确认
        asdu_ack = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=COT.ACTCON, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

        # 根据qcc组号确定COT
        group = qcc & 0x0F
        cot = COT.INTROGEN if group == 0 else COT.group_response(group)

        # 发送电度数据 - 使用正确的类型 M_IT_NA_1 (累计量)
        MAX_IT_PER_FRAME = 50  # 每帧最多50个累计量

        ym_batch = []
        for p in self._point_table.get_all_ym():
            if not p.enabled:
                continue
            ym_data = self._data_store.get_ym(p.ioa)
            if ym_data:
                ym_batch.append((p.ioa, ym_data.value, ym_data.quality.to_int(), 0))

        # 分批打包发送
        for i in range(0, len(ym_batch), MAX_IT_PER_FRAME):
            chunk = ym_batch[i:i + MAX_IT_PER_FRAME]
            asdu_data = ASDUBuilder.build_counter_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # 结束
        asdu_term = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=COT.ACTTERM, common_addr=self._common_addr,
        )
        asdu_term.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_term.encode())

    async def _handle_clock_sync(self, state: _ClientState, asdu: ASDU) -> None:
        """处理时钟同步."""
        await self._apply_command_delay()
        logger.info(f"Clock Sync from {state.conn.name}")

        # 回复确认（使用收到的时间）
        received_time = None
        if asdu.objects and hasattr(asdu.objects[0].data, 'time_tag'):
            received_time = asdu.objects[0].data.time_tag
        elif asdu.objects and isinstance(asdu.objects[0].data, CP56Time2a):
            received_time = asdu.objects[0].data

        ack = ASDUBuilder.build_clock_sync_ack(self._common_addr, time_tag=received_time)
        await self._send_i_frame(state, ack)

        self._fire_event(SlaveEvent.CLOCK_SYNC_RECEIVED, {
            "client_id": state.conn.name
        })

    async def _handle_read_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理读命令."""
        await self._apply_command_delay()
        if not asdu.objects:
            return
        ioa = asdu.objects[0].ioa
        logger.info(f"Read Command from {state.conn.name}: IOA={ioa}")

        # 查找并返回对应数据
        yx = self._data_store.get_yx(ioa)
        if yx:
            asdu_data = ASDUBuilder.build_single_point(
                self._common_addr, ioa, yx.value,
                yx.quality.to_int(), cot=COT.REQ
            )
            await self._send_i_frame(state, asdu_data)
            return

        yc = self._data_store.get_yc(ioa)
        if yc:
            asdu_data = ASDUBuilder.build_short_float(
                self._common_addr, ioa, yc.value,
                yc.quality.to_int(), cot=COT.REQ
            )
            await self._send_i_frame(state, asdu_data)
            return

        ym = self._data_store.get_ym(ioa)
        if ym:
            asdu_data = ASDUBuilder.build_counter_value(
                self._common_addr, ioa, ym.value,
                ym.quality.to_int(), cot=COT.REQ
            )
            await self._send_i_frame(state, asdu_data)
            return

    async def _handle_reset_process(self, state: _ClientState, asdu: ASDU) -> None:
        """处理复位进程."""
        logger.info(f"Reset Process from {state.conn.name}")
        # 确认
        ack = ASDUBuilder.build_reset_process(self._common_addr)
        asdu_ack = ASDU(
            type_id=TypeID.C_RP_NA_1, sq=False, num=1,
            cot=COT.ACTCON, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

    async def _handle_test_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理测试命令."""
        logger.info(f"Test Command from {state.conn.name}")
        asdu_ack = ASDU(
            type_id=asdu.type_id, sq=False, num=1,
            cot=COT.ACTCON, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

    async def _handle_single_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理单命令."""
        await self._apply_command_delay()
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: SingleCommand = obj.data
        logger.info(
            f"Single Command from {state.conn.name}: "
            f"IOA={obj.ioa} state={cmd.state} select={cmd.select}"
        )

        self._fire_event(SlaveEvent.COMMAND_RECEIVED, {
            "client_id": state.conn.name,
            "type": "single",
            "ioa": obj.ioa,
            "state": cmd.state,
            "select": cmd.select,
        })

        if asdu.cot == COT.ACT:
            if cmd.select:
                # 选择命令：记录选择状态和时间
                state.selected_commands[obj.ioa] = (cmd, time.monotonic())
                # 回复选择确认
                ack_asdu = ASDU(
                    type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                    cot=COT.ACTCON, common_addr=self._common_addr,
                )
                ack_asdu.objects.append(obj)
                await self._send_i_frame(state, ack_asdu.encode())
                logger.info(f"Single Command SELECT ACK: IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    ack_asdu = ASDU(
                        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())

                    # 更新数据
                    self._data_store.update_yk(obj.ioa, "execute", cmd.state)

                    # 发送激活终止
                    term_asdu = ASDU(
                        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                        cot=COT.ACTTERM, common_addr=self._common_addr,
                    )
                    term_asdu.objects.append(obj)
                    await self._send_i_frame(state, term_asdu.encode())
                else:
                    # 未选择，回复否定确认 (PN=1)
                    ack_asdu = ASDU(
                        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    # 设置否定确认标志 (PN=1, bit7 of first byte)
                    obj_data = bytearray(obj.data.to_bytes())
                    obj_data[0] |= 0x80  # PN=1
                    obj.data = bytes(obj_data)
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())
                    logger.warning(f"Single Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            ack_asdu = ASDU(
                type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                cot=COT.DEACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
            logger.info(f"Single Command DEACTCON: IOA={obj.ioa}")

    async def _handle_double_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理双命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: DoubleCommand = obj.data
        logger.info(
            f"Double Command from {state.conn.name}: "
            f"IOA={obj.ioa} state={cmd.state} select={cmd.select}"
        )

        if asdu.cot == COT.ACT:
            if cmd.select:
                # 选择命令：记录选择状态和时间
                state.selected_commands[obj.ioa] = (cmd, time.monotonic())
                # 回复选择确认
                ack_asdu = ASDU(
                    type_id=TypeID.C_DC_NA_1, sq=False, num=1,
                    cot=COT.ACTCON, common_addr=self._common_addr,
                )
                ack_asdu.objects.append(obj)
                await self._send_i_frame(state, ack_asdu.encode())
                logger.info(f"Double Command SELECT ACK: IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    ack_asdu = ASDU(
                        type_id=TypeID.C_DC_NA_1, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())

                    # 发送激活终止
                    term_asdu = ASDU(
                        type_id=TypeID.C_DC_NA_1, sq=False, num=1,
                        cot=COT.ACTTERM, common_addr=self._common_addr,
                    )
                    term_asdu.objects.append(obj)
                    await self._send_i_frame(state, term_asdu.encode())
                else:
                    # 未选择，回复否定确认 (PN=1)
                    ack_asdu = ASDU(
                        type_id=TypeID.C_DC_NA_1, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    # 设置否定确认标志 (PN=1, bit7 of first byte)
                    obj_data = bytearray(obj.data.to_bytes())
                    obj_data[0] |= 0x80  # PN=1
                    obj.data = bytes(obj_data)
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())
                    logger.warning(f"Double Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            ack_asdu = ASDU(
                type_id=TypeID.C_DC_NA_1, sq=False, num=1,
                cot=COT.DEACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
            logger.info(f"Double Command DEACTCON: IOA={obj.ioa}")

    async def _handle_setpoint_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理设点命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        logger.info(f"Setpoint Command from {state.conn.name}: IOA={obj.ioa}")

        if asdu.cot == COT.ACT:
            # 检查是否是选择命令
            is_select = False
            if hasattr(obj.data, 'select'):
                is_select = obj.data.select

            if is_select:
                # 选择命令：记录选择状态和时间
                state.selected_commands[obj.ioa] = (obj.data, time.monotonic())
                # 回复选择确认
                ack_asdu = ASDU(
                    type_id=asdu.type_id, sq=False, num=1,
                    cot=COT.ACTCON, common_addr=self._common_addr,
                )
                ack_asdu.objects.append(obj)
                await self._send_i_frame(state, ack_asdu.encode())
                logger.info(f"Setpoint Command SELECT ACK: IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    ack_asdu = ASDU(
                        type_id=asdu.type_id, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())

                    # 发送激活终止
                    term_asdu = ASDU(
                        type_id=asdu.type_id, sq=False, num=1,
                        cot=COT.ACTTERM, common_addr=self._common_addr,
                    )
                    term_asdu.objects.append(obj)
                    await self._send_i_frame(state, term_asdu.encode())
                else:
                    # 未选择，回复否定确认 (PN=1)
                    ack_asdu = ASDU(
                        type_id=asdu.type_id, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    # 设置否定确认标志 (PN=1, bit7 of first byte)
                    obj_data = bytearray(obj.data.to_bytes())
                    obj_data[0] |= 0x80  # PN=1
                    obj.data = bytes(obj_data)
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())
                    logger.warning(f"Setpoint Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            ack_asdu = ASDU(
                type_id=asdu.type_id, sq=False, num=1,
                cot=COT.DEACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
            logger.info(f"Setpoint Command DEACTCON: IOA={obj.ioa}")

    async def _handle_regulating_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理升降命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: RegulatingStepCommand = obj.data
        logger.info(
            f"Regulating Command from {state.conn.name}: "
            f"IOA={obj.ioa} state={cmd.state_str} select={cmd.select}"
        )
        self._fire_event(SlaveEvent.COMMAND_RECEIVED, {
            "client_id": state.conn.name,
            "type": "regulating",
            "ioa": obj.ioa,
            "state": cmd.state,
            "select": cmd.select,
        })
        if asdu.cot == COT.ACT:
            if cmd.select:
                # 选择命令：记录选择状态和时间
                state.selected_commands[obj.ioa] = (cmd, time.monotonic())
                # 回复选择确认
                ack_asdu = ASDU(
                    type_id=TypeID.C_RC_NA_1, sq=False, num=1,
                    cot=COT.ACTCON, common_addr=self._common_addr,
                )
                ack_asdu.objects.append(obj)
                await self._send_i_frame(state, ack_asdu.encode())
                logger.info(f"Regulating Command SELECT ACK: IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    ack_asdu = ASDU(
                        type_id=TypeID.C_RC_NA_1, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())

                    # 发送激活终止
                    term_asdu = ASDU(
                        type_id=TypeID.C_RC_NA_1, sq=False, num=1,
                        cot=COT.ACTTERM, common_addr=self._common_addr,
                    )
                    term_asdu.objects.append(obj)
                    await self._send_i_frame(state, term_asdu.encode())
                else:
                    # 未选择，回复否定确认 (PN=1)
                    ack_asdu = ASDU(
                        type_id=TypeID.C_RC_NA_1, sq=False, num=1,
                        cot=COT.ACTCON, common_addr=self._common_addr,
                    )
                    # 设置否定确认标志 (PN=1, bit7 of first byte)
                    obj_data = bytearray(obj.data.to_bytes())
                    obj_data[0] |= 0x80  # PN=1
                    obj.data = bytes(obj_data)
                    ack_asdu.objects.append(obj)
                    await self._send_i_frame(state, ack_asdu.encode())
                    logger.warning(f"Regulating Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            ack_asdu = ASDU(
                type_id=TypeID.C_RC_NA_1, sq=False, num=1,
                cot=COT.DEACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
            logger.info(f"Regulating Command DEACTCON: IOA={obj.ioa}")

    async def _handle_bitstring_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理比特串命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: BitString32Command = obj.data
        logger.info(f"Bitstring Command from {state.conn.name}: IOA={obj.ioa} value=0x{cmd.value:08X}")
        if asdu.cot == COT.ACT:
            # 比特串命令通常不需要选择-执行流程
            ack_asdu = ASDU(
                type_id=TypeID.C_BO_NA_1, sq=False, num=1,
                cot=COT.ACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())

            # 发送激活终止
            term_asdu = ASDU(
                type_id=TypeID.C_BO_NA_1, sq=False, num=1,
                cot=COT.ACTTERM, common_addr=self._common_addr,
            )
            term_asdu.objects.append(obj)
            await self._send_i_frame(state, term_asdu.encode())
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            ack_asdu = ASDU(
                type_id=TypeID.C_BO_NA_1, sq=False, num=1,
                cot=COT.DEACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
            logger.info(f"Bitstring Command DEACTCON: IOA={obj.ioa}")

    async def _handle_delay_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理延时获得命令."""
        logger.info(f"Delay Command from {state.conn.name}")
        # 延时获得命令是主站向子站请求延时信息
        # 子站收到后应以突发(COT=SPONT)方式回复延时值
        if asdu.cot == COT.ACT and asdu.objects:
            obj = asdu.objects[0]
            # 计算延时值（这里使用固定值，实际应用中应计算实际延时）
            delay_ms = 100  # 示例延时值
            asdu_data = ASDUBuilder.build_delay_command(
                self._common_addr, delay_ms
            )
            await self._send_i_frame(state, asdu_data)
            logger.info(f"Delay Response sent: delay={delay_ms}ms")

    async def _handle_parameter_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理参数命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        logger.info(f"Parameter Command from {state.conn.name}: type={asdu.type_id} IOA={obj.ioa}")
        if asdu.cot == COT.ACT:
            ack_asdu = ASDU(
                type_id=asdu.type_id, sq=False, num=1,
                cot=COT.ACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            ack_asdu = ASDU(
                type_id=asdu.type_id, sq=False, num=1,
                cot=COT.DEACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())
            logger.info(f"Parameter Command DEACTCON: IOA={obj.ioa}")

    async def _handle_file_transfer(self, state: _ClientState, asdu: ASDU) -> None:
        """处理文件传输."""
        type_id = asdu.type_id
        cot = asdu.cot
        logger.info(f"File Transfer from {state.conn.name}: type={type_id}, cot={cot}")

        if not asdu.objects:
            return

        obj = asdu.objects[0]

        # 召唤目录
        if type_id == TypeID.F_SC_NA_1 and cot == COT.ACT:
            if isinstance(obj.data, CallDirectory):
                self._file_transfer.handle_file_request(obj.ioa, obj.data.file_name, obj.data.qualifier)

        # 文件选择/召唤/获取
        elif type_id == TypeID.F_SC_NB_1 and cot == COT.ACT:
            if isinstance(obj.data, FileSelectCallGet):
                self._file_transfer.handle_file_request(obj.ioa, obj.data.file_name, obj.data.qualifier)

        # 文件准备就绪确认
        elif type_id == TypeID.F_FR_NB_1:
            if isinstance(obj.data, FileReadyAck):
                self._file_transfer.handle_file_ready_ack(obj.ioa, obj.data)

        # 节准备就绪确认
        elif type_id == TypeID.F_SR_NB_1:
            if isinstance(obj.data, SectionReadyAck):
                self._file_transfer.handle_section_ready_ack(obj.ioa, obj.data)

        # 确认文件/节
        elif type_id == TypeID.F_AF_NA_1:
            if isinstance(obj.data, AckFileSection):
                self._file_transfer.handle_ack(obj.ioa, obj.data)

        # 段
        elif type_id == TypeID.F_SG_NA_1:
            if isinstance(obj.data, FileSegment):
                self._file_transfer.handle_file_segment(obj.data)

        # 最后的节/段
        elif type_id == TypeID.F_LS_NA_1:
            if isinstance(obj.data, LastSection):
                self._file_transfer.handle_last_section(obj.data)

        else:
            logger.debug(f"Unhandled file transfer type: {type_id}")

    # ── 数据变化上送 ──────────────────────────────────────────────

    async def send_spontaneous_yx(self, ioa: int, value: bool,
                                    quality: int = 0) -> None:
        """自发上送遥信变化."""
        self._data_store.update_yx(ioa, value, QualityDescriptor(quality))

        if not self._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_spontaneous_single_point(
            self._common_addr, ioa, value, quality
        )
        await self._broadcast_i_frame(asdu_data)

    async def send_spontaneous_yc(self, ioa: int, value: float,
                                    quality: int = 0) -> None:
        """自发上送遥测变化."""
        self._data_store.update_yc(ioa, value, QualityDescriptor(quality))

        if not self._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_short_float(
            self._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await self._broadcast_i_frame(asdu_data)

    async def send_spontaneous_dp(self, ioa: int, value: int,
                                    quality: int = 0) -> None:
        """自发上送双点遥信变化."""
        self._data_store.update_yx(ioa, value == 2, QualityDescriptor(quality), double_state=value)

        if not self._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_double_point(
            self._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await self._broadcast_i_frame(asdu_data)

    async def send_spontaneous_ym(self, ioa: int, value: int,
                                    quality: int = 0) -> None:
        """自发上送累计量变化."""
        self._data_store.update_ym(ioa, value, QualityDescriptor(quality))

        if not self._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_counter_value(
            self._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await self._broadcast_i_frame(asdu_data)

    async def send_spontaneous_step(self, ioa: int, value: int,
                                      quality: int = 0) -> None:
        """自发上送步位置变化."""
        self._data_store.update_yc(ioa, float(value), QualityDescriptor(quality))

        if not self._spontaneous_enabled:
            return

        asdu_data = ASDUBuilder.build_step_position(
            self._common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )
        await self._broadcast_i_frame(asdu_data)

    # ── 数据模拟 ──────────────────────────────────────────────────

    def simulate_yx_change(self, ioa: int, value: bool) -> None:
        """模拟遥信变化."""
        self._data_store.update_yx(ioa, value)
        self._spawn(self.send_spontaneous_yx(ioa, value))

    def simulate_yc_change(self, ioa: int, value: float) -> None:
        """模拟遥测变化."""
        self._data_store.update_yc(ioa, value)
        self._spawn(self.send_spontaneous_yc(ioa, value))

    async def start_simulation(
        self,
        yx_interval: float = 5.0,
        yc_interval: float = 2.0,
        yx_change_rate: float = 0.1,
        yc_change_range: float = 0.05,
    ) -> None:
        """启动自动数据模拟."""
        if self._simulation_running:
            return

        self._simulation_running = True
        self._simulation_task = self._spawn(
            self._simulation_loop(yx_interval, yc_interval, yx_change_rate, yc_change_range)
        )
        logger.info("Simulation started")

    async def stop_simulation(self) -> None:
        """停止模拟."""
        self._simulation_running = False
        if self._simulation_task:
            self._simulation_task.cancel()
            try:
                await self._simulation_task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("Simulation stopped")

    async def _simulation_loop(
        self,
        yx_interval: float,
        yc_interval: float,
        yx_change_rate: float,
        yc_change_range: float,
    ) -> None:
        """模拟数据变化循环（随机变化）."""
        yx_tick = 0.0
        yc_tick = 0.0

        while self._simulation_running:
            await asyncio.sleep(0.1)
            now = time.monotonic()

            # 遥信随机变化
            if now - yx_tick >= yx_interval:
                yx_tick = now
                yx_points = self._point_table.get_all_yx()
                for p in yx_points:
                    if random.random() < yx_change_rate:
                        current = self._data_store.get_yx(p.ioa)
                        new_value = not current.value if current else True
                        await self.send_spontaneous_yx(p.ioa, new_value)

            # 遥测随机波动
            if now - yc_tick >= yc_interval:
                yc_tick = now
                yc_points = self._point_table.get_all_yc()
                for p in yc_points:
                    current = self._data_store.get_yc(p.ioa)
                    if current:
                        delta = current.value * yc_change_range * (random.random() * 2 - 1)
                        new_value = current.value + delta
                        new_value = max(p.min_value, min(p.max_value, new_value))
                        await self.send_spontaneous_yc(p.ioa, new_value)

    async def _auto_change_loop(self) -> None:
        """逐点自动变化循环 — 标记为 is_changing 的点按 change_interval 周期变化."""
        change_ticks: dict[int, float] = {}

        while self._auto_change_running:
            await asyncio.sleep(0.1)
            now = time.monotonic()

            # 遥信自动变化（翻转）
            yx_data = self._data_store._yx
            for ioa, point in list(yx_data.items()):
                if point.is_changing:
                    last_tick = change_ticks.get(ioa, 0)
                    if now - last_tick >= point.change_interval:
                        change_ticks[ioa] = now
                        new_value = not point.value
                        await self.send_spontaneous_yx(ioa, new_value)

            # 遥测自动变化（在最小值最大值范围内随机）
            yc_data = self._data_store._yc
            for ioa, point in list(yc_data.items()):
                if point.is_changing:
                    last_tick = change_ticks.get(f"yc_{ioa}", 0)
                    if now - last_tick >= point.change_interval:
                        change_ticks[f"yc_{ioa}"] = now
                        min_val = point.min_val if point.min_val != float('inf') else 0.0
                        max_val = point.max_val if point.max_val != float('-inf') else 100.0
                        if min_val >= max_val:
                            min_val, max_val = max_val - 100, max_val
                        new_value = min_val + random.random() * (max_val - min_val)
                        await self.send_spontaneous_yc(ioa, new_value)

    # ── 命令超时检查 ──────────────────────────────────────────────

    async def _timeout_check_loop(self) -> None:
        """定期检查命令选择超时和协议定时器."""
        while True:
            try:
                await asyncio.sleep(1.0)  # 每秒检查一次
                for conn_id, state in list(self._client_states.items()):
                    # 检查命令选择超时
                    timeout_ioas = state.check_command_timeout()
                    for ioa in timeout_ioas:
                        logger.warning(f"Command select timeout: client={conn_id}, IOA={ioa}")

                    # 检查协议定时器
                    expired = state.state_machine.check_timers()
                    if expired:
                        logger.warning(f"Timer expired: client={conn_id}, timer={expired}")
                        if expired == TimerType.T1:
                            # T1超时应断开连接
                            logger.error(f"T1 timeout: disconnecting client={conn_id}")
                            await state.conn.stop()
                        elif expired == TimerType.T2:
                            # T2超时发送S帧确认
                            rx_seq = state.seq.get_recv_seq()
                            frame = APCICodec.encode_s(rx_seq)
                            self._spawn(self._send_to_client(state, frame))
                            state.state_machine.on_s_frame_sent()
                            logger.info(f"T2 expired: S-Frame sent to {conn_id}")
                        elif expired == TimerType.T3:
                            # T3空闲超时发送TESTFR ACT
                            self._spawn(self._send_to_client(state, APCICodec.testfr_act()))
                            logger.info(f"T3 expired: TESTFR ACT sent to {conn_id}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Timeout check error: {e}")

            # 响应行为：主动 TESTFR
            if self._response_behavior.send_testfr and self._client_states:
                self._testfr_timer += 1.0
                interval = max(5.0, self._response_behavior.testfr_interval)
                if self._testfr_timer >= interval:
                    self._testfr_timer = 0.0
                    for conn_id, state in list(self._client_states.items()):
                        if state.data_transfer_enabled:
                            self._spawn(self._send_to_client(state, APCICodec.testfr_act()))
                            logger.info(f"Config TESTFR ACT sent to {conn_id}")

    # ── S帧回调 ───────────────────────────────────────────────────

    def _on_s_frame_needed(self, state: _ClientState, rx_seq: int) -> None:
        """当收到w个未确认的I帧时，由SequenceManager回调发送S帧."""
        frame = APCICodec.encode_s(rx_seq)
        self._spawn(self._send_to_client(state, frame))
        state.state_machine.on_s_frame_sent()
        logger.debug(f"S-Frame sent to {state.conn.name}: rx_seq={rx_seq}")
        # 通知等待窗口空间的协程
        state.window_available.set()

    # ── 内部发送 ──────────────────────────────────────────────────

    async def _send_i_frame(self, state: _ClientState, asdu_data: bytes) -> None:
        """向指定客户端发送 I 帧，窗口满时等待确认."""
        # 等待发送窗口可用（最多等 t1 超时时间）
        if not state.seq.send_window_available:
            logger.debug(f"Send window full for {state.conn.name}, waiting for S-frame...")
            state.window_available.clear()
            try:
                await asyncio.wait_for(state.window_available.wait(), timeout=self._t1)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Send window timeout: no S-frame received within t1={self._t1}s"
                )

        tx_seq = state.seq.get_send_seq()
        rx_seq = state.seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        await self._send_to_client(state, frame)
        state.state_machine.on_i_frame_sent()

    async def _send_to_client(self, state: _ClientState, frame: bytes) -> None:
        """发送帧到指定客户端。"""
        # 错误注入：丢帧
        if self._maybe_drop_frame():
            logger.warning(f"Frame dropped by response config (len={len(frame)})")
            self._errors += 1
            return

        # 错误注入：损坏帧（翻转最后一字节）
        if self._response_behavior.corrupt and len(frame) > 0:
            frame = bytearray(frame)
            frame[-1] ^= 0xFF
            frame = bytes(frame)
            logger.warning("Frame corrupted by response config")

        try:
            await state.conn.send_frame(frame)

            # 更新统计
            self._frames_sent += 1
            self._bytes_sent += len(frame)

            if self._raw_frame_callback:
                try:
                    self._raw_frame_callback(frame, "tx", state.conn.name)
                except Exception:
                    pass

            # 报文录制
            if self._recorder:
                self._recorder.record_frame(frame, direction="tx", metadata={"client_id": state.conn.name})

            self._tx_buffer.append((time.monotonic(), frame, state.conn.name))
            state.state_machine.on_any_frame_sent()

            # 记录到历史数据库
            if self._history_db:
                frame_type = "I" if len(frame) >= 6 and (frame[2] & 0x01) == 0 else (
                    "S" if len(frame) >= 6 and (frame[2] & 0x03) == 0x01 else "U"
                )
                self._history_db.record_frame("tx", frame, frame_type=frame_type, client_id=state.conn.name)
        except Exception as e:
            logger.error(f"Send to {state.conn.name} failed: {e}")
            self._errors += 1

    async def _broadcast_i_frame(self, asdu_data: bytes) -> None:
        """向所有已启动的客户端广播 I 帧."""
        for conn_id, state in self._client_states.items():
            if state.data_transfer_enabled and state.conn.is_connected:
                try:
                    await self._send_i_frame(state, asdu_data)
                except Exception as e:
                    logger.error(f"Broadcast to {conn_id} failed: {e}")

    # ── 事件分发 ──────────────────────────────────────────────────

    def _fire_event(self, event: SlaveEvent, data: dict = None) -> None:
        if self._event_callback:
            try:
                self._event_callback(event, data or {})
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    # ── 报文缓冲 ──────────────────────────────────────────────────

    def get_rx_buffer(self, count: int = 100) -> list[tuple[float, bytes, str]]:
        return self._rx_buffer[-count:]

    def get_tx_buffer(self, count: int = 100) -> list[tuple[float, bytes, str]]:
        return self._tx_buffer[-count:]


class _ClientState:
    """单个客户端连接的状态."""

    # 命令选择超时时间（秒）
    COMMAND_SELECT_TIMEOUT = 30.0

    def __init__(
        self,
        conn: TCPConnection,
        seq: SequenceManager,
        state_machine: ConnectionStateMachine,
    ):
        self.conn = conn
        self.seq = seq
        self.state_machine = state_machine
        self.data_transfer_enabled = False
        self.connected_at = time.monotonic()
        self.window_available = asyncio.Event()  # S帧确认后触发
        self.window_available.set()  # 初始时窗口可用

        # 命令选择状态存储 (IOA -> (命令对象, 选择时间))
        self.selected_commands: dict[int, tuple[Any, float]] = {}

    def check_command_timeout(self) -> list[int]:
        """检查命令选择超时，返回超时的IOA列表."""
        now = time.monotonic()
        timeout_ioas = []
        for ioa, (cmd, select_time) in list(self.selected_commands.items()):
            if now - select_time > self.COMMAND_SELECT_TIMEOUT:
                timeout_ioas.append(ioa)
                del self.selected_commands[ioa]
        return timeout_ioas
