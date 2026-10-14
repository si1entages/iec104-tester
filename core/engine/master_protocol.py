"""主站协议处理器 — 命令构建 / 帧编解码分发 / ASDU 处理.

从 ``core/engine/master.py`` 抽出的协议行为：

- 发送窗口等待（k 窗口耗尽 → 等待至多 t1）与命令 ASDU 发送封装
- 遥控/遥调/参数/文件传输等全部命令的构建与单帧下发（``*_raw``）
- SBO（选择-执行）判定与选择确认（ACTCON）等待
- I 帧 ASDU 解码分发与各类遥信/遥测/累计量/命令确认的业务处理
- 点位自学习（定义表自动补点）

设计：**组合 + 构造期注入**。引擎的全部共享状态（``_seq`` /
``_state_machine`` / ``_point_table`` / ``_pending_acks`` / ``_data_store`` …）
仍由 ``MasterEngine`` 持有，本类只持有引擎引用并按需读写，避免子模块反向
``import`` ``master.py`` 造成循环依赖（类型仅经 ``TYPE_CHECKING`` 前置引用）。

注意：命令单帧下发统一经 ``engine._send_command_asdu`` 这一「引擎属性」转发，
以保证测试/外部对 ``engine._send_command_asdu`` 的替换（帧捕获）依然生效。
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import TYPE_CHECKING

from ..data.point_table import (
    PointTable,
    YcPointDef,
    YcType,
    YmPointDef,
    YxPointDef,
    YxType,
)
from ..protocol.apci import APCICodec
from ..protocol.asdu import ASDU, ASDUBuilder
from ..protocol.file_transfer import FileTransferState
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

if TYPE_CHECKING:
    from .master import MasterEngine

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


class MasterProtocolHandler:
    """主站协议处理器（由 ``MasterEngine`` 组合持有）."""

    # 数据类型 → 遥信/遥测/遥脉的映射（用于自动补充定义表）
    _YX_SINGLE_TYPES = {TypeID.M_SP_NA_1, TypeID.M_SP_TA_1, TypeID.M_SP_TB_1}
    _YX_DOUBLE_TYPES = {TypeID.M_DP_NA_1, TypeID.M_DP_TA_1, TypeID.M_DP_TB_1}
    _YC_NORMALIZED_TYPES = {TypeID.M_ME_NA_1, TypeID.M_ME_TA_1,
                            TypeID.M_ME_TD_1, TypeID.M_ME_ND_1}
    _YC_SCALED_TYPES = {TypeID.M_ME_NB_1, TypeID.M_ME_TB_1, TypeID.M_ME_TE_1}
    _YC_SHORT_TYPES = {TypeID.M_ME_NC_1, TypeID.M_ME_TC_1, TypeID.M_ME_TF_1}
    _YM_TYPES = {TypeID.M_IT_NA_1, TypeID.M_IT_TA_1, TypeID.M_IT_TB_1}

    def __init__(self, engine: MasterEngine) -> None:
        self._engine = engine

    # ── 发送窗口与命令 ASDU 发送 ─────────────────────────────────

    async def await_send_window(self) -> None:
        """等待发送窗口可用（最多 t1）— 与子站行为对称.

        标准 (IEC 60870-5-104 Section 5.5): 发送方在有 k 个 I 帧未获确认时
        停止数据传送。本实现不立即失败，而是等待至多 t1；若仍无确认则认为
        TCP 连接异常，抛出 RuntimeError（与 SlaveEngine._send_i_frame 一致）。

        Raises:
            RuntimeError: 在 t1 内窗口未释放（迟迟收不到对端确认）。
        """
        e = self._engine
        if e._seq.send_window_available:
            return
        logger.debug("Send window full, waiting for acknowledgement...")
        e._window_available.clear()
        try:
            await asyncio.wait_for(e._window_available.wait(), timeout=e._t1)
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Send window timeout: no acknowledgement within t1={e._t1}s"
            ) from None

    async def send_command_asdu(self, asdu_data: bytes) -> None:
        """发送命令 ASDU — 公共封装：状态检查 + 序列号 + 编码 + 发送.

        所有命令方法（总召唤/遥控/遥调/参数等）共用此方法，
        消除重复的状态检查和帧编码样板代码。
        """
        e = self._engine
        if not e._state_machine.is_running:
            raise RuntimeError("Not in running state")
        await self.await_send_window()
        tx_seq = e._seq.get_send_seq()
        rx_seq = e._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)
        e._state_machine.on_i_frame_sent()
        await e._send_frame(frame)
        # 发送后若窗口已满，清除事件以等待对端确认
        if not e._seq.send_window_available:
            e._window_available.clear()

    # ── 协议命令 ──────────────────────────────────────────────────

    async def general_interrogation(self, qoi: int = 20) -> None:
        """发送总召唤命令.

        Args:
            qoi: 召唤范围 — 20=站召唤；1-16=第1-16组召唤。
                 内部换算为标准限定词 QOI（组召唤 → 20+组号，即 21-36）。
        """
        e = self._engine
        if qoi == 20:
            std_qoi = 20
        elif 1 <= qoi <= 16:
            std_qoi = 20 + qoi
        else:
            raise ValueError(
                f"Invalid interrogation qualifier {qoi} (expected 1-16 or 20)"
            )

        asdu_data = ASDUBuilder.build_general_interrogation(
            e._common_addr, std_qoi
        )
        await e._send_command_asdu(asdu_data)

        logger.info(f"General Interrogation sent (group={qoi}, QOI={std_qoi})")
        e._fire_event(MasterEvent.GENERAL_INTERROGATION, {"qoi": qoi})

    async def counter_interrogation(self, qcc: int = 0) -> None:
        """发送累计量召唤命令."""
        e = self._engine
        asdu_data = ASDUBuilder.build_counter_interrogation(
            e._common_addr, qcc
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Counter Interrogation sent (QCC={qcc})")

    async def clock_sync(self, time_tag: CP56Time2a | None = None) -> None:
        """发送时钟同步命令."""
        e = self._engine
        asdu_data = ASDUBuilder.build_clock_sync(e._common_addr, time_tag)
        await e._send_command_asdu(asdu_data)

        # 记录发送时间用于校验
        e._last_clock_sync_sent_time = time.monotonic()

        logger.info("Clock Sync sent")
        e._fire_event(MasterEvent.CLOCK_SYNC)

    async def reset_process(self, qrp: int = 1) -> None:
        """发送复位进程命令."""
        e = self._engine
        asdu_data = ASDUBuilder.build_reset_process(e._common_addr, qrp)
        await e._send_command_asdu(asdu_data)
        logger.info(f"Reset Process sent (QRP={qrp})")

    async def send_test_command(self) -> None:
        """发送测试命令."""
        e = self._engine
        asdu_data = ASDUBuilder.build_test_command(e._common_addr)
        await e._send_command_asdu(asdu_data)
        logger.info("Test Command sent")

    # ── 遥控操作 ──────────────────────────────────────────────────

    def sbo_required(self, ioa: int, kind: str) -> bool:
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
        e = self._engine
        if e._point_table is None:
            return False
        yk_point = e._point_table.get_yk(ioa)
        if yk_point is not None:
            return bool(yk_point.select_before_execute)
        # 未命中 YK 点表: 遥控与设点均不强制 SBO (设点回落同子站语义)
        return False

    async def wait_select_ack(self, ioa: int, timeout: float) -> bool:
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
        e = self._engine
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        # 并发覆盖防护: 取消同一 IOA 上残留的旧等待
        old = e._pending_acks.get(ioa)
        if old is not None and not old.done():
            logger.warning(f"SBO: concurrent wait on IOA={ioa}, cancelling stale waiter")
            old.cancel()
        e._pending_acks[ioa] = fut
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
            if e._pending_acks.get(ioa) is fut:
                e._pending_acks.pop(ioa, None)
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
        if not select and self.sbo_required(ioa, "yk"):
            await self.send_single_command_raw(ioa, state, select=True, qu=qu)
            acked = await self.wait_select_ack(ioa, self._engine._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for single command IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self.send_single_command_raw(ioa, state, select=select, qu=qu)

    async def send_single_command_raw(self, ioa: int, state: bool,
                                       select: bool, qu: int) -> None:
        """发送单命令单帧（不做 SBO 决策）."""
        e = self._engine
        asdu_data = ASDUBuilder.build_single_command(
            e._common_addr, ioa, state, select, qu
        )
        await e._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        state_str = "ON" if state else "OFF"
        logger.info(f"Single Command: IOA={ioa} {action} {state_str}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "single_command", "ioa": ioa,
            "state": state, "select": select
        })

    async def double_command(self, ioa: int, state: int,
                              select: bool = False, qu: int = 0) -> None:
        """发送双命令 (选择/执行).

        对 SBO 点位自动两段式下发，语义同 ``single_command``。
        """
        if not select and self.sbo_required(ioa, "yk"):
            await self.send_double_command_raw(ioa, state, select=True, qu=qu)
            acked = await self.wait_select_ack(ioa, self._engine._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for double command IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self.send_double_command_raw(ioa, state, select=select, qu=qu)

    async def send_double_command_raw(self, ioa: int, state: int,
                                       select: bool, qu: int) -> None:
        """发送双命令单帧（不做 SBO 决策）."""
        e = self._engine
        asdu_data = ASDUBuilder.build_double_command(
            e._common_addr, ioa, state, select, qu
        )
        await e._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Double Command: IOA={ioa} {action} state={state}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
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
        if not select and self.sbo_required(ioa, "yc"):
            await self.send_setpoint_normalized_raw(ioa, value, select=True)
            acked = await self.wait_select_ack(ioa, self._engine._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for setpoint IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self.send_setpoint_normalized_raw(ioa, value, select=select)

    async def send_setpoint_normalized_raw(self, ioa: int, value: float,
                                            select: bool) -> None:
        """发送归一化设点单帧（不做 SBO 决策）."""
        e = self._engine
        asdu_data = ASDUBuilder.build_setpoint_normalized(
            e._common_addr, ioa, value, select
        )
        await e._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint Normalized: IOA={ioa} {action} value={value}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "setpoint_normalized", "ioa": ioa,
            "value": value, "select": select
        })

    async def setpoint_shortfloat(self, ioa: int, value: float,
                                    select: bool = False) -> None:
        """发送短浮点设点命令 (选择/执行).

        与 ``setpoint_normalized`` 语义一致：命中 YK 点表且 SBO 配置为 True 时
        自动两段式下发；否则直发执行（向后兼容），可用 ``select`` 显式覆盖。
        """
        if not select and self.sbo_required(ioa, "yc"):
            await self.send_setpoint_shortfloat_raw(ioa, value, select=True)
            acked = await self.wait_select_ack(ioa, self._engine._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for setpoint IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self.send_setpoint_shortfloat_raw(ioa, value, select=select)

    async def send_setpoint_shortfloat_raw(self, ioa: int, value: float,
                                            select: bool) -> None:
        """发送短浮点设点单帧（不做 SBO 决策）."""
        e = self._engine
        asdu_data = ASDUBuilder.build_setpoint_shortfloat(
            e._common_addr, ioa, value, select
        )
        await e._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint ShortFloat: IOA={ioa} {action} value={value}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
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
        if not select and self.sbo_required(ioa, "yk"):
            await self.send_regulating_step_raw(ioa, state, select=True, qu=qu)
            acked = await self.wait_select_ack(ioa, self._engine._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for regulating step IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self.send_regulating_step_raw(ioa, state, select=select, qu=qu)

    async def send_regulating_step_raw(self, ioa: int, state: int,
                                        select: bool, qu: int) -> None:
        """发送升降命令单帧（不做 SBO 决策）."""
        e = self._engine
        asdu_data = ASDUBuilder.build_regulating_step_command(
            e._common_addr, ioa, state, select, qu
        )
        await e._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        state_str = {1: "降一步", 2: "升一步"}.get(state, f"未知({state})")
        logger.info(f"Regulating Step Command: IOA={ioa} {action} {state_str}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
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
        if not select and self.sbo_required(ioa, "yc"):
            await self.send_setpoint_scaled_raw(ioa, value, select=True)
            acked = await self.wait_select_ack(ioa, self._engine._t1)
            if not acked:
                raise RuntimeError(
                    f"SBO select failed for setpoint IOA={ioa} "
                    f"(rejected or timed out); execute not sent"
                )
        await self.send_setpoint_scaled_raw(ioa, value, select=select)

    async def send_setpoint_scaled_raw(self, ioa: int, value: int,
                                        select: bool) -> None:
        """发送标度化设点单帧（不做 SBO 决策）."""
        e = self._engine
        asdu_data = ASDUBuilder.build_setpoint_scaled(
            e._common_addr, ioa, value, select
        )
        await e._send_command_asdu(asdu_data)

        action = "SELECT" if select else "EXECUTE"
        logger.info(f"Setpoint Scaled: IOA={ioa} {action} value={value}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "setpoint_scaled", "ioa": ioa,
            "value": value, "select": select
        })

    async def bitstring_command(self, ioa: int, value: int) -> None:
        """发送比特串命令 (C_BO_NA_1).

        Args:
            ioa: 信息对象地址
            value: 32位无符号整数
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_bitstring_command(
            e._common_addr, ioa, value
        )
        await e._send_command_asdu(asdu_data)

        logger.info(f"Bitstring Command: IOA={ioa} value=0x{value:08X}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "bitstring", "ioa": ioa, "value": value
        })

    # ── 带时标 CP56Time2a 的控制命令 (TypeID 58-64) ────────────────

    async def single_command_with_time(self, ioa: int, state: bool,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None) -> None:
        """发送带时标单命令 (C_SC_TA_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_single_command_with_time(
            e._common_addr, ioa, state, select, qu, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Single Command (with time): IOA={ioa} state={state}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "single_command_ta", "ioa": ioa, "state": state,
        })

    async def double_command_with_time(self, ioa: int, state: int,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None) -> None:
        """发送带时标双命令 (C_DC_TA_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_double_command_with_time(
            e._common_addr, ioa, state, select, qu, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Double Command (with time): IOA={ioa} state={state}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "double_command_ta", "ioa": ioa, "state": state,
        })

    async def regulating_step_command_with_time(self, ioa: int, state: int,
                                                 select: bool = False, qu: int = 0,
                                                 time_tag: CP56Time2a | None = None) -> None:
        """发送带时标升降命令 (C_RC_TA_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_regulating_step_command_with_time(
            e._common_addr, ioa, state, select, qu, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Regulating Step Command (with time): IOA={ioa} state={state}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "regulating_step_ta", "ioa": ioa, "state": state,
        })

    async def setpoint_normalized_with_time(self, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None) -> None:
        """发送带时标归一化设点命令 (C_SE_TA_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_setpoint_normalized_with_time(
            e._common_addr, ioa, value, select, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Setpoint Normalized (with time): IOA={ioa} value={value}")

    async def setpoint_scaled_with_time(self, ioa: int, value: int,
                                         select: bool = False,
                                         time_tag: CP56Time2a | None = None) -> None:
        """发送带时标标度化设点命令 (C_SE_TB_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_setpoint_scaled_with_time(
            e._common_addr, ioa, value, select, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Setpoint Scaled (with time): IOA={ioa} value={value}")

    async def setpoint_shortfloat_with_time(self, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None) -> None:
        """发送带时标短浮点设点命令 (C_SE_TC_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_setpoint_shortfloat_with_time(
            e._common_addr, ioa, value, select, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Setpoint ShortFloat (with time): IOA={ioa} value={value}")

    async def bitstring_command_with_time(self, ioa: int, value: int,
                                           time_tag: CP56Time2a | None = None) -> None:
        """发送带时标比特串命令 (C_BO_TA_1)."""
        e = self._engine
        asdu_data = ASDUBuilder.build_bitstring_command_with_time(
            e._common_addr, ioa, value, time_tag
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"Bitstring Command (with time): IOA={ioa} value=0x{value:08X}")
        e._fire_event(MasterEvent.COMMAND_SENT, {
            "type": "bitstring_ta", "ioa": ioa, "value": value,
        })

    async def read_command(self, ioa: int) -> None:
        """发送读命令 (C_RD_NA_1).

        Args:
            ioa: 信息对象地址
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_read_command(e._common_addr, ioa)
        await e._send_command_asdu(asdu_data)

        logger.info(f"Read Command: IOA={ioa}")

    async def delay_command(self, delay_ms: int) -> None:
        """发送延时获得命令 (C_CD_NA_1).

        Args:
            delay_ms: 延时值（毫秒）
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_delay_command(e._common_addr, delay_ms)
        await e._send_command_asdu(asdu_data)

        logger.info(f"Delay Command: delay={delay_ms}ms")

    async def test_command_with_time(self, time_tag: CP56Time2a | None = None) -> None:
        """发送带时标测试命令 (C_TS_TA_1).

        Args:
            time_tag: 时标，默认使用当前时间
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_test_command_with_time(
            e._common_addr, time_tag
        )
        await e._send_command_asdu(asdu_data)

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
        e = self._engine
        asdu_data = ASDUBuilder.build_parameter_normalized(
            e._common_addr, ioa, value, param_change
        )
        await e._send_command_asdu(asdu_data)

        logger.info(f"Parameter Normalized: IOA={ioa} value={value} change={param_change}")

    async def parameter_scaled(self, ioa: int, value: int,
                                param_change: int = 0) -> None:
        """发送测量值参数-标度化 (P_ME_NB_1).

        Args:
            ioa: 信息对象地址
            value: 标度化值 (-32768..+32767)
            param_change: 参数变更标志
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_parameter_scaled(
            e._common_addr, ioa, value, param_change
        )
        await e._send_command_asdu(asdu_data)

        logger.info(f"Parameter Scaled: IOA={ioa} value={value} change={param_change}")

    async def parameter_float(self, ioa: int, value: float,
                               param_change: int = 0) -> None:
        """发送测量值参数-短浮点 (P_ME_NC_1).

        Args:
            ioa: 信息对象地址
            value: 短浮点值
            param_change: 参数变更标志
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_parameter_float(
            e._common_addr, ioa, value, param_change
        )
        await e._send_command_asdu(asdu_data)

        logger.info(f"Parameter Float: IOA={ioa} value={value} change={param_change}")

    async def parameter_activation(self, ioa: int, qualifier: int = 1) -> None:
        """发送参数激活 (P_AC_NA_1).

        Args:
            ioa: 信息对象地址
            qualifier: 0=未用/取消, 1=激活/周期, 2=去激活
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_parameter_activation(
            e._common_addr, ioa, qualifier
        )
        await e._send_command_asdu(asdu_data)

        action_str = {0: "未用", 1: "激活", 2: "去激活"}.get(qualifier, f"未知({qualifier})")
        logger.info(f"Parameter Activation: IOA={ioa} qualifier={action_str}")

    # ── 文件传输命令 ──────────────────────────────────────────────

    async def file_call_directory(self, ioa: int = 0) -> None:
        """发送召唤目录命令 (F_SC_NA_1).

        Args:
            ioa: 信息对象地址
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_call_directory(
            e._common_addr, ioa, qualifier=5
        )
        # 与非文件传输命令一致：窗口满时等待至多 t1（文件传输会产生大量 I 帧，
        # 是最容易打满 k 窗口的场景）。
        await e._send_command_asdu(asdu_data)
        logger.info("File Call Directory sent")

    async def file_select(self, ioa: int, file_name: int) -> None:
        """发送文件选择命令 (F_SC_NB_1).

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_file_select_call_get(
            e._common_addr, ioa, file_name, qualifier=4
        )
        await e._send_command_asdu(asdu_data)
        logger.info(f"File Select: file_name={file_name}")

    async def file_request(self, ioa: int, file_name: int) -> None:
        """发送文件请求命令 (F_SC_NB_1).

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_file_select_call_get(
            e._common_addr, ioa, file_name, qualifier=1
        )
        await e._send_command_asdu(asdu_data)
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
        e = self._engine
        asdu_data = ASDUBuilder.build_ack_file_section(
            e._common_addr, ioa, file_name, section_name, qualifier
        )
        await e._send_command_asdu(asdu_data)
        qual_str = {0: "缺省", 1: "肯定文件", 2: "否定文件", 3: "肯定节", 4: "否定节"}.get(qualifier, f"未知({qualifier})")
        logger.info(f"File ACK: file_name={file_name} section={section_name} qualifier={qual_str}")

    async def request_file(self, ioa: int, file_name: int) -> None:
        """请求文件（使用文件传输管理器）.

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
        """
        e = self._engine
        if not e._state_machine.is_running:
            raise RuntimeError("Not in running state")
        e._file_transfer.request_file(ioa, file_name)

    async def send_i_frame_with_data(self, asdu_data: bytes) -> None:
        """发送I帧（内部方法）— 与命令发送共享 k 窗口等待语义."""
        e = self._engine
        await self.await_send_window()
        tx_seq = e._seq.get_send_seq()
        rx_seq = e._seq.get_recv_seq()
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)
        e._state_machine.on_i_frame_sent()
        await e._send_frame(frame)
        if not e._seq.send_window_available:
            e._window_available.clear()

    def on_file_received(self, file_name: int, data: bytes) -> None:
        """文件接收完成回调."""
        e = self._engine
        logger.info(f"File received: name={file_name} size={len(data)}")
        e._fire_event(MasterEvent.DATA_RECEIVED, {
            "type_id": "file",
            "file_name": file_name,
            "data": data,
        })

    def on_file_transfer_error(self, error: str) -> None:
        """文件传输错误回调."""
        e = self._engine
        logger.error(f"File transfer error: {error}")
        e._fire_event(MasterEvent.ERROR, {"error": error})

    # ── I 帧 ASDU 解码分发 ────────────────────────────────────────

    def decode_and_dispatch(self, asdu_data: bytes) -> None:
        """解码 I 帧 ASDU 并分发；解码失败时按标准 COT 优雅处理."""
        try:
            asdu = ASDU.decode(asdu_data)
            self.process_asdu(asdu)
        except Exception as exc:
            # 解码失败可能因"未知类型标识"应答 — 仅解析头部以优雅处理
            try:
                header = ASDU.decode_header(asdu_data)
                if header.cot in (COT.UNKNOWN_TYPE, COT.UNKNOWN_COT, COT.UNKNOWN_CA):
                    self.handle_standard_error_reply(header)
                else:
                    logger.error(f"ASDU decode error: {exc}")
            except Exception:
                logger.error(f"ASDU decode error: {exc}")

    def process_asdu(self, asdu: ASDU) -> None:
        """处理解析后的 ASDU."""
        e = self._engine
        type_id = asdu.type_id
        cot = asdu.cot

        # ── 标准应答: 未知类型标识/未知传送原因/未知公共地址 (COT 42/43/44) ──
        # 子站无法识别来报时按标准回送 COT=42/43/44 并保持连接；主站优雅处理。
        # 注意: 需在公共地址校验之前处理 —— COT=44 应答会回显"错误的"公共地址，
        # 若先做地址校验会被误丢弃。
        if cot in (COT.UNKNOWN_TYPE, COT.UNKNOWN_COT, COT.UNKNOWN_CA):
            self.handle_standard_error_reply(asdu)
            return

        # 公共地址校验（广播地址255不检查）
        if asdu.common_addr != 255 and asdu.common_addr != e._common_addr:
            logger.warning(
                f"Common addr mismatch: expected={e._common_addr}, got={asdu.common_addr}"
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
                self.process_interrogation_response(asdu)
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
                self.process_counter(asdu)
            else:
                logger.debug(f"Counter Interrogation with unexpected COT={cot}")

        # 单点遥信
        elif type_id in (TypeID.M_SP_NA_1, TypeID.M_SP_TB_1):
            self.process_single_point(asdu)

        # 双点遥信
        elif type_id in (TypeID.M_DP_NA_1, TypeID.M_DP_TB_1):
            self.process_double_point(asdu)

        # 步位置信息
        elif type_id in (TypeID.M_ST_NA_1, TypeID.M_ST_TB_1):
            self.process_step_position(asdu)

        # 32比特串
        elif type_id in (TypeID.M_BO_NA_1, TypeID.M_BO_TB_1):
            self.process_bitstring32(asdu)

        # 归一化值
        elif type_id in (TypeID.M_ME_NA_1, TypeID.M_ME_TA_1, TypeID.M_ME_TD_1, TypeID.M_ME_ND_1):
            self.process_normalized(asdu)

        # 标度化值
        elif type_id in (TypeID.M_ME_NB_1, TypeID.M_ME_TB_1, TypeID.M_ME_TE_1):
            self.process_scaled(asdu)

        # 短浮点数
        elif type_id in (TypeID.M_ME_NC_1, TypeID.M_ME_TC_1, TypeID.M_ME_TF_1):
            self.process_short_float(asdu)

        # 累计量（含 CP24 短时标变体 M_IT_TA_1 —— 漏掉会把真机的 CP24 电度静默丢弃）
        elif type_id in (TypeID.M_IT_NA_1, TypeID.M_IT_TA_1, TypeID.M_IT_TB_1):
            self.process_counter(asdu)

        # 继电保护事件
        elif type_id in (TypeID.M_EP_TA_1, TypeID.M_EP_TB_1, TypeID.M_EP_TC_1,
                          TypeID.M_EP_TD_1, TypeID.M_EP_TE_1, TypeID.M_EP_TF_1):
            self.process_protection_event(asdu)

        # 成组单点状态检出
        elif type_id in (TypeID.M_PS_NA_1, TypeID.M_PS_TB_1):
            self.process_group_single_point(asdu)

        # 命令确认
        elif type_id in (TypeID.C_SC_NA_1, TypeID.C_DC_NA_1, TypeID.C_RC_NA_1,
                          TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1,
                          TypeID.C_BO_NA_1,
                          TypeID.C_SC_TA_1, TypeID.C_DC_TA_1, TypeID.C_RC_TA_1,
                          TypeID.C_SE_TA_1, TypeID.C_SE_TB_1, TypeID.C_SE_TC_1,
                          TypeID.C_BO_TA_1):
            self.process_command_ack(asdu)

        # 时钟同步确认
        elif type_id == TypeID.C_CS_NA_1:
            if e._last_clock_sync_sent_time:
                round_trip = time.monotonic() - e._last_clock_sync_sent_time
                logger.info(f"Clock Sync ACK received: round-trip={round_trip*1000:.1f}ms, COT={cot}")
                e._last_clock_sync_sent_time = None
            else:
                logger.info(f"Clock Sync ACK received, COT={cot}")

        # 读命令响应
        elif type_id == TypeID.C_RD_NA_1:
            self.process_read_response(asdu)

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
            if cot == COT.INIT and e._auto_gi_on_init_end:
                e._spawn(e._regi_after_init())

        # 参数命令确认
        elif type_id in (TypeID.P_ME_NA_1, TypeID.P_ME_NB_1, TypeID.P_ME_NC_1,
                          TypeID.P_ME_ND_1, TypeID.P_AC_NA_1):
            logger.info(f"Parameter Command ACK: type={type_id}, COT={cot}")

        # 文件传输
        elif type_id in (TypeID.F_FR_NA_1, TypeID.F_SR_NA_1, TypeID.F_SC_NA_1,
                          TypeID.F_LS_NA_1, TypeID.F_AF_NA_1, TypeID.F_SG_NA_1,
                          TypeID.F_DR_TA_1, TypeID.F_SC_NB_1,
                          TypeID.F_FR_NB_1, TypeID.F_SR_NB_1):
            self.process_file_transfer(asdu)

        else:
            logger.debug(f"Unhandled ASDU: type={type_id}, cot={cot}")

        e._fire_event(MasterEvent.DATA_RECEIVED, {
            "type_id": type_id,
            "cot": cot,
            "common_addr": asdu.common_addr,
            "objects": asdu.objects,
        })

    # ── 点位自学习 ────────────────────────────────────────────────

    def ensure_points_defined(self, asdu: ASDU) -> None:
        """按报文解析结果自动补充定义表（点位自学习，**默认开启**）.

        真机点位规划与本地定义表往往不一致（实测：设备的遥测在 IOA 16385+，
        本地表只有 4001 等）——值其实已进实时库，只是定义表没有该点位导致
        界面不显示。这里把数据帧中出现、定义表缺失的 IOA 自动补齐：
        单/双点遥信 → YX、归一化/标度化/短浮点 → YC、累计量 → YM，
        命名 ``遥信<IOA>`` / ``遥测<IOA>`` / ``遥脉<IOA>``。
        """
        e = self._engine
        if not e._auto_add_points:
            return
        table = e._point_table
        if table is None:
            table = PointTable()
            e._point_table = table

        added: list[str] = []
        tid = asdu.type_id
        for obj in asdu.objects:
            ioa = obj.ioa
            if tid in self._YX_SINGLE_TYPES and table.get_yx(ioa) is None:
                table.add_yx(YxPointDef(ioa=ioa, name=f"遥信{ioa}", group=1,
                                        point_type=YxType.SINGLE))
                added.append(f"YX:{ioa}")
            elif tid in self._YX_DOUBLE_TYPES and table.get_yx(ioa) is None:
                table.add_yx(YxPointDef(ioa=ioa, name=f"遥信{ioa}", group=1,
                                        point_type=YxType.DOUBLE))
                added.append(f"YX(双点):{ioa}")
            elif (tid in (self._YC_NORMALIZED_TYPES | self._YC_SCALED_TYPES
                          | self._YC_SHORT_TYPES) and table.get_yc(ioa) is None):
                data_type = (YcType.NORMALIZED if tid in self._YC_NORMALIZED_TYPES
                             else YcType.SCALED if tid in self._YC_SCALED_TYPES
                             else YcType.SHORT_FLOAT)
                table.add_yc(YcPointDef(ioa=ioa, name=f"遥测{ioa}", group=1,
                                        data_type=data_type))
                added.append(f"YC:{ioa}")
            elif tid in self._YM_TYPES and table.get_ym(ioa) is None:
                table.add_ym(YmPointDef(ioa=ioa, name=f"遥脉{ioa}", group=1))
                added.append(f"YM:{ioa}")
        if added:
            logger.info(f"Auto-added points from type={tid}: {', '.join(added[:8])}"
                        f"{' ...' if len(added) > 8 else ''}（定义表现有 "
                        f"{len(table.get_all_yx()) + len(table.get_all_yc()) + len(table.get_all_ym())} 点）")

    def process_single_point(self, asdu: ASDU) -> None:
        """处理单点遥信."""
        e = self._engine
        self.ensure_points_defined(asdu)
        for obj in asdu.objects:
            sp: SinglePoint = obj.data
            e._data_store.update_yx(
                obj.ioa, sp.value, sp.quality
            )
            if e._history_db:
                e._history_db.record_data_change(
                    "yx", obj.ioa, sp.value,
                    quality=str(sp.quality),
                    source="spont" if asdu.cot == COT.SPONT else "gi",
                )

    def process_double_point(self, asdu: ASDU) -> None:
        """处理双点遥信."""
        e = self._engine
        self.ensure_points_defined(asdu)
        for obj in asdu.objects:
            dp: DoublePoint = obj.data
            e._data_store.update_yx(
                obj.ioa, dp.value == 2, dp.quality,
                double_state=dp.value
            )
            if e._history_db:
                e._history_db.record_data_change(
                    "yx", obj.ioa, dp.value,
                    quality=str(dp.quality),
                )

    def process_short_float(self, asdu: ASDU) -> None:
        """处理短浮点遥测."""
        e = self._engine
        self.ensure_points_defined(asdu)
        for obj in asdu.objects:
            sf: ShortFloat = obj.data
            e._data_store.update_yc(
                obj.ioa, sf.value, sf.quality
            )
            if e._history_db:
                e._history_db.record_data_change(
                    "yc", obj.ioa, sf.value,
                    quality=str(sf.quality),
                )

    def process_normalized(self, asdu: ASDU) -> None:
        """处理归一化遥测."""
        e = self._engine
        self.ensure_points_defined(asdu)
        for obj in asdu.objects:
            nv: NormalizedValue = obj.data
            e._data_store.update_yc(
                obj.ioa, nv.value, nv.quality
            )

    def process_scaled(self, asdu: ASDU) -> None:
        """处理标度化遥测."""
        e = self._engine
        self.ensure_points_defined(asdu)
        for obj in asdu.objects:
            sv: ScaledValue = obj.data
            e._data_store.update_yc(
                obj.ioa, float(sv.value), sv.quality
            )

    def process_counter(self, asdu: ASDU) -> None:
        """处理累计量."""
        e = self._engine
        self.ensure_points_defined(asdu)
        for obj in asdu.objects:
            cv: CounterValue = obj.data
            e._data_store.update_ym(
                obj.ioa, cv.value, cv.quality
            )

    def process_file_transfer(self, asdu: ASDU) -> None:
        """处理文件传输."""
        e = self._engine
        type_id = asdu.type_id
        if not asdu.objects:
            return

        obj = asdu.objects[0]

        if type_id == TypeID.F_FR_NA_1:
            e._file_transfer.handle_file_ready(obj.data)
            # 主站收到"文件准备就绪"应立即回复 F_FR_NB_1 确认
            e._file_transfer.send_file_ready_ack(obj.ioa)
        elif type_id == TypeID.F_SR_NA_1:
            e._file_transfer.handle_section_ready(obj.data)
            # 主站收到"节准备就绪"应立即回复 F_SR_NB_1 确认
            e._file_transfer.send_section_ready_ack(obj.ioa)
        elif type_id == TypeID.F_SG_NA_1:
            e._file_transfer.handle_file_segment(obj.data)
        elif type_id == TypeID.F_LS_NA_1:
            e._file_transfer.handle_last_section(obj.data)
            # 收到"最后的节/段"后回复 F_AF_NA_1 (肯定节) 完成握手
            e._file_transfer.send_ack(obj.ioa, qualifier=3)
        elif type_id == TypeID.F_DR_TA_1:
            e._file_transfer.handle_directory_entry(obj.data)
        elif type_id == TypeID.F_FR_NB_1:
            logger.info(f"File Ready ACK: file_name={obj.data.file_name if hasattr(obj.data, 'file_name') else 'N/A'}")
        elif type_id == TypeID.F_SR_NB_1:
            logger.info(f"Section Ready ACK: file_name={obj.data.file_name if hasattr(obj.data, 'file_name') else 'N/A'}")

        logger.info(f"File Transfer: type={type_id}, state={e._file_transfer.state}")

    def process_interrogation_response(self, asdu: ASDU) -> None:
        """处理总召唤响应."""
        e = self._engine
        for obj in asdu.objects:
            if isinstance(obj.data, SinglePoint):
                e._data_store.update_yx(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, DoublePoint):
                e._data_store.update_yx(
                    obj.ioa, obj.data.value == 2, obj.data.quality,
                    double_state=obj.data.value
                )
            elif isinstance(obj.data, NormalizedValue):
                e._data_store.update_yc(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, ScaledValue):
                e._data_store.update_yc(obj.ioa, float(obj.data.value), obj.data.quality)
            elif isinstance(obj.data, ShortFloat):
                e._data_store.update_yc(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, StepPosition):
                e._data_store.update_yc(obj.ioa, float(obj.data.value), obj.data.quality)
            elif isinstance(obj.data, BitString32):
                e._data_store.update_yc(obj.ioa, float(obj.data.value), QualityDescriptor())
            elif isinstance(obj.data, CounterValue):
                e._data_store.update_ym(obj.ioa, obj.data.value, obj.data.quality)
            elif isinstance(obj.data, GroupSinglePointWithStatus):
                for i, (state, _detected) in enumerate(obj.data.points):
                    e._data_store.update_yx(obj.ioa + i, state, QualityDescriptor())

    def handle_standard_error_reply(self, asdu: ASDU) -> None:
        """优雅处理子站按标准回送的 COT 42/43/44 应答.

        - COT 42: 未知类型标识 (unknown type identification)
        - COT 43: 未知传送原因 (unknown cause of transmission)
        - COT 44: 未知公共地址 (unknown common address)

        主站记录告警并触发事件，但**不**断开连接（连接本身正常）。
        """
        e = self._engine
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
        e._fire_event(MasterEvent.DATA_RECEIVED, {
            "type_id": asdu.type_id,
            "cot": cot,
            "common_addr": asdu.common_addr,
            "error_reply": reason,
            "objects": asdu.objects,
        })

    def process_command_ack(self, asdu: ASDU) -> None:
        """处理命令确认.

        否定确认 (P/N) 严格取自标准 COT bit6 (``asdu.pn``)。
        不再退回解析命令数据字节 bit7 —— 该字节是 S/E (选择/执行) 位，
        对 SBO 选择命令 S/E=1，会把"肯定选择确认"误判为 NACK
        (子站自 P0/#4 起已不再用数据字节伪造 P/N)。
        """
        e = self._engine
        cot = asdu.cot
        pn = asdu.pn
        for obj in asdu.objects:
            if cot == COT.ACTCON:
                if pn:
                    logger.warning(f"Command NACK (PN=1): type={asdu.type_id} IOA={obj.ioa}")
                    e._data_store.update_yk(obj.ioa, "nack")
                else:
                    logger.info(f"Command ACK: type={asdu.type_id} IOA={obj.ioa}")
                    e._data_store.update_yk(obj.ioa, "ack")
                # 唤醒等待该 IOA 命令确认的两段式下发逻辑
                e._resolve_pending_ack(obj.ioa, pn=pn, cot=cot)
            elif cot == COT.DEACTCON:
                logger.info(f"Command DEACTCON: type={asdu.type_id} IOA={obj.ioa}")
                e._resolve_pending_ack(obj.ioa, pn=pn, cot=cot)
            elif cot == COT.ACTTERM:
                logger.info(f"Command ACTTERM: type={asdu.type_id} IOA={obj.ioa}")
                e._resolve_pending_ack(obj.ioa, pn=pn, cot=cot)
            else:
                logger.warning(f"Command with COT={cot}")

    def process_step_position(self, asdu: ASDU) -> None:
        """处理步位置信息."""
        e = self._engine
        for obj in asdu.objects:
            sp: StepPosition = obj.data
            e._data_store.update_yc(obj.ioa, float(sp.value), sp.quality)

    def process_bitstring32(self, asdu: ASDU) -> None:
        """处理32比特串."""
        e = self._engine
        for obj in asdu.objects:
            bs: BitString32 = obj.data
            e._data_store.update_yc(obj.ioa, float(bs.value), QualityDescriptor())

    def process_protection_event(self, asdu: ASDU) -> None:
        """处理继电保护事件."""
        for obj in asdu.objects:
            pe: ProtectionEvent = obj.data
            logger.info(f"Protection Event: IOA={obj.ioa} value={pe.event_value}")

    def process_group_single_point(self, asdu: ASDU) -> None:
        """处理成组单点状态检出."""
        e = self._engine
        for obj in asdu.objects:
            gsp: GroupSinglePointWithStatus = obj.data
            for i, (state, _detected) in enumerate(gsp.points):
                e._data_store.update_yx(obj.ioa + i, state, QualityDescriptor())

    def process_read_response(self, asdu: ASDU) -> None:
        """处理读命令响应."""
        for obj in asdu.objects:
            logger.info(f"Read Response: IOA={obj.ioa}")

    @property
    def file_transfer_state(self) -> FileTransferState:
        """获取文件传输状态."""
        return self._engine._file_transfer.state
