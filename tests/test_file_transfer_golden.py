"""文件传输 F_* 类型的字节级黄金用例（T24 5.1~5.4 收口）.

**动机**：收发自洽的往返测试无法发现**对称性**错误——编码器与解码器犯同一个错时，
round-trip 依旧全绿（a75b9da 修的「LSQ/CHS 两字节用反」正是这样潜伏下来的）。
本文件把每个 F_* 类型的**完整线缆帧期望 hex 硬编码**在测试里，期望值不经本仓库
编码器生成，而是按下列标准布局逐字节手工写出（依据见 docs/file_transfer_fls.md §2）：

  帧结构 = TypeID(1) + VSQ(1) + COT(2,LE) + CA(2,LE) + IOA(3,LE) + 信息体
  信息体（不含 IOA）：
    F_FR_NA_1(120)  = NOF(2,LE) + LOF(3,LE) + FRQ(1)          = 6
    F_SR_NA_1(121)  = NOF(2) + NOS(1) + LOF(3,LE) + SRQ(1)    = 7
    F_SC_NA_1(122)  = NOF(2) + NOS(1) + SCQ(1)                = 4
    F_LS_NA_1(123)  = NOF(2) + NOS(1) + LSQ(1) + CHS(1)       = 5
    F_AF_NA_1(124)  = NOF(2) + NOS(1) + AFQ(1)                = 4
    F_SG_NA_1(125)  = NOF(2) + NOS(1) + LOS(1) + 数据          = 4+len（**无段号**）
    F_DR_TA_1(126)  = NOF(2) + LOF(3,LE) + SOF(1) + CP56(7)   = 13
    F_SC_NB_1(127)  = NOF(2) + NOS(1) + SCQ(1)                = 4
    F_FR_NB_1(128)  = NOF(2) + LOF(3,LE) + FRQ(1)             = 6
    F_SR_NB_1(129)  = NOF(2) + NOS(1) + LOF(3,LE) + SRQ(1)    = 7

  **LOF 为 24 位（3 字节）**。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.types import CP56Time2a

#: 公共头部（TypeID 之后由各用例拼）：COT=6(ACT,LE) + CA=1(LE) + IOA=100(3,LE)
_TAIL = bytes([0x06, 0x00, 0x01, 0x00, 0x64, 0x00, 0x00])
_TAIL_FILE = bytes([0x0D, 0x00, 0x01, 0x00, 0x64, 0x00, 0x00])
_NOF5 = bytes([0x05, 0x00])          # NOF=5 (LE)
_LOF1024 = bytes([0x00, 0x04, 0x00])  # LOF=1024=0x000400 (24-bit LE)
#: CP56Time2a(ms=12345, min=7, hour=8, day=9, month=10, year=26) = 39 30 07 08 09 0A 1A
_TT = bytes([0x39, 0x30, 0x07, 0x08, 0x09, 0x0A, 0x1A])


def _tt() -> CP56Time2a:
    return CP56Time2a(millisecond=12345, minute=7, hour=8,
                      day=9, month=10, year=26, weekday=0, invalid=False)


# ── 编码侧：builder 输出必须与手工写出的标准帧逐字节一致 ──────────────

def test_golden_f_fr_n1_120_body_6():
    """F_FR_NA_1：NOF(2)+LOF(3,LE)+FRQ(1)，信息体 6 字节."""
    assert ASDUBuilder.build_file_ready(1, 100, 5, 1024, 0) == (
        bytes([120, 0x01]) + _TAIL_FILE + _NOF5 + _LOF1024 + bytes([0x00])
    )
    assert ASDUBuilder.build_file_ready(1, 100, 5, 1024, 0) == bytes.fromhex(
        "78 01 0d 00 01 00 64 00 00 05 00 00 04 00 00".replace(" ", ""))


def test_golden_f_sr_n1_121_body_7():
    """F_SR_NA_1：NOF(2)+NOS(1)+LOF(3,LE)+SRQ(1)，信息体 7 字节."""
    assert ASDUBuilder.build_section_ready(1, 100, 5, 1, 1024, 0) == (
        bytes([121, 0x01]) + _TAIL_FILE + _NOF5 + bytes([0x01]) + _LOF1024 + bytes([0x00])
    )
    assert ASDUBuilder.build_section_ready(1, 100, 5, 1, 1024, 0) == bytes.fromhex(
        "79 01 0d 00 01 00 64 00 00 05 00 01 00 04 00 00".replace(" ", ""))


def test_golden_f_sc_na1_122_body_4():
    """F_SC_NA_1：NOF(2)+NOS(1)+SCQ(1)，信息体 4 字节（SCQ=1 选择文件）."""
    assert ASDUBuilder.build_call_directory(1, 100, 5, 1, 1) == bytes.fromhex(
        "7a 01 0d 00 01 00 64 00 00 05 00 01 01".replace(" ", ""))


def test_golden_f_sc_na1_directory_cot_overrides():
    """目录召唤 COT 覆盖（T50/C4 §2 组合矩阵）：第 3 字节（COT|T|P/N）随 cot 变化.

    lib60870.NET 实测口径：服务端只认 COT=REQUEST(5) 回 F_DR_TA_1（SCQ 不参与判断）；
    项目约定默认 COT=FILE(13)+SCQ=5 对独立实现无回帧——此用例锁死两条编码路径。
    """
    # 帧形：type/vsq/cot/oa/ca(2) + IOA(3) + NOF(2) + NOS(1) + SCQ(1)
    # 默认：COT=13(FILE) + SCQ=5（项目约定，行为不变）
    assert ASDUBuilder.build_call_directory(1, 0) == bytes.fromhex(
        "7a 01 0d 00 01 00 00 00 00 00 00 00 05".replace(" ", ""))
    # Ed.2/第三方口径：COT=5(REQ) + SCQ=0
    assert ASDUBuilder.build_call_directory(1, 0, cot=5, qualifier=0) == bytes.fromhex(
        "7a 01 05 00 01 00 00 00 00 00 00 00 00".replace(" ", ""))
    # COT=5 + SCQ=5（验证 SCQ 与 COT 解耦）
    assert ASDUBuilder.build_call_directory(1, 0, cot=5, qualifier=5) == bytes.fromhex(
        "7a 01 05 00 01 00 00 00 00 00 00 00 05".replace(" ", ""))


def test_golden_f_ls_na1_123_body_5():
    """F_LS_NA_1：NOF(2)+NOS(1)+LSQ(1)+CHS(1)，信息体 5 字节、末两字节 = LSQ|CHS."""
    assert ASDUBuilder.build_last_section(1, 100, 5, 1, 1, 0xAB) == bytes.fromhex(
        "7b 01 0d 00 01 00 64 00 00 05 00 01 01 ab".replace(" ", ""))


def test_golden_f_af_na1_124_body_4():
    """F_AF_NA_1：NOF(2)+NOS(1)+AFQ(1)，信息体 4 字节（AFQ=3 肯定节）."""
    assert ASDUBuilder.build_ack_file_section(1, 100, 5, 1, 3) == bytes.fromhex(
        "7c 01 0d 00 01 00 64 00 00 05 00 01 03".replace(" ", ""))


def test_golden_f_sg_na1_125_body_4_plus_data():
    """F_SG_NA_1：NOF(2)+NOS(1)+LOS(1)+数据，无段号字段，LOS 在第 4 字节."""
    assert ASDUBuilder.build_file_segment(1, 100, 5, 1, b"\xde\xad\xbe\xef") == bytes.fromhex(
        "7d 01 0d 00 01 00 64 00 00 05 00 01 04 deadbeef".replace(" ", ""))


def test_golden_f_dr_ta1_126_body_13():
    """F_DR_TA_1：NOF(2)+LOF(3,LE)+SOF(1)+CP56Time2a(7)，信息体 13 字节."""
    assert ASDUBuilder.build_directory_entry(1, 100, 5, 1024, 0, _tt()) == bytes.fromhex(
        "7e 01 0d 00 01 00 64 00 00 05 00 00 04 00 00 39 30 07 08 09 0a 1a".replace(" ", ""))


def test_golden_f_sc_nb1_127_body_4():
    """F_SC_NB_1：NOF(2)+NOS(1)+SCQ(1)，信息体 4 字节（SCQ=2 请求文件）."""
    assert ASDUBuilder.build_file_select_call_get(1, 100, 5, 1, 2) == bytes.fromhex(
        "7f 01 06 00 01 00 64 00 00 05 00 01 02".replace(" ", ""))


def test_golden_f_fr_nb1_128_body_6():
    """F_FR_NB_1：NOF(2)+LOF(3,LE)+FRQ(1)，信息体 6 字节."""
    assert ASDUBuilder.build_file_ready_ack(1, 100, 5, 1024, 0) == bytes.fromhex(
        "80 01 06 00 01 00 64 00 00 05 00 00 04 00 00".replace(" ", ""))


def test_golden_f_sr_nb1_129_body_7():
    """F_SR_NB_1：NOF(2)+NOS(1)+LOF(3,LE)+SRQ(1)，信息体 7 字节."""
    assert ASDUBuilder.build_section_ready_ack(1, 100, 5, 1, 1024, 0) == bytes.fromhex(
        "81 01 06 00 01 00 64 00 00 05 00 01 00 04 00 00".replace(" ", ""))


# ── 解码侧：不经本仓库编码器，直接解手工帧并核对字段 ──────────────────

def test_golden_decode_f_fr_24bit_lof_boundary():
    """解码侧独立核对：LOF=0xFF FF FF（24 位上界 16777215）不被误读为 32 位."""
    frame = bytes([120, 0x01]) + _TAIL + _NOF5 + bytes([0xFF, 0xFF, 0xFF, 0x80])
    obj = ASDU.decode(frame).objects[0].data
    assert obj.file_name == 5
    assert obj.file_length == 0xFFFFFF          # 24 位上界（若按 32 位会读出 0x80FFFFFF…）
    assert obj.status == 0x80


def test_golden_decode_f_ls_lsq_chs_octets():
    """解码侧独立核对：第 4 信息体字节 → lsq、第 5 → chs（不得颠倒）."""
    frame = bytes([123, 0x01]) + _TAIL + _NOF5 + bytes([0x01, 0x03, 0x42])
    obj = ASDU.decode(frame).objects[0].data
    assert (obj.file_name, obj.section_name, obj.lsq, obj.chs) == (5, 1, 0x03, 0x42)


def test_golden_decode_f_sg_no_segment_number():
    """解码侧独立核对：第 4 信息体字节 = LOS=3，其后 3 字节全为段数据."""
    frame = bytes([125, 0x01]) + _TAIL + _NOF5 + bytes([0x01, 0x03]) + b"abc" + b"X"
    obj = ASDU.decode(frame).objects[0].data
    assert obj.data == b"abc"                   # LOS=3：只取 3 字节，尾随的 X 不属于本段


def test_golden_decode_f_dr_13_octets():
    """解码侧独立核对：F_DR_TA_1 信息体 13 字节，SOF 在 LOF 之后、时标之前."""
    frame = bytes([126, 0x01]) + _TAIL + _NOF5 + _LOF1024 + bytes([0x40]) + _TT
    obj = ASDU.decode(frame).objects[0].data
    assert (obj.file_name, obj.file_length, obj.status) == (5, 1024, 0x40)
    assert (obj.time_tag.millisecond, obj.time_tag.minute, obj.time_tag.hour) == (12345, 7, 8)
    assert (obj.time_tag.day, obj.time_tag.month, obj.time_tag.year) == (9, 10, 26)


def test_master_processes_multi_entry_directory_sq1():
    """F_DR 多条目（SQ=1 连续编址）必须逐对象处理——lib60870.NET 实测帧回归.

    2026-11-10 实测：目录回帧为单 ASDU 携带 2 条目（IOA 30000/30001 连续编址），
    旧实现只取 objects[0] 丢第二条目（T50/C4 §2 实测发现）。
    """
    from core.engine.master_protocol import MasterProtocolHandler as MasterCommands
    from core.protocol.asdu import ASDU

    # lib60870.NET 实测完整帧（去掉 68 27 起始/长度字节，保留 APCI 控制域 + ASDU）
    frame = bytes.fromhex(
        "00000400"
        "7E8205000100307500010001040000B8A419170A0B1A"
        "0100580200 20BAA419170A0B1A".replace(" ", ""))
    asdu = ASDU.decode(frame[4:])
    assert asdu.sq is True and len(asdu.objects) == 2
    assert asdu.objects[0].ioa == 30000
    assert asdu.objects[0].data.file_name == 1
    assert asdu.objects[0].data.file_length == 1025
    assert asdu.objects[1].ioa == 30001          # SQ=1 连续编址自动 +1
    assert asdu.objects[1].data.file_name == 1   # NOF 同为 TRANSPARENT_FILE
    assert asdu.objects[1].data.file_length == 600

    seen: list[tuple[int, int]] = []

    class _FT:
        state = "IDLE"

        def handle_directory_entry(self, data):
            seen.append((data.file_name, data.file_length))

    class _Engine:
        _file_transfer = _FT()
        _spawn = staticmethod(lambda coro: None)

    MasterCommands(_Engine()).process_file_transfer(asdu)
    assert seen == [(1, 1025), (1, 600)], f"两条目都必须被处理: {seen}"
