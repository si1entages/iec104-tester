"""文件传输管理器 — IEC 60870-5-104 文件传输协议实现.

实现完整的文件传输流程：
- 文件选择 → 文件准备就绪 → 节准备就绪 → 段传输 → 最后的节 → 确认

F_LS_NA_1 八位组语义已按参考实现核实，见 ``docs/file_transfer_fls.md``：
信息体 = ``NOF(2, LE) | NOS(1) | LSQ(1) | CHS(1)``（不含 IOA，共 5 字节），
LSQ 取值 0-4 见下方 ``LSQ_*`` 常量。**仅 LSQ=1/2（文件传输结束）判定接收完成**。
"""

from __future__ import annotations

import enum
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .types import (
    LSQ_NAMES,
    AckFileSection,
    DirectoryEntry,
    FileReady,
    FileReadyAck,
    FileSegment,
    LastSection,
    SectionReady,
    SectionReadyAck,
)

logger = logging.getLogger("iec104.file_transfer")

# ── F_LS_NA_1 的 LSQ（Last Section or Segment Qualifier）取值 ─────────
#
# 依据（已核实，见 docs/file_transfer_fls.md）：lib60870.NET（mz-automation）
# ``CS101/FileObjects.cs`` 的 ``LastSectionOrSegmentQualifier`` 枚举。
LSQ_NOT_USED = 0                        # 未使用（目录结束标记即用此值）
LSQ_FILE_TRANSFER_WITHOUT_DEACT = 1     # 整个文件传输的最后一节，不要求去激活
LSQ_FILE_TRANSFER_WITH_DEACT = 2        # 整个文件传输的最后一节，要求去激活
LSQ_SECTION_TRANSFER_WITHOUT_DEACT = 3  # 仅本节传输结束（文件未结束），不要求去激活
LSQ_SECTION_TRANSFER_WITH_DEACT = 4     # 仅本节传输结束（文件未结束），要求去激活

# ── F_SC_NA_1 / F_SC_NB_1 的 SCQ（Select and Call Qualifier）取值 ─────
#
# 依据：lib60870.NET ``enum SelectAndCallQualifier`` + go-iecp5 ``FileCallOrSelect``
# （两个互相独立的字节级实现取值一致）。
SCQ_SELECT_FILE = 1        # 选择文件
SCQ_REQUEST_FILE = 2       # 请求文件
SCQ_DEACTIVATE_FILE = 3    # 去激活文件
SCQ_DELETE_FILE = 4        # 删除文件（**不是**"选择文件"，见 docs/file_transfer_fls.md §5.3）
SCQ_SELECT_SECTION = 5     # 选择节
SCQ_REQUEST_SECTION = 6    # 请求节
SCQ_DEACTIVATE_SECTION = 7  # 去激活节

# ── F_AF_NA_1 的 AFQ（Acknowledge Qualifier）取值 ─────────────────────
#
# 依据：lib60870.NET ``enum AcknowledgeQualifier``（与 docs/file_transfer_fls.md §2.4 一致）。
AFQ_NOT_USED = 0           # 未用
AFQ_POS_ACK_FILE = 1       # 肯定文件
AFQ_NEG_ACK_FILE = 2       # 否定文件
AFQ_POS_ACK_SECTION = 3    # 肯定节
AFQ_NEG_ACK_SECTION = 4    # 否定节

#: 请求目录在本实现中暂用的 SCQ 值。**未核实**：标准 SCQ=5 为 SELECT_SECTION，
#: 且参考实现以 COT=REQUEST 触发目录召唤（见 docs/file_transfer_fls.md §4.4）。
#: 本实现暂沿用 5 触发目录上送——该组合保持开放，未按标准推断。
SCQ_REQUEST_DIRECTORY = 5

#: F_LS_NA_1 的 CHS = 本节所有段数据的**算术和 mod 256**。
#: 依据（两个互相独立的字节级实现一致）：lib60870-C ``file_server.c::calculateChecksum``
#: （``checksum += data[i]``，uint8 溢出即 mod 256）与 go-iecp5 ``docs/filetransfer.md``
#: （「该节所有段八位组的算术和 mod 256」）。**非标准原文**，故接收侧校验不通过时
#: 仅记告警、不丢弃数据（见 ``FileTransferManager.handle_last_section``）。
CHECKSUM_MODULUS = 256


