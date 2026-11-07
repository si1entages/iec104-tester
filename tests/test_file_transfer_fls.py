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
    SCQ_REQUEST_FILE,
    SCQ_REQUEST_SECTION,
    SCQ_SELECT_FILE,
    FileTransferManager,
    FileTransferSlave,
    FileTransferState,
)
from core.protocol.types import FileSegment, LastSection

#: ASDU 头(类型1 + VSQ1 + COT2 + 公共地址2) + IOA3 = 9 字节；其后为信息体
IO_BODY_OFFSET = 9
FILE_NAME = 5
IOA = 100


# ── helpers ─────────────────────────────────────────────────────

def _last_section(lsq: int, chs: int = 0) -> LastSection:
    """构造 F_LS_NA_1 信息对象：第 4 字节 = LSQ，第 5 字节 = CHS."""
    return LastSection(ioa=IOA, file_name=FILE_NAME, section_name=1,
                       lsq=lsq, chs=chs)


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
    """跑完一遍标准上送流程：SELECT → F_FR → REQUEST → F_SR → SECTION → F_SG/F_LS."""
    mgr.handle_file_request(IOA, FILE_NAME, SCQ_SELECT_FILE)
    mgr.handle_file_request(IOA, FILE_NAME, SCQ_REQUEST_FILE)
    mgr.handle_file_request(IOA, FILE_NAME, SCQ_REQUEST_SECTION)


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
    # CHS = 本节所有段八位组的算术和 mod 256（b"\x5a" * size）
    assert body[4] == (0x5A * size) % 256


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


# ── ③ 缺陷钉桩（已全部翻转为标准断言；下述用例保留为长期回归） ──────

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


def test_last_section_field_names_match_standard():
    """``LastSection`` 字段名与标准语义一致：lsq（限定词）/ chs（校验和）.

    （原缺陷钉桩：字段名为 ``last_segment``/``status``，与标准命名相悖且旧注释
    互相矛盾，已按字节位置映射更名为 ``lsq``/``chs``。）
    """
    ls = _last_section(lsq=1, chs=0)

    assert ls.to_bytes() == bytes([FILE_NAME, 0, 1, 1, 0])   # 末两字节 = (LSQ, CHS)
    assert ls.lsq_str == "FILE_TRANSFER_WITHOUT_DEACT"
    assert LastSection(lsq=4).lsq_str == "SECTION_TRANSFER_WITH_DEACT"
    assert LastSection(lsq=9).lsq_str == "未定义(9)"         # 超出 0-4 定义域


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


# ── ⑤ CHS 校验和：发送侧按算术和 mod 256 计算，接收侧校验不通过仅告警 ──

def test_section_checksum_known_vectors():
    """CHS 算法锚定：算术和 mod 256（溢出回绕、空节为 0）."""
    from core.protocol.file_transfer import CHECKSUM_MODULUS, section_checksum

    assert CHECKSUM_MODULUS == 256
    assert section_checksum(b"") == 0
    assert section_checksum(b"\x01\x02\x03") == 6
    assert section_checksum(b"\xff\x02") == 0x01    # 0x101 → mod 256 回绕
    assert section_checksum(b"\x5a" * 700) == (0x5A * 700) % 256


def test_send_side_writes_computed_chs_octet():
    """发送侧 F_LS 的第 5 字节 = 已发段数据的算术和 mod 256（不再是占位 0）."""
    payload = bytes(range(50))                       # sum=1225 → 1225 % 256 = 201
    mgr, sent = _slave_with_file(payload)

    _upload_whole_file(mgr)

    body = sent[-1][IO_BODY_OFFSET:]
    assert body[3] == LSQ_FILE_TRANSFER_WITHOUT_DEACT
    assert body[4] == 201
    from core.protocol.file_transfer import section_checksum
    assert body[4] == section_checksum(payload)


def test_file_end_marker_section_skips_chs_check(caplog):
    """lib60870 末帧用新节号（如 section=3）且 CHS=0：不得按上一节数据误报 CHS 不符."""
    mgr, received = _receiver()
    mgr.handle_file_segment(_segment(b"AB"))          # section 1, sum=0x83

    with caplog.at_level("WARNING", logger="iec104.file_transfer"):
        mgr.handle_last_section(LastSection(
            ioa=IOA, file_name=FILE_NAME, section_name=1, lsq=3, chs=0x83))
        mgr.handle_last_section(LastSection(
            ioa=IOA, file_name=FILE_NAME, section_name=2, lsq=1, chs=0))

    assert mgr.state is FileTransferState.COMPLETED
    assert received == [b"AB"]
    assert not any("CHS mismatch" in r.getMessage() for r in caplog.records)


