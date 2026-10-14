"""主站引擎 — IEC 60870-5-104 Master Station.

实现:
- 连接管理（STARTDT/STOPDT）
- 总召唤/组召唤
- 时钟同步
- 累计量召唤
- 遥控/遥调操作
- 周期轮询
- 报文解析与分发

本模块保留 ``MasterEngine`` 的编排与**公开 API**（薄门面）；连接/状态/重连/
帧接收/定时器逻辑见 ``master_session.MasterSession``，命令构建与 ASDU 解码
分发见 ``master_protocol.MasterProtocolHandler``。二者以组合方式持有，全部
共享状态仍由本类持有，公开方法签名与行为保持不变。
"""

from __future__ import annotations

import asyncio
import logging
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
from .master_session import MasterSession
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
        self._session = MasterSession(self)
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
        self._timer_task = self._spawn(self._session.timer_loop())

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
        await self._session.send_startdt()

    async def send_stopdt(self) -> None:
        """发送 STOPDT ACT."""
        await self._session.send_stopdt()

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

    # ── 帧接收处理（门面 → MasterSession）─────────────────────────

    def _on_frame_received(self, frame: bytes) -> None:
        """收到原始帧回调（从TCP层）."""
        self._session.on_frame_received(frame)

    def _handle_s_frame(self, apci: APCI) -> None:
        """处理 S 帧."""
        self._session.handle_s_frame(apci)

    async def _send_frame(self, frame: bytes) -> None:
        """发送帧并记录."""
        await self._session.send_frame(frame)

    def _send_s_frame(self, rx_seq: int) -> None:
        """S帧回调（从序列号管理器触发）."""
        frame = APCICodec.encode_s(rx_seq)
        self._spawn(self._send_frame(frame))
        self._state_machine.on_s_frame_sent()
        logger.debug(f"S-Frame sent: rx_seq={rx_seq}")

    # ── TCP 事件（门面 → MasterSession）───────────────────────────

    def _on_tcp_connected(self) -> None:
        """TCP 连接建立."""
        self._session.on_tcp_connected()

    def _on_tcp_disconnected(self) -> None:
        """TCP 连接断开."""
        self._session.on_tcp_disconnected()

    def _on_state_change(self, old_state: str, new_state: str) -> None:
        self._session.on_state_change(old_state, new_state)

    def _on_timer_expired(self, timer_type: TimerType) -> None:
        self._session.on_timer_expired(timer_type)

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
