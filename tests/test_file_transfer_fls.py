"""F_LS_NA_1（最后的节/最后的段）八位组语义测试与缺陷钉桩（T24）.

**已核实依据**（详见 ``docs/file_transfer_fls.md``）：
lib60870.NET（mz-automation，业界广泛使用的参考栈）``lib60870/CS101/FileObjects.cs``
中 ``FileLastSegmentOrSection`` 的编解码实现与 ``LastSectionOrSegmentQualifier`` 枚举：

- F_LS_NA_1(123) 信息体（不含 IOA）= ``NOF(2, LE) | NOS(1) | LSQ(1) | CHS(1)``，共 5 字节；
- LSQ 定义域：0=NOT_USED / 1=FILE_TRANSFER_WITHOUT_DEACT / 2=FILE_TRANSFER_WITH_DEACT /
  3=SECTION_TRANSFER_WITHOUT_DEACT / 4=SECTION_TRANSFER_WITH_DEACT；
- **仅 LSQ=1/2 表示"整个文件传输结束"**；LSQ=3/4 只表示"本节结束"（文件未结束）。

本文件分三部分：
1. 已验证语义的行为断言（应长期成立）；
2. 收发闭环（编码 → 解码 → 主站判定）回归；
3. **缺陷钉桩**——把当前与标准不符之处按仓库既有惯例（参照
   ``test_capture_recorder.py::test_export_format_argument_is_currently_ignored``）
   钉住当前行为，修复后这些用例需同步改为断言正确行为；每条都标了标准要求值。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.file_transfer import (
    LSQ_FILE_COMPLETE,
    LSQ_FILE_TRANSFER_WITHOUT_DEACT,
    LSQ_NOT_USED,
    LSQ_SECTION_COMPLETE,
    FileTransferManager,
    FileTransferSlave,
    FileTransferState,
)
from core.protocol.types import FileReadyAck, FileSegment, LastSection, SectionReadyAck

#: ASDU 头(类型1 + VSQ1 + COT2 + 公共地址2) + IOA3 = 9 字节；其后为信息体
IO_BODY_OFFSET = 9
FILE_NAME = 5
IOA = 100


# ── helpers ─────────────────────────────────────────────────────

def _last_section(lsq: int, chs: int = 0) -> LastSection:
    """构造 F_LS_NA_1 信息对象：第 4 字节 = LSQ，第 5 字节 = CHS."""
    return LastSection(ioa=IOA, file_name=FILE_NAME, section_name=1,
                       last_segment=lsq, status=chs)


def _segment(data: bytes) -> FileSegment:
    return FileSegment(ioa=IOA, file_name=FILE_NAME, section_name=1, data=data)


def _receiver():
    """主站侧管理器：预置文件名，并收集交付的数据."""
    mgr = FileTransferManager(common_addr=1)
    mgr.context.file_name = FILE_NAME
    received: list[bytes] = []
    mgr.set_callbacks(on_file_received=lambda _name, data: received.append(data))
    return mgr, received


def _slave_with_file(data: bytes) -> tuple[FileTransferSlave, list[bytes]]:
    """子站侧管理器 + 收帧回调（返回已发出的帧列表）."""
    mgr = FileTransferSlave(common_addr=1)
    sent: list[bytes] = []
    mgr.set_callbacks(on_send_asdu=sent.append)
    mgr.set_file_data(FILE_NAME, data)
    return mgr, sent


def _upload_whole_file(mgr: FileTransferSlave) -> None:
    """跑完一遍完整上送流程（请求 → FR ACK → SR ACK → 各段 + F_LS）."""
    mgr.handle_file_request(IOA, FILE_NAME, 1)
    mgr.handle_file_ready_ack(
        IOA, FileReadyAck(ioa=IOA, file_name=FILE_NAME, status=0)
    )
    mgr.handle_section_ready_ack(
        IOA, SectionReadyAck(ioa=IOA, file_name=FILE_NAME, section_name=1, status=0)
    )


# ── ① 已核实的 LSQ 定义域与语义 ──────────────────────────────────

def test_lsq_definition_domain_matches_standard():
    """LSQ 定义域 0-4，且"文件传输结束"与"本节结束"两组互斥、不重叠."""
    assert LSQ_NOT_USED == 0
    assert LSQ_FILE_TRANSFER_WITHOUT_DEACT == 1
    assert LSQ_FILE_COMPLETE == (1, 2)
    assert LSQ_SECTION_COMPLETE == (3, 4)
    assert set(LSQ_FILE_COMPLETE).isdisjoint(LSQ_SECTION_COMPLETE)
    assert sorted(set(LSQ_FILE_COMPLETE) | set(LSQ_SECTION_COMPLETE)) == [1, 2, 3, 4]


@pytest.mark.parametrize("lsq", [1, 2])
def test_file_transfer_lsq_completes_and_delivers_file(lsq):
    """LSQ=1/2（FILE_TRANSFER_*）→ 判定整个文件接收完成并回调交付数据."""
    mgr, received = _receiver()
    mgr.handle_file_segment(_segment(b"AB"))

    mgr.handle_last_section(_last_section(lsq=lsq))

    assert mgr.state is FileTransferState.COMPLETED
    assert received == [b"AB"]
    assert mgr.context.lsq == lsq


@pytest.mark.parametrize("lsq", [3, 4])
def test_section_transfer_lsq_does_not_complete_file(lsq):
    """LSQ=3/4（SECTION_TRANSFER_*）→ 仅本节结束，**不得**判定文件完成."""
    mgr, received = _receiver()
    mgr.handle_file_segment(_segment(b"AB"))

    mgr.handle_last_section(_last_section(lsq=lsq))

    assert mgr.state is FileTransferState.LAST_SECTION
    assert received == []
    assert mgr.context.lsq == lsq


def test_lsq_not_used_is_not_a_completion_signal():
    """LSQ=0（NOT_USED）→ 不表示任何传输结束（目录结束标记即此值）."""
    mgr, received = _receiver()

    mgr.handle_last_section(_last_section(lsq=LSQ_NOT_USED))

    assert mgr.state is FileTransferState.LAST_SECTION
    assert received == []


def test_undefined_lsq_is_warned_and_not_treated_as_completion(caplog):
    """非法组合：LSQ=7（超出 0-4 定义域）→ 记告警且不判定完成."""
    mgr, received = _receiver()

    with caplog.at_level("WARNING", logger="iec104.file_transfer"):
        mgr.handle_last_section(_last_section(lsq=7))

    assert mgr.state is FileTransferState.LAST_SECTION
    assert received == []
    assert any("不在标准定义域" in r.getMessage() for r in caplog.records)


def test_chs_octet_does_not_drive_completion():
    """完成判定只看 LSQ 八位组，与 CHS（校验和）取值无关.

    核心回归点：修正前实现读的是第 5 字节（标准中的 CHS），于是任何"校验和恰好为
    1/2"的报文都会被误判为传输完成（而"LSQ=1、校验和为别的值"反而不会完成）。
    """
    mgr, received = _receiver()

    mgr.handle_last_section(_last_section(lsq=3, chs=1))   # LSQ=本节结束，CHS 恰为 1

    assert mgr.state is FileTransferState.LAST_SECTION
    assert received == []


# ── ② 发送侧：LSQ 落在正确八位组，且与段数无关 ────────────────────

@pytest.mark.parametrize("size,expected_segments", [(0, 0), (1, 1), (200, 1), (201, 2), (700, 4)])
def test_last_section_always_sends_file_transfer_lsq(size, expected_segments):
    """无论文件被切成几段，F_LS 的 LSQ 恒为 1（整个文件传输结束）.

    回归点：修正前实现把"段数"写进 LSQ 八位组、把常量 1 写进 CHS 八位组。
    对 ≥3 段的文件，LSQ 会落在 3/4（=仅本节结束）甚至 >4（非法）区间。
    """
    mgr, sent = _slave_with_file(b"\x5a" * size)

    _upload_whole_file(mgr)

    body = sent[-1][IO_BODY_OFFSET:]
    assert len(body) == 5
    assert body[3] == LSQ_FILE_TRANSFER_WITHOUT_DEACT
    assert mgr.context.segment_number == expected_segments
    # CHS 校验和算法待核实（见 docs/file_transfer_fls.md），当前发送占位 0
    assert body[4] == 0


def test_upload_roundtrip_completes_on_master_side():
    """上送侧发出的 F_LS 经 ASDU 解码后，在主站侧仍判定为"文件完成"（收发闭环）."""
    mgr, sent = _slave_with_file(b"\x01\x02\x03")

    _upload_whole_file(mgr)

    segment_asdu = ASDU.decode(sent[-2])      # 倒数第 2 帧 = 唯一一段
    last_asdu = ASDU.decode(sent[-1])         # 最后一帧 = F_LS

    receiver, received = _receiver()
    receiver.handle_file_segment(segment_asdu.objects[0].data)
    receiver.handle_last_section(last_asdu.objects[0].data)

    assert receiver.state is FileTransferState.COMPLETED
    assert received == [b"\x01\x02\x03"]


def test_directory_terminator_uses_lsq_not_used():
    """目录传输的结束标记：F_LS 的 LSQ = 0（NOT_USED），不表示文件完成."""
    mgr, sent = _slave_with_file(b"x")

    mgr.handle_file_request(IOA, FILE_NAME, 5)   # SCQ=5 → 请求目录

    body = sent[-1][IO_BODY_OFFSET:]
    assert body[3] == LSQ_NOT_USED


# ── ③ 缺陷钉桩：当前与标准不符，修复后需同步改断言 ────────────────

def test_fr_sr_io_body_length_matches_standard():
    """F_FR/F_SR 信息体长度与标准一致：LOF 为 24 位（3 字节）→ F_FR=6、F_SR=7.

    标准（lib60870 ``FileObjects.cs``）：F_FR = ``NOF(2)+LOF(3)+FRQ(1)`` = **6** 字节、
    F_SR = ``NOF(2)+NOS(1)+LOF(3)+SRQ(1)`` = **7** 字节。
    （原缺陷钉桩：本实现曾把 LOF 当 32 位 → F_FR=7、F_SR=8，已修。）
    """
    assert len(ASDUBuilder.build_file_ready(1, IOA, FILE_NAME, 1024, 0)) - IO_BODY_OFFSET == 6
    assert len(ASDUBuilder.build_section_ready(1, IOA, FILE_NAME, 1, 1024, 0)) - IO_BODY_OFFSET == 7


def test_sg_io_body_matches_standard_layout():
    """F_SG 信息体 = ``NOF(2)+NOS(1)+LOS(1)+数据``，无段号字段，LOS=本段长度.

    标准：F_SG = ``NOF(2)+NOS(1)+LOS(1)+数据``，**没有段号字段**（LOS 即本段长度）。
    （原缺陷钉桩：本实现曾在第 4 字节插入"段号"，使信息体比标准多 1 字节，已修。）
    """
    body = ASDUBuilder.build_file_segment(1, IOA, FILE_NAME, 1, b"AB")[IO_BODY_OFFSET:]

    assert body == bytes([FILE_NAME, 0, 1, 2]) + b"AB"      # 标准布局：LOS=2 在第 4 字节
    assert len(body) == 4 + len(b"AB")


def test_last_section_field_names_disagree_with_standard_currently_known_defect():
    """**已知缺陷（待修）**：``LastSection`` 字段命名与标准语义不符.

    标准字段名是 LSQ（限定词）与 CHS（校验和）；本实现命名为 ``last_segment``（段号）
    与 ``status``（状态），且 ``types.py`` 与 ``file_transfer.py`` 的旧注释各自给出
    互相矛盾的解释。本用例钉住 **字节位置** 映射，供修复时改名为 ``lsq``/``chs``。
    """
    ls = _last_section(lsq=1, chs=0)

    assert ls.to_bytes() == bytes([FILE_NAME, 0, 1, 1, 0])   # 末字节对 = (LSQ, CHS)
    assert ls.status_str == "缺省"                            # 旧标注按"状态"解释，语义有误


def test_scq_qualifier_table_matches_standard():
    """SCQ 取值表与标准一致（lib60870 ``SelectAndCallQualifier``）.

    1=SELECT_FILE、2=REQUEST_FILE、3=DEACTIVATE_FILE、4=DELETE_FILE、
    5=SELECT_SECTION、6=REQUEST_SECTION、7=DEACTIVATE_SECTION。
    （原缺陷钉桩：本实现旧表为 1=请求读、2=停止、3=删除、4=选择、5=请求目录，已修。）
    """
    from core.protocol.types import FileSelectCallGet

    assert FileSelectCallGet(qualifier=1).qualifier_str == "选择文件"
    assert FileSelectCallGet(qualifier=2).qualifier_str == "请求文件"
    assert FileSelectCallGet(qualifier=3).qualifier_str == "去激活文件"
    assert FileSelectCallGet(qualifier=4).qualifier_str == "删除文件"
    assert FileSelectCallGet(qualifier=5).qualifier_str == "选择节"
    assert FileSelectCallGet(qualifier=6).qualifier_str == "请求节"
    assert FileSelectCallGet(qualifier=7).qualifier_str == "去激活节"


def test_handle_file_request_scq4_deletes_file_and_never_uploads():
    """SCQ=4（标准 = DELETE_FILE）必须走删除分支：不上送任何文件帧，且文件被移除.

    回归点：旧实现把 SCQ=4 当"选择文件"，会向真机回送 F_FR_NA_1(=120) 触发整个
    文件上送——真机语义下这是"删除文件"，行为完全相反。
    """
    mgr, sent = _slave_with_file(b"payload")

    mgr.handle_file_request(IOA, FILE_NAME, qualifier=4)

    # 不得发出 F_FR_NA_1(=120) 等任何文件上送帧；只回一条 F_AF_NA_1(=124) 确认
    assert len(sent) == 1
    assert all(frame[0] != 120 for frame in sent)
    assert sent[0][0] == 124                # F_AF_NA_1（AFQ 肯定文件）
    assert FILE_NAME not in mgr._file_data  # 文件已从缓存删除

    # 删除后同文件再请求（SCQ=2 请求文件）→ 上送空文件（长度 0）
    sent.clear()
    mgr.handle_file_request(IOA, FILE_NAME, qualifier=2)
    assert sent and sent[0][0] == 120       # 仍按流程回 F_FR_NA_1


def test_handle_file_request_scq2_requests_file():
    """SCQ=2（REQUEST_FILE）与 SCQ=1（SELECT_FILE）一样触发文件上送流程."""
    mgr, sent = _slave_with_file(b"payload")

    mgr.handle_file_request(IOA, FILE_NAME, qualifier=2)

    assert sent and sent[0][0] == 120       # F_FR_NA_1


# ── ④ 裸字节钉桩：直接解一条手工构造的 F_LS 线缆帧 ─────────────────

def _raw_fls_frame(lsq: int, chs: int) -> bytes:
    """手工构造一条 F_LS_NA_1 线缆帧（不经过本仓库编码器）.

    布局（已核实，见 docs/file_transfer_fls.md §2.2）：
      [0]=TypeID 123, [1]=VSQ, [2..3]=COT, [4..5]=CA,
      [6..8]=IOA(3), [9..10]=NOF(2, LE), [11]=NOS, [12]=LSQ, [13]=CHS
    """
    return bytes([
        123, 1, 13, 0, 1, 0,
        IOA & 0xFF, (IOA >> 8) & 0xFF, (IOA >> 16) & 0xFF,
        FILE_NAME & 0xFF, (FILE_NAME >> 8) & 0xFF,
        1, lsq, chs,
    ])


def test_raw_wire_fls_lsq_is_octet_4_and_chs_is_octet_5():
    """裸字节钉桩：LSQ 在第 4 个信息体八位组、CHS 在第 5 个（两者不得颠倒）."""
    for lsq in (0, 1, 2, 3, 4):
        for chs in (0, 1, 255):
            frame = _raw_fls_frame(lsq, chs)
            body = frame[IO_BODY_OFFSET:]
            assert len(body) == 5
            assert body[:3] == bytes([FILE_NAME & 0xFF, FILE_NAME >> 8, 1])
            assert body[3] == lsq           # 第 4 字节 = LSQ
            assert body[4] == chs           # 第 5 字节 = CHS

            # 解码后经管理器判定：结论只由第 4 字节决定
            decoded = ASDU.decode(frame).objects[0].data
            mgr, received = _receiver()
            mgr.handle_last_section(decoded)

            if lsq in (1, 2):
                assert mgr.state is FileTransferState.COMPLETED
                assert received == [b""]     # 无段数据 → 交付空文件
            else:
                assert mgr.state is FileTransferState.LAST_SECTION
                assert received == []


def test_raw_wire_chs_never_flips_completion():
    """裸字节回归：第 5 字节（CHS）取任意值都不得改变完成判定."""
    for chs in (0, 1, 2, 3, 255):
        mgr, received = _receiver()
        mgr.handle_last_section(ASDU.decode(_raw_fls_frame(3, chs)).objects[0].data)
        assert mgr.state is FileTransferState.LAST_SECTION, f"CHS={chs} 误判为完成"
        assert received == []