def test_receive_side_chs_mismatch_warns_but_still_delivers(caplog):
    """接收侧校验不通过 → 记告警，**不丢弃**数据、不阻止完成判定（非标准原文，见 docs §4.1）."""
    mgr, received = _receiver()
    mgr.handle_file_segment(_segment(b"AB"))         # 期望 CHS = 0x41+0x42 = 0x83

    with caplog.at_level("WARNING", logger="iec104.file_transfer"):
        mgr.handle_last_section(_last_section(lsq=1, chs=0x00))   # 错误校验和

    assert mgr.state is FileTransferState.COMPLETED  # 完成判定只看 LSQ
    assert received == [b"AB"]                       # 数据未丢弃
    assert any("CHS mismatch" in r.getMessage() for r in caplog.records)


def test_receive_side_chs_match_no_warning(caplog):
    """接收侧校验通过 → 不产生 CHS 告警."""
    mgr, received = _receiver()
    mgr.handle_file_segment(_segment(b"AB"))

    with caplog.at_level("WARNING", logger="iec104.file_transfer"):
        mgr.handle_last_section(_last_section(lsq=1, chs=0x83))   # 正确校验和

    assert mgr.state is FileTransferState.COMPLETED
    assert received == [b"AB"]
    assert not any("CHS mismatch" in r.getMessage() for r in caplog.records)


def test_receive_side_lsq0_and_undefined_lsq_skip_chs_validation(caplog):
    """LSQ=0（目录结束标记）与超定义域取值不做 CHS 校验."""
    mgr, received = _receiver()

    with caplog.at_level("WARNING", logger="iec104.file_transfer"):
        mgr.handle_last_section(_last_section(lsq=0, chs=0xFF))   # 必然不匹配
        mgr.handle_last_section(_last_section(lsq=9, chs=0xFF))

    assert not any("CHS mismatch" in r.getMessage() for r in caplog.records)
    assert received == []


# ── ⑥ master 协议层红线：SCQ 一律带名常量，任何路径不得发出 DELETE_FILE ──

