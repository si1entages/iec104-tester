"""日志查看器和连接状态面板."""

from __future__ import annotations

import time
import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QLabel, QCheckBox, QComboBox, QGroupBox,
    QGridLayout, QFrame,
)


class LogViewer(QWidget):
    """日志/事件查看器."""

    MAX_LINES = 10000

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        toolbar = QHBoxLayout()

        self._clear_btn = QPushButton("清空")
        self._clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self._clear_btn)

        toolbar.addWidget(QLabel("级别:"))
        self._level_combo = QComboBox()
        self._level_combo.addItems(["全部", "DEBUG", "INFO", "WARNING", "ERROR"])
        self._level_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._level_combo)

        self._auto_scroll = QCheckBox("自动滚动")
        self._auto_scroll.setChecked(True)
        toolbar.addWidget(self._auto_scroll)

        toolbar.addStretch()

        self._count_label = QLabel("0 条")
        toolbar.addWidget(self._count_label)

        layout.addLayout(toolbar)

        # 日志显示
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Cascadia Code", 11))
        layout.addWidget(self._text)

        self._entries: list[tuple[float, str, str]] = []  # (time, level, message)
        self._filter_level = "全部"

        # 颜色
        self._colors = {
            "DEBUG": QColor("#6c7086"),
            "INFO": QColor("#cdd6f4"),
            "WARNING": QColor("#f9e2af"),
            "ERROR": QColor("#f38ba8"),
            "EVENT": QColor("#cba6f7"),
        }

    def add_log(self, message: str, level: str = "INFO", timestamp: float = None) -> None:
        """添加日志."""
        ts = timestamp or time.time()
        self._entries.append((ts, level, message))

        if self._filter_level != "全部" and level != self._filter_level:
            return

        self._append_text(message, level, ts)
        self._count_label.setText(f"{len(self._entries)} 条")

        if len(self._entries) > self.MAX_LINES:
            self._entries = self._entries[-self.MAX_LINES:]

    def add_event(self, event_type: str, data: dict) -> None:
        """添加事件记录."""
        msg = f"[{event_type}] {data}"
        self.add_log(msg, "EVENT")

    def _append_text(self, message: str, level: str, timestamp: float) -> None:
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)

        ts = time.strftime("%H:%M:%S", time.localtime(timestamp))
        ms = int(timestamp % 1 * 1000)
        text = f"[{ts}.{ms:03d}] [{level:7s}] {message}\n"

        fmt = QTextCharFormat()
        fmt.setForeground(self._colors.get(level, QColor("#cdd6f4")))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)

        if self._auto_scroll.isChecked():
            scrollbar = self._text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _clear(self) -> None:
        self._text.clear()
        self._entries.clear()
        self._count_label.setText("0 条")

    def _apply_filter(self, level: str) -> None:
        self._filter_level = level
        self._text.clear()
        for ts, lvl, msg in self._entries:
            if level == "全部" or lvl == level:
                self._append_text(msg, lvl, ts)


