"""报文查看器 — HEX 显示 + 协议解析。"""

from __future__ import annotations

import struct
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
    """原始报文 HEX 查看器。

    功能:
    - HEX + ASCII 双栏显示
    - 自动协议解析
    - 颜色区分收发方向
    - 报文过滤
    - 解析/原始报文切换
    """

    MAX_LINES = 5000  # 最大保留行数

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: list[tuple[float, bytes, str]] = []  # (time, data, direction)
        self._paused = False
        self._parse_mode = "parsed"  # "parsed" 或 "raw"

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

        toolbar.addWidget(QLabel("显示:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["解析报文", "原始报文"])
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self._mode_combo)

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
        self._text.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self._text)

        self._rx_color = QColor("#89dceb")   # 青色 - 接收
        self._tx_color = QColor("#a6e3a1")   # 绿色 - 发送
        self._err_color = QColor("#f38ba8")  # 红色 - 错误
        self._info_color = QColor("#cba6f7") # 紫色 - 信息
        self._parsed_color = QColor("#a6adc8")  # 灰色 - 解析信息

    def add_frame(self, data: bytes, direction: str, timestamp: float = None) -> None:
        """添加报文。"""
        if self._paused:
            self._frames.append((timestamp or time.monotonic(), data, direction))
            return

        self._frames.append((timestamp or time.monotonic(), data, direction))
        self._render_frame(data, direction, timestamp)

        # 限制行数
        if len(self._frames) > self.MAX_LINES:
            self._frames = self._frames[-self.MAX_LINES:]

        self._count_label.setText(f"{len(self._frames)} 帧")

        # 自动滚动
        if self._auto_scroll.isChecked():
            scrollbar = self._text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _render_frame(self, data: bytes, direction: str, timestamp: float = None) -> None:
        """渲染单帧。"""
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

        # 写入
        fmt = QTextCharFormat()
        fmt.setForeground(color)

        cursor.setCharFormat(fmt)
        cursor.insertText(f"{header}{arrow}[{len(data)}B] {hex_str}\n")

        # 解析模式下显示解析信息
        if self._parse_mode == "parsed":
            parsed = self._parse_frame_full(data)
            if parsed:
                fmt.setForeground(self._parsed_color)
                cursor.setCharFormat(fmt)
                for line in parsed:
                    cursor.insertText(f"        {line}\n")

    def _parse_frame_full(self, data: bytes) -> list[str]:
        """完整解析帧，返回多行解析结果。"""
        lines = []
        try:
            if len(data) < 6 or data[0] != 0x68:
                return lines

            length = data[1]
            cf = data[2]

            # 帧头解析
            lines.append(f"起始符=0x68, 长度={length}, 控制域=[{data[2]:02X} {data[3]:02X} {data[4]:02X} {data[5]:02X}]")

            # 判断帧类型
            if (cf & 0x01) == 0:
                # I帧
                tx_seq = (data[2] >> 1) | (data[3] << 7)
                rx_seq = (data[4] >> 1) | (data[5] << 7)
                lines.append(f"{{I帧: N(S)={tx_seq}, N(R)={rx_seq}}}")

                # 解析ASDU
                asdu_data = data[6:]
                asdu_lines = self._parse_asdu_full(asdu_data)
                lines.extend(asdu_lines)

            elif (cf & 0x03) == 0x01:
                # S帧
                rx_seq = (data[4] >> 1) | (data[5] << 7)
                lines.append(f"{{S帧: N(R)={rx_seq}}}")

            elif (cf & 0x03) == 0x03:
                # U帧
                funcs = {
                    0x07: "STARTDT ACT", 0x0B: "STARTDT CON",
                    0x13: "STOPDT ACT", 0x23: "STOPDT CON",
                    0x43: "TESTFR ACT", 0x83: "TESTFR CON",
                }
                lines.append(f"{{U帧: {funcs.get(cf, f'0x{cf:02X}')}}}")

        except Exception as e:
            lines.append(f"解析错误: {e}")
        return lines

    def _parse_asdu_full(self, data: bytes) -> list[str]:
        """完整解析ASDU，返回多行解析结果。"""
        lines = []
        try:
            if len(data) < 6:
                return lines

            type_id = TypeID(data[0])
            vsq = data[1]
            cot_raw = data[2] | (data[3] << 8) if len(data) > 3 else data[2]
            cot = cot_raw & 0x3F
            common_addr = data[4] | (data[5] << 8) if len(data) > 5 else data[4]

            sq = (vsq >> 7) & 0x01
            num = vsq & 0x7F

            # 类型标识
            type_names = {
                TypeID.M_SP_NA_1: "M_SP_NA_1 单点信息",
                TypeID.M_SP_TB_1: "M_SP_TB_1 带时标单点信息",
                TypeID.M_DP_NA_1: "M_DP_NA_1 双点信息",
                TypeID.M_DP_TB_1: "M_DP_TB_1 带时标双点信息",
                TypeID.M_ME_NA_1: "M_ME_NA_1 归一化遥测值",
                TypeID.M_ME_NB_1: "M_ME_NB_1 标度化遥测值",
                TypeID.M_ME_NC_1: "M_ME_NC_1 短浮点遥测值",
                TypeID.M_ME_TF_1: "M_ME_TF_1 带时标短浮点遥测值",
                TypeID.M_IT_NA_1: "M_IT_NA_1 累计量",
                TypeID.C_SC_NA_1: "C_SC_NA_1 单命令",
                TypeID.C_DC_NA_1: "C_DC_NA_1 双命令",
                TypeID.C_SE_NA_1: "C_SE_NA_1 归一化设点命令",
                TypeID.C_SE_NC_1: "C_SE_NC_1 短浮点设点命令",
                TypeID.C_IC_NA_1: "C_IC_NA_1 总召唤命令",
                TypeID.C_CI_NA_1: "C_CI_NA_1 累计量召唤命令",
                TypeID.C_CS_NA_1: "C_CS_NA_1 时钟同步命令",
                TypeID.C_RP_NA_1: "C_RP_NA_1 复位进程命令",
                TypeID.C_TS_NA_1: "C_TS_NA_1 测试命令",
                TypeID.M_EI_NA_1: "M_EI_NA_1 初始化结束",
            }
            type_name = type_names.get(type_id, type_id.name)

            # 传送原因
            cot_names = {
                1: "per/cyc", 2: "back", 3: "spont", 4: "init",
                5: "req", 6: "act", 7: "actcon", 8: "deact",
                9: "deactcon", 10: "actterm", 20: "gi",
                21: "gi(con)", 100: "inro", 101: "inro(con)",
            }
            cot_name = cot_names.get(cot, COT(cot).name if cot in COT._value2member_map_ else str(cot))

            lines.append(f"类型标识TI={data[0]}{{{type_name}}}")
            lines.append(f"可变结构限定词VSQ=0x{vsq:02X}{{SQ={sq}(连续{'寻址' if sq else '单个寻址'}), NUM={num}}}")
            lines.append(f"传送原因COT={cot}{{{cot_name}}}, 公共地址={common_addr}")

            # 解析信息对象
            io_data = data[6:]
            io_lines = self._parse_info_objects(type_id, io_data, sq, num)
            lines.extend(io_lines)

        except Exception as e:
            lines.append(f"ASDU解析错误: {e}")
        return lines

    def _parse_info_objects(self, type_id: TypeID, data: bytes, sq: int, num: int) -> list[str]:
        """解析信息对象。"""
        lines = []
        try:
            if sq == 0:
                # 连续寻址 - 只有一个信息对象地址，后续数据连续
                if len(data) < 3:
                    return lines
                ioa = data[0] | (data[1] << 8) | (data[2] << 16)
                lines.append(f"信息对象地址=0x{ioa:06X}({ioa})")

                # 根据类型解析数据
                value_data = data[3:]
                value_str = self._parse_value(type_id, value_data)
                if value_str:
                    lines.append(value_str)
            else:
                # 单个寻址 - 每个信息对象都有独立地址
                offset = 0
                for i in range(min(num, 50)):  # 限制最多解析50个
                    if offset + 3 > len(data):
                        break
                    ioa = data[offset] | (data[offset+1] << 8) | (data[offset+2] << 16)
                    offset += 3

                    value_data = data[offset:]
                    value_str = self._parse_value(type_id, value_data)
                    if value_str:
                        # 计算下一个IOA的偏移
                        next_offset = self._get_value_size(type_id)
                        if next_offset > 0:
                            offset += next_offset
                        lines.append(f"信息对象地址=0x{ioa:06X}({ioa}), {value_str}")
                    else:
                        break

        except Exception as e:
            lines.append(f"信息对象解析错误: {e}")
        return lines

    def _get_value_size(self, type_id: TypeID) -> int:
        """获取值的字节大小。"""
        sizes = {
            TypeID.M_SP_NA_1: 1,   # 单点信息
            TypeID.M_SP_TB_1: 8,   # 带时标单点信息
            TypeID.M_DP_NA_1: 1,   # 双点信息
            TypeID.M_DP_TB_1: 8,   # 带时标双点信息
            TypeID.M_ME_NA_1: 3,   # 归一化遥测值
            TypeID.M_ME_NB_1: 3,   # 标度化遥测值
            TypeID.M_ME_NC_1: 5,   # 短浮点遥测值
            TypeID.M_ME_TF_1: 12,  # 带时标短浮点遥测值
            TypeID.M_IT_NA_1: 5,   # 累计量
            TypeID.C_SC_NA_1: 1,   # 单命令
            TypeID.C_DC_NA_1: 1,   # 双命令
            TypeID.C_SE_NA_1: 3,   # 归一化设点命令
            TypeID.C_SE_NC_1: 5,   # 短浮点设点命令
        }
        return sizes.get(type_id, 0)

    def _parse_value(self, type_id: TypeID, data: bytes) -> str:
        """解析值。"""
        try:
            if type_id in (TypeID.M_ME_NC_1, TypeID.M_ME_TF_1):
                # 短浮点遥测值
                if len(data) < 4:
                    return ""
                value = struct.unpack('<f', data[:4])[0]
                return f"短浮点值={value:.6f}"
            elif type_id == TypeID.M_ME_NA_1:
                # 归一化遥测值
                if len(data) < 2:
                    return ""
                value = struct.unpack('<h', data[:2])[0]
                return f"归一化值={value/32768:.6f}"
            elif type_id == TypeID.M_ME_NB_1:
                # 标度化遥测值
                if len(data) < 2:
                    return ""
                value = struct.unpack('<h', data[:2])[0]
                return f"标度化值={value}"
            elif type_id in (TypeID.M_SP_NA_1, TypeID.M_SP_TB_1):
                # 单点信息
                if len(data) < 1:
                    return ""
                value = data[0] & 0x01
                return f"单点值={'ON' if value else 'OFF'}"
            elif type_id in (TypeID.M_DP_NA_1, TypeID.M_DP_TB_1):
                # 双点信息
                if len(data) < 1:
                    return ""
                value = data[0] & 0x03
                dp_names = {0: "不确定", 1: "分(OFF)", 2: "合(ON)", 3: "中间状态"}
                return f"双点值={dp_names.get(value, str(value))}"
            elif type_id == TypeID.M_IT_NA_1:
                # 累计量
                if len(data) < 4:
                    return ""
                value = struct.unpack('<I', data[:4])[0]
                return f"累计量值={value}"
            elif type_id in (TypeID.C_SC_NA_1, TypeID.C_DC_NA_1):
                # 命令
                if len(data) < 1:
                    return ""
                value = data[0] & 0x01
                return f"命令值={'ON' if value else 'OFF'}"
            elif type_id in (TypeID.C_SE_NA_1,):
                # 归一化设点
                if len(data) < 2:
                    return ""
                value = struct.unpack('<h', data[:2])[0]
                return f"设点值={value/32768:.6f}"
            elif type_id in (TypeID.C_SE_NC_1,):
                # 短浮点设点
                if len(data) < 4:
                    return ""
                value = struct.unpack('<f', data[:4])[0]
                return f"设点值={value:.6f}"
            elif type_id == TypeID.C_IC_NA_1:
                # 总召唤
                if len(data) < 1:
                    return ""
                qoi = data[0]
                return f"召唤限定词={qoi}"
            elif type_id == TypeID.C_CI_NA_1:
                # 累计量召唤
                if len(data) < 1:
                    return ""
                qcc = data[0]
                return f"召唤限定词={qcc}"
            elif type_id == TypeID.C_CS_NA_1:
                # 时钟同步
                if len(data) < 7:
                    return ""
                ms = struct.unpack('<H', data[0:2])[0]
                min_h = data[2]
                hour = data[3]
                day = data[4]
                month = data[5]
                year = data[6]
                return f"时间={year:02d}-{month:02d}-{day:02d} {hour:02d}:{min_h:02d}:{ms:03d}"
            elif type_id == TypeID.C_RP_NA_1:
                # 复位进程
                if len(data) < 1:
                    return ""
                return f"复位原因={data[0]}"
            elif type_id == TypeID.C_TS_NA_1:
                # 测试命令
                if len(data) < 2:
                    return ""
                tsc = struct.unpack('<H', data[:2])[0]
                return f"测试命令码={tsc}"
            elif type_id == TypeID.M_EI_NA_1:
                # 初始化结束
                if len(data) < 1:
                    return ""
                return f"初始化原因={data[0]}"
        except Exception:
            pass
        return ""

    def _parse_asdu(self, data: bytes) -> str:
        """简单解析 ASDU 信息（用于兼容）。"""
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

    def _on_mode_changed(self, mode_text: str) -> None:
        """切换解析模式。"""
        if "解析" in mode_text:
            self._parse_mode = "parsed"
        else:
            self._parse_mode = "raw"
        # 重新渲染所有帧
        self._apply_filter(self._filter_combo.currentText())

    def _toggle_pause(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("▶ 继续" if paused else "⏸ 暂停")

    def _clear(self) -> None:
        self._text.clear()
        self._frames.clear()
        self._count_label.setText("0 帧")

    def _apply_filter(self, filter_text: str) -> None:
        """应用过滤器（重新渲染，批量操作）。"""
        self._text.clear()

        # 过滤帧
        filtered = []
        for ts, data, direction in self._frames:
            if filter_text == "全部":
                filtered.append((ts, data, direction))
            elif filter_text == "仅RX" and direction == "rx":
                filtered.append((ts, data, direction))
            elif filter_text == "仅TX" and direction == "tx":
                filtered.append((ts, data, direction))
            elif filter_text == "仅I帧" and len(data) >= 6 and (data[2] & 0x01) == 0:
                filtered.append((ts, data, direction))
            elif filter_text == "仅U帧" and len(data) >= 6 and (data[2] & 0x03) == 0x03:
                filtered.append((ts, data, direction))
            elif filter_text == "仅S帧" and len(data) >= 6 and (data[2] & 0x03) == 0x01:
                filtered.append((ts, data, direction))

        # 批量渲染（限制最多渲染最后1000条）
        self._text.setUpdatesEnabled(False)
        for ts, data, direction in filtered[-1000:]:
            self._render_frame(data, direction, ts)
        self._text.setUpdatesEnabled(True)
        self._count_label.setText(f"{len(filtered)} 帧")
