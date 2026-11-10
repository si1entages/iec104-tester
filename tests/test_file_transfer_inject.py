"""T50/C4 §3/§5 场景注入验证（子站侧注入钩子 → 主站行为锁定）.

两个 lib60870 实现（C v2.4.1 / .NET master）都只产生 LSQ=1/3 且不构造否定
F_SR——这三种路径必须靠**子站侧注入钩子**合成（真机到位前唯一的场景合成手段）：

- §3：LSQ=2（FILE_TRANSFER_WITH_DEACT）/ LSQ=4（SECTION_TRANSFER_WITH_DEACT）
  → 主站判定必须与 LSQ=1/3 一致（2 归文件结束、4 归节结束）；
- §5：否定节就绪（F_SR SRQ=0x80）→ 主站必须中止（2026-11-10 按标准修复，
  旧实现忽略 SRQ 继续请求不存在的节——缺陷钉桩见 git 历史）。

注入钩子默认关闭（FileTransferSlave() 行为不变），仅测试/联调显式开启。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.protocol.asdu import ASDU
from core.protocol.file_transfer import (
    FileTransferMaster,
    FileTransferSlave,
    FileTransferState,
)

IOA = 100
FILE_NAME = 5
DATA = b"\x01\x02\x03\x04"


def _slave_frames(slave: FileTransferSlave, ioa: int = IOA) -> list[ASDU]:
    """驱动从站完整状态机（select → F_FR ack → F_SR ack → 段+LS），收集发出的 ASDU."""
    from core.protocol.types import FileReadyAck, SectionReadyAck

    out: list[ASDU] = []
    slave.set_callbacks(on_send_asdu=lambda raw: out.append(ASDU.decode(raw)))
    slave.set_file_data(FILE_NAME, DATA)
    slave.handle_file_request(ioa, FILE_NAME, qualifier=1)   # select → F_FR
    slave.handle_file_ready_ack(
        ioa, FileReadyAck(ioa=ioa, file_name=FILE_NAME,
                          file_length=len(DATA), status=0))  # → F_SR
    slave.handle_section_ready_ack(
        ioa, SectionReadyAck(ioa=ioa, file_name=FILE_NAME,
                             section_name=1, section_length=len(DATA),
                             status=0))                      # → F_SG×N + F_LS
    return out


def _feed_master(master: FileTransferMaster, asdu: ASDU) -> None:
    """把从站 ASDU 喂给主站管理器（按类型分发，等价 process_file_transfer 的 F_* 分支）."""
    from core.protocol.asdu import TypeID

    obj = asdu.objects[0]
    tid = asdu.type_id
    if tid == TypeID.F_FR_NA_1:
        master.handle_file_ready(obj.data)
    elif tid == TypeID.F_SR_NA_1:
        master.handle_section_ready(obj.data)
    elif tid == TypeID.F_SG_NA_1:
        master.handle_file_segment(obj.data)
    elif tid == TypeID.F_LS_NA_1:
        master.handle_last_section(obj.data)


# ── §3：LSQ=2 / LSQ=4 注入 ──────────────────────────────────────────────


def test_section3_lsq2_with_deact_completes_file():
    """LSQ=2（文件结束+要求去激活）：主站判定与 LSQ=1 一致——文件完成."""
    errors: list[str] = []
    received: list[tuple[int, bytes]] = []
    master = FileTransferMaster(1)
    master.set_callbacks(on_file_received=lambda n, d: received.append((n, d)),
                         on_error=errors.append)
    slave = FileTransferSlave(1, inject_lsq=2)               # ← 注入
    frames = _slave_frames(slave)
    ls_frames = [f for f in frames if f.type_id.value == 123]
    assert ls_frames and ls_frames[0].objects[0].data.lsq == 2
    for f in frames:
        _feed_master(master, f)
    assert master.context.state == FileTransferState.COMPLETED
    assert received and received[0][0] == FILE_NAME and received[0][1] == DATA
    assert errors == []


def test_section3_lsq4_section_deact_not_file_complete():
    """LSQ=4（仅节结束+要求去激活）：主站不得判文件完成（与 LSQ=3 同判）."""
    errors: list[str] = []
    received: list[tuple[int, bytes]] = []
    master = FileTransferMaster(1)
    master.set_callbacks(on_file_received=lambda n, d: received.append((n, d)),
                         on_error=errors.append)
    slave = FileTransferSlave(1, inject_lsq=4)               # ← 注入
    frames = _slave_frames(slave)
    ls_frames = [f for f in frames if f.type_id.value == 123]
    assert ls_frames and ls_frames[0].objects[0].data.lsq == 4
    for f in frames:
        _feed_master(master, f)
    assert master.context.state != FileTransferState.COMPLETED
    assert received == []
    assert errors == []                                      # 节结束不是错误


def test_section3_default_lsq1_unchanged():
    """注入默认关闭：LSQ=1 行为与修复前完全一致（回归护栏）."""
    received: list[tuple[int, bytes]] = []
    master = FileTransferMaster(1)
    master.set_callbacks(on_file_received=lambda n, d: received.append((n, d)))
    slave = FileTransferSlave(1)                             # 默认（无注入）
    frames = _slave_frames(slave)
    ls_frames = [f for f in frames if f.type_id.value == 123]
    assert ls_frames[0].objects[0].data.lsq == 1
    for f in frames:
        _feed_master(master, f)
    assert master.context.state == FileTransferState.COMPLETED and received


# ── §5：否定节就绪（SRQ=0x80）注入 ──────────────────────────────────────


def test_section5_negative_section_ready_aborts():
    """否定 F_SR（SRQ=0x80）：主站必须中止——不得当正常节就绪请求该节."""
    errors: list[str] = []
    master = FileTransferMaster(1)
    master.set_callbacks(on_error=errors.append)
    slave = FileTransferSlave(1, inject_srq_negative=True)   # ← 注入
    frames = _slave_frames(slave)
    sr_frames = [f for f in frames if f.type_id.value == 121]
    assert sr_frames, "从站应发出 F_SR"
    from core.protocol.types import SectionReady

    sr: SectionReady = sr_frames[0].objects[0].data
    assert sr.status & 0x80, f"SRQ 否定位应置位: 0x{sr.status:02x}"
    _feed_master(master, sr_frames[0])
    assert master.context.state == FileTransferState.ERROR
    assert errors and "否定节就绪" in errors[0]


def test_section5_positive_section_ready_unchanged():
    """默认（SRQ=0）：正常节就绪行为不变（回归护栏）."""
    master = FileTransferMaster(1)
    errors: list[str] = []
    master.set_callbacks(on_error=errors.append)
    slave = FileTransferSlave(1)                             # 默认（无注入）
    frames = _slave_frames(slave)
    sr_frames = [f for f in frames if f.type_id.value == 121]
    assert sr_frames[0].objects[0].data.status == 0
    _feed_master(master, sr_frames[0])
    assert master.context.state == FileTransferState.SECTION_READY
    assert errors == []
