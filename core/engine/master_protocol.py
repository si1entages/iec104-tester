"""主站协议处理器 — I 帧 ASDU 解析、分发与文件传输.

从 ``core/engine/master_protocol.py`` 保留的**接收侧**行为（控制/参数命令构建已
抽至 ``core/engine/master_commands.py``）：

- I 帧 ASDU 解码分发（``decode_and_dispatch``）与总入口 ``process_asdu``
- 各类遥信/遥测/累计量/保护事件/命令确认的解析与入库
- 标准 COT 42/43/44 错误应答的优雅处理
- 点位自学习（定义表自动补点）
- 文件传输（召唤目录/选择/请求/确认命令的构建下发 + ``process_file_transfer``
  与文件事件回调）——收发两侧内聚，故置于本模块

设计：**组合 + 构造期注入**。引擎的全部共享状态（``_state_machine`` /
``_point_table`` / ``_data_store`` / ``_history_db`` …）仍由 ``MasterEngine``
持有，本类只持有引擎引用并按需读写，避免子模块反向 ``import`` ``master.py``
造成循环依赖（类型仅经 ``TYPE_CHECKING`` 前置引用）。

``MasterEvent`` 事件枚举定义在本模块：会话层与命令层都需要它，而本模块不反向
依赖它们，故由其承载并由 ``master.py`` 再导出
（``from core.engine.master import MasterEvent`` 保持兼容）。
"""

from __future__ import annotations

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
from ..protocol.file_transfer import (
    AFQ_NEG_ACK_FILE,
    AFQ_NEG_ACK_SECTION,
    AFQ_NOT_USED,
    AFQ_POS_ACK_FILE,
    AFQ_POS_ACK_SECTION,
    SCQ_REQUEST_DIRECTORY,
    SCQ_REQUEST_FILE,
    SCQ_SELECT_FILE,
    FileTransferState,
)
from ..protocol.types import (
    COT,
    BitString32,
    CounterValue,
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

    # ── 文件传输命令 ──────────────────────────────────────────────

    async def file_call_directory(self, ioa: int = 0) -> None:
        """发送召唤目录命令 (F_SC_NA_1).

        Args:
            ioa: 信息对象地址
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_call_directory(
            e._common_addr, ioa, qualifier=SCQ_REQUEST_DIRECTORY
        )
        # SCQ_REQUEST_DIRECTORY=5 是**项目约定值**（标准表中 5=SELECT_SECTION）：
        # 主站发 5 → 子站 handle_file_request 按约定回目录，本仓库内闭环；
        # 该组合与标准表可能冲突，待真机核实（见 docs/file_transfer_fls.md §4.4）。
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
            e._common_addr, ioa, file_name, qualifier=SCQ_SELECT_FILE
        )
        # SCQ_SELECT_FILE=1（曾用魔法数字 4——SCQ 表修正后 4=DELETE_FILE，
        # "选择文件"会变成向真机发删除命令，故一律改用带名常量）。
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
            e._common_addr, ioa, file_name, qualifier=SCQ_REQUEST_FILE
        )
        # SCQ_REQUEST_FILE=2（曾用魔法数字 1——新表中 1=SELECT_FILE，语义静默翻转）。
        await e._send_command_asdu(asdu_data)
        logger.info(f"File Request: file_name={file_name}")

    async def file_ack(self, ioa: int, file_name: int,
                        section_name: int = 0, qualifier: int = AFQ_POS_ACK_FILE) -> None:
        """发送文件/节确认命令 (F_AF_NA_1).

        Args:
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
            section_name: 节名 (8-bit)
            qualifier: AFQ — 见 ``file_transfer.AFQ_*`` 常量
                (0=未用, 1=肯定文件, 2=否定文件, 3=肯定节, 4=否定节)
        """
        e = self._engine
        asdu_data = ASDUBuilder.build_ack_file_section(
            e._common_addr, ioa, file_name, section_name, qualifier
        )
        await e._send_command_asdu(asdu_data)
        qual_str = {
            AFQ_NOT_USED: "缺省",
            AFQ_POS_ACK_FILE: "肯定文件",
            AFQ_NEG_ACK_FILE: "否定文件",
            AFQ_POS_ACK_SECTION: "肯定节",
            AFQ_NEG_ACK_SECTION: "否定节",
        }.get(qualifier, f"未知({qualifier})")
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
        await e._await_send_window()
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
                e._spawn(e._session.regi_after_init())

        # 参数命令确认（装载/激活结果跟踪，见 process_parameter_ack）
        elif type_id in (TypeID.P_ME_NA_1, TypeID.P_ME_NB_1, TypeID.P_ME_NC_1,
                          TypeID.P_ME_ND_1, TypeID.P_AC_NA_1):
            self.process_parameter_ack(asdu)

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
            e._file_transfer.send_ack(obj.ioa, qualifier=AFQ_POS_ACK_SECTION)
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

    def process_parameter_ack(self, asdu: ASDU) -> None:
        """处理参数命令应答 (P_ME_*/P_AC_NA_1)，跟踪装载 / 激活结果.

        主站侧需区分并记录：激活确认 (ACTCON)、激活终止 (ACTTERM)、
        否定确认 (PN=1)、以及应答超时未回（超时由 ``MasterEngine`` 侧与 SBO
        同一机制的应答等待判定并写入状态）。

        - P_ME_NA_1 / P_ME_NB_1 / P_ME_NC_1 / P_ME_ND_1 → 记入 ``load`` 维度
        - P_AC_NA_1 → 记入 ``activation`` 维度
        """
        e = self._engine
        cot = asdu.cot
        pn = asdu.pn
        kind = "activation" if asdu.type_id == TypeID.P_AC_NA_1 else "load"
        for obj in asdu.objects:
            logger.info(
                f"Parameter Command ACK: type={asdu.type_id} IOA={obj.ioa} "
                f"COT={cot} pn={pn}"
            )
            e._record_parameter_ack(obj.ioa, kind, cot, pn)
        if not asdu.objects:
            logger.info(f"Parameter Command ACK: type={asdu.type_id} COT={cot} (no objects)")

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
