"""主站引擎 — IEC 60870-5-104 Master Station.

实现:
- 连接管理（STARTDT/STOPDT）
- 总召唤/组召唤
- 时钟同步
- 累计量召唤
- 遥控/遥调操作
- 周期轮询
- 报文解析与分发

本模块保留 ``MasterEngine`` 的编排与**公开 API**（薄门面）；命令构建与 ASDU
解码分发见 ``master_protocol.MasterProtocolHandler``（组合持有）。连接/状态/
帧接收/定时器逻辑暂仍由本类承载。全部共享状态由本类持有，公开方法签名与行为
保持不变。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from ..data.data_store import RealtimeDB
from ..data.history import HistoryDB
from ..data.point_table import PointTable
from ..protocol.apci import APCI, APCICodec
from ..protocol.asdu import ASDU
from ..protocol.file_transfer import FileTransferMaster, FileTransferState
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..protocol.types import COT, CP56Time2a
from ..transport.connection import ConnectionStats, TCPClient
from .base import EngineBase
from .master_protocol import MasterEvent, MasterProtocolHandler
from .scheduler import TaskScheduler

logger = logging.getLogger("iec104.master")

# 兼容旧导入路径：MasterEvent 仍可从 core.engine.master 导入
__all__ = ["MasterEngine", "MasterEvent"]

EventCallback = Callable[[MasterEvent, dict[str, Any]], None]


class MasterEngine(EngineBase):
    """IEC 104 主站引擎.

    典型使用:
        engine = MasterEngine(host="192.168.1.100", port=2404)
        engine.set_event_callback(my_handler)
        await engine.start()
        await engine.general_interrogation()
        ...
        await engine.stop()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2404,
        common_addr: int = 1,
        k: int = 12,
        w: int = 8,
        t0: float = 30,
        t1: float = 15,
        t2: float = 10,
        t3: float = 20,
        auto_start: bool = True,        # 连接后自动发送STARTDT
        auto_gi: bool = False,           # STARTDT后自动总召唤
        auto_gi_on_init_end: bool = False,  # 收到初始化结束(COT=4)后自动重总召唤
        # 默认关闭：实测部分真机在收到主站 I 帧后会断开或停摆数据流，
        # 自动重 GI 会造成「重连→EI→GI→被断开」的无限循环。对这类装置请保持
        # 关闭，改为手动总召唤；对支持该语义的装置可开启。
        auto_add_points: bool = True,   # 按报文解析结果自动补充定义表点位（点位自学习）
        gi_interval: float = 0.0,       # 周期总召唤间隔（秒），0=不周期召唤
        reconnect: bool = True,
        reconnect_interval: float = 5.0,
        history_db: HistoryDB | None = None,
        point_table: PointTable | None = None,
    ):
        super().__init__()

        # 组合组件（构造期注入引擎引用；仅保存引用，不读取尚未初始化的状态）
        self._protocol = MasterProtocolHandler(self)

        self._host = host
        self._port = port
        self._common_addr = common_addr
        self._auto_start = auto_start
        self._auto_gi = auto_gi
        self._auto_gi_on_init_end = auto_gi_on_init_end
        self._auto_add_points = auto_add_points
        self._gi_interval = float(gi_interval or 0.0)
        self._periodic_gi_task: asyncio.Task | None = None

        # 协议组件
        self._seq = SequenceManager(k=k, w=w)
        self._state_machine = ConnectionStateMachine(
            t0=t0, t1=t1, t2=t2, t3=t3,
            on_state_change=self._on_state_change,
            on_timer_expired=self._on_timer_expired,
        )

        # 发送超时 t1（用于 k 窗口耗尽的对称等待，与子站行为一致）
        self._t1 = t1
        # 发送窗口可用事件：窗口满时清除，收到确认释放空间时置位
        self._window_available = asyncio.Event()
        self._window_available.set()

        # 数据存储
        self._data_store = RealtimeDB()

        # 点表（可选）：用于查询遥控点的 SBO (选择-执行) 配置。
        # 为 None 时不启用自动两段式，保持既有单帧发送语义。
        self._point_table: PointTable | None = point_table

        # 命令确认（ACTCON）等待：IOA → Future，由 _resolve_pending_ack 唤醒。
        self._pending_acks: dict[int, asyncio.Future] = {}

        # 历史数据库
        self._history_db = history_db

        # 定时任务调度器
        self._scheduler = TaskScheduler()

        # 报文录制器
        self._recorder = None

        # TCP 客户端
        self._client = TCPClient(
            host=host,
            port=port,
            reconnect_interval=reconnect_interval,
            max_reconnects=0 if reconnect else 1,
            on_frame=self._on_frame_received,
            on_connected=self._on_tcp_connected,
            on_disconnected=self._on_tcp_disconnected,
        )

        # 回调
        self._event_callback: EventCallback | None = None
        self._raw_frame_callback: Callable[[bytes, str], None] | None = None

        # 定时器检查任务
        self._timer_task: asyncio.Task | None = None

        # 报文缓冲
        self._rx_buffer: deque = deque(maxlen=1000)
        self._tx_buffer: deque = deque(maxlen=1000)

        # 时钟同步校验
        self._last_clock_sync_sent_time: float | None = None

        # 文件传输管理器
        self._file_transfer = FileTransferMaster(common_addr)
        self._file_transfer.set_callbacks(
            on_send_asdu=lambda data: self._spawn(
                self._protocol.send_i_frame_with_data(data)
            ),
            on_file_received=self._protocol.on_file_received,
            on_error=self._protocol.on_file_transfer_error,
        )

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state_machine.state

    @property
    def is_running(self) -> bool:
        return self._state_machine.is_running

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
    def sequence_manager(self) -> SequenceManager:
        return self._seq

    @property
    def connection_stats(self) -> ConnectionStats | None:
        return self._client.stats

    @property
    def scheduler(self) -> TaskScheduler:
        return self._scheduler

    @property
    def history_db(self) -> HistoryDB | None:
        return self._history_db

    @property
    def point_table(self) -> PointTable | None:
        """当前点表引用（供 SBO 查询使用），未设置时为 None."""
        return self._point_table

    def set_point_table(self, point_table: PointTable | None) -> None:
        """设置点表引用.

        设置后，遥控/设点命令在发送前会查询该 IOA 的 ``select_before_execute``，
        对 SBO 点位自动执行"选择-执行"两段式下发。
        """
        self._point_table = point_table

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_event_callback(self, callback: EventCallback) -> None:
        self._event_callback = callback

    def set_raw_frame_callback(self, callback: Callable[[bytes, str], None]) -> None:
        """设置原始帧回调 (data, direction: 'rx'/'tx')."""
        self._raw_frame_callback = callback

    def get_raw_frame_callback(self) -> Callable | None:
        """获取当前原始帧回调（供外部模块安全访问，避免直接访问私有属性）."""
        return self._raw_frame_callback

    def set_packet_recorder(self, recorder) -> None:
        """设置报文录制器."""
        self._recorder = recorder

    # ── 生命周期 ──────────────────────────────────────────────────

    async def start(self) -> None:
        """启动主站引擎."""
        logger.info(f"Starting master engine: {self._host}:{self._port}")

        # S帧回调
        self._seq.set_s_frame_callback(self._send_s_frame)

        # 启动定时器检查
        self._timer_task = self._spawn(self._timer_loop())

        # 启动定时任务调度器
        await self._scheduler.start()

        # 启动TCP连接
        await self._client.start()

    async def stop(self) -> None:
        """停止主站引擎."""
        logger.info("Stopping master engine")

        # 停止调度器
        await self._scheduler.stop()

        # 停止周期总召唤
        if self._periodic_gi_task:
            self._periodic_gi_task.cancel()
            try:
                await asyncio.wait_for(self._periodic_gi_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            self._periodic_gi_task = None

        if self._timer_task:
            self._timer_task.cancel()
            try:
                await asyncio.wait_for(self._timer_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        # 刷新历史数据库
        if self._history_db:
            await asyncio.to_thread(self._history_db.flush)

        await asyncio.wait_for(self._client.stop(), timeout=3.0)
        self._state_machine.on_disconnected()
        self._fire_event(MasterEvent.STOPPED)

    # ── 协议命令（门面 → MasterProtocolHandler / MasterSession）────

    async def send_startdt(self) -> None:
        """发送 STARTDT ACT."""
        frame = APCICodec.startdt_act()
        await self._send_frame(frame)
        self._state_machine.on_startdt_act_sent()
        logger.info("STARTDT ACT sent")

    async def send_stopdt(self) -> None:
        """发送 STOPDT ACT."""
        frame = APCICodec.stopdt_act()
        await self._send_frame(frame)
        # STOPDT ACT 属 U 格式报文，发送后须在 t1 内收到 STOPDT CON
        self._state_machine.on_u_frame_act_sent()
        logger.info("STOPDT ACT sent")

    async def _await_send_window(self) -> None:
        """等待发送窗口可用（最多 t1）— 与子站行为对称."""
        await self._protocol.await_send_window()

    async def _send_command_asdu(self, asdu_data: bytes) -> None:
        """发送命令 ASDU — 公共封装（状态检查 + 序列号 + 编码 + 发送）."""
        await self._protocol.send_command_asdu(asdu_data)

    async def general_interrogation(self, qoi: int = 20) -> None:
        """发送总召唤命令."""
        await self._protocol.general_interrogation(qoi)

    async def counter_interrogation(self, qcc: int = 0) -> None:
        """发送累计量召唤命令."""
        await self._protocol.counter_interrogation(qcc)

    async def clock_sync(self, time_tag: CP56Time2a | None = None) -> None:
        """发送时钟同步命令."""
        await self._protocol.clock_sync(time_tag)

    async def reset_process(self, qrp: int = 1) -> None:
        """发送复位进程命令."""
        await self._protocol.reset_process(qrp)

    async def send_test_command(self) -> None:
        """发送测试命令."""
        await self._protocol.send_test_command()

    # ── 遥控操作 ──────────────────────────────────────────────────

    def _sbo_required(self, ioa: int, kind: str) -> bool:
        """判断指定 IOA 的遥控/设点命令是否需要"选择-执行"(SBO) 两段式."""
        return self._protocol.sbo_required(ioa, kind)

    async def _wait_select_ack(self, ioa: int, timeout: float) -> bool:
        """等待指定 IOA 的选择阶段确认 (ACTCON)."""
        return await self._protocol.wait_select_ack(ioa, timeout)

    async def single_command(self, ioa: int, state: bool,
                              select: bool = False, qu: int = 0) -> None:
        """发送单命令 (选择/执行)."""
        await self._protocol.single_command(ioa, state, select=select, qu=qu)

    async def _send_single_command_raw(self, ioa: int, state: bool,
                                        select: bool, qu: int) -> None:
        """发送单命令单帧（不做 SBO 决策）."""
        await self._protocol.send_single_command_raw(ioa, state, select=select, qu=qu)

    async def double_command(self, ioa: int, state: int,
                              select: bool = False, qu: int = 0) -> None:
        """发送双命令 (选择/执行)."""
        await self._protocol.double_command(ioa, state, select=select, qu=qu)

    async def _send_double_command_raw(self, ioa: int, state: int,
                                        select: bool, qu: int) -> None:
        """发送双命令单帧（不做 SBO 决策）."""
        await self._protocol.send_double_command_raw(ioa, state, select=select, qu=qu)

    async def setpoint_normalized(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送归一化设点命令 (选择/执行)."""
        await self._protocol.setpoint_normalized(ioa, value, select=select)

    async def _send_setpoint_normalized_raw(self, ioa: int, value: float,
                                             select: bool) -> None:
        """发送归一化设点单帧（不做 SBO 决策）."""
        await self._protocol.send_setpoint_normalized_raw(ioa, value, select=select)

    async def setpoint_shortfloat(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送短浮点设点命令 (选择/执行)."""
        await self._protocol.setpoint_shortfloat(ioa, value, select=select)

    async def _send_setpoint_shortfloat_raw(self, ioa: int, value: float,
                                             select: bool) -> None:
        """发送短浮点设点单帧（不做 SBO 决策）."""
        await self._protocol.send_setpoint_shortfloat_raw(ioa, value, select=select)

    async def regulating_step_command(self, ioa: int, state: int,
                                       select: bool = False, qu: int = 0) -> None:
        """发送升降命令 (C_RC_NA_1)."""
        await self._protocol.regulating_step_command(ioa, state, select=select, qu=qu)

    async def _send_regulating_step_raw(self, ioa: int, state: int,
                                         select: bool, qu: int) -> None:
        """发送升降命令单帧（不做 SBO 决策）."""
        await self._protocol.send_regulating_step_raw(ioa, state, select=select, qu=qu)

    async def setpoint_scaled(self, ioa: int, value: int,
                               select: bool = False) -> None:
        """发送标度化设点命令 (C_SE_NB_1)."""
        await self._protocol.setpoint_scaled(ioa, value, select=select)

    async def _send_setpoint_scaled_raw(self, ioa: int, value: int,
                                         select: bool) -> None:
        """发送标度化设点单帧（不做 SBO 决策）."""
        await self._protocol.send_setpoint_scaled_raw(ioa, value, select=select)

    async def bitstring_command(self, ioa: int, value: int) -> None:
        """发送比特串命令 (C_BO_NA_1)."""
        await self._protocol.bitstring_command(ioa, value)

    # ── 带时标 CP56Time2a 的控制命令 (TypeID 58-64) ────────────────

    async def single_command_with_time(self, ioa: int, state: bool,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None) -> None:
        """发送带时标单命令 (C_SC_TA_1)."""
        await self._protocol.single_command_with_time(
            ioa, state, select=select, qu=qu, time_tag=time_tag
        )

    async def double_command_with_time(self, ioa: int, state: int,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None) -> None:
        """发送带时标双命令 (C_DC_TA_1)."""
        await self._protocol.double_command_with_time(
            ioa, state, select=select, qu=qu, time_tag=time_tag
        )

    async def regulating_step_command_with_time(self, ioa: int, state: int,
                                                 select: bool = False, qu: int = 0,
                                                 time_tag: CP56Time2a | None = None) -> None:
        """发送带时标升降命令 (C_RC_TA_1)."""
        await self._protocol.regulating_step_command_with_time(
            ioa, state, select=select, qu=qu, time_tag=time_tag
        )

    async def setpoint_normalized_with_time(self, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None) -> None:
        """发送带时标归一化设点命令 (C_SE_TA_1)."""
        await self._protocol.setpoint_normalized_with_time(
            ioa, value, select=select, time_tag=time_tag
        )

    async def setpoint_scaled_with_time(self, ioa: int, value: int,
                                         select: bool = False,
                                         time_tag: CP56Time2a | None = None) -> None:
        """发送带时标标度化设点命令 (C_SE_TB_1)."""
        await self._protocol.setpoint_scaled_with_time(
            ioa, value, select=select, time_tag=time_tag
        )

    async def setpoint_shortfloat_with_time(self, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None) -> None:
        """发送带时标短浮点设点命令 (C_SE_TC_1)."""
        await self._protocol.setpoint_shortfloat_with_time(
            ioa, value, select=select, time_tag=time_tag
        )

    async def bitstring_command_with_time(self, ioa: int, value: int,
                                           time_tag: CP56Time2a | None = None) -> None:
        """发送带时标比特串命令 (C_BO_TA_1)."""
        await self._protocol.bitstring_command_with_time(ioa, value, time_tag)

    async def read_command(self, ioa: int) -> None:
        """发送读命令 (C_RD_NA_1)."""
        await self._protocol.read_command(ioa)

    async def delay_command(self, delay_ms: int) -> None:
        """发送延时获得命令 (C_CD_NA_1)."""
        await self._protocol.delay_command(delay_ms)

    async def test_command_with_time(self, time_tag: CP56Time2a | None = None) -> None:
        """发送带时标测试命令 (C_TS_TA_1)."""
        await self._protocol.test_command_with_time(time_tag)

    # ── 参数命令 ──────────────────────────────────────────────────

    async def parameter_normalized(self, ioa: int, value: float,
                                    param_change: int = 0) -> None:
        """发送测量值参数-归一化 (P_ME_NA_1)."""
        await self._protocol.parameter_normalized(ioa, value, param_change)

    async def parameter_scaled(self, ioa: int, value: int,
                                param_change: int = 0) -> None:
        """发送测量值参数-标度化 (P_ME_NB_1)."""
        await self._protocol.parameter_scaled(ioa, value, param_change)

    async def parameter_float(self, ioa: int, value: float,
                               param_change: int = 0) -> None:
        """发送测量值参数-短浮点 (P_ME_NC_1)."""
        await self._protocol.parameter_float(ioa, value, param_change)

    async def parameter_activation(self, ioa: int, qualifier: int = 1) -> None:
        """发送参数激活 (P_AC_NA_1)."""
        await self._protocol.parameter_activation(ioa, qualifier)

    # ── 文件传输命令 ──────────────────────────────────────────────

    async def file_call_directory(self, ioa: int = 0) -> None:
        """发送召唤目录命令 (F_SC_NA_1)."""
        await self._protocol.file_call_directory(ioa)

    async def file_select(self, ioa: int, file_name: int) -> None:
        """发送文件选择命令 (F_SC_NB_1)."""
        await self._protocol.file_select(ioa, file_name)

    async def file_request(self, ioa: int, file_name: int) -> None:
        """发送文件请求命令 (F_SC_NB_1)."""
        await self._protocol.file_request(ioa, file_name)

    async def file_ack(self, ioa: int, file_name: int,
                        section_name: int = 0, qualifier: int = 1) -> None:
        """发送文件/节确认命令 (F_AF_NA_1)."""
        await self._protocol.file_ack(ioa, file_name, section_name, qualifier)

    async def request_file(self, ioa: int, file_name: int) -> None:
        """请求文件（使用文件传输管理器）."""
        await self._protocol.request_file(ioa, file_name)

    @property
    def file_transfer_state(self) -> FileTransferState:
        """获取文件传输状态."""
        return self._protocol.file_transfer_state

    # ── ASDU 处理（门面 → MasterProtocolHandler）──────────────────

    def _process_asdu(self, asdu: ASDU) -> None:
        """处理解析后的 ASDU."""
        self._protocol.process_asdu(asdu)

    def _resolve_pending_ack(self, ioa: int, pn: bool, cot: int) -> None:
        """唤醒正在等待指定 IOA 命令确认的协程.

        竞态防护: 只有 ACTCON（激活确认）才唤醒 SBO 选择等待。ACTTERM/DEACTCON
        等后续帧可能是上一条命令的滞后帧，若用来唤醒本次选择等待，会导致
        ``cot != ACTCON`` 被误判为"选择被拒"，从而偶发遥控失败。故此处直接忽略
        非 ACTCON 帧，等待者拿到的一定是 ACTCON 语义。
        """
        if cot != COT.ACTCON:
            return
        fut = self._pending_acks.get(ioa)
        if fut is not None and not fut.done():
            fut.set_result((pn, cot))

    # ── 帧接收处理 ────────────────────────────────────────────────

    def _on_frame_received(self, frame: bytes) -> None:
        """收到原始帧回调（从TCP层）."""
        if self._raw_frame_callback:
            try:
                self._raw_frame_callback(frame, "rx")
            except Exception:
                pass

        # 报文录制
        if self._recorder:
            self._recorder.record_frame(frame, direction="rx")

        self._rx_buffer.append((time.monotonic(), frame))

        # 记录到历史数据库
        if self._history_db:
            frame_type = APCICodec.frame_type_of(frame)
            self._history_db.record_frame("rx", frame, frame_type=frame_type)

        try:
            apci, _ = APCICodec.decode(frame)

            if apci.is_i_frame:
                self._handle_i_frame(apci, frame)
            elif apci.is_s_frame:
                self._handle_s_frame(apci)
            elif apci.is_u_frame:
                self._handle_u_frame(apci)

            self._state_machine.on_any_frame_received()

        except Exception as exc:
            logger.error(f"Frame decode error: {exc}")

    def _handle_i_frame(self, apci: APCI, frame: bytes) -> None:
        """处理 I 帧."""
        seq_ok = self._seq.process_rx_i_frame(apci.tx_seq)
        if not seq_ok:
            # 标准: 报文丢失/错序意味着 TCP 连接异常，应关闭连接并重建。
            # 主站与子站策略统一：均断开连接。使用 disconnect() 仅重建当前
            # 连接 —— 关闭底层连接后 _connect_loop 会触发 _on_tcp_disconnected
            # (状态机离开 Running + 触发 DISCONNECTED) 并按配置重连；
            # 若用 stop() 会取消重连循环并跳过 on_disconnected 回调。
            logger.error(
                f"Sequence mismatch: expected={self._seq.recv_seq}, "
                f"received={apci.tx_seq}, disconnecting"
            )
            self._spawn(self._client.disconnect())
            return
        # I帧的rx_seq是隐式确认，等效于S帧
        self._seq.process_rx_i_frame_ack(apci.rx_seq)
        # 隐式确认可能释放了发送窗口
        if self._seq.send_window_available:
            self._window_available.set()

        # 解析 ASDU
        asdu_data = frame[6:6 + apci.asdu_length]
        self._protocol.decode_and_dispatch(asdu_data)

        self._state_machine.on_i_frame_received()

    def _handle_s_frame(self, apci: APCI) -> None:
        """处理 S 帧."""
        self._seq.process_rx_s_frame(apci.rx_seq)
        # S帧确认释放了发送窗口
        if self._seq.send_window_available:
            self._window_available.set()
        self._state_machine.on_ack_received()
        logger.debug(f"S-Frame: rx_seq={apci.rx_seq}")

    def _handle_u_frame(self, apci: APCI) -> None:
        """处理 U 帧."""
        if apci.is_startdt_con:
            self._state_machine.on_startdt_con()
            self._seq.process_rx_u_frame_startdt_con()
            logger.info("STARTDT CON received")
            self._fire_event(MasterEvent.STARTED)

            # 自动总召唤
            if self._auto_gi:
                self._spawn(self._auto_general_interrogation())

            # 周期总召唤（对"只在总召时才回遥测"的装置是必要手段）
            if self._gi_interval > 0 and not self._periodic_gi_task:
                self._periodic_gi_task = self._spawn(self._periodic_gi_loop())

        elif apci.is_stopdt_con:
            self._state_machine.on_stopdt_con()
            logger.info("STOPDT CON received")

        elif apci.is_testfr_act:
            # 回复 TESTFR CON
            self._spawn(self._send_frame(APCICodec.testfr_con()))
            self._state_machine.on_testfr_act_received()
            logger.debug("TESTFR ACT received, CON sent")

        elif apci.is_testfr_con:
            self._state_machine.on_ack_received()
            logger.debug("TESTFR CON received")

    async def _auto_general_interrogation(self) -> None:
        """自动总召唤（连接建立后）."""
        await asyncio.sleep(0.5)  # 短暂延迟
        try:
            await self.general_interrogation()
        except Exception as exc:
            logger.error(f"Auto GI failed: {exc}")

    async def _send_frame(self, frame: bytes) -> None:
        """发送帧并记录."""
        await self._client.send(frame)

        if self._raw_frame_callback:
            try:
                self._raw_frame_callback(frame, "tx")
            except Exception:
                pass

        # 报文录制
        if self._recorder:
            self._recorder.record_frame(frame, direction="tx")

        self._tx_buffer.append((time.monotonic(), frame))
        self._state_machine.on_any_frame_sent()

        # 记录到历史数据库
        if self._history_db:
            frame_type = APCICodec.frame_type_of(frame)
            self._history_db.record_frame("tx", frame, frame_type=frame_type)

    def _send_s_frame(self, rx_seq: int) -> None:
        """S帧回调（从序列号管理器触发）."""
        frame = APCICodec.encode_s(rx_seq)
        self._spawn(self._send_frame(frame))
        self._state_machine.on_s_frame_sent()
        logger.debug(f"S-Frame sent: rx_seq={rx_seq}")

    # ── TCP 事件 ──────────────────────────────────────────────────

    def _on_tcp_connected(self) -> None:
        """TCP 连接建立."""
        self._state_machine.on_connected()
        self._fire_event(MasterEvent.CONNECTED)

        # 自动发送 STARTDT
        if self._auto_start:
            self._spawn(self._auto_startdt())

    def _on_tcp_disconnected(self) -> None:
        """TCP 连接断开."""
        self._state_machine.on_disconnected()
        self._fire_event(MasterEvent.DISCONNECTED)

    async def _auto_startdt(self) -> None:
        """自动发送 STARTDT."""
        await asyncio.sleep(0.2)
        try:
            await self.send_startdt()
        except Exception as exc:
            logger.error(f"Auto STARTDT failed: {exc}")

    async def _periodic_gi_loop(self) -> None:
        """周期总召唤循环（``gi_interval > 0`` 时启用）.

        部分真机**从不自发上送遥测**，只在收到总召唤时回数据（实测：静默
        70s 内零遥测帧）。这类装置只能靠周期总召刷新遥测值。
        仅在 Running 状态召唤；异常不影响连接。
        """
        try:
            while self._gi_interval > 0:
                await asyncio.sleep(self._gi_interval)
                if not self._state_machine.is_running:
                    continue
                try:
                    logger.info(f"Periodic GI (interval={self._gi_interval}s)")
                    await self.general_interrogation()
                except Exception as exc:
                    logger.warning(f"Periodic GI failed: {exc}")
        except asyncio.CancelledError:
            raise
        finally:
            self._periodic_gi_task = None

    async def _regi_after_init(self) -> None:
        """收到初始化结束(M_EI_NA_1, COT=4)后的自动重总召唤.

        装置重启后原实时数据可能已失效，标准要求主站重新召唤；
        延迟 2s 等待装置完成初始化收尾（部分真机对连接初期的 I 帧敏感），
        失败不影响连接（t1 超时会按标准断开并自动重连）。
        """
        await asyncio.sleep(2.0)
        try:
            if self._state_machine.is_running:
                logger.info("Auto re-GI after End of Initialization")
                await self.general_interrogation()
        except Exception as exc:
            logger.warning(f"Auto re-GI after init failed: {exc}")

    def _on_state_change(self, old_state: str, new_state: str) -> None:
        logger.info(f"State: {old_state} → {new_state}")

    def _on_timer_expired(self, timer_type: TimerType) -> None:
        logger.warning(f"Timer expired: {timer_type}")
        self._fire_event(MasterEvent.TIMER_EXPIRED, {"timer": timer_type})

        if timer_type == TimerType.T0:
            # 连接超时：仅重建当前连接，保留重连循环（stop() 会取消重连）
            self._spawn(self._client.disconnect())
        elif timer_type == TimerType.T1:
            # 发送超时 - 根据规范应断开连接。
            # 必须用 disconnect() 而非 stop()：stop() 会取消重连循环且跳过
            # on_disconnected 回调，导致 t1 超时后永久停在 Stopped（真机实测：
            # 对未知 IOA 的读命令，设备不回 ACK → t1 超时 → 再也不重连）。
            logger.error("T1 timeout: no confirmation received, disconnecting")
            self._spawn(self._client.disconnect())
        elif timer_type == TimerType.T2:
            # 无数据确认超时 — 发送S帧确认已收到的I帧
            rx_seq = self._seq.get_recv_seq()
            frame = APCICodec.encode_s(rx_seq)
            self._spawn(self._send_frame(frame))
            self._state_machine.on_s_frame_sent()
            logger.info(f"T2 expired: S-Frame sent (rx_seq={rx_seq})")
        elif timer_type == TimerType.T3:
            # 空闲超时，发送测试帧 — U 帧 ACT，发送后须在 t1 内收到 TESTFR CON
            self._spawn(self._send_frame(APCICodec.testfr_act()))
            self._state_machine.on_u_frame_act_sent()

    # ── 定时器循环 ─────────────────────────────────────────────────

    async def _timer_loop(self) -> None:
        """定时器检查循环."""
        while True:
            try:
                expired = self._state_machine.check_timers()
                if expired:
                    self._on_timer_expired(expired)
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Timer loop error: {exc}")

    # ── 事件分发 ──────────────────────────────────────────────────

    def _fire_event(self, event: MasterEvent, data: dict = None) -> None:
        if self._event_callback:
            try:
                self._event_callback(event, data or {})
            except Exception as exc:
                logger.error(f"Event callback error: {exc}")

    # ── 报文缓冲访问 ──────────────────────────────────────────────

    def get_rx_buffer(self, count: int = 100) -> list[tuple[float, bytes]]:
        return list(self._rx_buffer)[-count:]

    def get_tx_buffer(self, count: int = 100) -> list[tuple[float, bytes]]:
        return list(self._tx_buffer)[-count:]