class StatusPanel(QWidget):
    """连接状态面板 — 显示协议状态、定时器、序列号等."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 连接状态
        conn_group = QGroupBox("连接状态")
        conn_layout = QGridLayout()

        conn_layout.addWidget(QLabel("状态:"), 0, 0)
        self._state_label = QLabel("已断开")
        self._state_label.setObjectName("statusDisconnected")
        conn_layout.addWidget(self._state_label, 0, 1)

        conn_layout.addWidget(QLabel("对端:"), 0, 2)
        self._peer_label = QLabel("-")
        conn_layout.addWidget(self._peer_label, 0, 3)

        conn_layout.addWidget(QLabel("运行时间:"), 1, 0)
        self._uptime_label = QLabel("-")
        conn_layout.addWidget(self._uptime_label, 1, 1)

        conn_layout.addWidget(QLabel("连接数:"), 1, 2)
        self._conn_count_label = QLabel("0")
        conn_layout.addWidget(self._conn_count_label, 1, 3)

        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # 序列号状态
        seq_group = QGroupBox("序列号 / 流控")
        seq_layout = QGridLayout()

        seq_layout.addWidget(QLabel("V(S):"), 0, 0)
        self._vs_label = QLabel("0")
        seq_layout.addWidget(self._vs_label, 0, 1)

        seq_layout.addWidget(QLabel("V(R):"), 0, 2)
        self._vr_label = QLabel("0")
        seq_layout.addWidget(self._vr_label, 0, 3)

        seq_layout.addWidget(QLabel("未确认:"), 1, 0)
        self._unack_label = QLabel("0")
        seq_layout.addWidget(self._unack_label, 1, 1)

        seq_layout.addWidget(QLabel("k/w:"), 1, 2)
        self._kw_label = QLabel("12/8")
        seq_layout.addWidget(self._kw_label, 1, 3)

        seq_group.setLayout(seq_layout)
        layout.addWidget(seq_group)

        # 定时器状态
        timer_group = QGroupBox("定时器")
        timer_layout = QGridLayout()

        self._timer_labels = {}
        for i, (name, desc) in enumerate([
            ("t0", "连接建立"), ("t1", "发送确认"),
            ("t2", "延迟确认"), ("t3", "空闲测试"),
        ]):
            row, col = divmod(i, 2)
            timer_layout.addWidget(QLabel(f"{name} ({desc}):"), row, col * 2)
            label = QLabel("-")
            self._timer_labels[name] = label
            timer_layout.addWidget(label, row, col * 2 + 1)

        timer_group.setLayout(timer_layout)
        layout.addWidget(timer_group)

        # 通信统计
        stats_group = QGroupBox("通信统计")
        stats_layout = QGridLayout()

        stats_layout.addWidget(QLabel("发送帧数:"), 0, 0)
        self._tx_frames = QLabel("0")
        stats_layout.addWidget(self._tx_frames, 0, 1)

        stats_layout.addWidget(QLabel("接收帧数:"), 0, 2)
        self._rx_frames = QLabel("0")
        stats_layout.addWidget(self._rx_frames, 0, 3)

        stats_layout.addWidget(QLabel("发送字节:"), 1, 0)
        self._tx_bytes = QLabel("0")
        stats_layout.addWidget(self._tx_bytes, 1, 1)

        stats_layout.addWidget(QLabel("接收字节:"), 1, 2)
        self._rx_bytes = QLabel("0")
        stats_layout.addWidget(self._rx_bytes, 1, 3)

        stats_layout.addWidget(QLabel("错误数:"), 2, 0)
        self._errors = QLabel("0")
        self._errors.setStyleSheet("color: #f38ba8;")
        stats_layout.addWidget(self._errors, 2, 1)

        stats_layout.addWidget(QLabel("重连数:"), 2, 2)
        self._reconnects = QLabel("0")
        stats_layout.addWidget(self._reconnects, 2, 3)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()

    def update_state(self, state: str, connected: bool = False) -> None:
        self._state_label.setText(state)
        if connected:
            self._state_label.setObjectName("statusConnected")
        else:
            self._state_label.setObjectName("statusDisconnected")
        self._state_label.style().unpolish(self._state_label)
        self._state_label.style().polish(self._state_label)

    def update_sequences(self, vs: int, vr: int, unack: int, k: int, w: int) -> None:
        self._vs_label.setText(str(vs))
        self._vr_label.setText(str(vr))
        self._unack_label.setText(str(unack))
        self._kw_label.setText(f"{k}/{w}")

        # 未确认接近上限时标红
        if unack >= k * 0.8:
            self._unack_label.setStyleSheet("color: #f38ba8; font-weight: bold;")
        else:
            self._unack_label.setStyleSheet("")

    def update_timer(self, name: str, remaining: float, active: bool) -> None:
        label = self._timer_labels.get(name)
        if label:
            if active:
                label.setText(f"{remaining:.1f}s")
                if remaining < 3:
                    label.setStyleSheet("color: #f38ba8;")
                else:
                    label.setStyleSheet("color: #a6e3a1;")
            else:
                label.setText("-")
                label.setStyleSheet("")

    def update_stats(self, tx_frames: int, rx_frames: int,
                      tx_bytes: int, rx_bytes: int,
                      errors: int = 0, reconnects: int = 0,
                      conn_count: int = 0) -> None:
        self._tx_frames.setText(str(tx_frames))
        self._rx_frames.setText(str(rx_frames))
        self._tx_bytes.setText(self._format_bytes(tx_bytes))
        self._rx_bytes.setText(self._format_bytes(rx_bytes))
        self._errors.setText(str(errors))
        self._reconnects.setText(str(reconnects))
        self._conn_count_label.setText(str(conn_count))

    def update_peer(self, peer: str) -> None:
        self._peer_label.setText(peer or "-")

    def update_uptime(self, seconds: float) -> None:
        h, r = divmod(int(seconds), 3600)
        m, s = divmod(r, 60)
        self._uptime_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    @staticmethod
    def _format_bytes(n: int) -> str:
        if n < 1024:
            return f"{n} B"
        elif n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        else:
            return f"{n / 1024 / 1024:.1f} MB"