def section_checksum(data: bytes) -> int:
    """计算一节（或整个单节文件）的 CHS：所有段数据八位组的算术和 mod 256."""
    return sum(data) % CHECKSUM_MODULUS

#: LSQ 值 → 名称（唯一出处 `core.protocol.types.LSQ_NAMES`，供日志复用）
_LSQ_NAMES = LSQ_NAMES
#: 表示**整个文件传输结束**的 LSQ（此时才可判定接收完成）
LSQ_FILE_COMPLETE = (LSQ_FILE_TRANSFER_WITHOUT_DEACT, LSQ_FILE_TRANSFER_WITH_DEACT)
#: 表示**仅当前节结束**的 LSQ（文件未结束，可能还有后续节）
LSQ_SECTION_COMPLETE = (
    LSQ_SECTION_TRANSFER_WITHOUT_DEACT,
    LSQ_SECTION_TRANSFER_WITH_DEACT,
)


class FileTransferState(enum.Enum):
    """文件传输状态."""
    IDLE = "idle"                    # 空闲
    FILE_SELECTED = "file_selected"  # 文件已选择
    FILE_READY = "file_ready"        # 文件准备就绪
    SECTION_READY = "section_ready"  # 节准备就绪
    TRANSFERRING = "transferring"    # 传输中
    LAST_SECTION = "last_section"    # 最后的节
    COMPLETED = "completed"          # 完成
    ERROR = "error"                  # 错误


class FileTransferDirection(enum.Enum):
    """文件传输方向."""
    DOWNLOAD = "download"  # 主站→子站
    UPLOAD = "upload"      # 子站→主站


@dataclass
class FileTransferContext:
    """文件传输上下文."""
    file_name: int = 0
    file_length: int = 0
    section_name: int = 0
    section_length: int = 0
    segment_number: int = 0  # 已收/已发的段计数（F_SG 无段号字段，仅作计数）
    #: 最近一次 F_LS_NA_1 的 LSQ 值（0-4，见模块顶部 ``LSQ_*`` 常量）。
    #: 注意：标准中 F_LS_NA_1 的信息体为 ``NOF|NOS|LSQ|CHS``，**没有**"段号"字段。
    lsq: int = 0
    direction: FileTransferDirection = FileTransferDirection.UPLOAD
    state: FileTransferState = FileTransferState.IDLE
    start_time: float = 0.0
    data: bytearray = field(default_factory=bytearray)
    sections: dict[int, bytearray] = field(default_factory=dict)
    timeout: float = 30.0  # 超时时间（秒）

    @property
    def elapsed(self) -> float:
        """已用时间."""
        return time.monotonic() - self.start_time if self.start_time else 0.0

    @property
    def is_timeout(self) -> bool:
        """是否超时."""
        return self.elapsed > self.timeout if self.start_time else False

    def reset(self):
        """重置上下文."""
        self.file_name = 0
        self.file_length = 0
        self.section_name = 0
        self.section_length = 0
        self.segment_number = 0
        self.lsq = 0
        self.state = FileTransferState.IDLE
        self.start_time = 0.0
        self.data.clear()
        self.sections.clear()


