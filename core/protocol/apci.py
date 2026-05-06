"""APCI (Application Protocol Control Information) — 帧编解码器.

IEC 60870-5-104 帧结构:
  ┌──────┬────────┬──────────────────────┐
  │ 0x68 │ Length │   Control Fields     │
  │ 1B   │ 1B     │   4 bytes            │
  └──────┴────────┴──────────────────────┘

I-Frame (信息传输):
  Byte 1: [0] [SendSeq bit15-8]
  Byte 2: [SendSeq bit7-0]
  Byte 3: [1] [RecvSeq bit15-8]
  Byte 4: [RecvSeq bit7-0]

S-Frame (确认):
  Byte 1: [0] [1]
  Byte 2: [0] [0]
  Byte 3: [1] [RecvSeq bit15-8]
  Byte 4: [RecvSeq bit7-0]

U-Frame (控制):
  Byte 1: [U-type bits]  (STARTDT/STOPDT/TESTFR)
  Byte 2: [0] [0]
  Byte 3: [0] [0]
  Byte 4: [0] [0]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .constants import (
    START_BYTE, APCI_LENGTH,
    U_STARTDT_ACT, U_STARTDT_CON, U_STOPDT_ACT, U_STOPDT_CON,
    U_TESTFR_ACT, U_TESTFR_CON, U_TYPE_MASK,
    I_FORMAT_LENGTH, S_FORMAT_LENGTH, U_FORMAT_LENGTH,
)
from .types import APDUType


@dataclass
class APCI:
    """Application Protocol Control Information."""
    frame_type: APDUType = APDUType.U
    # I-frame fields
    tx_seq: int = 0           # 发送序列号 (0-32767)
    rx_seq: int = 0           # 接收序列号 (0-32767)
    # U-frame fields
    u_func: int = 0           # U帧功能 (STARTDT/STOPDT/TESTFR + ACT/CON)
    # Common
    asdu_length: int = 0      # ASDU长度（不含APCI头）

    @property
    def apdu_length(self) -> int:
        """APDU总长度 = APCI(4) + ASDU."""
        return APCI_LENGTH + self.asdu_length

    @property
    def is_i_frame(self) -> bool:
        return self.frame_type == APDUType.I

    @property
    def is_s_frame(self) -> bool:
        return self.frame_type == APDUType.S

    @property
    def is_u_frame(self) -> bool:
        return self.frame_type == APDUType.U

    @property
    def is_startdt_act(self) -> bool:
        return self.is_u_frame and self.u_func == U_STARTDT_ACT

    @property
    def is_startdt_con(self) -> bool:
        return self.is_u_frame and self.u_func == U_STARTDT_CON

    @property
    def is_stopdt_act(self) -> bool:
        return self.is_u_frame and self.u_func == U_STOPDT_ACT

    @property
    def is_stopdt_con(self) -> bool:
        return self.is_u_frame and self.u_func == U_STOPDT_CON

    @property
    def is_testfr_act(self) -> bool:
        return self.is_u_frame and self.u_func == U_TESTFR_ACT

    @property
    def is_testfr_con(self) -> bool:
        return self.is_u_frame and self.u_func == U_TESTFR_CON


class APCICodec:
    """APCI 编解码器."""

    @staticmethod
    def decode(data: bytes) -> tuple[APCI, int]:
        """解码 APCI.

        Args:
            data: 原始字节数据

        Returns:
            (APCI对象, APCI+ASDU已消费字节数)

        Raises:
            ValueError: 帧格式错误
        """
        if len(data) < 2:
            raise ValueError(f"APCI data too short: {len(data)} bytes")

        if data[0] != START_BYTE:
            raise ValueError(f"Invalid start byte: 0x{data[0]:02X}, expected 0x68")

        length = data[1]
        if length < 4:
            raise ValueError(f"APDU length too small: {length}, minimum is 4")

        # 需要的总字节数 = start(1) + length(1) + length
        total_needed = 2 + length
        if len(data) < total_needed:
            raise ValueError(f"Incomplete APDU: need {total_needed}, have {len(data)}")

        # 提取4字节控制域
        cf = data[2:6]
        asdu_len = length - 4

        apci = APCI()

        # 判断帧类型
        # I帧: bit0 of byte1 = 0
        if (cf[0] & 0x01) == 0:
            # I-Frame
            apci.frame_type = APDUType.I
            apci.tx_seq = (cf[0] >> 1) | (cf[1] << 7)
            apci.rx_seq = (cf[2] >> 1) | (cf[3] << 7)
            apci.asdu_length = asdu_len

        # S帧: bit0=1, bit1=0 of byte1, byte2=0x00
        elif (cf[0] & 0x03) == 0x01 and cf[1] == 0x00:
            # S-Frame
            apci.frame_type = APDUType.S
            apci.rx_seq = (cf[2] >> 1) | (cf[3] << 7)
            apci.asdu_length = 0

        # U帧: bit0=1, bit1=1 of byte1
        elif (cf[0] & 0x03) == 0x03:
            # U-Frame
            apci.frame_type = APDUType.U
            apci.u_func = cf[0]
            apci.asdu_length = 0

        else:
            raise ValueError(f"Unknown frame type: byte1=0x{cf[0]:02X}")

        return apci, total_needed

    @staticmethod
    def encode_i(tx_seq: int, rx_seq: int, asdu_data: bytes) -> bytes:
        """编码 I-Frame.

        Args:
            tx_seq: 发送序列号 (0-32767)
            rx_seq: 接收序列号 (0-32767)
            asdu_data: ASDU 数据

        Returns:
            完整 APDU 字节
        """
        tx_seq = tx_seq & 0x7FFF
        rx_seq = rx_seq & 0x7FFF

        length = 4 + len(asdu_data)  # APCI控制域(4) + ASDU
        if length > 253:
            raise ValueError(f"ASDU too large: {len(asdu_data)} bytes, max 249")

        cf = bytes([
            (tx_seq & 0x7F) << 1,               # byte1: bit0=0(I帧标志), bit1-7=tx_seq低7位
            (tx_seq >> 7) & 0xFF,                # byte2: tx_seq 高8位
            ((rx_seq & 0x7F) << 1) | 0x01,      # byte3: bit0=1, bit1-7=rx_seq低7位
            (rx_seq >> 7) & 0xFF,                # byte4: rx_seq 高8位
        ])

        return bytes([START_BYTE, length]) + cf + asdu_data

    @staticmethod
    def encode_s(rx_seq: int) -> bytes:
        """编码 S-Frame (确认帧)."""
        rx_seq = rx_seq & 0x7FFF

        length = 4  # S帧没有ASDU
        cf = bytes([
            0x01,                               # byte1: bit0=1, bit1=0 (S帧标志)
            0x00,                               # byte2
            ((rx_seq & 0x7F) << 1) | 0x01,      # byte3: 低7位左移 + bit0=1
            (rx_seq >> 7) & 0xFF,               # byte4: 高8位
        ])

        return bytes([START_BYTE, length]) + cf

    @staticmethod
    def encode_u(func: int) -> bytes:
        """编码 U-Frame.

        Args:
            func: U帧功能码 (U_STARTDT_ACT, U_TESTFR_ACT, etc.)
        """
        length = 4
        cf = bytes([
            func,    # byte1: 功能码
            0x00,    # byte2
            0x00,    # byte3
            0x00,    # byte4
        ])

        return bytes([START_BYTE, length]) + cf

    # ── Convenience Methods ────────────────────────────────────────

    @staticmethod
    def startdt_act() -> bytes:
        return APCICodec.encode_u(U_STARTDT_ACT)

    @staticmethod
    def startdt_con() -> bytes:
        return APCICodec.encode_u(U_STARTDT_CON)

    @staticmethod
    def stopdt_act() -> bytes:
        return APCICodec.encode_u(U_STOPDT_ACT)

    @staticmethod
    def stopdt_con() -> bytes:
        return APCICodec.encode_u(U_STOPDT_CON)

    @staticmethod
    def testfr_act() -> bytes:
        return APCICodec.encode_u(U_TESTFR_ACT)

    @staticmethod
    def testfr_con() -> bytes:
        return APCICodec.encode_u(U_TESTFR_CON)