def _make_master_engine():
    """轻量主站引擎（mock TCPClient），截获 master 协议层实际发出的 ASDU."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from core.engine.master import MasterEngine
    from core.protocol.types import ConnState

    with patch("core.engine.master.TCPClient") as mock_client_cls:
        client = mock_client_cls.return_value
        client.send = AsyncMock()
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.stats = MagicMock()
        engine = MasterEngine(host="127.0.0.1", port=2404, common_addr=1,
                              auto_start=False, auto_gi=False, reconnect=False)
    engine._state_machine._state = ConnState.RUNNING
    return engine, client


def _sent_asdu_frames(client) -> list[bytes]:
    """从 mock 的 client.send 调用中提取全部 ASDU（APDU 去掉 6 字节 APCI 头）."""
    frames = []
    for call in client.send.call_args_list:
        apdu = call.args[0] if call.args else call.kwargs.get("data")
        frames.append(apdu[6:])
    return frames


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args,expected_scq", [
    ("file_select", (0, 5), 1),         # SCQ_SELECT_FILE
    ("file_request", (0, 5), 2),        # SCQ_REQUEST_FILE
    ("file_call_directory", (0,), 5),   # SCQ_REQUEST_DIRECTORY（项目约定，见 ⑦）
])
async def test_master_file_commands_send_named_scq(method, args, expected_scq):
    """master 协议层三个文件命令的 SCQ 字节必须等于带名常量的值.

    回归点：``file_select`` 曾发魔法数字 4——SCQ 表修正后 4=DELETE_FILE，
    "选择文件"会向真机发出**删除文件命令**（破坏性操作）；``file_request``
    曾发 1（新表=SELECT_FILE，语义静默翻转）。
    """
    engine, client = _make_master_engine()
    await getattr(engine, method)(*args)

    frames = _sent_asdu_frames(client)
    assert frames, f"{method} 未发出任何帧"
    body = frames[-1][IO_BODY_OFFSET:]
    assert body[3] == expected_scq


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("file_select", (0, 5)),
    ("file_request", (0, 5)),
    ("file_call_directory", (0,)),
])
async def test_master_never_sends_scq_delete_file(method, args):
    """红线：master 协议层**任何路径**不得发出 SCQ_DELETE_FILE(4).

    当前 master 侧不存在删除文件 API，故凡 F_SC_NA_1/F_SC_NB_1 出帧，
    SCQ 一律不得为 4。
    """
    from core.protocol.asdu import ASDU
    from core.protocol.file_transfer import SCQ_DELETE_FILE
    from core.protocol.types import TypeID

    engine, client = _make_master_engine()
    await getattr(engine, method)(*args)

    frames = _sent_asdu_frames(client)
    assert frames, f"{method} 未发出任何帧"
    for frame in frames:
        asdu = ASDU.decode(frame)
        if asdu.type_id in (TypeID.F_SC_NA_1, TypeID.F_SC_NB_1):
            assert asdu.objects[0].data.qualifier != SCQ_DELETE_FILE, (
                f"{method} 发出了 SCQ=4（DELETE_FILE）——破坏性命令！"
            )


def test_master_manager_request_file_sends_scq_request_file():
    """``FileTransferMaster.request_file``（engine 包装之外的另一条 master 路径）发 SCQ=2.

    回归点：该方法曾发魔法数字 1（新表=SELECT_FILE），已改用 ``SCQ_REQUEST_FILE``。
    """
    from core.protocol.file_transfer import SCQ_REQUEST_FILE, FileTransferMaster

    mgr = FileTransferMaster(common_addr=1)
    sent: list[bytes] = []
    mgr.set_callbacks(on_send_asdu=sent.append)

    mgr.request_file(IOA, FILE_NAME)

    body = sent[0][IO_BODY_OFFSET:]
    assert body[3] == SCQ_REQUEST_FILE
    # 第三方实测：必须 F_SC_NA_1(122)+COT=FILE(13)，不能再用 127/COT=ACT
    asdu = ASDU.decode(sent[0])
    from core.protocol.types import COT, TypeID
    assert asdu.type_id == TypeID.F_SC_NA_1
    assert int(asdu.cot) == int(COT.FILE)


def test_slave_standard_select_request_section_sequence():
    """标准上送序列：SELECT→F_FR、REQUEST→F_SR、SECTION→F_SG/F_LS；不得发 128/129."""
    mgr, sent = _slave_with_file(b"abcdef")

    mgr.handle_file_request(IOA, FILE_NAME, SCQ_SELECT_FILE)
    assert sent[-1][0] == 120

    mgr.handle_file_request(IOA, FILE_NAME, SCQ_REQUEST_FILE)
    assert sent[-1][0] == 121

    mgr.handle_file_request(IOA, FILE_NAME, SCQ_REQUEST_SECTION)
    assert sent[-1][0] == 123
    assert any(f[0] == 125 for f in sent)
    assert all(f[0] not in (128, 129) for f in sent)


@pytest.mark.asyncio
async def test_directory_request_closes_loop_master_to_slave():
    """目录请求**内部闭环**：master 发 SCQ=5（项目约定）→ 子站回目录条目 + F_LS(LSQ=0).

    本仓库内自洽：master ``file_call_directory`` → 子站 ``handle_file_request(5)``
    → 每个文件一条 F_DR_TA_1(126) + 一条 F_LS_NA_1(123, LSQ=0) 终止标记。
    该 5 值与标准表（5=SELECT_SECTION）可能冲突，属项目约定，待真机核实
    （docs/file_transfer_fls.md §4.4）。
    """
    from core.protocol.asdu import ASDU
    from core.protocol.types import TypeID

    master, client = _make_master_engine()
    slave, slave_sent = _slave_with_file(b"x")
    slave.set_file_data(99, b"y")          # 两个文件 → 两条目录条目

    await master.file_call_directory(0)

    master_frames = _sent_asdu_frames(client)
    assert master_frames, "master 未发出目录请求"
    req = ASDU.decode(master_frames[-1])
    assert req.type_id == TypeID.F_SC_NA_1
    assert req.objects[0].data.qualifier == 5

    obj = req.objects[0]
    slave.handle_file_request(obj.ioa, obj.data.file_name, obj.data.qualifier)

    assert len(slave_sent) == 3
    assert all(frame[0] == 126 for frame in slave_sent[:2])      # 2 × F_DR_TA_1
    assert slave_sent[-1][0] == 123                              # F_LS 终止标记
    assert slave_sent[-1][IO_BODY_OFFSET + 3] == LSQ_NOT_USED    # LSQ=0
