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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..data.data_store import RealtimeDB
from ..data.history import HistoryDB
from ..data.point_table import PointTable, YxType
from ..protocol.apci import APCI, APCICodec
from ..protocol.asdu import ASDU, ASDUBuilder, InformationObject
from ..protocol.file_transfer import FileTransferSlave
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..protocol.types import (
    COT,
    AckFileSection,
    BitString32Command,
    CallDirectory,
    CP56Time2a,
    DoubleCommand,
    DoublePoint,
    FileReadyAck,
    FileSegment,
    FileSelectCallGet,
    LastSection,
    QualityDescriptor,
    RegulatingStepCommand,
    SectionReadyAck,
    SingleCommand,
    TypeID,
)
from ..transport.connection import TCPConnection, TCPServer
from .base import EngineBase

logger = logging.getLogger("iec104.slave")

# 标准已定义的传送原因取值集合（用于识别"未知传送原因"）。
_VALID_COTS: frozenset[int] = frozenset(int(member) for member in COT)


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
    def from_dict(cls, config: dict) -> ResponseBehavior:
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


def _split_contiguous(batch: list[tuple], max_per_frame: int) -> list[list[tuple]]:
    """把批量点拆分为「IOA 连续」的若干帧数据.

    SQ=1 的序列帧只在帧内发送**第一个**对象的 IOA，其余对象 IOA 由 +1 推得
    （见 ``ASDU.encode``），因此只有 IOA 连续的点才能打包进同一帧。

    实测缺陷：点表 YX={1, 2001, 2002} 曾被打包成一帧 SQ=1（首 IOA=1，num=3），
    主站按标准解出 IOA=1/2/3 —— 2001/2002 的遥信被静默错址写入 2/3。
    本函数按 IOA 升序切分连续段，并对每段再做 ``max_per_frame`` 限长。

    Args:
        batch: [(ioa, ...), ...]，元素仅要求首项为 IOA。
        max_per_frame: 单帧最大对象数（受 APDU 253 字节约束）。

    Returns:
        帧数据列表，每段可直接喂给 ``build_*_sequence``。
    """
    ordered = sorted(batch, key=lambda item: item[0])
    chunks: list[list[tuple]] = []
    current: list[tuple] = []
    for item in ordered:
        if current and (item[0] != current[-1][0] + 1 or len(current) >= max_per_frame):
            chunks.append(current)
            current = []
        current.append(item)
    if current:
        chunks.append(current)
    return chunks


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
    ):
        super().__init__()
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
        self._file_transfer = FileTransferSlave(common_addr)
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

    def _apply_quality(self, quality: int) -> int:
        """按配置强制注入品质位。"""
        mask = self._response_behavior.quality_mask()
        if mask:
            return quality | mask
        return quality

    def _reply_cot(self, cot: int) -> int:
        """应答的传送原因（按配置可注入错误 COT）。

        配置 ``errors.wrong_cot=True`` 时，子站对请求的应答（命令确认、
        召唤确认/数据/结束、时钟同步确认）的 COT 整体错位 ``_WRONG_COT_OFFSET``，
        用于验证主站对 COT 的严格校验与超时处理。自发上送与标准错误应答
        （COT 42/43/44）不参与注入，避免混淆测试结论。
        """
        if not self._response_behavior.wrong_cot:
            return int(cot)
        return (int(cot) + self._WRONG_COT_OFFSET) & 0x3F

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
                # t0 是"连接建立超时"，仅适用于发起连接的控制站（主站）。
                # 子站为被控站，被动接受连接，不使用 t0（标准 IEC 60870-5-104）。
                use_t0=False,
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
            frame_type = APCICodec.frame_type_of(frame)
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
            # 解码失败（多为未知类型标识）→ 解析头部后按标准回送 COT=42
            logger.error(f"ASDU decode error: {e}")
            self._spawn(self._send_unknown_type_response(state, asdu_data))

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
        """发送初始化结束报文 (M_EI_NA_1).

        使用协议层构造器（原为内联手搓 ASDU，构造逻辑不统一）。
        """
        asdu_data = ASDUBuilder.build_initialization_end(
            self._common_addr, cot=COT.INIT, cause=2,   # cause=2: 远方复位
        )
        await self._send_i_frame(state, asdu_data)
        logger.info(f"Initialization End sent to {state.conn.name}")

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

    async def _send_standard_error(self, state: _ClientState, type_id: Any,
                                    cot: int, common_addr: int) -> None:
        """按标准回送错误应答 (COT=42/43/44).

        ASDU 仅含头部（无信息体），携带原类型标识与公共地址，保持连接不中断。
        标准依据: IEC 60870-5-104 Table 1-72 (COT 42/43/44)。
        """
        ack = ASDU(
            type_id=type_id,
            sq=False, num=0, cot=cot, common_addr=common_addr,
        )
        await self._send_i_frame(state, ack.encode())
        logger.info(
            f"Standard error reply sent: COT={cot}, type={type_id}, ca={common_addr}"
        )

    async def _send_unknown_type_response(self, state: _ClientState,
                                           asdu_data: bytes) -> None:
        """解码失败（多为未知类型标识）→ 回送 COT=42（未知类型标识）.

        通过 ASDU.decode_header 仅解析头部，即使信息体类型未知也能提取
        TypeID/COT/CA，从而按标准应答并保持连接。
        """
        try:
            header = ASDU.decode_header(asdu_data)
        except Exception as e:
            logger.error(f"Cannot decode header for unknown-type reply: {e}")
            return
        await self._send_standard_error(
            state, header.type_id, COT.UNKNOWN_TYPE, header.common_addr
        )

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
        ack = ASDUBuilder.build_general_interrogation_ack(
            self._common_addr, qoi, cot=self._reply_cot(COT.ACTCON)
        )
        await self._send_i_frame(state, ack)

        # 发送所有数据
        await self._send_interrogation_data(state, qoi)

        # 发送激活结束
        term = ASDUBuilder.build_general_interrogation_end(
            self._common_addr, qoi, cot=self._reply_cot(COT.ACTTERM)
        )
        await self._send_i_frame(state, term)

        self._fire_event(SlaveEvent.GI_RECEIVED, {
            "client_id": state.conn.name, "qoi": qoi
        })

    async def _send_interrogation_data(self, state: _ClientState, qoi: int) -> None:
        """发送总召唤数据（批量打包，SQ=1，分批发送）.

        qoi 为收到的标准限定词: 20=站召唤; 21-36=第1-16组召唤。
        组号 = qoi - 20；响应 COT 采用标准值 (20 或 21-36)。

        打包约束: SQ=1 只发送帧内首个 IOA，故必须先按 IOA 连续段切分
        （``_split_contiguous``），否则接收方会按 +1 推出错误的 IOA。

        范围说明: 召唤应答只上送**当前值**（M_SP_NA_1 / M_DP_NA_1 / M_ME_NC_1 /
        M_IT_NA_1）。带时标的 SOE（M_SP_TB_1, COT=3）属突发上送，由
        ``send_spontaneous_yx`` 在变位发生时发送；此处不应重复上送，
        否则同一遥信会在召唤里出现两次且类型不符合标准。
        """
        group = COT.get_group_number(qoi) if COT.is_group_response(qoi) else None
        cot = self._reply_cot(
            COT.INTROGEN if group is None else COT.group_response(group)
        )

        # IEC 104 限制: VSQ 低7位最大127，APDU最大253字节
        # 实际安全批次大小（考虑APDU长度限制）— 使用类属性常量

        # ── 遥信打包发送（单点/双点按**点表声明**分流，每点只上送一次）──
        yx_points = self._point_table.get_all_yx()
        if group is not None:
            yx_points = self._point_table.get_yx_by_group(group)

        yx_batch = []
        dp_batch = []
        for p in yx_points:
            if not p.enabled:
                continue
            yx_data = self._data_store.get_yx(p.ioa)
            if yx_data is None:
                continue
            quality = self._apply_quality(yx_data.quality.to_int())
            if p.point_type == YxType.DOUBLE:
                # 双点状态 0/1/2/3 均为合法取值（1=分, 2=合, 0/3=非确定态），
                # 必须原样上送 —— 用真值判断（`if yx_data.double_state`）会漏掉状态 0
                dp_batch.append((p.ioa, int(yx_data.double_state), quality))
            else:
                yx_batch.append((p.ioa, yx_data.value, quality))

        for chunk in _split_contiguous(yx_batch, self._MAX_SP_PER_FRAME):
            asdu_data = ASDUBuilder.build_single_point_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # ── 双点遥信打包发送 ──
        for chunk in _split_contiguous(dp_batch, self._MAX_DP_PER_FRAME):
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
        if group is not None:
            yc_points = self._point_table.get_yc_by_group(group)

        yc_batch = []
        for p in yc_points:
            if not p.enabled:
                continue
            yc_data = self._data_store.get_yc(p.ioa)
            if yc_data:
                yc_batch.append((p.ioa, yc_data.value, self._apply_quality(yc_data.quality.to_int())))

        for chunk in _split_contiguous(yc_batch, self._MAX_MV_PER_FRAME):
            asdu_data = ASDUBuilder.build_short_float_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # ── 累计量打包发送 ──
        ym_points = self._point_table.get_all_ym()
        if group is not None:
            ym_points = self._point_table.get_ym_by_group(group) if hasattr(self._point_table, 'get_ym_by_group') else []

        ym_batch = []
        for p in ym_points:
            if not p.enabled:
                continue
            ym_data = self._data_store.get_ym(p.ioa)
            if ym_data:
                ym_batch.append((p.ioa, ym_data.value, ym_data.quality.to_int(), 0))

        for chunk in _split_contiguous(ym_batch, self._MAX_IT_PER_FRAME):
            asdu_data = ASDUBuilder.build_counter_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

    async def _handle_counter_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理累计量召唤."""
        qcc = asdu.objects[0].data[0] if asdu.objects else 0
        logger.info(f"Counter Interrogation from {state.conn.name}: QCC={qcc}")

        # 确认
        asdu_ack = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=self._reply_cot(COT.ACTCON), common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

        # 根据 qcc 组号确定标准响应 COT:
        #   组号 0 → 37 (累计量总请求); 组号 1-4 → 38-41 (第1-4组请求)
        group = qcc & 0x07
        if 1 <= group <= 4:
            cot = self._reply_cot(COT.counter_group_response(group))
        else:
            cot = self._reply_cot(COT.COUNTER_REQ)

        # 发送电度数据 - 使用正确的类型 M_IT_NA_1 (累计量)

        ym_batch = []
        for p in self._point_table.get_all_ym():
            if not p.enabled:
                continue
            ym_data = self._data_store.get_ym(p.ioa)
            if ym_data:
                ym_batch.append((p.ioa, ym_data.value, ym_data.quality.to_int(), 0))

        # 分批打包发送（SQ=1 要求帧内 IOA 连续）
        for chunk in _split_contiguous(ym_batch, self._MAX_IT_PER_FRAME):
            asdu_data = ASDUBuilder.build_counter_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

        # 结束
        asdu_term = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=self._reply_cot(COT.ACTTERM), common_addr=self._common_addr,
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

        ack = ASDUBuilder.build_clock_sync_ack(
            self._common_addr, time_tag=received_time,
            cot=self._reply_cot(COT.ACTCON),
        )
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

        # 点表无此 IOA：按标准回送 COT=45（未知信息对象地址），而不是静默丢弃
        logger.info(f"Read Command for unknown IOA={ioa} → reply COT=45")
        await self._send_standard_error(state, asdu.type_id, COT.UNKNOWN_IOA,
                                        self._common_addr)

    async def _handle_reset_process(self, state: _ClientState, asdu: ASDU) -> None:
        """处理复位进程."""
        logger.info(f"Reset Process from {state.conn.name}")
        # 确认（回送 ACTCON + 原对象）
        asdu_ack = ASDU(
            type_id=TypeID.C_RP_NA_1, sq=False, num=1,
            cot=COT.ACTCON, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

    async def _handle_test_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理测试命令.

        按标准回显 T 试验位（COT bit7）：主站以 T=1 下发测试命令时，应答必须同样置位，
        否则一致性测试会判为未正确响应试验报文。
        """
        logger.info(f"Test Command from {state.conn.name} (T={int(asdu.test)})")
        asdu_ack = ASDU(
            type_id=asdu.type_id, sq=False, num=1,
            cot=COT.ACTCON, test=asdu.test, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

    def _command_requires_sbo(self, ioa: int, *, is_setpoint: bool = False) -> bool:
        """判定指定 IOA 的遥控命令是否需要 SBO (选择-执行) 过程.

        来源为子站自身点表:
        - 遥控点 (YK): ``YkPointDef.select_before_execute`` (YAML ``sbo`` 字段)
        - 设点对应的遥测点 (YC) 无该字段, 默认按 False (直发执行) 处理

        Args:
            ioa: 信息对象地址。
            is_setpoint: 是否为设点(遥调)命令。设点在点表中对应遥测点，
                因此回落顺序为 YK → YC，且无点表定义时默认 False。

        Returns:
            True 表示需要 SBO (未选择则拒绝)；False 表示可直接执行。
        """
        yk_point = self._point_table.get_yk(ioa)
        if yk_point is not None:
            return bool(yk_point.select_before_execute)

        # 设点命令: 对应的 YC 点无 sbo 字段, 默认直发执行 (False);
        # 未在遥控点表中定义的其它命令: 保持现有严格 SBO 行为 (True), 不破坏既有用例
        return not is_setpoint

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
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Single Command SELECT ACK: IOA={obj.ioa}")
            elif not self._command_requires_sbo(obj.ioa):
                # 直发执行点 (sbo=false)：无需预先选择，直接执行
                state.selected_commands.pop(obj.ioa, None)
                # 回复执行确认
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                # 更新数据
                self._data_store.update_yk(obj.ioa, "execute", cmd.state)

                # 发送激活终止
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                await self._reflect_command_result(obj.ioa, single=bool(cmd.state))
                logger.info(f"Single Command DIRECT EXECUTE (sbo=false): IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 更新数据
                    self._data_store.update_yk(obj.ioa, "execute", cmd.state)

                    # 发送激活终止
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                    # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                    await self._reflect_command_result(obj.ioa, single=bool(cmd.state))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Single Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
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
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Double Command SELECT ACK: IOA={obj.ioa}")
            elif not self._command_requires_sbo(obj.ioa):
                # 直发执行点 (sbo=false)：无需预先选择，直接执行
                state.selected_commands.pop(obj.ioa, None)
                # 回复执行确认
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                # 更新数据
                self._data_store.update_yk(obj.ioa, "execute", cmd.state)

                # 发送激活终止
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                await self._reflect_command_result(obj.ioa, double_state=int(cmd.state))
                logger.info(f"Double Command DIRECT EXECUTE (sbo=false): IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 更新数据
                    self._data_store.update_yk(obj.ioa, "execute", cmd.state)

                    # 发送激活终止
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                    # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                    await self._reflect_command_result(obj.ioa, double_state=int(cmd.state))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Double Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Double Command DEACTCON: IOA={obj.ioa}")

    async def _handle_setpoint_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理设点命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        # 设点目标值（归一化/标度化/短浮点均有 .value）
        setpoint_value = getattr(obj.data, "value", None)
        logger.info(f"Setpoint Command from {state.conn.name}: IOA={obj.ioa} value={setpoint_value}")

        if asdu.cot == COT.ACT:
            # 检查是否是选择命令
            is_select = False
            if hasattr(obj.data, 'select'):
                is_select = obj.data.select

            if is_select:
                # 选择命令：记录选择状态和时间
                state.selected_commands[obj.ioa] = (obj.data, time.monotonic())
                # 回复选择确认
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Setpoint Command SELECT ACK: IOA={obj.ioa}")
            elif not self._command_requires_sbo(obj.ioa, is_setpoint=True):
                # 直发执行点 (sbo=false / 无 sbo 字段的 YC 点)：直接执行
                state.selected_commands.pop(obj.ioa, None)
                # 回复执行确认
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                # 发送激活终止
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                # 真机语义：遥调成功后同 IOA 遥测更新并主动上送
                if setpoint_value is not None:
                    await self._reflect_command_result(obj.ioa, yc_value=float(setpoint_value))
                logger.info(f"Setpoint Command DIRECT EXECUTE (sbo=false): IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 发送激活终止
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                    # 真机语义：遥调成功后同 IOA 遥测更新并主动上送
                    if setpoint_value is not None:
                        await self._reflect_command_result(obj.ioa, yc_value=float(setpoint_value))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Setpoint Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Setpoint Command DEACTCON: IOA={obj.ioa}")

    async def _handle_regulating_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理升降命令.

        说明（与遥控/遥调的联动策略不同，属有意为之）：升降命令改变的是**调节步位置**
        （真机上为 M_ST_NA_1 步位置或档位），不是遥信位置；本工具点表未建模步位置点，
        故不做联动上送。若后续需要，应新增步位置点类型与对应的自发上送路径。
        """
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
                await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Regulating Command SELECT ACK: IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 发送激活终止
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Regulating Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
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
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

            # 发送激活终止
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Bitstring Command DEACTCON: IOA={obj.ioa}")

    async def _handle_delay_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理延时获得命令 (C_CD_NA_1).

        真机语义：主站在命令中给出期望延时，子站**按该延时**推迟应答并回显实际延时
        （原实现固定回 100ms 示例值，与请求无关）。
        """
        logger.info(f"Delay Command from {state.conn.name}")
        if asdu.cot == COT.ACT and asdu.objects:
            data = asdu.objects[0].data
            requested = int(getattr(data, "delay_ms", 0) or 0)
            applied = max(0, min(requested, self._MAX_DELAY_MS))
            if applied:
                await asyncio.sleep(applied / 1000.0)
            asdu_data = ASDUBuilder.build_delay_command(self._common_addr, applied)
            await self._send_i_frame(state, asdu_data)
            logger.info(f"Delay Response sent: requested={requested}ms applied={applied}ms")

    async def _handle_parameter_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理参数命令.

        标准流程:
          - P_ME_NA_1/NB_1/NC_1/ND_1 (参数装载): ACT → ACTCON
          - P_AC_NA_1 (参数激活):             ACT → ACTCON → ACTTERM
        未装载直接激活时回否定确认 (COT bit6 P/N=1)。
        """
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        logger.info(f"Parameter Command from {state.conn.name}: type={asdu.type_id} IOA={obj.ioa}")
        if asdu.cot == COT.ACT:
            if asdu.type_id == TypeID.P_AC_NA_1:
                qualifier = getattr(obj.data, "qualifier", 0)
                if qualifier == 1 and obj.ioa not in state.loaded_parameters:
                    # 激活但尚未装载 → 否定确认
                    await self._send_i_frame(
                        state,
                        self._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True),
                    )
                    logger.warning(
                        f"Parameter Activation REJECTED (not loaded): IOA={obj.ioa}"
                    )
                else:
                    await self._send_i_frame(
                        state,
                        self._build_command_ack(asdu.type_id, COT.ACTCON, obj),
                    )
                    await self._send_i_frame(
                        state,
                        self._build_command_ack(asdu.type_id, COT.ACTTERM, obj),
                    )
                    logger.info(f"Parameter Activation: IOA={obj.ioa} qualifier={qualifier}")
            else:
                # 参数装载 (P_ME_*): 记录已装载参数并回 ACTCON
                state.loaded_parameters.add(obj.ioa)
                await self._send_i_frame(
                    state,
                    self._build_command_ack(asdu.type_id, COT.ACTCON, obj),
                )
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态并移除已装载记录
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            state.loaded_parameters.discard(obj.ioa)
            # 回复停止激活确认
            await self._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
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

    async def _reflect_command_result(self, ioa: int, *,
                                      single: bool | None = None,
                                      double_state: int | None = None,
                                      yc_value: float | None = None) -> bool:
        """把命令执行结果联动到被控点并自发上送（**以真机为准**）.

        真机语义：
        - 遥控执行成功后，同 IOA 的遥信立即变位并带时标上送（COT=3, SOE）；
        - 遥调/设点执行成功后，同 IOA 的遥测更新并上报（COT=3）；
        - 上送类型由**点表声明**决定：单点遥信 → M_SP_TB_1，双点遥信 → M_DP_TB_1；
        - 点表没有该点、或值未发生变化时不上送（真机不做无变化的冗余上送）。

        上送受 ``spontaneous_enabled`` 约束（关闭时仍更新实时库，供召唤使用）。

        Args:
            ioa: 被控点 IOA（与命令 IOA 相同）。
            single: 单命令目标状态（True=合）。
            double_state: 双命令目标状态（1=分, 2=合）。
            yc_value: 设点目标值（工程值）。

        Returns:
            True 表示已完成联动（值有变化或被更新）。
        """
        if yc_value is not None:
            if self._point_table.get_yc(ioa) is None:
                logger.debug(f"Command feedback: YC IOA={ioa} 不在点表，跳过联动")
                return False
            current_yc = self._data_store.get_yc(ioa)
            if current_yc is not None and abs(float(current_yc.value) - float(yc_value)) < 1e-9:
                return False
            await self.send_spontaneous_yc(ioa, float(yc_value))
            return True

        point = self._point_table.get_yx(ioa)
        if point is None:
            logger.debug(f"Command feedback: YX IOA={ioa} 不在点表，跳过联动")
            return False
        current = self._data_store.get_yx(ioa)

        if double_state is not None and point.point_type == YxType.DOUBLE:
            if current is not None and current.double_state == int(double_state):
                return False
            await self.send_spontaneous_dp(ioa, int(double_state))
            return True

        value = bool(single) if single is not None else (double_state == 2)
        if current is not None and bool(current.value) == value:
            return False
        await self.send_spontaneous_yx(ioa, value)
        return True

    async def send_spontaneous_yx(self, ioa: int, value: bool,
                                    quality: int = 0) -> None:
        """自发上送遥信变化.

        若该 IOA 在点表中声明为**双点**，则按真机语义转成双点上送
        （M_DP_TB_1，状态 2=合/1=分），避免双点遥信以单点类型上送造成类型错配。
        """
        point = self._point_table.get_yx(ioa)
        if point is not None and point.point_type == YxType.DOUBLE:
            await self.send_spontaneous_dp(ioa, 2 if value else 1)
            return
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

    async def send_protection_event(self, ioa: int, event_value: int = 1,
                                     with_time: bool = True, quality: int = 0) -> None:
        """模拟继电保护设备事件上送 (M_EP_TD_1 / M_EP_TA_1, COT=3).

        说明：点表未建模继保事件点，本方法为**测试注入**用途——直接广播报文，
        不落实时库（主站侧按 M_EP_* 类型自行处理/展示）。
        """
        if not self._spontaneous_enabled:
            return
        asdu_data = ASDUBuilder.build_protection_event(
            self._common_addr, ioa, event_value, quality,
            with_time=with_time, cot=COT.SPONT,
        )
        await self._broadcast_i_frame(asdu_data)

    async def send_group_single_point(self, ioa: int,
                                       points: list[tuple[bool, bool]],
                                       with_time: bool = False) -> None:
        """模拟带状态检出的成组单点信息上送 (M_PS_NA_1 / M_PS_TB_1, COT=3).

        同上，属测试注入：每点 (状态, 检出位)，最多 8 点，不落实时库。
        注意：M_PS_* 信息体本身不含品质描述词。
        """
        if not self._spontaneous_enabled:
            return
        asdu_data = ASDUBuilder.build_group_single_point(
            self._common_addr, ioa, points,
            cot=COT.SPONT, with_time=with_time,
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
                            # T3空闲超时发送TESTFR ACT（U帧，需在t1内收到CON）
                            self._spawn(self._send_to_client(state, APCICodec.testfr_act()))
                            state.state_machine.on_u_frame_act_sent()
                            logger.info(f"T3 expired: TESTFR ACT sent to {conn_id}")
                        # 注: T0 为"连接建立超时"，仅适用于发起连接的控制站（主站）。
                        # 子站为被控站，其状态机以 use_t0=False 创建（见
                        # _on_client_connected），不会启动 t0，故此处无需处理。
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
                            state.state_machine.on_u_frame_act_sent()
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
                ) from None

        tx_seq = state.seq.get_send_seq()
        rx_seq = state.seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        await self._send_to_client(state, frame)
        state.state_machine.on_i_frame_sent()

    def _build_command_ack(self, type_id: TypeID, cot: int,
                            obj: InformationObject, pn: bool = False) -> bytes:
        """构造命令确认/终止 ASDU 并编码为字节序列.

        消除各命令处理方法中重复的 ASDU 构造样板代码。

        Args:
            type_id: 类型标识
            cot: 传送原因
            obj: 回显的信息对象
            pn: 否定确认标志 (COT bit6)；True 表示否定确认
        """
        ack_asdu = ASDU(
            type_id=type_id, sq=False, num=1,
            cot=self._reply_cot(cot), pn=pn, common_addr=self._common_addr,
        )
        ack_asdu.objects.append(obj)
        return ack_asdu.encode()

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
                frame_type = APCICodec.frame_type_of(frame)
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
        return list(self._rx_buffer)[-count:]

    def get_tx_buffer(self, count: int = 100) -> list[tuple[float, bytes, str]]:
        return list(self._tx_buffer)[-count:]


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

        # 已装载参数 (IOA 集合) — 用于 P_AC_NA_1 激活前校验
        self.loaded_parameters: set[int] = set()

    def check_command_timeout(self) -> list[int]:
        """检查命令选择超时，返回超时的IOA列表."""
        now = time.monotonic()
        timeout_ioas = []
        for ioa, (_cmd, select_time) in list(self.selected_commands.items()):
            if now - select_time > self.COMMAND_SELECT_TIMEOUT:
                timeout_ioas.append(ioa)
                del self.selected_commands[ioa]
        return timeout_ioas
