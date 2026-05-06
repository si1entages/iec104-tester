"""报文查看器 — HEX 显示 + 协议解析."""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QCheckBox, QComboBox, QSplitter,
)

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.protocol.types import TypeID, COT, APDUType


class HexViewer(QWidget):
    """原始报文 HEX 查看器.

    功能:
    - HEX + ASCII 双栏显示
    - 自动协议解析
    - 颜色区分收发方向
    - 报文过滤
    """

    MAX_LINES = 5000  # 最大保留行数

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: list[tuple[float, bytes, str]] = []  # (time, data, direction)
        self._paused = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        toolbar = QHBoxLayout()

        self._pause_btn = QPushButton("⏸ 暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._toggle_pause)
        toolbar.addWidget(self._pause_btn)

        self._clear_btn = QPushButton("🗑 清空")
        self._clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self._clear_btn)

        toolbar.addWidget(QLabel("过滤:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["全部", "仅RX", "仅TX", "仅I帧", "仅U帧", "仅S帧"])
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._filter_combo)

        self._auto_scroll = QCheckBox("自动滚动")
        self._auto_scroll.setChecked(True)
        toolbar.addWidget(self._auto_scroll)

        toolbar.addStretch()

        self._count_label = QLabel("0 帧")
        toolbar.addWidget(self._count_label)

        layout.addLayout(toolbar)

        # 报文显示区
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Cascadia Code", 11))
        self._text.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self._text)

        self._rx_color = QColor("#89dceb")   # 青色 - 接收
        self._tx_color = QColor("#a6e3a1")   # 绿色 - 发送
        self._err_color = QColor("#f38ba8")  # 红色 - 错误
        self._info_color = QColor("#cba6f7") # 紫色 - 信息

    def add_frame(self, data: bytes, direction: str, timestamp: float = None) -> None:
        """添加报文."""
        if self._paused:
            self._frames.append((timestamp or time.monotonic(), data, direction))
            return

        self._frames.append((timestamp or time.monotonic(), data, direction))
        self._render_frame(data, direction, timestamp)

        # 限制行数
        if len(self._frames) > self.MAX_LINES:
            self._frames = self._frames[-self.MAX_LINES:]
            # QTextEdit 自动管理

        self._count_label.setText(f"{len(self._frames)} 帧")

        # 自动滚动
        if self._auto_scroll.isChecked():
            scrollbar = self._text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _render_frame(self, data: bytes, direction: str, timestamp: float = None) -> None:
        """渲染单帧."""
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)

        # 时间戳
        ts = time.strftime("%H:%M:%S", time.localtime(timestamp or time.time()))
        ms = int((timestamp or time.time()) % 1 * 1000)
        header = f"[{ts}.{ms:03d}] "

        # 方向标记
        if direction == "rx":
            arrow = "◀ RX "
            color = self._rx_color
        else:
            arrow = "▶ TX "
            color = self._tx_color

        # HEX 显示
        hex_str = " ".join(f"{b:02X}" for b in data)
        if len(hex_str) > 80:
            hex_str = hex_str[:80] + "..."

        # ASCII 显示
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in data[:40])

        # 协议解析
        parsed = self._parse_frame(data)

        # 写入
        fmt = QTextCharFormat()
        fmt.setForeground(color)

        cursor.setCharFormat(fmt)
        cursor.insertText(f"{header}{arrow}[{len(data)}B] {hex_str}\n")

        if parsed:
            fmt.setForeground(QColor("#a6adc8"))
            cursor.setCharFormat(fmt)
            cursor.insertText(f"        {parsed}\n")

    def _parse_frame(self, data: bytes) -> str:
        """尝试解析帧."""
        try:
            if len(data) < 6:
                return ""

            if data[0] != 0x68:
                return ""

            length = data[1]
            cf = data[2]

            # 判断帧类型
            if (cf & 0x01) == 0:
                # I帧
                tx_seq = (data[2] >> 1) | (data[3] << 7)
                rx_seq = (data[4] >> 1) | (data[5] << 7)
                asdu_data = data[6:]
                asdu_info = self._parse_asdu(asdu_data)
                return f"I-frame TX={tx_seq} RX={rx_seq} | {asdu_info}"

            elif (cf & 0x03) == 0x01:
                # S帧
                rx_seq = (data[4] >> 1) | (data[5] << 7)
                return f"S-frame RX={rx_seq}"

            elif (cf & 0x03) == 0x03:
                # U帧
                funcs = {
                    0x07: "STARTDT ACT", 0x0B: "STARTDT CON",
                    0x13: "STOPDT ACT", 0x23: "STOPDT CON",
                    0x43: "TESTFR ACT", 0x83: "TESTFR CON",
                }
                return f"U-frame {funcs.get(cf, f'0x{cf:02X}')}"

        except Exception:
            pass
        return ""

    def _parse_asdu(self, data: bytes) -> str:
        """解析 ASDU 信息."""
        try:
            if len(data) < 6:
                return ""

            type_id = TypeID(data[0])
            vsq = data[1]
            cot = data[2] & 0x3F
            num = vsq & 0x7F

            cot_name = COT(cot).name if cot in COT._value2member_map_ else str(cot)

            type_names = {
                TypeID.M_SP_NA_1: "单点遥信",
                TypeID.M_SP_TB_1: "带时标单点遥信",
                TypeID.M_DP_NA_1: "双点遥信",
                TypeID.M_DP_TB_1: "带时标双点遥信",
                TypeID.M_ME_NA_1: "归一化遥测",
                TypeID.M_ME_NB_1: "标度化遥测",
                TypeID.M_ME_NC_1: "短浮点遥测",
                TypeID.M_ME_TF_1: "带时标短浮点遥测",
                TypeID.M_IT_NA_1: "累计量",
                TypeID.C_SC_NA_1: "单命令",
                TypeID.C_DC_NA_1: "双命令",
                TypeID.C_SE_NA_1: "归一化设点",
                TypeID.C_SE_NC_1: "短浮点设点",
                TypeID.C_IC_NA_1: "总召唤",
                TypeID.C_CI_NA_1: "累计量召唤",
                TypeID.C_CS_NA_1: "时钟同步",
                TypeID.C_RP_NA_1: "复位进程",
                TypeID.C_TS_NA_1: "测试命令",
            }

            type_name = type_names.get(type_id, type_id.name)
            return f"{type_name} COT={cot_name} N={num}"

        except Exception:
            return ""

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("▶ 继续" if paused else "⏸ 暂停")

    def _clear(self) -> None:
        self._text.clear()
        self._frames.clear()
        self._count_label.setText("0 帧")

    def _apply_filter(self, filter_text: str) -> None:
        """应用过滤器（重新渲染）."""
        self._text.clear()
        for ts, data, direction in self._frames:
            if filter_text == "全部":
                self._render_frame(data, direction, ts)
            elif filter_text == "仅RX" and direction == "rx":
                self._render_frame(data, direction, ts)
            elif filter_text == "仅TX" and direction == "tx":
                self._render_frame(data, direction, ts)
            elif filter_text == "仅I帧" and len(data) >= 6 and (data[2] & 0x01) == 0:
                self._render_frame(data, direction, ts)
            elif filter_text == "仅U帧" and len(data) >= 6 and (data[2] & 0x03) == 0x03:
                self._render_frame(data, direction, ts)
            elif filter_text == "仅S帧" and len(data) >= 6 and (data[2] & 0x03) == 0x01:
                self._render_frame(data, direction, ts)
