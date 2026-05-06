"""主站监控总览 — 连接状态、数据统计、告警汇总."""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QGridLayout, QFrame, QProgressBar,
    QTableWidget, QTableWidgetItem, QHeaderView,
)


class MonitorPanel(QWidget):
    """主站监控总览面板.

    显示:
    - 连接状态概览
    - 数据点统计
    - 最近告警/事件
    - 通信质量指标
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── 连接概览 ──
        conn_group = QGroupBox("连接概览")
        conn_layout = QGridLayout()

        self._state_indicator = QLabel("●")
        self._state_indicator.setStyleSheet("font-size: 24px; color: #f38ba8;")
        self._state_indicator.setAlignment(Qt.AlignCenter)
        conn_layout.addWidget(self._state_indicator, 0, 0, 2, 1)

        self._state_text = QLabel("已断开")
        self._state_text.setStyleSheet("font-size: 16px; font-weight: bold;")
        conn_layout.addWidget(self._state_text, 0, 1, 1, 2)

        self._peer_label = QLabel("对端: -")
        conn_layout.addWidget(self._peer_label, 1, 1)

        self._uptime_label = QLabel("运行时间: 00:00:00")
        conn_layout.addWidget(self._uptime_label, 1, 2)

        # 通信质量
        conn_layout.addWidget(QLabel("通信质量:"), 2, 0)
        self._quality_bar = QProgressBar()
        self._quality_bar.setRange(0, 100)
        self._quality_bar.setValue(100)
        self._quality_bar.setFormat("%p%")
        conn_layout.addWidget(self._quality_bar, 2, 1, 1, 2)

        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # ── 数据统计 ──
        data_group = QGroupBox("数据点统计")
        data_layout = QGridLayout()

        stats = [
            ("遥信 (YX)", "0", "正常"),
            ("遥测 (YC)", "0", "正常"),
            ("遥控 (YK)", "0", "-"),
            ("遥脉 (YM)", "0", "正常"),
        ]
        self._data_labels = {}
        for i, (name, count, status) in enumerate(stats):
            row, col = divmod(i, 2)
            data_layout.addWidget(QLabel(f"{name}:"), row, col * 3)
            count_label = QLabel(count)
            count_label.setStyleSheet("font-weight: bold; font-size: 16px;")
            data_layout.addWidget(count_label, row, col * 3 + 1)
            status_label = QLabel(status)
            data_layout.addWidget(status_label, row, col * 3 + 2)
            self._data_labels[name] = (count_label, status_label)

        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # ── 最近事件 ──
        event_group = QGroupBox("最近事件")
        event_layout = QVBoxLayout()

        self._event_table = QTableWidget()
        self._event_table.setColumnCount(4)
        self._event_table.setHorizontalHeaderLabels(["时间", "类型", "描述", "详情"])
        self._event_table.horizontalHeader().setStretchLastSection(True)
        self._event_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._event_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._event_table.setMaximumHeight(200)
        event_layout.addWidget(self._event_table)

        event_group.setLayout(event_layout)
        layout.addWidget(event_group)

        layout.addStretch()

        # 事件缓冲
        self._events: list[tuple[float, str, str, str]] = []
        self._max_events = 100

    def update_connection(self, state: str, connected: bool, peer: str = "") -> None:
        """更新连接状态."""
        self._state_text.setText(state)
        if connected:
            self._state_indicator.setStyleSheet("font-size: 24px; color: #a6e3a1;")
        else:
            self._state_indicator.setStyleSheet("font-size: 24px; color: #f38ba8;")
        if peer:
            self._peer_label.setText(f"对端: {peer}")

    def update_data_stats(self, yx: int, yc: int, yk: int, ym: int,
                           yx_quality: int = 100, yc_quality: int = 100) -> None:
        """更新数据统计."""
        labels = self._data_labels
        if "遥信 (YX)" in labels:
            labels["遥信 (YX)"][0].setText(str(yx))
            labels["遥信 (YX)"][1].setText(f"质量{yx_quality}%")
        if "遥测 (YC)" in labels:
            labels["遥测 (YC)"][0].setText(str(yc))
            labels["遥测 (YC)"][1].setText(f"质量{yc_quality}%")
        if "遥控 (YK)" in labels:
            labels["遥控 (YK)"][0].setText(str(yk))
        if "遥脉 (YM)" in labels:
            labels["遥脉 (YM)"][0].setText(str(ym))

    def update_quality(self, percent: int) -> None:
        """更新通信质量."""
        self._quality_bar.setValue(percent)
        if percent >= 90:
            self._quality_bar.setStyleSheet("")
        elif percent >= 70:
            self._quality_bar.setStyleSheet("QProgressBar::chunk { background-color: #f9e2af; }")
        else:
            self._quality_bar.setStyleSheet("QProgressBar::chunk { background-color: #f38ba8; }")

    def add_event(self, event_type: str, description: str, detail: str = "") -> None:
        """添加事件."""
        ts = time.strftime("%H:%M:%S")
        self._events.append((time.time(), event_type, description, detail))

        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

        self._refresh_event_table()

    def _refresh_event_table(self) -> None:
        """刷新事件表格."""
        events = self._events[-20:]  # 显示最近20条
        self._event_table.setRowCount(len(events))

        for i, (ts, etype, desc, detail) in enumerate(reversed(events)):
            time_str = time.strftime("%H:%M:%S", time.localtime(ts))
            self._event_table.setItem(i, 0, QTableWidgetItem(time_str))
            self._event_table.setItem(i, 1, QTableWidgetItem(etype))
            self._event_table.setItem(i, 2, QTableWidgetItem(desc))
            self._event_table.setItem(i, 3, QTableWidgetItem(detail))

            # 颜色
            color = None
            if etype in ("ERROR", "告警"):
                color = QColor(243, 139, 168, 30)
            elif etype in ("WARNING", "注意"):
                color = QColor(249, 226, 175, 30)

            if color:
                for col in range(4):
                    item = self._event_table.item(i, col)
                    if item:
                        item.setBackground(color)
