"""S 帧编码字节级回归测试.

真机实测缺陷：``encode_s`` 曾把 SS 字段的 bit0 置 1（``| 0x01``），产生
``680401001100`` 这类 SS 恒为奇数的畸形确认帧 —— 自家解码用 ``>> 1`` 掩掉
bit0 所以互通自洽，但真机按标准校验直接断开连接。
"""

from __future__ import annotations

import pytest

from core.protocol.apci import APCICodec


@pytest.mark.parametrize("rx_seq,expected_cf", [
    (0, "01000000"),
    (1, "01000200"),
    (7, "01000e00"),
    (8, "01001000"),
    (100, "0100c800"),
    (0x3FFF, "0100fe7f"),
])
def test_encode_s_ss_field_is_even(rx_seq: int, expected_cf: str):
    """S 帧 SS = rx_seq<<1，bit0 恒为 0；整个控制域与标准逐字节一致."""
    frame = APCICodec.encode_s(rx_seq)
    assert frame[:2] == b"\x68\x04"
    assert frame[2:].hex() == expected_cf, (
        f"encode_s({rx_seq}) 控制域错误: {frame[2:].hex()} (期望 {expected_cf})"
    )


def test_encode_s_ss_bit0_always_zero():
    """任意序号下 SS 最低位必须为 0（真机按标准校验，畸形 SS 会被断开）."""
    for seq in range(0, 0x8000, 97):
        frame = APCICodec.encode_s(seq)
        ss = frame[4] | frame[5] << 8
        assert ss & 1 == 0, f"encode_s({seq}) SS=0x{ss:04x} 的 bit0 应为 0"
        assert ss >> 1 == seq


def test_decode_accepts_canonical_s_frame():
    """自家解码器解码标准 S 帧应得到正确 SS."""
    apci, _ = APCICodec.decode(bytes.fromhex("680401001000"))
    assert apci.is_s_frame
    assert apci.rx_seq == 8
