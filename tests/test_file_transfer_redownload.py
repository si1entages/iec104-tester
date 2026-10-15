"""D2 回归测试：主站文件重复下载不得累积上一轮数据.

复现（QA 互调报告 2026-10-15 §C4/D2）：同一文件第二次下载
``File received size=1200``（600+600 累积）。根因：
``FileTransferManager.handle_file_ready`` 在新文件传输开始时未重置
``_context.data``。

修复边界：
- 重置发生在「新文件传输开始」（收到 F_FR_NA_1）——本测试覆盖；
- 单次传输内的多节累积**不得回归**：3 段 × 200B 累积成完整 600B
  （QA 实测单次 600B = 3 段为正确行为）——本测试同时断言。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.protocol.file_transfer import (
    LSQ_FILE_TRANSFER_WITHOUT_DEACT,
    FileTransferManager,
    FileTransferState,
    section_checksum,
)
from core.protocol.types import (
    FileReady,
    FileSegment,
    LastSection,
    SectionReady,
)

FILE_NAME = 7
SECTION_NAME = 1
PAYLOAD = bytes(range(256)) * 2 + bytes(88)  # 600B，非全零（CHS 非平凡）
SEGMENT_SIZE = 200


def _run_one_download(mgr: FileTransferManager, received: list) -> None:
    """按主站接收时序注入一次完整文件传输（600B = 3 段 × 200B）."""
    chunks = [PAYLOAD[i:i + SEGMENT_SIZE] for i in range(0, len(PAYLOAD), SEGMENT_SIZE)]
    mgr.handle_file_ready(FileReady(ioa=0, file_name=FILE_NAME,
                                    file_length=len(PAYLOAD), status=0))
    mgr.handle_section_ready(SectionReady(ioa=0, file_name=FILE_NAME,
                                          section_name=SECTION_NAME,
                                          section_length=len(PAYLOAD), status=0))
    for chunk in chunks:
        mgr.handle_file_segment(FileSegment(ioa=0, file_name=FILE_NAME,
                                            section_name=SECTION_NAME,
                                            data=chunk))
    mgr.handle_last_section(LastSection(
        ioa=0, file_name=FILE_NAME, section_name=SECTION_NAME,
        lsq=LSQ_FILE_TRANSFER_WITHOUT_DEACT,
        chs=section_checksum(PAYLOAD),
    ))


def test_same_file_downloaded_twice_returns_full_data_both_times():
    """同一文件连续两次下载：两次均为完整 600B（D2 缺陷修复断言）."""
    mgr = FileTransferManager(common_addr=1)
    received: list[tuple[int, bytes]] = []
    mgr.set_callbacks(on_file_received=lambda name, data: received.append((name, data)))

    _run_one_download(mgr, received)
    _run_one_download(mgr, received)

    assert len(received) == 2
    for name, data in received:
        assert name == FILE_NAME
        assert len(data) == len(PAYLOAD), (
            f"重复下载累积残留：期望 {len(PAYLOAD)}B，实际 {len(data)}B"
        )
    assert received[0][1] == PAYLOAD
    assert received[1][1] == PAYLOAD


def test_segment_counter_resets_per_transfer():
    """段计数随新传输重置：第二次传输后 segment_number == 3（而非累积 6）."""
    mgr = FileTransferManager(common_addr=1)
    mgr.set_callbacks(on_file_received=lambda name, data: None)

    _run_one_download(mgr, [])
    assert mgr.context.segment_number == 3
    _run_one_download(mgr, [])
    assert mgr.context.segment_number == 3


def test_multi_segment_accumulation_within_single_transfer_preserved():
    """单次传输内的多节累积行为不回归：3 段 × 200B = 完整 600B，CHS 匹配."""
    mgr = FileTransferManager(common_addr=1)
    received: list[tuple[int, bytes]] = []
    mgr.set_callbacks(on_file_received=lambda name, data: received.append((name, data)))

    _run_one_download(mgr, received)

    assert len(received) == 1
    assert mgr.context.state == FileTransferState.COMPLETED
    assert received[0][1] == PAYLOAD  # 逐字节一致 → 累积顺序与完整性正确
    # CHS 校验路径：末节校验和与累积数据一致（无 mismatch 告警即通过）


def test_context_buffer_cleared_on_new_file_ready():
    """直接断言修复点：handle_file_ready 后累积缓冲为空、lsq 归零."""
    mgr = FileTransferManager(common_addr=1)
    mgr.set_callbacks(on_file_received=lambda name, data: None)

    _run_one_download(mgr, [])
    assert len(mgr.context.data) == len(PAYLOAD)

    # 新一轮传输开始（仅到 F_FR_NA_1）→ 残留必须已清空
    mgr.handle_file_ready(FileReady(ioa=0, file_name=FILE_NAME,
                                    file_length=len(PAYLOAD), status=0))
    assert len(mgr.context.data) == 0
    assert mgr.context.segment_number == 0
    assert mgr.context.lsq == 0