class FileTransferManager:
    """文件传输管理器.

    管理文件传输的状态机和流程控制。
    """

    def __init__(self, common_addr: int = 1):
        self._common_addr = common_addr
        self._context = FileTransferContext()
        self._on_send_asdu: Callable[[bytes], None] | None = None
        self._on_file_received: Callable[[int, bytes], None] | None = None
        self._on_error: Callable[[str], None] | None = None

    @property
    def context(self) -> FileTransferContext:
        return self._context

    @property
    def state(self) -> FileTransferState:
        return self._context.state

    def set_callbacks(
        self,
        on_send_asdu: Callable[[bytes], None] | None = None,
        on_file_received: Callable[[int, bytes], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        """设置回调函数."""
        self._on_send_asdu = on_send_asdu
        self._on_file_received = on_file_received
        self._on_error = on_error

    def handle_file_ready(self, data: FileReady) -> None:
        """处理文件准备就绪 (F_FR_NA_1).

        F_FR_NA_1 标志**一次新文件传输的开始**：此处重置累积缓冲与段计数，
        防止同一文件（或同名文件的新一轮）重复下载时上一轮的段数据残留
        （QA 互调 C4/D2：第二次下载 size=1200 = 600+600）。单次传输内的
        多节累积不受影响 —— 段数据在 file_ready 之后经 handle_file_segment
        逐段到达，仍正常累积。
        """
        logger.info(f"File Ready: name={data.file_name} length={data.file_length} status={data.status}")
        self._context.file_name = data.file_name
        self._context.file_length = data.file_length
        # 新传输边界：清空上一轮残留（D2）
        self._context.data.clear()
        self._context.segment_number = 0
        self._context.lsq = 0
        self._context.state = FileTransferState.FILE_READY

    def handle_section_ready(self, data: SectionReady) -> None:
        """处理节准备就绪 (F_SR_NA_1)."""
        logger.info(f"Section Ready: name={data.file_name} section={data.section_name} length={data.section_length}")
        self._context.section_name = data.section_name
        self._context.section_length = data.section_length
        self._context.state = FileTransferState.SECTION_READY

    def handle_file_segment(self, data: FileSegment) -> None:
        """处理段 (F_SG_NA_1)."""
        # F_SG_NA_1 信息体 = NOF(2)+NOS(1)+LOS(1)+数据，无段号字段 → 只做段计数
        logger.debug(f"File Segment: name={data.file_name} section={data.section_name} len={len(data.data)}")
        self._context.segment_number += 1
        self._context.data.extend(data.data)
        self._context.state = FileTransferState.TRANSFERRING

    def handle_last_section(self, data: LastSection) -> None:
        """处理最后的节/段 (F_LS_NA_1).

        信息体为 ``NOF(2, LE) | NOS(1) | LSQ(1) | CHS(1)``（不含 IOA）；
        ``LastSection.lsq``/``.chs`` 与标准八位组一一对应。

        - LSQ = 1/2（``FILE_TRANSFER_*``）→ **整个文件传输结束** → COMPLETED 并回调；
        - LSQ = 3/4（``SECTION_TRANSFER_*``）→ 仅本节结束、文件未结束。
          本管理器未实现真正的多节累积与逐节校验，故仅记录并保留日志；
        - LSQ = 0（``NOT_USED``）→ 不判定结束（目录传输的结束标记即用此值）；
        - 其它取值 → 超出 0-4 定义域，记告警（真机对端非标 / 字段错位）。
        """
        lsq = data.lsq
        logger.info(
            f"Last Section: name={data.file_name} section={data.section_name} "
            f"LSQ={lsq}({_LSQ_NAMES.get(lsq, '未定义')}) CHS={data.chs}"
        )
        self._context.lsq = lsq
        self._context.state = FileTransferState.LAST_SECTION

        # CHS 接收侧校验：算法为「该节所有段八位组的算术和 mod 256」（非标准原文，
        # 见模块顶部说明与 docs/file_transfer_fls.md §4.1）。LSQ=0（目录结束标记）
        # 与超出定义域的取值不校验。校验不通过 → **记告警，不丢弃**已收数据。
        if lsq in LSQ_FILE_COMPLETE or lsq in LSQ_SECTION_COMPLETE:
            expected = section_checksum(bytes(self._context.data))
            if data.chs != expected:
                logger.warning(
                    f"F_LS_NA_1 CHS mismatch: received={data.chs:#04x} "
                    f"calculated={expected:#04x} (checksum=sum(section octets) mod 256; "
                    "warning only, data NOT dropped)"
                )

        if lsq in LSQ_FILE_COMPLETE:
            self._context.state = FileTransferState.COMPLETED
            if self._on_file_received:
                self._on_file_received(self._context.file_name, bytes(self._context.data))
        elif lsq in LSQ_SECTION_COMPLETE:
            logger.info(
                f"F_LS_NA_1 LSQ={lsq}：仅本节传输结束，文件未结束（多节累积未实现）"
            )
        elif lsq != LSQ_NOT_USED:
            logger.warning(f"F_LS_NA_1 LSQ={lsq} 不在标准定义域 0-4 内（非标对端？）")

    def handle_directory_entry(self, data: DirectoryEntry) -> None:
        """处理目录条目 (F_DR_TA_1)."""
        logger.info(f"Directory Entry: name={data.file_name} length={data.file_length} status={data.status}")

    def check_timeout(self) -> bool:
        """检查超时."""
        if self._context.start_time and self._context.is_timeout:
            logger.warning(f"File transfer timeout: state={self._context.state}")
            self._context.state = FileTransferState.ERROR
            if self._on_error:
                self._on_error(f"File transfer timeout in state {self._context.state}")
            return True
        return False

    def reset(self):
        """重置管理器."""
        self._context.reset()


class FileTransferMaster(FileTransferManager):
    """主站文件传输管理器.

    实现主站侧的文件传输流程：
    1. 发送文件选择 (F_SC_NB_1)
    2. 等待文件准备就绪 (F_FR_NA_1)
    3. 发送文件准备就绪确认 (F_FR_NB_1)
    4. 等待节准备就绪 (F_SR_NA_1)
    5. 发送节准备就绪确认 (F_SR_NB_1)
    6. 接收段 (F_SG_NA_1)
    7. 接收最后的节 (F_LS_NA_1)
    8. 发送确认 (F_AF_NA_1)
    """

    def __init__(self, common_addr: int = 1):
        super().__init__(common_addr)
        self._context.direction = FileTransferDirection.UPLOAD

    def request_file(self, ioa: int, file_name: int) -> None:
        """请求文件."""
        from .asdu import ASDUBuilder
        self._context.file_name = file_name
        self._context.state = FileTransferState.FILE_SELECTED
        self._context.start_time = time.monotonic()

        asdu_data = ASDUBuilder.build_file_select_call_get(
            self._common_addr, ioa, file_name, qualifier=SCQ_REQUEST_FILE
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        logger.info(f"File request sent: file_name={file_name}")

    def send_file_ready_ack(self, ioa: int, status: int = 0) -> None:
        """发送文件准备就绪确认."""
        from .asdu import ASDUBuilder
        asdu_data = ASDUBuilder.build_file_ready_ack(
            self._common_addr, ioa, self._context.file_name,
            self._context.file_length, status
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        logger.info(f"File Ready ACK sent: file_name={self._context.file_name}")

    def send_section_ready_ack(self, ioa: int, status: int = 0) -> None:
        """发送节准备就绪确认."""
        from .asdu import ASDUBuilder
        asdu_data = ASDUBuilder.build_section_ready_ack(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name, self._context.section_length, status
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        logger.info(f"Section Ready ACK sent: section={self._context.section_name}")

    def send_ack(self, ioa: int, qualifier: int = 3) -> None:
        """发送确认."""
        from .asdu import ASDUBuilder
        asdu_data = ASDUBuilder.build_ack_file_section(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name, qualifier
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        logger.info(f"File ACK sent: qualifier={qualifier}")


class FileTransferSlave(FileTransferManager):
    """子站文件传输管理器.

    实现子站侧的文件传输流程：
    1. 接收文件选择/召唤 (F_SC_NB_1/F_SC_NA_1)
    2. 发送文件准备就绪 (F_FR_NA_1)
    3. 等待文件准备就绪确认 (F_FR_NB_1)
    4. 发送节准备就绪 (F_SR_NA_1)
    5. 等待节准备就绪确认 (F_SR_NB_1)
    6. 发送段 (F_SG_NA_1)
    7. 发送最后的节 (F_LS_NA_1)
    8. 等待确认 (F_AF_NA_1)
    """

    def __init__(self, common_addr: int = 1):
        super().__init__(common_addr)
        self._context.direction = FileTransferDirection.DOWNLOAD
        self._file_data: dict[int, bytes] = {}  # 文件数据缓存
        self._segment_size: int = 200  # 每段最大字节数

    def set_file_data(self, file_name: int, data: bytes) -> None:
        """设置文件数据."""
        self._file_data[file_name] = data

    def handle_file_request(self, ioa: int, file_name: int, qualifier: int) -> None:
        """处理文件请求（F_SC_NA_1 / F_SC_NB_1 的 SCQ 分支）.

        SCQ 取值表（标准，见模块顶部 ``SCQ_*`` 常量与 ``types.SCQ_NAMES``）：
        1=选择文件、2=请求文件、3=去激活文件、4=删除文件、5=选择节、
        6=请求节、7=去激活节。**SCQ=4 是删除文件，不得当作"选择文件"上送。**
        """
        logger.info(f"File request received: file_name={file_name} qualifier={qualifier}")

        if qualifier in (SCQ_SELECT_FILE, SCQ_REQUEST_FILE):
            # 选择文件 / 请求文件：登记并回 F_FR_NA_1（FRQ 肯定）
            self._context.file_name = file_name
            self._context.state = FileTransferState.FILE_SELECTED
            self._context.start_time = time.monotonic()

            # 获取文件数据
            file_data = self._file_data.get(file_name, b'')
            self._context.file_length = len(file_data)
            self._context.data = bytearray(file_data)

            # 发送文件准备就绪
            self._send_file_ready(ioa)
        elif qualifier == SCQ_REQUEST_DIRECTORY:
            # SCQ=5 触发目录上送 —— 该组合**未核实**（标准 SCQ=5 为选择节），
            # 保持开放不推断（见 docs/file_transfer_fls.md §4.4）。
            self._send_directory(ioa)
        elif qualifier == SCQ_DELETE_FILE:
            # SCQ=4 = 删除文件：移出缓存并回 F_AF_NA_1（AFQ 肯定文件），
            # 绝不触发文件上送（旧实现把 4 当"选择文件"是危险误判）。
            removed = self._file_data.pop(file_name, None)
            if removed is None:
                logger.warning(f"Delete file (SCQ=4): file {file_name} not found")
            else:
                logger.info(f"File deleted on request (SCQ=4): file_name={file_name}")
            self._send_ack(ioa, qualifier=AFQ_POS_ACK_FILE)
        elif qualifier in (SCQ_DEACTIVATE_FILE, SCQ_DEACTIVATE_SECTION):
            # 去激活：多节/去激活流程未实现（开放项，见 docs §4.5/4.6），仅记录
            logger.info(f"Deactivate request (SCQ={qualifier}) noted, no-op (flow not implemented)")
        elif qualifier == SCQ_REQUEST_SECTION:
            # 请求节：多节流程未实现（开放项，见 docs §4.6），不推断
            logger.warning("Request section (SCQ=6) not implemented (multi-section flow open)")
        else:
            logger.warning(f"Unsupported file request qualifier: {qualifier}")

    def _send_file_ready(self, ioa: int) -> None:
        """发送文件准备就绪."""
        from .asdu import ASDUBuilder
        asdu_data = ASDUBuilder.build_file_ready(
            self._common_addr, ioa, self._context.file_name,
            self._context.file_length, status=0
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        self._context.state = FileTransferState.FILE_READY
        logger.info(f"File Ready sent: file_name={self._context.file_name} length={self._context.file_length}")

    def _send_ack(self, ioa: int, qualifier: int = AFQ_POS_ACK_FILE) -> None:
        """发送文件/节确认 (F_AF_NA_1)."""
        from .asdu import ASDUBuilder
        asdu_data = ASDUBuilder.build_ack_file_section(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name, qualifier
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        logger.info(f"File ACK sent: qualifier={qualifier}")

    def handle_file_ready_ack(self, ioa: int, data: FileReadyAck) -> None:
        """处理文件准备就绪确认."""
        logger.info(f"File Ready ACK received: file_name={data.file_name} status={data.status}")
        if data.status == 0:  # 肯定
            # 发送节准备就绪
            self._send_section_ready(ioa)

    def _send_section_ready(self, ioa: int) -> None:
        """发送节准备就绪."""
        from .asdu import ASDUBuilder
        self._context.section_name = 1  # 默认节1
        self._context.section_length = self._context.file_length

        asdu_data = ASDUBuilder.build_section_ready(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name, self._context.section_length, status=0
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        self._context.state = FileTransferState.SECTION_READY
        logger.info(f"Section Ready sent: section={self._context.section_name} length={self._context.section_length}")

    def handle_section_ready_ack(self, ioa: int, data: SectionReadyAck) -> None:
        """处理节准备就绪确认."""
        logger.info(f"Section Ready ACK received: file_name={data.file_name} section={data.section_name}")
        if data.status == 0:  # 肯定
            # 开始发送段
            self._send_segments(ioa)

    def _send_segments(self, ioa: int) -> None:
        """发送所有段."""
        from .asdu import ASDUBuilder
        data = bytes(self._context.data)
        segment_count = 0

        for i in range(0, len(data), self._segment_size):
            chunk = data[i:i + self._segment_size]
            segment_count += 1

            asdu_data = ASDUBuilder.build_file_segment(
                self._common_addr, ioa, self._context.file_name,
                self._context.section_name, chunk
            )
            if self._on_send_asdu:
                self._on_send_asdu(asdu_data)

        self._context.segment_number = segment_count
        self._context.state = FileTransferState.TRANSFERRING
        logger.info(f"Sent {segment_count} segments")

        # 发送最后的节
        self._send_last_section(ioa)

    def _send_last_section(self, ioa: int) -> None:
        """发送最后的节 (F_LS_NA_1).

        本实现把整个文件作为**单个节**发送，故 LSQ = 1
        （``FILE_TRANSFER_WITHOUT_DEACT``：整个文件传输结束、不要求去激活），
        由主站据此判定接收完成（见 ``FileTransferManager.handle_last_section``）。

        ``ASDUBuilder.build_last_section`` 的第 5/6 个位置参数分别是 LSQ 八位组与
        CHS 八位组；CHS = 本节所有段数据的算术和 mod 256（见 ``section_checksum``）。
        """
        from .asdu import ASDUBuilder
        asdu_data = ASDUBuilder.build_last_section(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name,
            LSQ_FILE_TRANSFER_WITHOUT_DEACT,                  # LSQ 八位组
            section_checksum(bytes(self._context.data)),      # CHS 八位组
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        self._context.state = FileTransferState.LAST_SECTION
        logger.info(f"Last Section sent: lsq={LSQ_FILE_TRANSFER_WITHOUT_DEACT} segments={self._context.segment_number}")

    def handle_ack(self, ioa: int, data: AckFileSection) -> None:
        """处理确认."""
        logger.info(f"ACK received: file_name={data.file_name} section={data.section_name} qualifier={data.qualifier}")
        if data.qualifier in (AFQ_POS_ACK_FILE, AFQ_POS_ACK_SECTION):
            self._context.state = FileTransferState.COMPLETED
            logger.info("File transfer completed")
        else:
            self._context.state = FileTransferState.ERROR
            logger.warning(f"File transfer rejected: qualifier={data.qualifier}")

    def _send_directory(self, ioa: int) -> None:
        """发送目录."""
        from .asdu import ASDUBuilder
        # 发送所有文件的目录条目
        for file_name, file_data in self._file_data.items():
            asdu_data = ASDUBuilder.build_directory_entry(
                self._common_addr, ioa, file_name, len(file_data), status=0
            )
            if self._on_send_asdu:
                self._on_send_asdu(asdu_data)

        # 发送目录结束标记 (F_LS_NA_1)：LSQ = 0（NOT_USED），不表示任何传输结束
        asdu_data = ASDUBuilder.build_last_section(
            self._common_addr, ioa, file_name=0,
            section_name=0, lsq=LSQ_NOT_USED, chs=0
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        logger.info(f"Directory sent: {len(self._file_data)} files")
