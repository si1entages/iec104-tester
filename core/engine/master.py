"""主站引擎 — IEC 60870-5-104 Master Station.

实现:
- 连接管理（STARTDT/STOPDT）
- 总召唤/组召唤
- 时钟同步
- 累计量召唤
- 遥控/遥调操作
- 周期轮询
- 报文解析与分发
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from enum import Enum
from typing import Any

from ..data.data_store import RealtimeDB
from ..data.history import HistoryDB
from ..data.point_table import PointTable
from ..protocol.apci import APCI, APCICodec
from ..protocol.asdu import ASDU, ASDUBuilder
from ..protocol.file_transfer import FileTransferMaster, FileTransferState
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..protocol.types import (
    COT,
    BitString32,
    CounterValue,
    CP56Time2a,
    DoublePoint,
    GroupSinglePointWithStatus,
    NormalizedValue,
    ProtectionEvent,
    QualityDescriptor,
    ScaledValue,
    ShortFloat,
    SinglePoint,
    StepPosition,
    TypeID,
)
from ..transport.connection import ConnectionStats, TCPClient
from .base import EngineBase
from .scheduler import TaskScheduler

logger = logging.getLogger("iec104.master")


class MasterEvent(Enum):
    """主站事件类型."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STARTED = "started"
    STOPPED = "stopped"
    GENERAL_INTERROGATION = "gi"
    CLOCK_SYNC = "clock_sync"
    COMMAND_SENT = "command_sent"
    DATA_RECEIVED = "data_received"
    TIMER_EXPIRED = "timer_expired"
    ERROR = "error"


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
        reconnect: bool = True,
        reconnect_interval: float = 5.0,
        history_db: HistoryDB | None = None,
        point_table: PointTable | None = None,
    ):
        super().__init__()
        self._host = host
        self._port = port
        self._common_addr = common_addr
        self._auto_start = auto_start
        self._auto_gi = auto_gi
        self._auto_gi_on_init_end = auto_gi_on_init_end

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

        # 命令确认（ACTCON）等待：IOA → Future，由 _process_command_ack 唤醒。
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
            on_send_asdu=lambda data: self._spawn(self._send_i_frame_with_data(data)),
            on_file_received=self._on_file_received,
            on_error=self._on_file_transfer_error,
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

    # ── 协议命令 ──────────────────────────────────────────────────

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
        """等待发送窗口可用（最多 t1）— 与子站行为对称.

        标准 (IEC 60870-5-104 Section 5.5): 发送方在有 k 个 I 帧未获确认时
        停止数据传送。本实现不立即失败，而是等待至多 t1；若仍无确认则认为
        TCP 连接异常，抛出 RuntimeError（与 SlaveEngine._send_i_frame 一致）。

        Raises:
            RuntimeError: 在 t1 内窗口未释放（迟迟收不到对端确认）。
        """
        if self._seq.send_window_available:
            return
        logger.debug("Send window full, waiting for acknowledgement...")
        self._window_available.clear()
        try:
            await asyncio.wait_for(self._window_available.wait(), timeout=self._t1)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Send window timeout: no acknowledgement within t1={self._t1}s"
            ) from None

    async def _send_command_asdu(self, asdu_data: bytes) -> None:
        """发送命令 ASDU — 公共封装：状态检查 + 序列号 + 编码 + 发送.

        所有命令方法（总召唤/遥控/遥调/参数等）共用此方法，
        消除重复的状态检查和帧编码样板代码。
        """
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")
        await self._await_send_window()
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)
        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)
        # 发送后若窗口已满，清除事件以等待对端确认
        if not self._seq.send_window_available:
            self._window_available.clear()

    async def general_interrogation(self, qoi: int = 20) -> None:
        """发送总召唤命令.

        Args:
            qoi: 召唤范围 — 20=站召唤；1-16=第1-16组召唤。
                 内部换算为标准限定词 QOI（组召唤 → 20+组号，即 21-36）。
        """
        if qoi == 20:
            std_qoi = 20
        elif 1 <= qoi <= 16:
            std_qoi = 20 + qoi
        else:
            raise ValueError(
                f"Invalid interrogation qualifier {qoi} (expected 1-16 or 20)"
            )

        asdu_data = ASDUBuilder.build_general_interrogation(
            self._common_addr, std_qoi
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"General Interrogation sent (group={qoi}, QOI={std_qoi})")
        self._fire_event(MasterEvent.GENERAL_INTERROGATION, {"qoi": qoi})

    async def counter_interrogation(self, qcc: int = 0) -> None:
        """发送累计量召唤命令."""
        asdu_data = ASDUBuilder.build_counter_interrogation(
            self._common_addr, qcc
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Counter Interrogation sent (QCC={qcc})")

    async def clock_sync(self, time_tag: CP56Time2a | None = None) -> None:
        """发送时钟同步命令."""
        asdu_data = ASDUBuilder.build_clock_sync(self._common_addr, time_tag)
        await self._send_command_asdu(asdu_data)

        # 记录发送时间用于校验
        self._last_clock_sync_sent_time = time.monotonic()

        logger.info("Clock Sync sent")
        self._fire_event(MasterEvent.CLOCK_SYNC)

    async def reset_process(self, qrp: int = 1) -> None:
        """发送复位进程命令."""
        asdu_data = ASDUBuilder.build_reset_process(self._common_addr, qrp)
        await self._send_command_asdu(asdu_data)
        logger.info(f"Reset Process sent (QRP={qrp})")

    async def send_test_command(self) -> None:
        """发送测试命令."""
        asdu_data = ASDUBuilder.build_test_command(self._common_addr)
        await self._send_command_asdu(asdu_data)
        logger.info("Test Command sent")

    # ── 遥控操作 ──────────────────────────────────────────────────

    def _sbo_required(self, ioa: int, kind: str) -> bool:
        """判断指定 IOA 的遥控/设点命令是否需要"选择-执行"(SBO) 两段式.

        语义与子站 ``SlaveEngine._command_requires_sbo`` 严格对称，保证主/子站
        两侧判定一致:

        - 若该 IOA 在 **YK 点表**中: 返回其 ``select_before_execute``
          （YAML ``sbo`` 字段）。这一判定对遥控与设点**一致** —— 因为 IEC 104
          中遥控/设点可共享同一 IOA 地址空间，子站对设点命令同样会先查 YK 表。
        - 若该 IOA 不在 YK 点表中: 设点 (yc) 返回 False（直发执行，向后兼容，
          与子站 ``is_setpoint=True`` 的回落一致）；遥控 (yk) 亦返回 False
          （主站侧未配置点表定义时不强制 SBO，避免影响既有调用方）。

        Args:
            ioa: 信息对象地址。
            kind: "yk"=遥控命令；"yc"=设点(遥调)命令。两者共用同一 YK 点表查询，
                仅当未命中 YK 点时行为一致（均 False）。
        Returns:
            仅当已注入点表且该 IOA 命中 YK 点表、``select_before_execute`` 为
            True 时返回 True。

        Note:
            **已知边界差异（有意保留，勿当缺陷"修复"）**：对点表中
            *不存在* 的 IOA 下发 **遥控** 命令时，本方法返回 False（主站直发
            执行），而子站 ``_command_requires_sbo(ioa, is_setpoint=False)``
            返回 True（要求 SBO），子站会回 ``ACTCON(PN=1)`` 拒绝。理由：

            1. 正常运维不会对未定义点下发遥控，该路径非实际使用场景；
            2. 子站保守拒绝是安全行为（未知点不动作）；
            3. 若把主站侧改为 True，会改变"未注入点表/点表无该点"时既有调用
               方的行为（如测试中 IOA=100/200），引入回归风险。

            该差异仅存在于"未命中 YK 点表 + 遥控"组合；"设点"组合两侧一致
            （均 False）。
        """
        if self._point_table is None:
            return False
        yk_point = self._point_table.get_yk(ioa)
        if yk_point is not None:
            return bool(yk_point.select_before_execute)
        # 未命中 YK 点表: 遥控与设点均不强制 SBO (设点回落同子站语义)
        return False

    async def _wait_select_ack(self, ioa: int, timeout: float) -> bool:
        """等待指定 IOA 的选择阶段确认 (ACTCON).

        由于 ``_resolve_pending_ack`` 仅在 ACTCON 时唤醒等待，本方法拿到的结果
        一定是 ACTCON 语义；此处再次校验 COT 以防未来实现变更。

        并发安全: 同一 IOA 上若已有未完成的等待，先取消旧的等待再登记本次，
        避免 ``_pending_acks`` 被静默覆盖导致旧等待悬挂；清理时只删除属于自己
        的 Future（``is fut`` 判定），不误删他人登记。

        Args:
            ioa: 信息对象地址
            timeout: 等待超时（秒）
        Returns:
            True=收到肯定确认 (PN=0)；False=收到否定确认或超时（调用方须中止执行）。
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        # 并发覆盖防护: 取消同一 IOA 上残留的旧等待
        old = self._pending_acks.get(ioa)
        if old is not None and not old.done():
            logger.warning(f"SBO: concurrent wait on IOA={ioa}, cancelling stale waiter")
            old.cancel()
        self._pending_acks[ioa] = fut
        try:
            pn, cot = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"SBO select timeout: IOA={ioa} no ACTCON within {timeout}s")
            return False
        except asyncio.CancelledError:
            # 同一 IOA 上被更新的等待取代（旧等待被 cancel），视为未确认
            logger.warning(f"SBO select superseded by newer wait: IOA={ioa}")
            return False
        finally:
            # 只删除自己登记的 Future，避免误删并发场景下他人替换后的登记
            if self._pending_acks.get(ioa) is fut:
                self._pending_acks.pop(ioa, None)
        if cot != COT.ACTCON or pn:
            logger.warning(f"SBO select rejected: IOA={ioa} pn={pn} cot={cot}")
            return False
        return True

    async def single_command(self, ioa: int, state: bool,
                              select: bool = False, qu: int = 0) -> None:
        """发送单命令 (选择/执行).

        当点表已设置且该 IOA 配置为 SBO (``select_before_execute=True``)、
        且调用方未显式要求 ``select=True`` 时，自动执行两段式：先发选择并等待
        肯定确认 (ACTCON, PN=0)，成功后再发执行；选择被拒或超时则中止，
        绝不继续发送执行帧。
        """
        if not select and self._sbo_required(ioa, "yk"):
            await self._send_single_command_raw(ioa, state, select=True, qu=qu)
            acked = await self._wait_select_ack(ioa, self._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for single command IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self._send_single_command_raw(ioa, state, select=select, qu=qu)

    async def _send_single_command_raw(self, ioa: int, state: bool,
                                        select: bool, qu: int) -> None:
        """发送单命令单帧（不做 SBO 决策）."""
        asdu_data = ASDUBuilder.build_single_command(
            self._common_addr, ioa, state, select, qu
        )
        await self._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        state_str = "ON" if state else "OFF"
        logger.info(f"Single Command: IOA={ioa} {action} {state_str}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "single_command", "ioa": ioa,
            "state": state, "select": select
        })

    async def double_command(self, ioa: int, state: int,
                              select: bool = False, qu: int = 0) -> None:
        """发送双命令 (选择/执行).

        对 SBO 点位自动两段式下发，语义同 ``single_command``。
        """
        if not select and self._sbo_required(ioa, "yk"):
            await self._send_double_command_raw(ioa, state, select=True, qu=qu)
            acked = await self._wait_select_ack(ioa, self._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for double command IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self._send_double_command_raw(ioa, state, select=select, qu=qu)

    async def _send_double_command_raw(self, ioa: int, state: int,
                                        select: bool, qu: int) -> None:
        """发送双命令单帧（不做 SBO 决策）."""
        asdu_data = ASDUBuilder.build_double_command(
            self._common_addr, ioa, state, select, qu
        )
        await self._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Double Command: IOA={ioa} {action} state={state}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "double_command", "ioa": ioa,
            "state": state, "select": select
        })

    async def setpoint_normalized(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送归一化设点命令 (选择/执行).

        当点表已设置且该 IOA 命中 YK 点表并配置为 SBO
        (``select_before_execute=True``) 时，自动执行两段式：先发选择并等待肯定
        确认 (ACTCON, PN=0)，成功后再发执行；选择被拒或超时则中止，绝不继续发送
        执行帧。与子站 ``_command_requires_sbo(is_setpoint=True)`` 语义对称。

        该 IOA 未在 YK 点表中时按直发执行处理（向后兼容），亦可通过 ``select``
        显式传参覆盖。
        """
        if not select and self._sbo_required(ioa, "yc"):
            await self._send_setpoint_normalized_raw(ioa, value, select=True)
            acked = await self._wait_select_ack(ioa, self._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for setpoint IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self._send_setpoint_normalized_raw(ioa, value, select=select)

    async def _send_setpoint_normalized_raw(self, ioa: int, value: float,
                                             select: bool) -> None:
        """发送归一化设点单帧（不做 SBO 决策）."""
        asdu_data = ASDUBuilder.build_setpoint_normalized(
            self._common_addr, ioa, value, select
        )
        await self._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint Normalized: IOA={ioa} {action} value={value}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "setpoint_normalized", "ioa": ioa,
            "value": value, "select": select
        })

    async def setpoint_shortfloat(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送短浮点设点命令 (选择/执行).

        与 ``setpoint_normalized`` 语义一致：命中 YK 点表且 SBO 配置为 True 时
        自动两段式下发；否则直发执行（向后兼容），可用 ``select`` 显式覆盖。
        """
        if not select and self._sbo_required(ioa, "yc"):
            await self._send_setpoint_shortfloat_raw(ioa, value, select=True)
            acked = await self._wait_select_ack(ioa, self._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for setpoint IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self._send_setpoint_shortfloat_raw(ioa, value, select=select)

    async def _send_setpoint_shortfloat_raw(self, ioa: int, value: float,
                                             select: bool) -> None:
        """发送短浮点设点单帧（不做 SBO 决策）."""
        asdu_data = ASDUBuilder.build_setpoint_shortfloat(
            self._common_addr, ioa, value, select
        )
        await self._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint ShortFloat: IOA={ioa} {action} value={value}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "setpoint_shortfloat", "ioa": ioa,
            "value": value, "select": select
        })

    async def regulating_step_command(self, ioa: int, state: int,
                                       select: bool = False, qu: int = 0) -> None:
        """发送升降命令 (C_RC_NA_1).

        Args:
            ioa: 信息对象地址
            state: 1=降一步, 2=升一步
            select: True=选择, False=执行
            qu: 限定词 (0-31)
        """
        if not select and self._sbo_required(ioa, "yk"):
            await self._send_regulating_step_raw(ioa, state, select=True, qu=qu)
            acked = await self._wait_select_ack(ioa, self._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for regulating step IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self._send_regulating_step_raw(ioa, state, select=select, qu=qu)

    async def _send_regulating_step_raw(self, ioa: int, state: int,
                                         select: bool, qu: int) -> None:
        """发送升降命令单帧（不做 SBO 决策）."""
        asdu_data = ASDUBuilder.build_regulating_step_command(
            self._common_addr, ioa, state, select, qu
        )
        await self._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        state_str = {1: "降一步", 2: "升一步"}.get(state, f"未知({state})")
        logger.info(f"Regulating Step Command: IOA={ioa} {action} {state_str}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "regulating_step", "ioa": ioa,
            "state": state, "select": select
        })

    async def setpoint_scaled(self, ioa: int, value: int,
                               select: bool = False) -> None:
        """发送标度化设点命令 (C_SE_NB_1).

        命中 YK 点表且 SBO 配置为 True 时自动两段式下发；否则直发执行，可用
        ``select`` 显式覆盖。

        Args:
            ioa: 信息对象地址
            value: 标度化值 (-32768..+32767)
            select: True=选择, False=执行
        """
        if not select and self._sbo_required(ioa, "yc"):
            await self._send_setpoint_scaled_raw(ioa, value, select=True)
            acked = await self._wait_select_ack(ioa, self._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for setpoint IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self._send_setpoint_scaled_raw(ioa, value, select=select)

    async def _send_setpoint_scaled_raw(self, ioa: int, value: int,
                                         select: bool) -> None:
        """发送标度化设点单帧（不做 SBO 决策）."""
        asdu_data = ASDUBuilder.build_setpoint_scaled(
            self._common_addr, ioa, value, select
        )
        await self._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint Scaled: IOA={ioa} {action} value={value}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "setpoint_scaled", "ioa": ioa,
            "value": value, "select": select
        })

    async def bitstring_command(self, ioa: int, value: int) -> None:
        """发送比特串命令 (C_BO_NA_1).

        Args:
            ioa: 信息对象地址
            value: 32位无符号整数
        """
        asdu_data = ASDUBuilder.build_bitstring_command(
            self._common_addr, ioa, value
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"Bitstring Command: IOA={ioa} value=0x{value:08X}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "bitstring", "ioa": ioa, "value": value
        })

    # ── 带时标 CP56Time2a 的控制命令 (TypeID 58-64) ────────────────

    async def single_command_with_time(self, ioa: int, state: bool,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None) -> None:
        """发送带时标单命令 (C_SC_TA_1)."""
        asdu_data = ASDUBuilder.build_single_command_with_time(
            self._common_addr, ioa, state, select, qu, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Single Command (with time): IOA={ioa} state={state}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "single_command_ta", "ioa": ioa, "state": state,
        })

    async def double_command_with_time(self, ioa: int, state: int,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None) -> None:
        """发送带时标双命令 (C_DC_TA_1)."""
        asdu_data = ASDUBuilder.build_double_command_with_time(
            self._common_addr, ioa, state, select, qu, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Double Command (with time): IOA={ioa} state={state}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "double_command_ta", "ioa": ioa, "state": state,
        })

    async def regulating_step_command_with_time(self, ioa: int, state: int,
                                                 select: bool = False, qu: int = 0,
                                                 time_tag: CP56Time2a | None = None) -> None:
        """发送带时标升降命令 (C_RC_TA_1)."""
        asdu_data = ASDUBuilder.build_regulating_step_command_with_time(
            self._common_addr, ioa, state, select, qu, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Regulating Step Command (with time): IOA={ioa} state={state}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "regulating_step_ta", "ioa": ioa, "state": state,
        })

    async def setpoint_normalized_with_time(self, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None) -> None:
        """发送带时标归一化设点命令 (C_SE_TA_1)."""
        asdu_data = ASDUBuilder.build_setpoint_normalized_with_time(
            self._common_addr, ioa, value, select, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Setpoint Normalized (with time): IOA={ioa} value={value}")

    async def setpoint_scaled_with_time(self, ioa: int, value: int,
                                         select: bool = False,
                                         time_tag: CP56Time2a | None = None) -> None:
        """发送带时标标度化设点命令 (C_SE_TB_1)."""
        asdu_data = ASDUBuilder.build_setpoint_scaled_with_time(
            self._common_addr, ioa, value, select, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Setpoint Scaled (with time): IOA={ioa} value={value}")

    async def setpoint_shortfloat_with_time(self, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None) -> None:
        """发送带时标短浮点设点命令 (C_SE_TC_1)."""
        asdu_data = ASDUBuilder.build_setpoint_shortfloat_with_time(
            self._common_addr, ioa, value, select, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Setpoint ShortFloat (with time): IOA={ioa} value={value}")

    async def bitstring_command_with_time(self, ioa: int, value: int,
                                           time_tag: CP56Time2a | None = None) -> None:
        """发送带时标比特串命令 (C_BO_TA_1)."""
        asdu_data = ASDUBuilder.build_bitstring_command_with_time(
            self._common_addr, ioa, value, time_tag
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"Bitstring Command (with time): IOA={ioa} value=0x{value:08X}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "bitstring_ta", "ioa": ioa, "value": value,
        })

    async def read_command(self, ioa: int) -> None:
        """发送读命令 (C_RD_NA_1).

        Args:
            ioa: 信息对象地址
        """
        asdu_data = ASDUBuilder.build_read_command(
            self._common_addr, ioa
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"Read Command: IOA={ioa}")

    async def delay_command(self, delay_ms: int) -> None:
        """发送延时获得命令 (C_CD_NA_1).

        Args:
            delay_ms: 延时值（毫秒）
        """
        asdu_data = ASDUBuilder.build_delay_command(
            self._common_addr, delay_ms
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"Delay Command: delay={delay_ms}ms")

    async def test_command_with_time(self, time_tag: CP56Time2a | None = None) -> None:
        """发送带时标测试命令 (C_TS_TA_1).

        Args:
            time_tag: 时标，默认使用当前时间
        """
        asdu_data = ASDUBuilder.build_test_command_with_time(
            self._common_addr, time_tag
        )
        await self._send_command_asdu(asdu_data)

        logger.info("Test Command with Time sent")

    # ── 参数命令 ──────────────────────────────────────────────────

    async def parameter_normalized(self, ioa: int, value: float,
                                    param_change: int = 0) -> None:
        """发送测量值参数-归一化 (P_ME_NA_1).

        Args:
            ioa: 信息对象地址
            value: 归一化值 (-1.0..+1.0)
            param_change: 参数变更标志 (0=未用, 1=运行中使用, 2=运行中不使用)
        """
        asdu_data = ASDUBuilder.build_parameter_normalized(
            self._common_addr, ioa, value, param_change
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"Parameter Normalized: IOA={ioa} value={value} change={param_change}")

    async def parameter_scaled(self, ioa: int, value: int,
                                param_change: int = 0) -> None:
        """发送测量值参数-标度化 (P_ME_NB_1).

        Args:
            ioa: 信息对象地址
            value: 标度化值 (-32768..+32767)
            param_change: 参数变更标志
        """
        asdu_data = ASDUBuilder.build_parameter_scaled(
            self._common_addr, ioa, value, param_change
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"Parameter Scaled: IOA={ioa} value={value} change={param_change}")

    async def parameter_float(self, ioa: int, value: float,
                               param_change: int = 0) -> None:
        """发送测量值参数-短浮点 (P_ME_NC_1).

        Args:
            ioa: 信息对象地址
            value: 短浮点值
            param_change: 参数变更标志
        """
        asdu_data = ASDUBuilder.build_parameter_float(
            self._common_addr, ioa, value, param_change
        )
        await self._send_command_asdu(asdu_data)

        logger.info(f"Parameter Float: IOA={ioa} value={value} change={param_change}")

    async def parameter_activation(self, ioa: int, qualifier: int = 1) -> None:
        """发送参数激活 (P_AC_NA_1).

        Args:
            ioa: 信息对象地址
            qualifier: 0=未用/取消, 1=激活/周期, 2=去激活
        """
        asdu_data = ASDUBuilder.build_parameter_activation(
            self._common_addr, ioa, qualifier
        )
        await self._send_command_asdu(asdu_data)

        action_str = {0: "未用", 1: "激活", 2: "去激活"}.get(qualifier, f"未知({qualifier})")
        logger.info(f"Parameter Activation: IOA={ioa} qualifier={action_str}")

    # ── 文件传输命令 ──────────────────────────────────────────────

    async def file_call_directory(self, ioa: int = 0) -> None:
        """发送召唤目录命令 (F_SC_NA_1).

        Args:
            ioa: 信息对象地址
        """
        asdu_data = ASDUBuilder.build_call_directory(
            self._common_addr, ioa, qualifier=5
        )
        # 与非文件传输命令一致：窗口满时等待至多 t1（文件传输会产生大量 I 帧，
        # 是最容易打满 k 窗口的场景）。
        await self._send_command_asdu(asdu_data)
        logger.info("File Call Directory sent")

    async def file_select(self, ioa: int, file_name: int) -> None:
        """发送文件选择命令 (F_SC_NB_1).

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
        """
        asdu_data = ASDUBuilder.build_file_select_call_get(
            self._common_addr, ioa, file_name, qualifier=4
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"File Select: file_name={file_name}")

    async def file_request(self, ioa: int, file_name: int) -> None:
        """发送文件请求命令 (F_SC_NB_1).

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
        """
        asdu_data = ASDUBuilder.build_file_select_call_get(
            self._common_addr, ioa, file_name, qualifier=1
        )
        await self._send_command_asdu(asdu_data)
        logger.info(f"File Request: file_name={file_name}")

    async def file_ack(self, ioa: int, file_name: int,
                        section_name: int = 0, qualifier: int = 1) -> None:
        """发送文件/节确认命令 (F_AF_NA_1).

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
            section_name: 节名 (8-bit)
            qualifier: 0=缺省, 1=肯定文件, 2=否定文件, 3=肯定节, 4=否定节
        """
        asdu_data = ASDUBuilder.build_ack_file_section(
            self._common_addr, ioa, file_name, section_name, qualifier
        )
        await self._send_command_asdu(asdu_data)
        qual_str = {0: "缺省", 1: "肯定文件", 2: "否定文件", 3: "肯定节", 4: "否定节"}.get(qualifier, f"未知({qualifier})")
        logger.info(f"File ACK: file_name={file_name} section={section_name} qualifier={qual_str}")

    async def request_file(self, ioa: int, file_name: int) -> None:
        """请求文件（使用文件传输管理器）.

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
        """
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")
        self._file_transfer.request_file(ioa, file_name)

    async def _send_i_frame_with_data(self, asdu_data: bytes) -> None:
        """发送I帧（内部方法）— 与命令发送共享 k 窗口等待语义."""
        await self._await_send_window()
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)
        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)
        if not self._seq.send_window_available:
            self._window_available.clear()

    def _on_file_received(self, file_name: int, data: bytes) -> None:
        """文件接收完成回调."""
        logger.info(f"File received: name={file_name} size={len(data)}")
        self._fire_event(MasterEvent.DATA_RECEIVED, {
            "type_id": "file",
            "file_name": file_name,
            "data": data,
        })

    def _on_file_transfer_error(self, error: str) -> None:
        """文件传输错误回调."""
        logger.error(f"File transfer error: {error}")
        self._fire_event(MasterEvent.ERROR, {"error": error})

    @property
    def file_transfer_state(self) -> FileTransferState:
        """获取文件传输状态."""
        return self._file_transfer.state

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

        except Exception as e:
            logger.error(f"Frame decode error: {e}")

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
        try:
            asdu = ASDU.decode(asdu_data)
            self._process_asdu(asdu)
        except Exception as e:
            # 解码失败可能因"未知类型标识"应答 — 仅解析头部以优雅处理
            try:
                header = ASDU.decode_header(asdu_data)
                if header.cot in (COT.UNKNOWN_TYPE, COT.UNKNOWN_COT, COT.UNKNOWN_CA):
                    self._handle_standard_error_reply(header)
                else:
                    logger.error(f"ASDU decode error: {e}")
            except Exception:
                logger.error(f"ASDU decode error: {e}")

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
        except Exception as e:
            logger.error(f"Auto GI failed: {e}")

    # ── ASDU 处理 ──────────────────────────────────────────────────

    def _process_asdu(self, asdu: ASDU) -> None:
        """处理解析后的 ASDU."""
        type_id = asdu.type_id
        cot = asdu.cot

        # ── 标准应答: 未知类型标识/未知传送原因/未知公共地址 (COT 42/43/44) ──
        # 子站无法识别来报时按标准回送 COT=42/43/44 并保持连接；主站优雅处理。
        # 注意: 需在公共地址校验之前处理 —— COT=44 应答会回显"错误的"公共地址，
        # 若先做地址校验会被误丢弃。
        if cot in (COT.UNKNOWN_TYPE, COT.UNKNOWN_COT, COT.UNKNOWN_CA):
            self._handle_standard_error_reply(asdu)
            return

        # 公共地址校验（广播地址255不检查）
        if asdu.common_addr != 255 and asdu.common_addr != self._common_addr:
            logger.warning(
                f"Common addr mismatch: expected={self._common_addr}, got={asdu.common_addr}"
            )
            return

        # ── 试验报文 (COT bit7: T=1) ──
        # 标准要求试验报文不得作为真实数据使用：监控方向（1-40/70/71）直接丢弃，
        # 不入实时库/历史库；命令与系统方向的应答仍继续处理（测试命令需回显 T 位）。
        if asdu.test and 1 <= int(type_id) <= 71:
            logger.info(
                f"Test message (T=1) skipped for data store: type={type_id}, cot={cot}"
            )
            return

        # 总召唤
        if type_id == TypeID.C_IC_NA_1:
            if cot == COT.ACTCON:
                logger.info("General Interrogation ACTCON received")
            elif cot == COT.ACTTERM:
                logger.info("General Interrogation ACTTERM received")
            elif cot == COT.INTROGEN or COT.is_group_response(cot):
                # 仅接受标准响应 COT: 20(站召唤) 或 21-36(第1-16组)
                self._process_interrogation_response(asdu)
            else:
                logger.debug(f"General Interrogation with unexpected COT={cot}")

        # 累计量召唤
        elif type_id == TypeID.C_CI_NA_1:
            if cot == COT.ACTCON:
                logger.info("Counter Interrogation ACTCON received")
            elif cot == COT.ACTTERM:
                logger.info("Counter Interrogation ACTTERM received")
            elif COT.is_counter_response(cot):
                # 仅接受标准响应 COT: 37(总请求) 或 38-41(第1-4组)
                self._process_counter(asdu)
            else:
                logger.debug(f"Counter Interrogation with unexpected COT={cot}")

        # 单点遥信
        elif type_id in (TypeID.M_SP_NA_1, TypeID.M_SP_TB_1):
            self._process_single_point(asdu)

        # 双点遥信
        elif type_id in (TypeID.M_DP_NA_1, TypeID.M_DP_TB_1):
            self._process_double_point(asdu)

        # 步位置信息
        elif type_id in (TypeID.M_ST_NA_1, TypeID.M_ST_TB_1):
            self._process_step_position(asdu)

        # 32比特串
        elif type_id in (TypeID.M_BO_NA_1, TypeID.M_BO_TB_1):
            self._process_bitstring32(asdu)

        # 归一化值
        elif type_id in (TypeID.M_ME_NA_1, TypeID.M_ME_TA_1, TypeID.M_ME_TD_1, TypeID.M_ME_ND_1):
            self._process_normalized(asdu)

        # 标度化值
        elif type_id in (TypeID.M_ME_NB_1, TypeID.M_ME_TB_1, TypeID.M_ME_TE_1):
            self._process_scaled(asdu)

        # 短浮点数
        elif type_id in (TypeID.M_ME_NC_1, TypeID.M_ME_TC_1, TypeID.M_ME_TF_1):
            self._process_short_float(asdu)

        # 累计量（含 CP24 短时标变体 M_IT_TA_1 —— 漏掉会把真机的 CP24 电度静默丢弃）
        elif type_id in (TypeID.M_IT_NA_1, TypeID.M_IT_TA_1, TypeID.M_IT_TB_1):
            self._process_counter(asdu)

        # 继电保护事件
        elif type_id in (TypeID.M_EP_TA_1, TypeID.M_EP_TB_1, TypeID.M_EP_TC_1,
                          TypeID.M_EP_TD_1, TypeID.M_EP_TE_1, TypeID.M_EP_TF_1):
            self._process_protection_event(asdu)

        # 成组单点状态检出
        elif type_id in (TypeID.M_PS_NA_1, TypeID.M_PS_TB_1):
            self._process_group_single_point(asdu)

        # 命令确认
        elif type_id in (TypeID.C_SC_NA_1, TypeID.C_DC_NA_1, TypeID.C_RC_NA_1,
                          TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1,
                          TypeID.C_BO_NA_1,
                          TypeID.C_SC_TA_1, TypeID.C_DC_TA_1, TypeID.C_RC_TA_1,
                          TypeID.C_SE_TA_1, TypeID.C_SE_TB_1, TypeID.C_SE_TC_1,
                          TypeID.C_BO_TA_1):
            self._process_command_ack(asdu)

        # 时钟同步确认
        elif type_id == TypeID.C_CS_NA_1:
            if self._last_clock_sync_sent_time:
                round_trip = time.monotonic() - self._last_clock_sync_sent_time
                logger.info(f"Clock Sync ACK received: round-trip={round_trip*1000:.1f}ms, COT={cot}")
                self._last_clock_sync_sent_time = None
            else:
                logger.info(f"Clock Sync ACK received, COT={cot}")

        # 读命令响应
        elif type_id == TypeID.C_RD_NA_1:
            self._process_read_response(asdu)

        # 测试命令确认
        elif type_id in (TypeID.C_TS_NA_1, TypeID.C_TS_TA_1, TypeID.C_TS_NB_1):
            logger.info(f"Test Command ACK received, COT={cot}")

        # 复位进程确认 (C_RP_NA_1)
        # 标准流程: ACT → ACTCON，不包含 ACTTERM；收到 ACTCON 即视为完成。
        elif type_id == TypeID.C_RP_NA_1:
            if cot == COT.ACTCON:
                logger.info("Reset Process ACTCON received (completed)")
            elif cot == COT.ACTTERM:
                logger.info("Reset Process ACTTERM received (non-standard)")
            else:
                logger.debug(f"Reset Process with unexpected COT={cot}")

        # 延时获得
        elif type_id == TypeID.C_CD_NA_1:
            logger.info(f"Delay Command received, COT={cot}")

        # 初始化结束
        elif type_id == TypeID.M_EI_NA_1:
            for obj in asdu.objects:
                if hasattr(obj.data, 'cause_str'):
                    logger.info(f"End of Initialization: {obj.data.cause_str}")
                else:
                    logger.info(f"End of Initialization received, COT={cot}")
            # 标准语义（真机为准）：子站初始化结束后其原实时数据可能已失效，
            # 主站应**重新总召唤**刷新全数据。但部分真机收到主站 I 帧后会直接
            # 断开/停摆（实测），故默认关闭、可经 auto_gi_on_init_end=True 开启。
            if cot == COT.INIT and self._auto_gi_on_init_end:
                self._spawn(self._regi_after_init())

        # 参数命令确认
        elif type_id in (TypeID.P_ME_NA_1, TypeID.P_ME_NB_1, TypeID.P_ME_NC_1,
                          TypeID.P_ME_ND_1, TypeID.P_AC_NA_1):
            logger.info(f"Parameter Command ACK: type={type_id}, COT={cot}")

        # 文件传输
        elif type_id in (TypeID.F_FR_NA_1, TypeID.F_SR_NA_1, TypeID.F_SC_NA_1,
                          TypeID.F_LS_NA_1, TypeID.F_AF_NA_1, TypeID.F_SG_NA_1,
                          TypeID.F_DR_TA_1, TypeID.F_SC_NB_1,
                          TypeID.F_FR_NB_1, TypeID.F_SR_NB_1):
            self._process_file_transfer(asdu)

        else:
            logger.debug(f"Unhandled ASDU: type={type_id}, cot={cot}")

        self._fire_event(MasterEvent.DATA_RECEIVED, {
            "type_id": type_id,
            "cot": cot,
            "common_addr": asdu.common_addr,
            "objects": asdu.objects,
        })

    def _process_single_point(self, asdu: ASDU) -> None:
        """处理单点遥信."""
        for obj in asdu.objects:
            sp: SinglePoint = obj.data
            self._data_store.update_yx(
                obj.ioa, sp.value, sp.quality
            )
            if self._history_db:
                self._history_db.record_data_change(
                    "yx", obj.ioa, sp.value,
                    quality=str(sp.quality),
                    source="spont" if asdu.cot == COT.SPONT else "gi",
                )

    def _process_double_point(self, asdu: ASDU) -> None:
        """处理双点遥信."""
        for obj in asdu.objects:
            dp: DoublePoint = obj.data
            self._data_store.update_yx(
                obj.ioa, dp.value == 2, dp.quality,
                double_state=dp.value
            )
            if self._history_db:
                self._history_db.record_data_change(
                    "yx", obj.ioa, dp.value,
                    quality=str(dp.quality),
                )

    def _process_short_float(self, asdu: ASDU) -> None:
        """处理短浮点遥测."""
        for obj in asdu.objects:
            sf: ShortFloat = obj.data
            self._data_store.update_yc(
                obj.ioa, sf.value, sf.quality
            )
            if self._history_db:
                self._history_db.record_data_change(
                    "yc", obj.ioa, sf.value,
                    quality=str(sf.quality),
                )

    def _process_normalized(self, asdu: ASDU) -> None:
        """处理归一化遥测."""
        for obj in asdu.objects:
            nv: NormalizedValue = obj.data
            self._data_store.update_yc(
                obj.ioa, nv.value, nv.quality
            )

    def _process_scaled(self, asdu: ASDU) -> None:
        """处理标度化遥测."""
        for obj in asdu.objects:
            sv: ScaledValue = obj.data
            self._data_store.update_yc(
                obj.ioa, float(sv.value), sv.quality
            )

    def _process_counter(self, asdu: ASDU) -> None:
        """处理累计量."""
        for obj in asdu.objects:
            cv: CounterValue = obj.data
            self._data_store.update_ym(
                obj.ioa, cv.value, cv.quality
            )

    def _process_file_transfer(self, asdu: ASDU) -> None:
        """处理文件传输."""
        type_id = asdu.type_id
        if not asdu.objects:
            return

        obj = asdu.objects[0]

        if type_id == TypeID.F_FR_NA_1:
            self._file_transfer.handle_file_ready(obj.data)
            # 主站收到"文件准备就绪"应立即回复 F_FR_NB_1 确认
            self._file_transfer.send_file_ready_ack(obj.ioa)
        elif type_id == TypeID.F_SR_NA_1:
            self._file_transfer.handle_section_ready(obj.data)
            # 主站收到"节准备就绪"应立即回复 F_SR_NB_1 确认
            self._file_transfer.send_section_ready_ack(obj.ioa)
        elif type_id == TypeID.F_SG_NA_1:
            self._file_transfer.handle_file_segment(obj.data)
        elif type_id == TypeID.F_LS_NA_1:
            self._file_transfer.handle_last_section(obj.data)
            # 收到"最后的节/段"后回复 F_AF_NA_1 (肯定节) 完成握手
            self._file_transfer.send_ack(obj.ioa, qualifier=3)
        elif type_id == TypeID.F_DR_TA_1:
            self._file_transfer.handle_directory_entry(obj.data)
        elif type_id == TypeID.F_FR_NB_1:
            logger.info(f"File Ready ACK: file_name={obj.data.file_name if hasattr(obj.data, 'file_name') else 'N/A'}")
        elif type_id == TypeID.F_SR_NB_1:
            logger.info(f"Section Ready ACK: file_name={obj.data.file_name if hasattr(obj.data, 'file_name') else 'N/A'}")

        logger.info(f"File Transfer: type={type_id}, state={self._file_transfer.state}")

    def _process_interrogation_response(self, asdu: ASDU) -> None:
        """处理总召唤响应."""
        for obj in asdu.objects:
            if isinstance(obj.data, SinglePoint):
                self._data_store.update_yx(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, DoublePoint):
                self._data_store.update_yx(
                    obj.ioa, obj.data.value == 2, obj.data.quality,
                    double_state=obj.data.value
                )
            elif isinstance(obj.data, NormalizedValue):
                self._data_store.update_yc(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, ScaledValue):
                self._data_store.update_yc(obj.ioa, float(obj.data.value), obj.data.quality)
            elif isinstance(obj.data, ShortFloat):
                self._data_store.update_yc(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, StepPosition):
                self._data_store.update_yc(obj.ioa, float(obj.data.value), obj.data.quality)
            elif isinstance(obj.data, BitString32):
                self._data_store.update_yc(obj.ioa, float(obj.data.value), QualityDescriptor())
            elif isinstance(obj.data, CounterValue):
                self._data_store.update_ym(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, GroupSinglePointWithStatus):
                for i, (state, _detected) in enumerate(obj.data.points):
                    self._data_store.update_yx(obj.ioa + i, state, QualityDescriptor())

    def _handle_standard_error_reply(self, asdu: ASDU) -> None:
        """优雅处理子站按标准回送的 COT 42/43/44 应答.

        - COT 42: 未知类型标识 (unknown type identification)
        - COT 43: 未知传送原因 (unknown cause of transmission)
        - COT 44: 未知公共地址 (unknown common address)

        主站记录告警并触发事件，但**不**断开连接（连接本身正常）。
        """
        cot = asdu.cot
        reason = {
            COT.UNKNOWN_TYPE: "未知类型标识 (COT=42)",
            COT.UNKNOWN_COT: "未知传送原因 (COT=43)",
            COT.UNKNOWN_CA: "未知公共地址 (COT=44)",
        }.get(cot, f"标准错误应答 (COT={cot})")
        logger.warning(
            f"Slave standard error reply: {reason}, type={asdu.type_id}, "
            f"ca={asdu.common_addr}"
        )
        self._fire_event(MasterEvent.DATA_RECEIVED, {
            "type_id": asdu.type_id,
            "cot": cot,
            "common_addr": asdu.common_addr,
            "error_reply": reason,
            "objects": asdu.objects,
        })

    def _process_command_ack(self, asdu: ASDU) -> None:
        """处理命令确认.

        否定确认 (P/N) 严格取自标准 COT bit6 (``asdu.pn``)。
        不再退回解析命令数据字节 bit7 —— 该字节是 S/E (选择/执行) 位，
        对 SBO 选择命令 S/E=1，会把"肯定选择确认"误判为 NACK
        (子站自 P0/#4 起已不再用数据字节伪造 P/N)。
        """
        cot = asdu.cot
        pn = asdu.pn
        for obj in asdu.objects:
            if cot == COT.ACTCON:
                if pn:
                    logger.warning(f"Command NACK (PN=1): type={asdu.type_id} IOA={obj.ioa}")
                    self._data_store.update_yk(obj.ioa, "nack")
                else:
                    logger.info(f"Command ACK: type={asdu.type_id} IOA={obj.ioa}")
                    self._data_store.update_yk(obj.ioa, "ack")
                # 唤醒等待该 IOA 命令确认的两段式下发逻辑
                self._resolve_pending_ack(obj.ioa, pn=pn, cot=cot)
            elif cot == COT.DEACTCON:
                logger.info(f"Command DEACTCON: type={asdu.type_id} IOA={obj.ioa}")
                self._resolve_pending_ack(obj.ioa, pn=pn, cot=cot)
            elif cot == COT.ACTTERM:
                logger.info(f"Command ACTTERM: type={asdu.type_id} IOA={obj.ioa}")
                self._resolve_pending_ack(obj.ioa, pn=pn, cot=cot)
            else:
                logger.warning(f"Command with COT={cot}")

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

    def _process_step_position(self, asdu: ASDU) -> None:
        """处理步位置信息."""
        for obj in asdu.objects:
            sp: StepPosition = obj.data
            self._data_store.update_yc(obj.ioa, float(sp.value), sp.quality)

    def _process_bitstring32(self, asdu: ASDU) -> None:
        """处理32比特串."""
        for obj in asdu.objects:
            bs: BitString32 = obj.data
            self._data_store.update_yc(obj.ioa, float(bs.value), QualityDescriptor())

    def _process_protection_event(self, asdu: ASDU) -> None:
        """处理继电保护事件."""
        for obj in asdu.objects:
            pe: ProtectionEvent = obj.data
            logger.info(f"Protection Event: IOA={obj.ioa} value={pe.event_value}")

    def _process_group_single_point(self, asdu: ASDU) -> None:
        """处理成组单点状态检出."""
        for obj in asdu.objects:
            gsp: GroupSinglePointWithStatus = obj.data
            for i, (state, _detected) in enumerate(gsp.points):
                self._data_store.update_yx(obj.ioa + i, state, QualityDescriptor())

    def _process_read_response(self, asdu: ASDU) -> None:
        """处理读命令响应."""
        for obj in asdu.objects:
            logger.info(f"Read Response: IOA={obj.ioa}")

    # ── 内部发送 ──────────────────────────────────────────────────

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
        except Exception as e:
            logger.error(f"Auto STARTDT failed: {e}")

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
        except Exception as e:
            logger.warning(f"Auto re-GI after init failed: {e}")

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
            except Exception as e:
                logger.error(f"Timer loop error: {e}")

    # ── 事件分发 ──────────────────────────────────────────────────

    def _fire_event(self, event: MasterEvent, data: dict = None) -> None:
        if self._event_callback:
            try:
                self._event_callback(event, data or {})
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    # ── 报文缓冲访问 ──────────────────────────────────────────────

    def get_rx_buffer(self, count: int = 100) -> list[tuple[float, bytes]]:
        return list(self._rx_buffer)[-count:]

    def get_tx_buffer(self, count: int = 100) -> list[tuple[float, bytes]]:
        return list(self._tx_buffer)[-count:]
