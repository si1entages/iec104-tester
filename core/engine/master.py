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
from typing import Optional, Callable, Any
from enum import Enum

from ..protocol.apci import APCICodec, APCI
from ..protocol.asdu import ASDU, ASDUBuilder, InformationObject
from ..protocol.types import (
    TypeID, COT, ConnState,
    SinglePoint, DoublePoint, NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, QualityDescriptor, CP56Time2a,
    SingleCommand, DoubleCommand,
    SetpointCommandN, SetpointCommandS,
)
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..transport.connection import TCPClient, ConnectionStats
from ..data.data_store import RealtimeDB
from ..data.history import HistoryDB
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


class MasterEngine:
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
        reconnect: bool = True,
        reconnect_interval: float = 5.0,
        history_db: Optional[HistoryDB] = None,
    ):
        self._host = host
        self._port = port
        self._common_addr = common_addr
        self._auto_start = auto_start
        self._auto_gi = auto_gi

        # 协议组件
        self._seq = SequenceManager(k=k, w=w)
        self._state_machine = ConnectionStateMachine(
            t0=t0, t1=t1, t2=t2, t3=t3,
            on_state_change=self._on_state_change,
            on_timer_expired=self._on_timer_expired,
        )

        # 数据存储
        self._data_store = RealtimeDB()

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
        self._event_callback: Optional[EventCallback] = None
        self._raw_frame_callback: Optional[Callable[[bytes, str], None]] = None

        # 定时器检查任务
        self._timer_task: Optional[asyncio.Task] = None

        # 报文缓冲
        self._rx_buffer: list[tuple[float, bytes]] = []
        self._tx_buffer: list[tuple[float, bytes]] = []

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state_machine.state

    @property
    def is_running(self) -> bool:
        return self._state_machine.is_running

    @property
    def data_store(self) -> RealtimeDB:
        return self._data_store

    @property
    def sequence_manager(self) -> SequenceManager:
        return self._seq

    @property
    def connection_stats(self) -> Optional[ConnectionStats]:
        return self._client.stats

    @property
    def scheduler(self) -> TaskScheduler:
        return self._scheduler

    @property
    def history_db(self) -> Optional[HistoryDB]:
        return self._history_db

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_event_callback(self, callback: EventCallback) -> None:
        self._event_callback = callback

    def set_raw_frame_callback(self, callback: Callable[[bytes, str], None]) -> None:
        """设置原始帧回调 (data, direction: 'rx'/'tx')."""
        self._raw_frame_callback = callback

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
        self._timer_task = asyncio.create_task(self._timer_loop())

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
                await self._timer_task
            except (asyncio.CancelledError, Exception):
                pass

        # 刷新历史数据库
        if self._history_db:
            self._history_db.flush()

        await self._client.stop()
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
        logger.info("STOPDT ACT sent")

    async def general_interrogation(self, qoi: int = 20) -> None:
        """发送总召唤命令.

        Args:
            qoi: 20=站召唤, 1-16=组召唤
        """
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_general_interrogation(
            self._common_addr, qoi
        )
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)

        logger.info(f"General Interrogation sent (QOI={qoi})")
        self._fire_event(MasterEvent.GENERAL_INTERROGATION, {"qoi": qoi})

    async def counter_interrogation(self, qcc: int = 0) -> None:
        """发送累计量召唤命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_counter_interrogation(
            self._common_addr, qcc
        )
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)
        logger.info(f"Counter Interrogation sent (QCC={qcc})")

    async def clock_sync(self, time_tag: Optional[CP56Time2a] = None) -> None:
        """发送时钟同步命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_clock_sync(self._common_addr, time_tag)
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)

        logger.info("Clock Sync sent")
        self._fire_event(MasterEvent.CLOCK_SYNC)

    async def reset_process(self, qrp: int = 1) -> None:
        """发送复位进程命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_reset_process(self._common_addr, qrp)
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)
        logger.info(f"Reset Process sent (QRP={qrp})")

    async def send_test_command(self) -> None:
        """发送测试命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_test_command(self._common_addr)
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)
        logger.info("Test Command sent")

    # ── 遥控操作 ──────────────────────────────────────────────────

    async def single_command(self, ioa: int, state: bool,
                              select: bool = False, qu: int = 0) -> None:
        """发送单命令 (选择/执行)."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_single_command(
            self._common_addr, ioa, state, select, qu
        )
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)

        action = "SELECT" if select else "EXECUTE"
        state_str = "ON" if state else "OFF"
        logger.info(f"Single Command: IOA={ioa} {action} {state_str}")
        self._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "single_command", "ioa": ioa,
            "state": state, "select": select
        })

    async def double_command(self, ioa: int, state: int,
                              select: bool = False, qu: int = 0) -> None:
        """发送双命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_double_command(
            self._common_addr, ioa, state, select, qu
        )
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Double Command: IOA={ioa} {action} state={state}")

    async def setpoint_normalized(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送归一化设点命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_setpoint_normalized(
            self._common_addr, ioa, value, select
        )
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint Normalized: IOA={ioa} {action} value={value}")

    async def setpoint_shortfloat(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送短浮点设点命令."""
        if not self._state_machine.is_running:
            raise RuntimeError("Not in running state")

        asdu_data = ASDUBuilder.build_setpoint_shortfloat(
            self._common_addr, ioa, value, select
        )
        tx_seq = self._seq.get_send_seq()
        rx_seq = self._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        self._state_machine.on_i_frame_sent()
        await self._send_frame(frame)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint ShortFloat: IOA={ioa} {action} value={value}")

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
            frame_type = "I" if len(frame) >= 6 and (frame[2] & 0x01) == 0 else (
                "S" if len(frame) >= 6 and (frame[2] & 0x03) == 0x01 else "U"
            )
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
        self._seq.process_rx_i_frame(apci.tx_seq)
        # I帧的rx_seq是隐式确认，等效于S帧
        self._seq.process_rx_i_frame_ack(apci.rx_seq)

        # 解析 ASDU
        asdu_data = frame[6:6 + apci.asdu_length]
        try:
            asdu = ASDU.decode(asdu_data)
            self._process_asdu(asdu)
        except Exception as e:
            logger.error(f"ASDU decode error: {e}")

        self._state_machine.on_i_frame_received()

    def _handle_s_frame(self, apci: APCI) -> None:
        """处理 S 帧."""
        self._seq.process_rx_s_frame(apci.rx_seq)
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
                asyncio.create_task(self._auto_general_interrogation())

        elif apci.is_stopdt_con:
            self._state_machine.on_stopdt_con()
            logger.info("STOPDT CON received")

        elif apci.is_testfr_act:
            # 回复 TESTFR CON
            asyncio.create_task(self._send_frame(APCICodec.testfr_con()))
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

        # 总召唤响应
        if type_id == TypeID.M_SP_NA_1 and cot >= COT.INTROGEN:
            self._process_interrogation_response(asdu)

        # 遥测数据
        elif type_id in (TypeID.M_ME_NC_1, TypeID.M_ME_TF_1):
            self._process_short_float(asdu)

        # 归一化值
        elif type_id in (TypeID.M_ME_NA_1, TypeID.M_ME_TD_1, TypeID.M_ME_ND_1):
            self._process_normalized(asdu)

        # 标度化值
        elif type_id in (TypeID.M_ME_NB_1, TypeID.M_ME_TB_1, TypeID.M_ME_TE_1):
            self._process_scaled(asdu)

        # 遥信
        elif type_id in (TypeID.M_SP_NA_1, TypeID.M_SP_TB_1):
            self._process_single_point(asdu)

        # 双点遥信
        elif type_id in (TypeID.M_DP_NA_1, TypeID.M_DP_TB_1):
            self._process_double_point(asdu)

        # 累计量
        elif type_id in (TypeID.M_IT_NA_1, TypeID.M_IT_TB_1):
            self._process_counter(asdu)

        # 命令确认
        elif type_id in (TypeID.C_SC_NA_1, TypeID.C_DC_NA_1,
                          TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1):
            self._process_command_ack(asdu)

        # 时钟同步确认
        elif type_id == TypeID.C_CS_NA_1:
            logger.info(f"Clock Sync ACK received, COT={cot}")

        # 总召唤确认/结束
        elif type_id == TypeID.C_IC_NA_1:
            if cot == COT.ACTCON:
                logger.info("General Interrogation ACTCON received")
            elif cot == COT.ACTTERM:
                logger.info("General Interrogation ACTTERM received")

        # 初始化结束
        elif type_id == TypeID.M_EI_NA_1:
            logger.info(f"End of Initialization received, COT={cot}")


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

    def _process_command_ack(self, asdu: ASDU) -> None:
        """处理命令确认."""
        cot = asdu.cot
        if cot == COT.ACTCON:
            logger.info("Command ACTCON received")
        elif cot == COT.DEACTCON:
            logger.info("Command DEACTCON received")
        elif cot == COT.ACTTERM:
            logger.info("Command ACTTERM received")
        else:
            logger.warning(f"Command with COT={cot}")

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
            frame_type = "I" if len(frame) >= 6 and (frame[2] & 0x01) == 0 else (
                "S" if len(frame) >= 6 and (frame[2] & 0x03) == 0x01 else "U"
            )
            self._history_db.record_frame("tx", frame, frame_type=frame_type)

    def _send_s_frame(self, rx_seq: int) -> None:
        """S帧回调（从序列号管理器触发）."""
        frame = APCICodec.encode_s(rx_seq)
        asyncio.create_task(self._send_frame(frame))
        self._state_machine.on_s_frame_sent()
        logger.debug(f"S-Frame sent: rx_seq={rx_seq}")

    # ── TCP 事件 ──────────────────────────────────────────────────

    def _on_tcp_connected(self) -> None:
        """TCP 连接建立."""
        self._state_machine.on_connected()
        self._fire_event(MasterEvent.CONNECTED)

        # 自动发送 STARTDT
        if self._auto_start:
            asyncio.create_task(self._auto_startdt())

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

    def _on_state_change(self, old_state: str, new_state: str) -> None:
        logger.info(f"State: {old_state} → {new_state}")

    def _on_timer_expired(self, timer_type: TimerType) -> None:
        logger.warning(f"Timer expired: {timer_type}")
        self._fire_event(MasterEvent.TIMER_EXPIRED, {"timer": timer_type})

        if timer_type == TimerType.T0:
            # 连接超时
            asyncio.create_task(self._client.stop())
        elif timer_type == TimerType.T1:
            # 发送超时
            logger.error("T1 timeout: no confirmation received")
        elif timer_type == TimerType.T2:
            # 无数据确认超时 — 发送S帧确认已收到的I帧
            rx_seq = self._seq.get_recv_seq()
            frame = APCICodec.encode_s(rx_seq)
            asyncio.create_task(self._send_frame(frame))
            self._state_machine.on_s_frame_sent()
            logger.info(f"T2 expired: S-Frame sent (rx_seq={rx_seq})")
        elif timer_type == TimerType.T3:
            # 空闲超时，发送测试帧
            asyncio.create_task(self._send_frame(APCICodec.testfr_act()))

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
        return self._rx_buffer[-count:]

    def get_tx_buffer(self, count: int = 100) -> list[tuple[float, bytes]]:
        return self._tx_buffer[-count:]
