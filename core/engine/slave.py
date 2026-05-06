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
    QualifierOfInterrogation,
)
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..transport.connection import TCPServer, TCPConnection
from ..data.data_store import RealtimeDB
from ..data.point_table import PointTable
from ..data.history import HistoryDB

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

        # 回调
        self._event_callback: Optional[EventCallback] = None
        self._raw_frame_callback: Optional[Callable[[bytes, str, str], None]] = None

        # 报文录制器
        self._recorder = None

        # 模拟任务
        self._simulation_task: Optional[asyncio.Task] = None
        self._simulation_running = False

        # 报文缓冲
        self._rx_buffer: list[tuple[float, bytes, str]] = []
        self._tx_buffer: list[tuple[float, bytes, str]] = []

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

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_event_callback(self, callback: EventCallback) -> None:
        self._event_callback = callback

    def set_raw_frame_callback(self, callback: Callable[[bytes, str, str], None]) -> None:
        """设置原始帧回调 (data, direction, client_id)."""
        self._raw_frame_callback = callback

    def set_packet_recorder(self, recorder) -> None:
        """设置报文录制器."""
        self._recorder = recorder

    # ── 生命周期 ──────────────────────────────────────────────────

    async def start(self) -> None:
        """启动子站引擎."""
        # 初始化实时数据库
        self._data_store.init_from_point_table(self._point_table)

        await self._server.start()
        logger.info(
            f"Slave engine started on {self._host}:{self._port} "
            f"(YX={self._point_table.yx_count}, YC={self._point_table.yc_count})"
        )

    async def stop(self) -> None:
        """停止子站引擎."""
        await self.stop_simulation()
        if self._history_db:
            self._history_db.flush()
        await self._server.stop()
        logger.info("Slave engine stopped")

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
        """收到帧."""
        conn_id = conn.name

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
        state.seq.process_rx_i_frame(apci.tx_seq)
        # I帧的rx_seq是隐式确认，等效于S帧
        old_unconfirmed = state.seq.unconfirmed_count
        state.seq.process_rx_i_frame_ack(apci.rx_seq)
        # 如果隐式确认释放了窗口空间，通知等待的协程
        if state.seq.unconfirmed_count < old_unconfirmed:
            state.window_available.set()

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
            # 回复 STARTDT CON
            asyncio.create_task(
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

        elif apci.is_stopdt_act:
            asyncio.create_task(
                self._send_to_client(state, APCICodec.stopdt_con())
            )
            state.state_machine.on_stopdt_con()
            state.data_transfer_enabled = False
            logger.info(f"STOPDT ACT from {state.conn.name}, CON sent")
            self._fire_event(SlaveEvent.STOPDT_RECEIVED, {
                "client_id": state.conn.name
            })

        elif apci.is_testfr_act:
            asyncio.create_task(
                self._send_to_client(state, APCICodec.testfr_con())
            )
            state.state_machine.on_testfr_act_received()

        elif apci.is_testfr_con:
            state.state_machine.on_ack_received()

    # ── ASDU 处理 ──────────────────────────────────────────────────

    def _process_asdu(self, state: _ClientState, asdu: ASDU) -> None:
        """处理收到的 ASDU."""
        type_id = asdu.type_id
        cot = asdu.cot

        # 总召唤
        if type_id == TypeID.C_IC_NA_1 and cot == COT.ACT:
            asyncio.create_task(self._handle_interrogation(state, asdu))

        # 累计量召唤
        elif type_id == TypeID.C_CI_NA_1 and cot == COT.ACT:
            asyncio.create_task(self._handle_counter_interrogation(state, asdu))

        # 时钟同步
        elif type_id == TypeID.C_CS_NA_1 and cot == COT.ACT:
            asyncio.create_task(self._handle_clock_sync(state, asdu))

        # 读命令
        elif type_id == TypeID.C_RD_NA_1 and cot == COT.REQ:
            asyncio.create_task(self._handle_read_command(state, asdu))

        # 复位进程
        elif type_id == TypeID.C_RP_NA_1 and cot == COT.ACT:
            asyncio.create_task(self._handle_reset_process(state, asdu))

        # 测试命令
        elif type_id == TypeID.C_TS_NA_1 and cot == COT.ACT:
            asyncio.create_task(self._handle_test_command(state, asdu))

        # 单命令
        elif type_id == TypeID.C_SC_NA_1:
            asyncio.create_task(self._handle_single_command(state, asdu))

        # 双命令
        elif type_id == TypeID.C_DC_NA_1:
            asyncio.create_task(self._handle_double_command(state, asdu))

        # 设点命令
        elif type_id in (TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1):
            asyncio.create_task(self._handle_setpoint_command(state, asdu))

        else:
            logger.warning(f"Unhandled ASDU: type={type_id}, cot={cot}")

    async def _handle_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理总召唤."""
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

        # ── 遥信打包发送 ──
        yx_points = self._point_table.get_all_yx()
        if qoi != 20:
            yx_points = self._point_table.get_yx_by_group(qoi)

        yx_batch = []
        for p in yx_points:
            if not p.enabled:
                continue
            yx_data = self._data_store.get_yx(p.ioa)
            if yx_data:
                yx_batch.append((p.ioa, yx_data.value, yx_data.quality.to_int()))

        for i in range(0, len(yx_batch), MAX_SP_PER_FRAME):
            chunk = yx_batch[i:i + MAX_SP_PER_FRAME]
            asdu_data = ASDUBuilder.build_single_point_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

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
                yc_batch.append((p.ioa, yc_data.value, yc_data.quality.to_int()))

        for i in range(0, len(yc_batch), MAX_MV_PER_FRAME):
            chunk = yc_batch[i:i + MAX_MV_PER_FRAME]
            asdu_data = ASDUBuilder.build_short_float_sequence(
                self._common_addr, chunk, cot=cot
            )
            await self._send_i_frame(state, asdu_data)

    async def _handle_counter_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理累计量召唤."""
        qcc = asdu.objects[0].data[0] if asdu.objects else 0
        logger.info(f"Counter Interrogation from {state.conn.name}: QCC={qcc}")

        # 确认
        ack = ASDUBuilder.build_counter_interrogation(self._common_addr, qcc)
        asdu_ack = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=COT.ACTCON, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

        # 发送电度数据
        for p in self._point_table.get_all_ym():
            if not p.enabled:
                continue
            ym_data = self._data_store.get_ym(p.ioa)
            if ym_data:
                self._send_i_frame(state, ASDUBuilder.build_short_float(
                    self._common_addr, p.ioa, float(ym_data.value),
                    ym_data.quality.to_int(), cot=COT.INTROGEN
                ))

        # 结束
        asdu_term = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=COT.ACTTERM, common_addr=self._common_addr,
        )
        asdu_term.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_term.encode())

    async def _handle_clock_sync(self, state: _ClientState, asdu: ASDU) -> None:
        """处理时钟同步."""
        logger.info(f"Clock Sync from {state.conn.name}")

        # 回复确认（使用收到的时间）
        ack = ASDUBuilder.build_clock_sync_ack(self._common_addr)
        await self._send_i_frame(state, ack)

        self._fire_event(SlaveEvent.CLOCK_SYNC_RECEIVED, {
            "client_id": state.conn.name
        })

    async def _handle_read_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理读命令."""
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
        # 原样回复
        asdu_ack = ASDU(
            type_id=TypeID.C_TS_NA_1, sq=False, num=1,
            cot=COT.ACTCON, common_addr=self._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await self._send_i_frame(state, asdu_ack.encode())

    async def _handle_single_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理单命令."""
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

        # 回复确认
        if asdu.cot == COT.ACT:
            ack_asdu = ASDU(
                type_id=TypeID.C_SC_NA_1, sq=False, num=1,
                cot=COT.ACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())

            # 更新数据
            self._data_store.update_yk(obj.ioa, "execute" if not cmd.select else "select", cmd.state)

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
            ack_asdu = ASDU(
                type_id=TypeID.C_DC_NA_1, sq=False, num=1,
                cot=COT.ACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())

    async def _handle_setpoint_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理设点命令."""
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        logger.info(f"Setpoint Command from {state.conn.name}: IOA={obj.ioa}")

        if asdu.cot == COT.ACT:
            ack_asdu = ASDU(
                type_id=asdu.type_id, sq=False, num=1,
                cot=COT.ACTCON, common_addr=self._common_addr,
            )
            ack_asdu.objects.append(obj)
            await self._send_i_frame(state, ack_asdu.encode())

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

    # ── 数据模拟 ──────────────────────────────────────────────────

    def simulate_yx_change(self, ioa: int, value: bool) -> None:
        """模拟遥信变化."""
        self._data_store.update_yx(ioa, value)
        asyncio.create_task(self.send_spontaneous_yx(ioa, value))

    def simulate_yc_change(self, ioa: int, value: float) -> None:
        """模拟遥测变化."""
        self._data_store.update_yc(ioa, value)
        asyncio.create_task(self.send_spontaneous_yc(ioa, value))

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
        self._simulation_task = asyncio.create_task(
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
        """模拟数据变化循环."""
        yx_tick = 0.0
        yc_tick = 0.0

        while self._simulation_running:
            await asyncio.sleep(0.5)
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

    # ── S帧回调 ───────────────────────────────────────────────────

    def _on_s_frame_needed(self, state: _ClientState, rx_seq: int) -> None:
        """当收到w个未确认的I帧时，由SequenceManager回调发送S帧."""
        frame = APCICodec.encode_s(rx_seq)
        asyncio.create_task(self._send_to_client(state, frame))
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
        """发送帧到指定客户端."""
        try:
            await state.conn.send_frame(frame)

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
