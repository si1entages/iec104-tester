"""主站命令构建 — 命令 ASDU 构建与单帧下发.

从 ``core/engine/master_protocol.py`` 抽出的**命令侧**行为：

- 发送窗口等待（k 窗口耗尽 → 至多等待 t1）与命令 ASDU 发送封装
- 总召唤/累计量/时钟同步/复位/测试等系统命令
- 遥控/遥调/升降/设点/比特串等控制命令构建与单帧下发（``*_raw``）
- SBO（选择-执行）判定与选择确认（ACTCON）等待
- 带时标 CP56Time2a 控制命令（TypeID 58-64）与参数命令

文件传输的收发两侧内聚于 ``master_protocol``（``process_file_transfer`` 已在其中）。

设计：**组合 + 构造期注入**。引擎的全部共享状态（``_seq`` / ``_state_machine``
/ ``_point_table`` / ``_pending_acks`` …）仍由 ``MasterEngine`` 持有，本类只持有
引擎引用并按需读写，避免子模块反向 ``import`` ``master.py`` 造成循环依赖
（类型仅经 ``TYPE_CHECKING`` 前置引用）。

注意：命令单帧下发统一经 ``engine._send_command_asdu`` 这一「引擎属性」转发，
以保证测试/外部对 ``engine._send_command_asdu`` 的替换（帧捕获）依然生效。

``MasterEvent`` 定义在 ``master_protocol``（不反向依赖本模块），本模块自其导入。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..protocol.apci import APCICodec
from ..protocol.asdu import ASDUBuilder
from ..protocol.types import COT, CP56Time2a
from .master_protocol import MasterEvent

if TYPE_CHECKING:
    from .master import MasterEngine

logger = logging.getLogger("iec104.master")


class MasterCommandHandler:
    """主站命令构建与单帧下发（由 ``MasterEngine`` 组合持有）."""

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

