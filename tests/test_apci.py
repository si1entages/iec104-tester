"""APCI帧编解码测试."""

import pytest

from core.protocol.apci import APCICodec
from core.protocol.constants import (
    START_BYTE,
    U_STARTDT_ACT,
    U_STARTDT_CON,
    U_STOPDT_ACT,
    U_STOPDT_CON,
    U_TESTFR_ACT,
    U_TESTFR_CON,
)


def test_apci_rejects_length_below_control_field():
    """长度域 0-3 不可能容纳 4 字节控制域，必须拒绝."""
    for length in (0, 1, 2, 3):
        with pytest.raises(ValueError, match="length too small"):
            APCICodec.decode(bytes([START_BYTE, length, 0, 0, 0, 0]))


def test_apci_u_frame():
    """测试 U 帧编解码."""
    print("=== U-Frame Tests ===")

    for name, func, expected_byte in [
        ("STARTDT ACT", APCICodec.startdt_act, U_STARTDT_ACT),
        ("STARTDT CON", APCICodec.startdt_con, U_STARTDT_CON),
        ("STOPDT ACT", APCICodec.stopdt_act, U_STOPDT_ACT),
        ("STOPDT CON", APCICodec.stopdt_con, U_STOPDT_CON),
        ("TESTFR ACT", APCICodec.testfr_act, U_TESTFR_ACT),
        ("TESTFR CON", APCICodec.testfr_con, U_TESTFR_CON),
    ]:
        frame = func()
        assert frame[0] == START_BYTE, f"{name}: wrong start byte"
        assert frame[1] == 4, f"{name}: wrong length"
        assert frame[2] == expected_byte, f"{name}: wrong control byte"

        apci, consumed = APCICodec.decode(frame)
        assert apci.is_u_frame, f"{name}: not U-frame"
        assert apci.u_func == expected_byte, f"{name}: wrong func"
        assert consumed == 6, f"{name}: wrong consumed"

    print("  ✅ All U-frame tests passed")


def test_apci_s_frame():
    """测试 S 帧编解码."""
    print("=== S-Frame Tests ===")

    for rx_seq in [0, 1, 100, 32767]:
        frame = APCICodec.encode_s(rx_seq)
        assert frame[0] == START_BYTE
        assert frame[1] == 4

        apci, _ = APCICodec.decode(frame)
        assert apci.is_s_frame
        assert apci.rx_seq == rx_seq

    print("  ✅ All S-frame tests passed")


def test_apci_i_frame():
    """测试 I 帧编解码."""
    print("=== I-Frame Tests ===")

    for tx_seq, rx_seq in [(0, 0), (1, 1), (100, 50), (32767, 32767)]:
        asdu_data = bytes([0x01, 0x01, 0x03, 0x00, 0x01, 0x00, 0x01, 0x00])
        frame = APCICodec.encode_i(tx_seq, rx_seq, asdu_data)

        assert frame[0] == START_BYTE
        assert frame[1] == 4 + len(asdu_data)

        apci, consumed = APCICodec.decode(frame)
        assert apci.is_i_frame
        assert apci.tx_seq == tx_seq
        assert apci.rx_seq == rx_seq
        assert apci.asdu_length == len(asdu_data)

    print("  ✅ All I-frame tests passed")
