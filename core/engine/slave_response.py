"""子站应答构建层 — 品质 / 传送原因 / 应答 ASDU 与各类请求处理.

从 ``core/engine/slave.py`` 抽出的"应答"职责：

- 品质描述词注入 (``_apply_quality``) 与应答传送原因注入 (``_reply_cot``)
- 错误注入：丢帧判定 (``_maybe_drop_frame``)、命令延时 (``_apply_command_delay``)
- 标准错误应答 (COT 42/43/44)、初始化结束报文、命令确认样板 (``_build_command_ack``)
- 总召唤 / 组召唤 / 累计量召唤、时钟同步、读命令、复位进程、测试命令、
  参数命令、比特串命令、延时获得、文件传输等**无状态请求**的处理与应答

设计：**组合 + 构造期注入**。引擎全部共享状态（``_common_addr`` /
``_response_behavior`` / ``_point_table`` / ``_data_store`` / ``_file_transfer`` …）
仍由 ``SlaveEngine`` 持有，本类只持有引擎引用并按需读写；类型仅经
``TYPE_CHECKING`` 前置引用，避免反向 import 造成循环依赖。这样测试对引擎实例
属性的替换依旧生效，行为零变化。

本模块还定义 ``SlaveEvent`` / ``ResponseBehavior`` / ``_split_contiguous``，
由 ``slave.py`` 重新导出以兼容既有导入路径。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from ..data.point_table import YxType
from ..protocol.asdu import ASDU, ASDUBuilder, InformationObject
from ..protocol.types import (
    COT,
    AckFileSection,
    BitString32Command,
    CallDirectory,
    CP56Time2a,
    DoublePoint,
    FileReadyAck,
    FileSegment,
    FileSelectCallGet,
    LastSection,
    QualityDescriptor,
    QualityFlag,
    SectionReadyAck,
    TypeID,
)

if TYPE_CHECKING:
    from .slave import SlaveEngine
    from .slave_session import _ClientState

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
    force_substituted: bool = False
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
            force_substituted=bool(quality.get("substituted", False)),
            force_not_topical=bool(quality.get("not_topical", False)),
            force_overflow=bool(quality.get("overflow", False)),
            reject_startdt=bool(conn.get("reject_startdt", False)),
            auto_stopdt=bool(conn.get("auto_stopdt", False)),
            send_testfr=bool(conn.get("send_testfr", False)),
            testfr_interval=float(conn.get("testfr_interval", 20) or 20),
        )

    def quality_mask(self) -> int:
        """合并品质描述词位（IEC 60870-5-101：IV=0x80, NT=0x40, SB=0x20, BL=0x10, OV=0x01）."""
        mask = 0
        if self.force_invalid:
            mask |= QualityFlag.IV
        if self.force_not_topical:
            mask |= QualityFlag.NT
        if self.force_blocked:
            mask |= QualityFlag.BL
        if self.force_substituted:
            mask |= QualityFlag.SB
        if self.force_overflow:
            mask |= QualityFlag.OV
        return int(mask)

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


class SlaveResponseBuilder:
    """子站应答构建器（由 ``SlaveEngine`` 组合持有）."""

    def __init__(self, engine: SlaveEngine) -> None:
        self._engine = engine

    # ── 品质 / COT / 错误注入 ─────────────────────────────────────

    def _apply_quality(self, quality: int) -> int:
        """按配置强制注入品质位。"""
        e = self._engine
        mask = e._response_behavior.quality_mask()
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
        e = self._engine
        if not e._response_behavior.wrong_cot:
            return int(cot)
        return (int(cot) + e._WRONG_COT_OFFSET) & 0x3F

    def _maybe_drop_frame(self) -> bool:
        """按配置决定是否丢弃当前发送帧。"""
        rb = self._engine._response_behavior
        if not rb.drop_frames:
            return False
        rate = max(0.0, min(1.0, rb.drop_rate))
        if rate <= 0:
            return True
        return random.random() < rate

    async def _apply_command_delay(self) -> None:
        delay = self._engine._response_behavior.command_delay
        if delay > 0:
            await asyncio.sleep(delay)

    # ── 标准错误应答 ──────────────────────────────────────────────

    async def _send_standard_error(self, state: _ClientState, type_id: Any,
                                   cot: int, common_addr: int) -> None:
        """按标准回送错误应答 (COT=42/43/44).

        ASDU 仅含头部（无信息体），携带原类型标识与公共地址，保持连接不中断。
        标准依据: IEC 60870-5-104 Table 1-72 (COT 42/43/44)。
        """
        e = self._engine
        ack = ASDU(
            type_id=type_id,
            sq=False, num=0, cot=cot, common_addr=common_addr,
        )
        await e._send_i_frame(state, ack.encode())
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
        e = self._engine
        ack_asdu = ASDU(
            type_id=type_id, sq=False, num=1,
            cot=self._reply_cot(cot), pn=pn, common_addr=e._common_addr,
        )
        ack_asdu.objects.append(obj)
        return ack_asdu.encode()

    # ── 总召唤 / 累计量召唤 ───────────────────────────────────────

    async def _handle_interrogation(self, state: _ClientState, asdu: ASDU) -> None:
        """处理总召唤."""
        e = self._engine
        if e._response_behavior.gi_delay > 0:
            await asyncio.sleep(e._response_behavior.gi_delay)

        qoi = 20
        if asdu.objects:
            qoi = asdu.objects[0].data[0] if isinstance(asdu.objects[0].data, bytes) else 20

        logger.info(f"Interrogation from {state.conn.name}: QOI={qoi}")

        # 发送激活确认
        ack = ASDUBuilder.build_general_interrogation_ack(
            e._common_addr, qoi, cot=self._reply_cot(COT.ACTCON)
        )
        await e._send_i_frame(state, ack)

        # 发送所有数据
        await self._send_interrogation_data(state, qoi)

        # 发送激活结束
        term = ASDUBuilder.build_general_interrogation_end(
            e._common_addr, qoi, cot=self._reply_cot(COT.ACTTERM)
        )
        await e._send_i_frame(state, term)

        e._fire_event(SlaveEvent.GI_RECEIVED, {
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
        e = self._engine
        group = COT.get_group_number(qoi) if COT.is_group_response(qoi) else None
        cot = self._reply_cot(
            COT.INTROGEN if group is None else COT.group_response(group)
        )

        # IEC 104 限制: VSQ 低7位最大127，APDU最大253字节
        # 实际安全批次大小（考虑APDU长度限制）— 使用类属性常量

        # ── 遥信打包发送（单点/双点按**点表声明**分流，每点只上送一次）──
        yx_points = e._point_table.get_all_yx()
        if group is not None:
            yx_points = e._point_table.get_yx_by_group(group)

        yx_batch = []
        dp_batch = []
        for p in yx_points:
            if not p.enabled:
                continue
            yx_data = e._data_store.get_yx(p.ioa)
            if yx_data is None:
                continue
            quality = self._apply_quality(yx_data.quality.to_int())
            if p.point_type == YxType.DOUBLE:
                # 双点状态 0/1/2/3 均为合法取值（1=分, 2=合, 0/3=非确定态），
                # 必须原样上送 —— 用真值判断（`if yx_data.double_state`）会漏掉状态 0
                dp_batch.append((p.ioa, int(yx_data.double_state), quality))
            else:
                yx_batch.append((p.ioa, yx_data.value, quality))

        for chunk in _split_contiguous(yx_batch, e._MAX_SP_PER_FRAME):
            asdu_data = ASDUBuilder.build_single_point_sequence(
                e._common_addr, chunk, cot=cot
            )
            await e._send_i_frame(state, asdu_data)

        # ── 双点遥信打包发送 ──
        for chunk in _split_contiguous(dp_batch, e._MAX_DP_PER_FRAME):
            # 使用ASDUBuilder构建双点遥信序列
            asdu = ASDU(
                type_id=TypeID.M_DP_NA_1,
                sq=True,
                num=len(chunk),
                cot=cot,
                common_addr=e._common_addr,
            )
            for ioa, value, quality in chunk:
                dp = DoublePoint(value=value, quality=QualityDescriptor(quality))
                asdu.objects.append(InformationObject(ioa=ioa, data=dp))
            await e._send_i_frame(state, asdu.encode())

        # ── 遥测打包发送 ──
        yc_points = e._point_table.get_all_yc()
        if group is not None:
            yc_points = e._point_table.get_yc_by_group(group)

        yc_batch = []
        for p in yc_points:
            if not p.enabled:
                continue
            yc_data = e._data_store.get_yc(p.ioa)
            if yc_data:
                yc_batch.append((p.ioa, yc_data.value,
                                 self._apply_quality(yc_data.quality.to_int())))

        for chunk in _split_contiguous(yc_batch, e._MAX_MV_PER_FRAME):
            asdu_data = ASDUBuilder.build_short_float_sequence(
                e._common_addr, chunk, cot=cot
            )
            await e._send_i_frame(state, asdu_data)

        # ── 累计量打包发送 ──
        ym_points = e._point_table.get_all_ym()
        if group is not None:
            ym_points = (e._point_table.get_ym_by_group(group)
                         if hasattr(e._point_table, 'get_ym_by_group') else [])

        ym_batch = []
        for p in ym_points:
            if not p.enabled:
                continue
            ym_data = e._data_store.get_ym(p.ioa)
            if ym_data:
                ym_batch.append((p.ioa, ym_data.value, ym_data.quality.to_int(), 0))

        for chunk in _split_contiguous(ym_batch, e._MAX_IT_PER_FRAME):
            asdu_data = ASDUBuilder.build_counter_sequence(
                e._common_addr, chunk, cot=cot
            )
            await e._send_i_frame(state, asdu_data)

    async def _handle_counter_interrogation(self, state: _ClientState,
                                            asdu: ASDU) -> None:
        """处理累计量召唤."""
        e = self._engine
        qcc = asdu.objects[0].data[0] if asdu.objects else 0
        logger.info(f"Counter Interrogation from {state.conn.name}: QCC={qcc}")

        # 确认
        asdu_ack = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=self._reply_cot(COT.ACTCON), common_addr=e._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await e._send_i_frame(state, asdu_ack.encode())

        # 根据 qcc 组号确定标准响应 COT:
        #   组号 0 → 37 (累计量总请求); 组号 1-4 → 38-41 (第1-4组请求)
        group = qcc & 0x07
        if 1 <= group <= 4:
            cot = self._reply_cot(COT.counter_group_response(group))
        else:
            cot = self._reply_cot(COT.COUNTER_REQ)

        # 发送电度数据 - 使用正确的类型 M_IT_NA_1 (累计量)

        ym_batch = []
        for p in e._point_table.get_all_ym():
            if not p.enabled:
                continue
            ym_data = e._data_store.get_ym(p.ioa)
            if ym_data:
                ym_batch.append((p.ioa, ym_data.value, ym_data.quality.to_int(), 0))

        # 分批打包发送（SQ=1 要求帧内 IOA 连续）
        for chunk in _split_contiguous(ym_batch, e._MAX_IT_PER_FRAME):
            asdu_data = ASDUBuilder.build_counter_sequence(
                e._common_addr, chunk, cot=cot
            )
            await e._send_i_frame(state, asdu_data)

        # 结束
        asdu_term = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=self._reply_cot(COT.ACTTERM), common_addr=e._common_addr,
        )
        asdu_term.objects.append(asdu.objects[0])
        await e._send_i_frame(state, asdu_term.encode())

    # ── 时钟同步 / 读命令 / 复位 / 测试 / 延时 ────────────────────

    async def _handle_clock_sync(self, state: _ClientState, asdu: ASDU) -> None:
        """处理时钟同步."""
        e = self._engine
        await self._apply_command_delay()
        logger.info(f"Clock Sync from {state.conn.name}")

        # 回复确认（IEC 60870-5-104：确认帧携带**子站当前时钟**，
        # 主站据此测量时钟偏差——曾错误回显主站发来的时间，偏差无法测量）
        ack = ASDUBuilder.build_clock_sync_ack(
            e._common_addr, time_tag=CP56Time2a.now(),
            cot=self._reply_cot(COT.ACTCON),
        )
        await e._send_i_frame(state, ack)

        e._fire_event(SlaveEvent.CLOCK_SYNC_RECEIVED, {
            "client_id": state.conn.name
        })

    async def _handle_read_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理读命令."""
        e = self._engine
        await self._apply_command_delay()
        if not asdu.objects:
            return
        ioa = asdu.objects[0].ioa
        logger.info(f"Read Command from {state.conn.name}: IOA={ioa}")

        # 查找并返回对应数据
        yx = e._data_store.get_yx(ioa)
        if yx:
            asdu_data = ASDUBuilder.build_single_point(
                e._common_addr, ioa, yx.value,
                yx.quality.to_int(), cot=COT.REQ
            )
            await e._send_i_frame(state, asdu_data)
            return

        yc = e._data_store.get_yc(ioa)
        if yc:
            asdu_data = ASDUBuilder.build_short_float(
                e._common_addr, ioa, yc.value,
                yc.quality.to_int(), cot=COT.REQ
            )
            await e._send_i_frame(state, asdu_data)
            return

        ym = e._data_store.get_ym(ioa)
        if ym:
            asdu_data = ASDUBuilder.build_counter_value(
                e._common_addr, ioa, ym.value,
                ym.quality.to_int(), cot=COT.REQ
            )
            await e._send_i_frame(state, asdu_data)
            return

        # 点表无此 IOA：按标准回送 COT=45（未知信息对象地址），而不是静默丢弃
        logger.info(f"Read Command for unknown IOA={ioa} → reply COT=45")
        await self._send_standard_error(state, asdu.type_id, COT.UNKNOWN_IOA,
                                        e._common_addr)

    async def _handle_reset_process(self, state: _ClientState, asdu: ASDU) -> None:
        """处理复位进程."""
        e = self._engine
        logger.info(f"Reset Process from {state.conn.name}")
        # 确认（回送 ACTCON + 原对象）
        asdu_ack = ASDU(
            type_id=TypeID.C_RP_NA_1, sq=False, num=1,
            cot=COT.ACTCON, common_addr=e._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await e._send_i_frame(state, asdu_ack.encode())

    async def _handle_test_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理测试命令.

        按标准回显 T 试验位（COT bit7）：主站以 T=1 下发测试命令时，应答必须同样置位，
        否则一致性测试会判为未正确响应试验报文。
        """
        e = self._engine
        logger.info(f"Test Command from {state.conn.name} (T={int(asdu.test)})")
        asdu_ack = ASDU(
            type_id=asdu.type_id, sq=False, num=1,
            cot=COT.ACTCON, test=asdu.test, common_addr=e._common_addr,
        )
        asdu_ack.objects.append(asdu.objects[0])
        await e._send_i_frame(state, asdu_ack.encode())

    async def _handle_bitstring_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理比特串命令."""
        e = self._engine
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        cmd: BitString32Command = obj.data
        logger.info(f"Bitstring Command from {state.conn.name}: "
                    f"IOA={obj.ioa} value=0x{cmd.value:08X}")
        if asdu.cot == COT.ACT:
            # 比特串命令通常不需要选择-执行流程
            await e._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTCON, obj))

            # 发送激活终止
            await e._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.ACTTERM, obj))
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            # 回复停止激活确认
            await e._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Bitstring Command DEACTCON: IOA={obj.ioa}")

    async def _handle_delay_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理延时获得命令 (C_CD_NA_1).

        真机语义：主站在命令中给出期望延时，子站**按该延时**推迟应答并回显实际延时
        （原实现固定回 100ms 示例值，与请求无关）。
        """
        e = self._engine
        logger.info(f"Delay Command from {state.conn.name}")
        if asdu.cot == COT.ACT and asdu.objects:
            data = asdu.objects[0].data
            requested = int(getattr(data, "delay_ms", 0) or 0)
            applied = max(0, min(requested, e._MAX_DELAY_MS))
            if applied:
                await asyncio.sleep(applied / 1000.0)
            asdu_data = ASDUBuilder.build_delay_command(e._common_addr, applied)
            await e._send_i_frame(state, asdu_data)
            logger.info(f"Delay Response sent: requested={requested}ms applied={applied}ms")

    async def _handle_parameter_command(self, state: _ClientState, asdu: ASDU) -> None:
        """处理参数命令.

        标准流程:
          - P_ME_NA_1/NB_1/NC_1/ND_1 (参数装载): ACT → ACTCON
          - P_AC_NA_1 (参数激活):             ACT → ACTCON → ACTTERM
        未装载直接激活时回否定确认 (COT bit6 P/N=1)。
        """
        e = self._engine
        if not asdu.objects:
            return
        obj = asdu.objects[0]
        logger.info(f"Parameter Command from {state.conn.name}: "
                    f"type={asdu.type_id} IOA={obj.ioa}")
        if asdu.cot == COT.ACT:
            if asdu.type_id == TypeID.P_AC_NA_1:
                qualifier = getattr(obj.data, "qualifier", 0)
                if qualifier == 1 and obj.ioa not in state.loaded_parameters:
                    # 激活但尚未装载 → 否定确认
                    await e._send_i_frame(
                        state,
                        self._build_command_ack(asdu.type_id, COT.ACTCON, obj, pn=True),
                    )
                    logger.warning(
                        f"Parameter Activation REJECTED (not loaded): IOA={obj.ioa}"
                    )
                else:
                    await e._send_i_frame(
                        state,
                        self._build_command_ack(asdu.type_id, COT.ACTCON, obj),
                    )
                    await e._send_i_frame(
                        state,
                        self._build_command_ack(asdu.type_id, COT.ACTTERM, obj),
                    )
                    logger.info(f"Parameter Activation: IOA={obj.ioa} qualifier={qualifier}")
            else:
                # 参数装载 (P_ME_*): 记录已装载参数并回 ACTCON
                state.loaded_parameters.add(obj.ioa)
                await e._send_i_frame(
                    state,
                    self._build_command_ack(asdu.type_id, COT.ACTCON, obj),
                )
        elif asdu.cot == COT.DEACT:
            # 停止激活：取消选择状态并移除已装载记录
            if obj.ioa in state.selected_commands:
                del state.selected_commands[obj.ioa]
            state.loaded_parameters.discard(obj.ioa)
            # 回复停止激活确认
            await e._send_i_frame(state, self._build_command_ack(asdu.type_id, COT.DEACTCON, obj))
            logger.info(f"Parameter Command DEACTCON: IOA={obj.ioa}")

    # ── 文件传输 ──────────────────────────────────────────────────

    async def _handle_file_transfer(self, state: _ClientState, asdu: ASDU) -> None:
        """处理文件传输."""
        e = self._engine
        type_id = asdu.type_id
        cot = asdu.cot
        logger.info(f"File Transfer from {state.conn.name}: type={type_id}, cot={cot}")

        if not asdu.objects:
            return

        obj = asdu.objects[0]

        # 召唤目录
        if type_id == TypeID.F_SC_NA_1 and cot in (COT.ACT, COT.FILE):
            if isinstance(obj.data, CallDirectory):
                e._file_transfer.handle_file_request(obj.ioa, obj.data.file_name, obj.data.qualifier)

        # 文件选择/召唤/获取
        elif type_id == TypeID.F_SC_NB_1 and cot in (COT.ACT, COT.FILE):
            if isinstance(obj.data, FileSelectCallGet):
                e._file_transfer.handle_file_request(obj.ioa, obj.data.file_name, obj.data.qualifier)

        # 文件准备就绪确认
        elif type_id == TypeID.F_FR_NB_1:
            if isinstance(obj.data, FileReadyAck):
                e._file_transfer.handle_file_ready_ack(obj.ioa, obj.data)

        # 节准备就绪确认
        elif type_id == TypeID.F_SR_NB_1:
            if isinstance(obj.data, SectionReadyAck):
                e._file_transfer.handle_section_ready_ack(obj.ioa, obj.data)

        # 确认文件/节
        elif type_id == TypeID.F_AF_NA_1:
            if isinstance(obj.data, AckFileSection):
                e._file_transfer.handle_ack(obj.ioa, obj.data)

        # 段
        elif type_id == TypeID.F_SG_NA_1:
            if isinstance(obj.data, FileSegment):
                e._file_transfer.handle_file_segment(obj.data)

        # 最后的节/段
        elif type_id == TypeID.F_LS_NA_1:
            if isinstance(obj.data, LastSection):
                e._file_transfer.handle_last_section(obj.data)

        else:
            logger.debug(f"Unhandled file transfer type: {type_id}")
