"""主站会话层 — 连接管理 / 状态机 / 帧接收 / 定时器 / 重连.

从 ``core/engine/master.py`` 抽出的连接中枢：

- TCP 连接建立与拆除（STARTDT/STOPDT、重连由 TCP 客户端自持）
- 原始帧接收回调与 I/S/U 帧的序列号 / 窗口 / 状态机处理
- t0/t1/t2/t3 定时器检查循环与超时处置
- 连接相关事件（CONNECTED / DISCONNECTED / STARTED / TIMER_EXPIRED）

设计：**组合 + 构造期注入**。引擎的全部共享状态（``_state_machine`` /
``_seq`` / ``_client`` / 收发缓冲 / 回调 / 历史库 …）仍由 ``MasterEngine`` 持有，
本类只持有引擎引用并按需读写，避免子模块反向 ``import`` ``master.py`` 造成
循环依赖（类型仅经 ``TYPE_CHECKING`` 前置引用）。这样测试对引擎实例属性的
替换（如 ``engine._state_machine = MagicMock()``）依然生效，行为零变化。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..protocol.apci import APCI, APCICodec
from ..protocol.state_machine import TimerType
from .master_protocol import MasterEvent

if TYPE_CHECKING:
    from .master import MasterEngine

logger = logging.getLogger("iec104.master")


class MasterSession:
    """主站连接 / 状态 / 帧接收中枢（由 ``MasterEngine`` 组合持有）."""

    def __init__(self, engine: MasterEngine) -> None:
        self._engine = engine

    # ── 连接控制 ──────────────────────────────────────────────────

    async def send_startdt(self) -> None:
        """发送 STARTDT ACT."""
        e = self._engine
        frame = APCICodec.startdt_act()
        await self.send_frame(frame)
        e._state_machine.on_startdt_act_sent()
        logger.info("STARTDT ACT sent")

    async def send_stopdt(self) -> None:
        """发送 STOPDT ACT."""
        e = self._engine
        frame = APCICodec.stopdt_act()
        await self.send_frame(frame)
        # STOPDT ACT 属 U 格式报文，发送后须在 t1 内收到 STOPDT CON
        e._state_machine.on_u_frame_act_sent()
        logger.info("STOPDT ACT sent")

    # ── 发送 ──────────────────────────────────────────────────────

    async def send_frame(self, frame: bytes) -> None:
        """发送帧并记录（回显回调 / 录制 / 缓冲 / 状态机 / 历史库）."""
        e = self._engine
        await e._client.send(frame)

        if e._raw_frame_callback:
            try:
                e._raw_frame_callback(frame, "tx")
            except Exception:
                pass

        # 报文录制
        if e._recorder:
            e._recorder.record_frame(frame, direction="tx")

        e._tx_buffer.append((time.monotonic(), frame))
        e._state_machine.on_any_frame_sent()

        # 记录到历史数据库
        if e._history_db:
            frame_type = APCICodec.frame_type_of(frame)
            e._history_db.record_frame("tx", frame, frame_type=frame_type)

    # ── TCP 事件 ──────────────────────────────────────────────────

    def on_tcp_connected(self) -> None:
        """TCP 连接建立."""
        e = self._engine
        e._state_machine.on_connected()
        e._fire_event(MasterEvent.CONNECTED)

        # 自动发送 STARTDT
        if e._auto_start:
            e._spawn(self.auto_startdt())

    def on_tcp_disconnected(self) -> None:
        """TCP 连接断开."""
        e = self._engine
        e._state_machine.on_disconnected()
        e._fire_event(MasterEvent.DISCONNECTED)

    async def auto_startdt(self) -> None:
        """自动发送 STARTDT."""
        e = self._engine
        await asyncio.sleep(0.2)
        try:
            await e.send_startdt()
        except Exception as exc:
            logger.error(f"Auto STARTDT failed: {exc}")

    # ── 帧接收处理 ────────────────────────────────────────────────

    def on_frame_received(self, frame: bytes) -> None:
        """收到原始帧回调（从TCP层）."""
        e = self._engine
        if e._raw_frame_callback:
            try:
                e._raw_frame_callback(frame, "rx")
            except Exception:
                pass

        # 报文录制
        if e._recorder:
            e._recorder.record_frame(frame, direction="rx")

        e._rx_buffer.append((time.monotonic(), frame))

        # 记录到历史数据库
        if e._history_db:
            frame_type = APCICodec.frame_type_of(frame)
            e._history_db.record_frame("rx", frame, frame_type=frame_type)

        try:
            apci, _ = APCICodec.decode(frame)

            if apci.is_i_frame:
                self.handle_i_frame(apci, frame)
            elif apci.is_s_frame:
                self.handle_s_frame(apci)
            elif apci.is_u_frame:
                self.handle_u_frame(apci)

            e._state_machine.on_any_frame_received()

        except Exception as exc:
            logger.error(f"Frame decode error: {exc}")

    def handle_i_frame(self, apci: APCI, frame: bytes) -> None:
        """处理 I 帧."""
        e = self._engine
        seq_ok = e._seq.process_rx_i_frame(apci.tx_seq)
        if not seq_ok:
            # 标准: 报文丢失/错序意味着 TCP 连接异常，应关闭连接并重建。
            # 主站与子站策略统一：均断开连接。使用 disconnect() 仅重建当前
            # 连接 —— 关闭底层连接后 _connect_loop 会触发 _on_tcp_disconnected
            # (状态机离开 Running + 触发 DISCONNECTED) 并按配置重连；
            # 若用 stop() 会取消重连循环并跳过 on_disconnected 回调。
            logger.error(
                f"Sequence mismatch: expected={e._seq.recv_seq}, "
                f"received={apci.tx_seq}, disconnecting"
            )
            e._spawn(e._client.disconnect())
            return
        # I帧的rx_seq是隐式确认，等效于S帧
        acked = e._seq.process_rx_i_frame_ack(apci.rx_seq)
        # 隐式确认可能释放了发送窗口
        if e._seq.send_window_available:
            e._window_available.set()
        if acked:
            # I 帧的 N(R) 推进 = 对端确认了我方 I 帧 —— 与 S 帧等效地停 t1
            # （标准 §5.3.3：确认既可以是 S 帧，也可以是后续 I 帧的 N(R)）。
            # 只认 S 帧会让「用 N(R) 隐式确认、少发 S 帧」的合规设备误判 t1 超时
            # （simulator4 真机联调实测：对端以命令回显应答、t1 仍超时断链）。
            e._state_machine.on_ack_received()

        # 切换窗口去重（T21）：序列号消费与确认在上面已照常完成，此处仅
        # 抑制应用层重复（同一 ASDU 在主备切换窗口内经两条链路重复送达时
        # 不重复入库/上事件）。传输层绝不丢 I 帧——丢帧会让 VR 失步。
        asdu_data = frame[6:6 + apci.asdu_length]
        if e._redundancy is not None and e._redundancy.is_duplicate_asdu(asdu_data):
            logger.info(
                "丢弃切换窗口内重复 ASDU（%d 字节，I 帧已按正常确认）",
                len(asdu_data),
            )
            e._state_machine.on_i_frame_received()
            return

        e._protocol.decode_and_dispatch(asdu_data)

        e._state_machine.on_i_frame_received()

    def handle_s_frame(self, apci: APCI) -> None:
        """处理 S 帧."""
        e = self._engine
        e._seq.process_rx_s_frame(apci.rx_seq)
        # S帧确认释放了发送窗口
        if e._seq.send_window_available:
            e._window_available.set()
        e._state_machine.on_ack_received()
        logger.debug(f"S-Frame: rx_seq={apci.rx_seq}")

    def handle_u_frame(self, apci: APCI) -> None:
        """处理 U 帧."""
        e = self._engine
        if apci.is_startdt_con:
            e._state_machine.on_startdt_con()
            e._seq.process_rx_u_frame_startdt_con()
            logger.info("STARTDT CON received")
            e._fire_event(MasterEvent.STARTED)

            # 自动总召唤
            if e._auto_gi:
                e._spawn(self.auto_general_interrogation())

            # WP11a：建链后自动时钟同步（默认关闭，行为与 v1.10.0 一致；
            # 显式开启时在 STARTDT CON 后发 C_CS_NA_1）。
            if getattr(e, "_auto_clock_sync", False):
                e._spawn(e.clock_sync())

            # 周期总召唤（对"只在总召时才回遥测"的装置是必要手段）
            if e._gi_interval > 0 and not e._periodic_gi_task:
                e._periodic_gi_task = e._spawn(self.periodic_gi_loop())

        elif apci.is_stopdt_con:
            e._state_machine.on_stopdt_con()
            logger.info("STOPDT CON received")

        elif apci.is_testfr_act:
            # 回复 TESTFR CON
            e._spawn(self.send_frame(APCICodec.testfr_con()))
            e._state_machine.on_testfr_act_received()
            logger.debug("TESTFR ACT received, CON sent")

        elif apci.is_testfr_con:
            e._state_machine.on_ack_received()
            logger.debug("TESTFR CON received")

    async def auto_general_interrogation(self) -> None:
        """自动总召唤（连接建立后）."""
        e = self._engine
        await asyncio.sleep(0.5)  # 短暂延迟
        try:
            await e.general_interrogation()
        except Exception as exc:
            logger.error(f"Auto GI failed: {exc}")

    async def periodic_gi_loop(self) -> None:
        """周期总召唤循环（``gi_interval > 0`` 时启用）.

        部分真机**从不自发上送遥测**，只在收到总召唤时回数据（实测：静默
        70s 内零遥测帧）。这类装置只能靠周期总召刷新遥测值。
        仅在 Running 状态召唤；异常不影响连接。
        """
        e = self._engine
        try:
            while e._gi_interval > 0:
                await asyncio.sleep(e._gi_interval)
                if not e._state_machine.is_running:
                    continue
                try:
                    logger.info(f"Periodic GI (interval={e._gi_interval}s)")
                    await e.general_interrogation()
                except Exception as exc:
                    logger.warning(f"Periodic GI failed: {exc}")
        except asyncio.CancelledError:
            raise
        finally:
            e._periodic_gi_task = None

    async def regi_after_init(self) -> None:
        """收到初始化结束(M_EI_NA_1, COT=4)后的自动重总召唤.

        装置重启后原实时数据可能已失效，标准要求主站重新召唤；
        延迟 2s 等待装置完成初始化收尾（部分真机对连接初期的 I 帧敏感），
        失败不影响连接（t1 超时会按标准断开并自动重连）。
        """
        e = self._engine
        await asyncio.sleep(2.0)
        try:
            if e._state_machine.is_running:
                logger.info("Auto re-GI after End of Initialization")
                await e.general_interrogation()
        except Exception as exc:
            logger.warning(f"Auto re-GI after init failed: {exc}")

    # ── 状态与定时器 ──────────────────────────────────────────────

    def on_state_change(self, old_state: str, new_state: str) -> None:
        logger.info(f"State: {old_state} → {new_state}")

    def on_timer_expired(self, timer_type: TimerType) -> None:
        e = self._engine
        logger.warning(f"Timer expired: {timer_type}")
        e._fire_event(MasterEvent.TIMER_EXPIRED, {"timer": timer_type})

        if timer_type == TimerType.T0:
            # 连接超时：仅重建当前连接，保留重连循环（stop() 会取消重连）
            e._spawn(e._client.disconnect())
        elif timer_type == TimerType.T1:
            # 发送超时 - 根据规范应断开连接。
            # 必须用 disconnect() 而非 stop()：stop() 会取消重连循环且跳过
            # on_disconnected 回调，导致 t1 超时后永久停在 Stopped（真机实测：
            # 对未知 IOA 的读命令，设备不回 ACK → t1 超时 → 再也不重连）。
            logger.error("T1 timeout: no confirmation received, disconnecting")
            e._spawn(e._client.disconnect())
        elif timer_type == TimerType.T2:
            # 无数据确认超时 — 发送S帧确认已收到的I帧
            rx_seq = e._seq.get_recv_seq()
            frame = APCICodec.encode_s(rx_seq)
            e._spawn(self.send_frame(frame))
            e._state_machine.on_s_frame_sent()
            logger.info(f"T2 expired: S-Frame sent (rx_seq={rx_seq})")
        elif timer_type == TimerType.T3:
            # 空闲超时，发送测试帧 — U 帧 ACT，发送后须在 t1 内收到 TESTFR CON
            e._spawn(self.send_frame(APCICodec.testfr_act()))
            e._state_machine.on_u_frame_act_sent()

    async def timer_loop(self) -> None:
        """定时器检查循环."""
        e = self._engine
        while True:
            try:
                expired = e._state_machine.check_timers()
                if expired:
                    self.on_timer_expired(expired)
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Timer loop error: {exc}")
