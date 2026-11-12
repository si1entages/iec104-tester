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
from typing import Any

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
        # 当前节数据（逐节 CHS 校验用；与跨节累积的 _context.data 分开）
        self._section_data = bytearray()

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
        self._section_data.clear()
        self._context.segment_number = 0
        self._context.lsq = 0
        self._context.state = FileTransferState.FILE_READY

    def handle_section_ready(self, data: SectionReady) -> None:
        """处理节准备就绪 (F_SR_NA_1).

        SRQ 最高位（0x80）= 否定：子站拒绝/无法提供该节（lib60870.NET 口径：
        ``SectionReady`` 的 negative 标志）——主站必须中止而非请求该节。
        2026-11-10 按标准修复（T50/C4 §5）：旧实现忽略 SRQ，把否定节就绪
        当正常处理并继续请求不存在的节。
        """
        srq_negative = bool(getattr(data, "status", 0) & 0x80)
        logger.info(
            f"Section Ready: name={data.file_name} section={data.section_name} "
            f"length={data.section_length} srq=0x{getattr(data, 'status', 0):02x}"
            f"{' (NEGATIVE)' if srq_negative else ''}"
        )
        if srq_negative:
            self._context.state = FileTransferState.ERROR
            if self._on_error:
                self._on_error(
                    f"否定节就绪 (SRQ=0x80)：子站拒绝提供节 {data.section_name}"
                    f"（文件 {data.file_name}），传输中止"
                )
            return
        self._context.section_name = data.section_name
        self._context.section_length = data.section_length
        self._section_data.clear()
        self._context.state = FileTransferState.SECTION_READY

    def handle_file_segment(self, data: FileSegment) -> None:
        """处理段 (F_SG_NA_1)."""
        # F_SG_NA_1 信息体 = NOF(2)+NOS(1)+LOS(1)+数据，无段号字段 → 只做段计数
        logger.debug(f"File Segment: name={data.file_name} section={data.section_name} len={len(data.data)}")
        self._context.segment_number += 1
        self._context.data.extend(data.data)
        self._section_data.extend(data.data)
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
        # 末帧可能用一个新的“文件结束节号”（lib60870 用 section=3），
        # 此时没有本节段数据，CHS 不应按上一节数据校验。
        same_section = bool(self._section_data) and (
            not self._context.section_name
            or data.section_name == self._context.section_name
        )
        self._context.lsq = lsq
        self._context.section_name = data.section_name
        self._context.state = FileTransferState.LAST_SECTION

        # CHS 接收侧校验：算法为「该节所有段八位组的算术和 mod 256」（非标准原文，
        # 见模块顶部说明与 docs/file_transfer_fls.md §4.1）。LSQ=0（目录结束标记）
        # 与超出定义域的取值不校验。校验不通过 → **记告警，不丢弃**已收数据。
        if (lsq in LSQ_FILE_COMPLETE or lsq in LSQ_SECTION_COMPLETE) and same_section:
            expected = section_checksum(bytes(self._section_data))
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
                f"F_LS_NA_1 LSQ={lsq}：仅本节传输结束，文件未结束（继续等待下一节）"
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
    1. 发送文件选择/请求 (F_SC_NA_1, COT=FILE, SCQ=1/2)
    2. 等待文件准备就绪 (F_FR_NA_1)；**不**回 F_FR_NB
    3. 等待节准备就绪 (F_SR_NA_1)
    4. 发送节请求 (F_SC_NA_1, SCQ=6)
    5. 接收段 (F_SG_NA_1) 与 F_LS_NA_1
    6. 按 LSQ 回 F_AF_NA_1：LSQ=1/2 → 肯定文件，LSQ=3/4 → 肯定节
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

        asdu_data = ASDUBuilder.build_call_directory(
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

    # ── WP3c：上传方向（主站 → 子站）────────────────────────────────

    def start_upload(self, ioa: int, file_name: int, data: bytes,
                     *, segment_size: int = 200) -> None:
        """发起一次上传：选文件 → 分段发 F_SG → F_LS 结束.

        方向判定由**调用方**保证（主站发、子站收）。子站收到 F_LS(LSQ=1)
        后回 F_AF(1)，主站 ``handle_ack`` 置 COMPLETED。
        段数据按 ``segment_size`` 切分（F_SG 的 LOS 为 1 字节，上限 255）。
        """
        from .asdu import ASDUBuilder

        if not data:
            raise ValueError("上传文件数据不能为空")
        size = max(1, min(int(segment_size), 255))
        self._context.file_name = file_name
        self._context.file_length = len(data)
        self._context.section_name = 1
        self._context.data = bytearray(data)
        self._context.start_time = time.monotonic()
        self._context.state = FileTransferState.FILE_SELECTED

        # 1) 选择文件（SCQ=1），子站回 F_FR 表示已准备好接收
        if self._on_send_asdu:
            self._on_send_asdu(ASDUBuilder.build_call_directory(
                self._common_addr, ioa, file_name, qualifier=SCQ_SELECT_FILE))
        # 2) 逐段发送
        for off in range(0, len(data), size):
            chunk = data[off:off + size]
            if self._on_send_asdu:
                self._on_send_asdu(ASDUBuilder.build_file_segment(
                    self._common_addr, ioa, file_name, 1, chunk))
        # 3) 最后一节（整个文件，LSQ=1）+ 本节 CHS
        if self._on_send_asdu:
            self._on_send_asdu(ASDUBuilder.build_last_section(
                self._common_addr, ioa, file_name, 1,
                LSQ_FILE_TRANSFER_WITHOUT_DEACT, section_checksum(data)))
        self._context.state = FileTransferState.LAST_SECTION
        logger.info(
            f"Upload sent: name={file_name} size={len(data)} "
            f"segments={(len(data) + size - 1) // size}")

    def handle_upload_ack(self, data: AckFileSection) -> bool:
        """上传侧收到 F_AF：肯定文件 → COMPLETED。返回是否成功."""
        if data.qualifier == AFQ_POS_ACK_FILE:
            self._context.state = FileTransferState.COMPLETED
            logger.info("Upload acknowledged (file positive)")
            return True
        self._context.state = FileTransferState.ERROR
        logger.warning(f"Upload rejected: AFQ={data.qualifier}")
        return False


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

    def __init__(self, common_addr: int = 1, *,
                 inject_lsq: int | None = None,
                 inject_srq_negative: bool = False,
                 semantics: Any = None):
        """子站文件传输管理器.

        Args:
            common_addr: 公共地址
            inject_lsq: F_LS 的 LSQ 覆盖值（T50/C4 §3 场景注入：2=文件带去激活、
                4=节带去激活；None=默认 1，行为不变）
            inject_srq_negative: F_SR 的 SRQ 置 0x80（§5 否定节就绪场景注入）
            semantics: WP3a 语义档位（None=ed1，历史单节行为）
        """
        super().__init__(common_addr)
        from .file_semantics import ED1

        self._semantics = semantics if semantics is not None else ED1
        self._context.direction = FileTransferDirection.DOWNLOAD
        self._file_data: dict[int, bytes] = {}  # 文件数据缓存
        self._segment_size: int = 200  # 每段最大字节数
        self._inject_lsq = inject_lsq
        self._inject_srq_negative = inject_srq_negative
        # WP3b：多节分包状态（section_size>0 时启用；0=历史单节行为）
        self._sections: list[tuple[int, bytes]] = []  # [(节号, 本节数据)]
        self._section_index: int = 0
        self._ioa: int = 0  # 记录本次传输的 IOA，供后续节主动上送
        self._awaiting_section_ack: bool = False

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
            # 选择文件 / 请求文件：登记并回 F_FR_NA_1（FRQ 肯定）。
            # 标准流程：SELECT(1) → F_FR → REQUEST(2) → F_SR → SECTION(6) → F_SG/F_LS。
            # 若调用方直接发 REQUEST（跳过 SELECT），这里补发 F_FR 再发 F_SR，
            # 保证单命令也能推进（内部 API 兼容）。
            was_ready = (
                self._context.state == FileTransferState.FILE_READY
                and self._context.file_name == file_name
            )
            self._context.file_name = file_name
            self._context.start_time = time.monotonic()
            file_data = self._file_data.get(file_name, b'')
            self._context.file_length = len(file_data)
            self._context.data = bytearray(file_data)
            self._context.state = FileTransferState.FILE_SELECTED
            self._ioa = ioa
            self._section_index = 0
            self._awaiting_section_ack = False
            self._sections = self._split_sections(bytes(file_data))

            if qualifier == SCQ_SELECT_FILE:
                self._send_file_ready(ioa)
            else:
                if not was_ready:
                    # 直接 REQUEST（跳过 SELECT）：补发 F_FR 保证状态完整
                    self._send_file_ready(ioa)
                self._send_section_ready(ioa)
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
            # 请求节：发送该节全部 F_SG，并以 F_LS 结束（当前实现单节）。
            # 标准/第三方流程：主站收到 F_SR 后必须发 SCQ=6，否则从站不发数据。
            self._send_segments(ioa)
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

    # ── WP3b：多节分包 ────────────────────────────────────────────

    def _split_sections(self, data: bytes) -> list[tuple[int, bytes]]:
        """按语义档位的 section_size 把文件切成多节；0/未配置=单节（历史行为）."""
        size = int(getattr(self._semantics, "section_size", 0) or 0)
        if size <= 0 or len(data) <= size:
            return [(1, data)]
        return [
            (i + 1, data[i * size:(i + 1) * size])
            for i in range((len(data) + size - 1) // size)
        ]

    def _send_section_ready(self, ioa: int) -> None:
        """发送当前节的节准备就绪 (F_SR_NA_1)——多节时按 _section_index 推进."""
        from .asdu import ASDUBuilder

        multi = len(self._sections) > 1
        if multi:
            if self._section_index >= len(self._sections):
                return
            number, payload = self._sections[self._section_index]
            self._context.section_name = number
            self._context.section_length = len(payload)
            self._context.data = bytearray(payload)  # 仅本节数据，供 _send_segments
        else:
            self._context.section_name = 1
            self._context.section_length = self._context.file_length
        srq = 0x80 if self._inject_srq_negative else 0
        asdu_data = ASDUBuilder.build_section_ready(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name, self._context.section_length, status=srq
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        self._context.state = FileTransferState.SECTION_READY
        self._awaiting_section_ack = False
        logger.info(
            f"Section Ready sent: section={self._context.section_name} "
            f"length={self._context.section_length} srq=0x{srq:02x} "
            f"({self._section_index + 1}/{len(self._sections)} sections)")

    def handle_section_ready_ack(self, ioa: int, data: SectionReadyAck) -> None:
        """处理节准备就绪确认（历史 F_SR_NB 路径）."""
        logger.info(f"Section Ready ACK received: file_name={data.file_name} section={data.section_name}")
        if data.status == 0:
            self._send_segments(ioa)

    def _send_segments(self, ioa: int) -> None:
        """发送**当前节**的所有段，并以 F_LS 结束本节.

        多节时：非最后节 LSQ=3（仅本节结束），最后节 LSQ=1（整个文件结束）。
        CHS 按**本节**数据计算（逐节校验，与主站 handle_last_section 对齐）。
        """
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
        logger.info(f"Sent {segment_count} segments (section={self._context.section_name})")
        self._send_last_section(ioa, data)

    def _send_last_section(self, ioa: int, section_data: bytes) -> None:
        """发送最后的节 (F_LS_NA_1).

        多节：非最后节 LSQ=3、最后节 LSQ=1；单节：LSQ=1（历史行为）。
        ``ASDUBuilder.build_last_section`` 第 5/6 位置参数为 LSQ/CHS 八位组；
        CHS = 本节所有段数据算术和 mod 256（见 ``section_checksum``）。
        """
        from .asdu import ASDUBuilder
        if self._inject_lsq is not None:
            lsq = self._inject_lsq
        elif len(self._sections) > 1 and self._section_index < len(self._sections) - 1:
            lsq = LSQ_SECTION_TRANSFER_WITHOUT_DEACT   # 3：本节结束，文件未结束
        else:
            lsq = LSQ_FILE_TRANSFER_WITHOUT_DEACT       # 1：整个文件结束
        asdu_data = ASDUBuilder.build_last_section(
            self._common_addr, ioa, self._context.file_name,
            self._context.section_name,
            lsq,
            section_checksum(section_data),
        )
        if self._on_send_asdu:
            self._on_send_asdu(asdu_data)
        self._context.state = FileTransferState.LAST_SECTION
        self._awaiting_section_ack = True
        logger.info(f"Last Section sent: lsq={lsq} segments={self._context.segment_number}")

    def handle_ack(self, ioa: int, data: AckFileSection) -> None:
        """处理 F_AF 确认：肯定节 → 主动推下一节；肯定文件 → 完成."""
        logger.info(f"ACK received: file_name={data.file_name} section={data.section_name} qualifier={data.qualifier}")
        if data.qualifier == AFQ_POS_ACK_SECTION:
            # 仅本节被确认：多节时推进到下一节，重新发 F_SR 驱动主站请求
            if self._section_index < len(self._sections) - 1:
                self._section_index += 1
                self._context.state = FileTransferState.SECTION_READY
                self._send_section_ready(self._ioa or ioa)
            else:
                self._context.state = FileTransferState.COMPLETED
        elif data.qualifier == AFQ_POS_ACK_FILE:
            self._context.state = FileTransferState.COMPLETED
            logger.info("File transfer completed")
        else:
            self._context.state = FileTransferState.ERROR
            logger.warning(f"File transfer rejected: qualifier={data.qualifier}")

    # ── WP3c：上传方向接收侧（主站 → 子站）──────────────────────────

    def handle_incoming_file_segment(self, data: FileSegment) -> None:
        """接收主站发来的段并累积（上传方向）."""
        self._context.file_name = data.file_name
        self._context.section_name = data.section_name
        self._context.data.extend(data.data)
        self._section_data.extend(data.data)
        self._context.state = FileTransferState.TRANSFERRING

    def handle_incoming_last_section(self, ioa: int, data: LastSection) -> bytes:
        """接收主站发来的 F_LS：校验 CHS、落盘、回 F_AF(肯定/否定文件).

        Returns: 要回送的 F_AF ASDU 字节（由 slave_response 发出）。
        """
        from .asdu import ASDUBuilder

        expected = section_checksum(bytes(self._section_data))
        ok = data.chs == expected
        if ok:
            payload = bytes(self._context.data)
            self._file_data[data.file_name] = payload
            self._context.file_length = len(payload)
            self._context.state = FileTransferState.COMPLETED
            logger.info(f"Upload received: name={data.file_name} size={len(payload)}")
        else:
            self._context.state = FileTransferState.ERROR
            logger.warning(
                f"Upload CHS mismatch: received={data.chs:#04x} expected={expected:#04x}; "
                "file rejected")
        afq = AFQ_POS_ACK_FILE if ok else AFQ_NEG_ACK_FILE
        return ASDUBuilder.build_ack_file_section(
            self._common_addr, ioa, data.file_name, data.section_name, afq)

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
