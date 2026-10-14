"""子站会话层 — 每客户端连接 / 帧处理 / SBO 命令会话 / 定时器 / 发送.

从 ``core/engine/slave.py`` 抽出的"每客户端会话"职责：

- ``_ClientState``：单个客户端的序列号管理器、状态机、窗口事件、
  命令选择态（SBO）与已装载参数集合
- 客户端连接 / 断开回调，以及原始帧接收与 I/S/U 帧的序列号 / 窗口 / 状态机处理
- 遥控 / 遥调 **SBO（选择-执行）命令会话**（单命令 / 双命令 / 设点 / 升降）
- 协议定时器检查循环（t1/t2/t3）与主动 TESTFR
- 按会话发送（I 帧、丢帧/损坏注入、广播、S 帧回调）

设计：**组合 + 构造期注入**。引擎全部共享状态（``_client_states`` /
``_k``/``_w``/``_t0``…``_t3`` / 收发缓冲 / 回调 / 历史库 …）仍由 ``SlaveEngine``
持有，本类只持有引擎引用并按需读写；类型仅经 ``TYPE_CHECKING`` 前置引用，
避免反向 import 造成循环依赖。这样测试对引擎实例属性的替换（如
``engine._rx_buffer``）依旧生效，行为零变化。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from ..protocol.apci import APCI, APCICodec
from ..protocol.asdu import ASDU, ASDUBuilder
from ..protocol.sequence import SequenceManager
from ..protocol.state_machine import ConnectionStateMachine, TimerType
from ..protocol.types import (
    COT,
    DoubleCommand,
    RegulatingStepCommand,
    SingleCommand,
)
from ..transport.connection import TCPConnection
from .slave_response import SlaveEvent

if TYPE_CHECKING:
    from .slave import SlaveEngine

logger = logging.getLogger("iec104.slave")


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


class SlaveSession:
    """子站每客户端连接 / 帧接收 / SBO 命令会话中枢（由 ``SlaveEngine`` 组合持有）."""

    def __init__(self, engine: SlaveEngine) -> None:
        self._engine = engine

    # ── 客户端连接管理 ────────────────────────────────────────────

    def on_client_connected(self, conn: TCPConnection) -> None:
        """新客户端连接."""
        e = self._engine
        conn_id = conn.name
        seq = SequenceManager(k=e._k, w=e._w)
        state = _ClientState(
            conn=conn,
            seq=seq,
            state_machine=ConnectionStateMachine(
                t0=e._t0, t1=e._t1, t2=e._t2, t3=e._t3,
                # t0 是"连接建立超时"，仅适用于发起连接的控制站（主站）。
                # 子站为被控站，被动接受连接，不使用 t0（标准 IEC 60870-5-104）。
                use_t0=False,
            ),
        )
        seq.set_s_frame_callback(lambda rx_seq: self.on_s_frame_needed(state, rx_seq))
        e._client_states[conn_id] = state
        state.state_machine.on_connected()
        logger.info(f"Client connected: {conn_id}")
        e._fire_event(SlaveEvent.CLIENT_CONNECTED, {"client_id": conn_id})

    def on_client_disconnected(self, conn: TCPConnection) -> None:
        """客户端断开."""
        e = self._engine
        conn_id = conn.name
        if conn_id in e._client_states:
            del e._client_states[conn_id]
        logger.info(f"Client disconnected: {conn_id}")
        e._fire_event(SlaveEvent.CLIENT_DISCONNECTED, {"client_id": conn_id})

    # ── 帧接收 ────────────────────────────────────────────────────

    def on_frame_received(self, conn: TCPConnection, frame: bytes) -> None:
        """收到帧。"""
        e = self._engine
        conn_id = conn.name

        # 更新统计
        e._frames_received += 1
        e._bytes_received += len(frame)

        if e._raw_frame_callback:
            try:
                e._raw_frame_callback(frame, "rx", conn_id)
            except Exception:
                pass

        # 报文录制
        if e._recorder:
            e._recorder.record_frame(frame, direction="rx", metadata={"client_id": conn_id})

        e._rx_buffer.append((time.monotonic(), frame, conn_id))

        # 记录到历史数据库
        if e._history_db:
            frame_type = APCICodec.frame_type_of(frame)
            e._history_db.record_frame("rx", frame, frame_type=frame_type, client_id=conn_id)

        state = e._client_states.get(conn_id)
        if not state:
            return

        try:
            apci, _ = APCICodec.decode(frame)

            if apci.is_i_frame:
                self.handle_i_frame(state, apci, frame)
            elif apci.is_s_frame:
                self.handle_s_frame(state, apci)
            elif apci.is_u_frame:
                self.handle_u_frame(state, apci)

            state.state_machine.on_any_frame_received()

        except Exception as exc:
            logger.error(f"Frame decode error from {conn_id}: {exc}")

    def handle_i_frame(self, state: _ClientState, apci: APCI, frame: bytes) -> None:
        """处理 I 帧."""
        e = self._engine
        # 无论STOPDT还是RUNNING状态，都处理序列号
        seq_ok = state.seq.process_rx_i_frame(apci.tx_seq)
        if not seq_ok:
            logger.error(f"Sequence mismatch from {state.conn.name}, disconnecting")
            e._spawn(state.conn.stop())
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
            e._process_asdu(state, asdu)
        except Exception as exc:
            # 解码失败（多为未知类型标识）→ 解析头部后按标准回送 COT=42
            logger.error(f"ASDU decode error: {exc}")
            e._spawn(e._response._send_unknown_type_response(state, asdu_data))

        state.state_machine.on_i_frame_received()

    def handle_s_frame(self, state: _ClientState, apci: APCI) -> None:
        """处理 S 帧."""
        state.seq.process_rx_s_frame(apci.rx_seq)
        state.state_machine.on_ack_received()
        # 通知等待窗口空间的协程
        state.window_available.set()

    def handle_u_frame(self, state: _ClientState, apci: APCI) -> None:
        """处理 U 帧."""
        e = self._engine
        if apci.is_startdt_act:
            if e._response_behavior.reject_startdt:
                logger.warning(
                    f"STARTDT ACT rejected by response config from {state.conn.name}"
                )
                e._fire_event(SlaveEvent.ERROR, {
                    "client_id": state.conn.name,
                    "error": "startdt_rejected",
                })
                return

            # 回复 STARTDT CON
            e._spawn(
                self.send_to_client(state, APCICodec.startdt_con())
            )
            state.state_machine.on_startdt_con()
            state.seq.process_rx_u_frame_startdt_con()
            state.data_transfer_enabled = True
            state.window_available.set()  # 序列号重置，窗口可用
            logger.info(f"STARTDT ACT from {state.conn.name}, CON sent")
            e._fire_event(SlaveEvent.STARTDT_RECEIVED, {
                "client_id": state.conn.name
            })

            # 发送初始化结束报文 M_EI_NA_1
            e._spawn(self.send_initialization_end(state))

            # 可选：自动 STOPDT
            if e._response_behavior.auto_stopdt:
                e._spawn(self.auto_stopdt_after_start(state))

        elif apci.is_stopdt_act:
            e._spawn(
                self.send_to_client(state, APCICodec.stopdt_con())
            )
            state.state_machine.on_stopdt_con()
            state.data_transfer_enabled = False
            logger.info(f"STOPDT ACT from {state.conn.name}, CON sent")
            e._fire_event(SlaveEvent.STOPDT_RECEIVED, {
                "client_id": state.conn.name
            })

        elif apci.is_testfr_act:
            e._spawn(
                self.send_to_client(state, APCICodec.testfr_con())
            )
            state.state_machine.on_testfr_act_received()

        elif apci.is_testfr_con:
            state.state_machine.on_ack_received()

    async def send_initialization_end(self, state: _ClientState) -> None:
        """发送初始化结束报文 (M_EI_NA_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_initialization_end(
            e._common_addr, cot=COT.INIT, cause=2,   # cause=2: 远方复位
        )
        await self.send_i_frame(state, asdu_data)
        logger.info(f"Initialization End sent to {state.conn.name}")

    async def auto_stopdt_after_start(self, state: _ClientState) -> None:
        """STARTDT 后按配置自动发送 STOPDT."""
        e = self._engine
        await asyncio.sleep(0.2)
        try:
            await self.send_to_client(state, APCICodec.stopdt_act())
            state.state_machine.on_stopdt_con()
            state.data_transfer_enabled = False
            logger.info(f"Auto STOPDT sent to {state.conn.name}")
            e._fire_event(SlaveEvent.STOPDT_RECEIVED, {
                "client_id": state.conn.name
            })
        except Exception as exc:
            logger.error(f"Auto STOPDT failed: {exc}")

    # ── SBO 命令会话（选择-执行）──────────────────────────────────

    def command_requires_sbo(self, ioa: int, *, is_setpoint: bool = False) -> bool:
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
        yk_point = self._engine._point_table.get_yk(ioa)
        if yk_point is not None:
            return bool(yk_point.select_before_execute)

        # 设点命令: 对应的 YC 点无 sbo 字段, 默认直发执行 (False);
        # 未在遥控点表中定义的其它命令: 保持现有严格 SBO 行为 (True), 不破坏既有用例
        return not is_setpoint

    async def handle_single_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理单命令."""
        e = self._engine
        await e._apply_command_delay()
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: SingleCommand = obj.data
        logger.info(
            f"Single Command from {state.conn.name}: "
            f"IOA={obj.ioa} state={cmd.state} select={cmd.select}"
        )

        e._fire_event(SlaveEvent.COMMAND_RECEIVED, {
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
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Single Command SELECT ACK: IOA={obj.ioa}")
            elif not self.command_requires_sbo(obj.ioa):
                # 直发执行点 (sbo=false)：无需预先选择，直接执行
                state.selected_commands.pop(obj.ioa, None)
                # 回复执行确认
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                # 更新数据
                e._data_store.update_yk(obj.ioa, "execute", cmd.state)

                # 发送激活终止
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                await e._reflect_command_result(obj.ioa, single=bool(cmd.state))
                logger.info(f"Single Command DIRECT EXECUTE (sbo=false): IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 更新数据
                    e._data_store.update_yk(obj.ioa, "execute", cmd.state)

                    # 发送激活终止
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                    # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                    await e._reflect_command_result(obj.ioa, single=bool(cmd.state))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Single Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Single Command DEACTCON: IOA={obj.ioa}")

    async def handle_double_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理双命令."""
        e = self._engine
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
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Double Command SELECT ACK: IOA={obj.ioa}")
            elif not self.command_requires_sbo(obj.ioa):
                # 直发执行点 (sbo=false)：无需预先选择，直接执行
                state.selected_commands.pop(obj.ioa, None)
                # 回复执行确认
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                # 更新数据
                e._data_store.update_yk(obj.ioa, "execute", cmd.state)

                # 发送激活终止
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                await e._reflect_command_result(obj.ioa, double_state=int(cmd.state))
                logger.info(f"Double Command DIRECT EXECUTE (sbo=false): IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 更新数据
                    e._data_store.update_yk(obj.ioa, "execute", cmd.state)

                    # 发送激活终止
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                    # 真机语义：遥控成功后同 IOA 遥信变位并主动上送
                    await e._reflect_command_result(obj.ioa, double_state=int(cmd.state))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Double Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Double Command DEACTCON: IOA={obj.ioa}")

    async def handle_setpoint_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理设点命令."""
        e = self._engine
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
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Setpoint Command SELECT ACK: IOA={obj.ioa}")
            elif not self.command_requires_sbo(obj.ioa, is_setpoint=True):
                # 直发执行点 (sbo=false / 无 sbo 字段的 YC 点)：直接执行
                state.selected_commands.pop(obj.ioa, None)
                # 回复执行确认
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                # 发送激活终止
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                # 真机语义：遥调成功后同 IOA 遥测更新并主动上送
                if setpoint_value is not None:
                    await e._reflect_command_result(obj.ioa, yc_value=float(setpoint_value))
                logger.info(f"Setpoint Command DIRECT EXECUTE (sbo=false): IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 发送激活终止
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                    # 真机语义：遥调成功后同 IOA 遥测更新并主动上送
                    if setpoint_value is not None:
                        await e._reflect_command_result(obj.ioa, yc_value=float(setpoint_value))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Setpoint Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Setpoint Command DEACTCON: IOA={obj.ioa}")

    async def handle_regulating_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理升降命令.

        说明（与遥控/遥调的联动策略不同，属有意为之）：升降命令改变的是**调节步位置**
        （真机上为 M_ST_NA_1 步位置或档位），不是遥信位置；本工具点表未建模步位置点，
        故不做联动上送。若后续需要，应新增步位置点类型与对应的自发上送路径。
        """
        e = self._engine
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: RegulatingStepCommand = obj.data
        logger.info(
            f"Regulating Command from {state.conn.name}: "
            f"IOA={obj.ioa} state={cmd.state_str} select={cmd.select}"
        )
        e._fire_event(SlaveEvent.COMMAND_RECEIVED, {
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
                await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))
                logger.info(f"Regulating Command SELECT ACK: IOA={obj.ioa}")
            else:
                # 执行命令：先验证是否已选择
                if obj.ioa in state.selected_commands:
                    # 已选择，执行操作
                    del state.selected_commands[obj.ioa]
                    # 回复执行确认
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj))

                    # 发送激活终止
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
                else:
                    # 未选择，回复否定确认 (COT bit6 P/N=1)
                    await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True))
                    logger.warning(f"Regulating Command REJECTED (not selected): IOA={obj.ioa}")
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await self.send_i_frame(state, e._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Regulating Command DEACTCON: IOA={obj.ioa}")

    # ── 命令超时检查 ──────────────────────────────────────────────

    async def timeout_check_loop(self) -> None:
        """定期检查命令选择超时和协议定时器."""
        e = self._engine
        while True:
            try:
                await asyncio.sleep(1.0)  # 每秒检查一次
                for conn_id, state in list(e._client_states.items()):
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
                            e._spawn(self.send_to_client(state, frame))
                            state.state_machine.on_s_frame_sent()
                            logger.info(f"T2 expired: S-Frame sent to {conn_id}")
                        elif expired == TimerType.T3:
                            # T3空闲超时发送TESTFR ACT（U帧，需在t1内收到CON）
                            e._spawn(self.send_to_client(state, APCICodec.testfr_act()))
                            state.state_machine.on_u_frame_act_sent()
                            logger.info(f"T3 expired: TESTFR ACT sent to {conn_id}")
                        # 注: T0 为"连接建立超时"，仅适用于发起连接的控制站（主站）。
                        # 子站为被控站，其状态机以 use_t0=False 创建（见
                        # _on_client_connected），不会启动 t0，故此处无需处理。
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Timeout check error: {exc}")

            # 响应行为：主动 TESTFR
            if e._response_behavior.send_testfr and e._client_states:
                e._testfr_timer += 1.0
                interval = max(5.0, e._response_behavior.testfr_interval)
                if e._testfr_timer >= interval:
                    e._testfr_timer = 0.0
                    for conn_id, state in list(e._client_states.items()):
                        if state.data_transfer_enabled:
                            e._spawn(self.send_to_client(state, APCICodec.testfr_act()))
                            state.state_machine.on_u_frame_act_sent()
                            logger.info(f"Config TESTFR ACT sent to {conn_id}")

    # ── S帧回调 ───────────────────────────────────────────────────

    def on_s_frame_needed(self, state: _ClientState, rx_seq: int) -> None:
        """当收到w个未确认的I帧时，由SequenceManager回调发送S帧."""
        e = self._engine
        frame = APCICodec.encode_s(rx_seq)
        e._spawn(self.send_to_client(state, frame))
        state.state_machine.on_s_frame_sent()
        logger.debug(f"S-Frame sent to {state.conn.name}: rx_seq={rx_seq}")
        # 通知等待窗口空间的协程
        state.window_available.set()

    # ── 内部发送 ──────────────────────────────────────────────────

    async def send_i_frame(self, state: _ClientState, asdu_data: bytes) -> None:
        """向指定客户端发送 I 帧，窗口满时等待确认."""
        e = self._engine
        # 等待发送窗口可用（最多等 t1 超时时间）
        if not state.seq.send_window_available:
            logger.debug(f"Send window full for {state.conn.name}, waiting for S-frame...")
            state.window_available.clear()
            try:
                await asyncio.wait_for(state.window_available.wait(), timeout=e._t1)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"Send window timeout: no S-frame received within t1={e._t1}s"
                ) from None

        tx_seq = state.seq.get_send_seq()
        rx_seq = state.seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        await self.send_to_client(state, frame)
        state.state_machine.on_i_frame_sent()

    async def send_to_client(self, state: _ClientState, frame: bytes) -> None:
        """发送帧到指定客户端。"""
        e = self._engine
        # 错误注入：丢帧
        if e._maybe_drop_frame():
            logger.warning(f"Frame dropped by response config (len={len(frame)})")
            e._errors += 1
            return

        # 错误注入：损坏帧（翻转最后一字节）
        if e._response_behavior.corrupt and len(frame) > 0:
            frame = bytearray(frame)
            frame[-1] ^= 0xFF
            frame = bytes(frame)
            logger.warning("Frame corrupted by response config")

        try:
            await state.conn.send_frame(frame)

            # 更新统计
            e._frames_sent += 1
            e._bytes_sent += len(frame)

            if e._raw_frame_callback:
                try:
                    e._raw_frame_callback(frame, "tx", state.conn.name)
                except Exception:
                    pass

            # 报文录制
            if e._recorder:
                e._recorder.record_frame(frame, direction="tx",
                                         metadata={"client_id": state.conn.name})

            e._tx_buffer.append((time.monotonic(), frame, state.conn.name))
            state.state_machine.on_any_frame_sent()

            # 记录到历史数据库
            if e._history_db:
                frame_type = APCICodec.frame_type_of(frame)
                e._history_db.record_frame("tx", frame, frame_type=frame_type,
                                           client_id=state.conn.name)
        except Exception as exc:
            logger.error(f"Send to {state.conn.name} failed: {exc}")
            e._errors += 1

    async def broadcast_i_frame(self, asdu_data: bytes) -> None:
        """向所有已启动的客户端广播 I 帧."""
        e = self._engine
        for conn_id, state in e._client_states.items():
            if state.data_transfer_enabled and state.conn.is_connected:
                try:
                    await self.send_i_frame(state, asdu_data)
                except Exception as exc:
                    logger.error(f"Broadcast to {conn_id} failed: {exc}")
