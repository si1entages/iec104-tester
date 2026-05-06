"""主站界面 — 遥控操作面板和命令栏."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QCheckBox, QComboBox,
    QLineEdit, QFormLayout, QFrame, QGridLayout,
)


class CommandBar(QWidget):
    """命令栏 — 总召/时钟同步/复位等快捷操作."""

    gi_requested = Signal()
    ci_requested = Signal()
    clock_sync_requested = Signal()
    reset_requested = Signal()
    test_requested = Signal()
    startdt_requested = Signal()
    stopdt_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 连接控制
        conn_group = QGroupBox("连接")
        conn_layout = QHBoxLayout()
        self._startdt_btn = QPushButton("▶ STARTDT")
        self._startdt_btn.setObjectName("primaryButton")
        self._startdt_btn.clicked.connect(self.startdt_requested.emit)
        conn_layout.addWidget(self._startdt_btn)

        self._stopdt_btn = QPushButton("⏹ STOPDT")
        self._stopdt_btn.setObjectName("dangerButton")
        self._stopdt_btn.clicked.connect(self.stopdt_requested.emit)
        conn_layout.addWidget(self._stopdt_btn)
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # 系统命令
        cmd_group = QGroupBox("系统命令")
        cmd_layout = QHBoxLayout()

        self._gi_btn = QPushButton("📡 总召唤")
        self._gi_btn.clicked.connect(self.gi_requested.emit)
        cmd_layout.addWidget(self._gi_btn)

        self._ci_btn = QPushButton("📊 累计量召唤")
        self._ci_btn.clicked.connect(self.ci_requested.emit)
        cmd_layout.addWidget(self._ci_btn)

        self._clock_btn = QPushButton("🕐 时钟同步")
        self._clock_btn.clicked.connect(self.clock_sync_requested.emit)
        cmd_layout.addWidget(self._clock_btn)

        self._reset_btn = QPushButton("🔄 复位进程")
        self._reset_btn.clicked.connect(self.reset_requested.emit)
        cmd_layout.addWidget(self._reset_btn)

        self._test_btn = QPushButton("🧪 测试")
        self._test_btn.clicked.connect(self.test_requested.emit)
        cmd_layout.addWidget(self._test_btn)

        cmd_group.setLayout(cmd_layout)
        layout.addWidget(cmd_group)

        layout.addStretch()

    def set_connected(self, connected: bool) -> None:
        """设置按钮启用状态."""
        for btn in [self._gi_btn, self._ci_btn, self._clock_btn,
                     self._reset_btn, self._test_btn, self._stopdt_btn]:
            btn.setEnabled(connected)
        self._startdt_btn.setEnabled(connected)


class ControlPanel(QWidget):
    """遥控/遥调操作面板."""

    command_ready = Signal(str, dict)  # (command_type, params)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # ── 单命令 ──
        sc_group = QGroupBox("单命令 (C_SC_NA_1)")
        sc_layout = QGridLayout()

        sc_layout.addWidget(QLabel("IOA:"), 0, 0)
        self._sc_ioa = QSpinBox()
        self._sc_ioa.setRange(0, 16777215)
        sc_layout.addWidget(self._sc_ioa, 0, 1)

        sc_layout.addWidget(QLabel("状态:"), 0, 2)
        self._sc_state = QComboBox()
        self._sc_state.addItems(["OFF (分)", "ON (合)"])
        sc_layout.addWidget(self._sc_state, 0, 3)

        sc_layout.addWidget(QLabel("操作:"), 1, 0)
        self._sc_action = QComboBox()
        self._sc_action.addItems(["执行", "选择"])
        sc_layout.addWidget(self._sc_action, 1, 1)

        sc_layout.addWidget(QLabel("QU:"), 1, 2)
        self._sc_qu = QSpinBox()
        self._sc_qu.setRange(0, 31)
        sc_layout.addWidget(self._sc_qu, 1, 3)

        self._sc_btn = QPushButton("发送单命令")
        self._sc_btn.setObjectName("primaryButton")
        self._sc_btn.clicked.connect(self._send_single_command)
        sc_layout.addWidget(self._sc_btn, 2, 0, 1, 4)

        sc_group.setLayout(sc_layout)
        layout.addWidget(sc_group)

        # ── 双命令 ──
        dc_group = QGroupBox("双命令 (C_DC_NA_1)")
        dc_layout = QGridLayout()

        dc_layout.addWidget(QLabel("IOA:"), 0, 0)
        self._dc_ioa = QSpinBox()
        self._dc_ioa.setRange(0, 16777215)
        dc_layout.addWidget(self._dc_ioa, 0, 1)

        dc_layout.addWidget(QLabel("状态:"), 0, 2)
        self._dc_state = QComboBox()
        self._dc_state.addItems(["不允许", "分(OFF)", "合(ON)", "不允许"])
        dc_layout.addWidget(self._dc_state, 0, 3)

        self._dc_btn = QPushButton("发送双命令")
        self._dc_btn.clicked.connect(self._send_double_command)
        dc_layout.addWidget(self._dc_btn, 1, 0, 1, 4)

        dc_group.setLayout(dc_layout)
        layout.addWidget(dc_group)

        # ── 设点命令 ──
        sp_group = QGroupBox("设点命令 (C_SE_NC_1)")
        sp_layout = QGridLayout()

        sp_layout.addWidget(QLabel("IOA:"), 0, 0)
        self._sp_ioa = QSpinBox()
        self._sp_ioa.setRange(0, 16777215)
        sp_layout.addWidget(self._sp_ioa, 0, 1)

        sp_layout.addWidget(QLabel("值:"), 0, 2)
        self._sp_value = QLineEdit("0.0")
        sp_layout.addWidget(self._sp_value, 0, 3)

        sp_layout.addWidget(QLabel("操作:"), 1, 0)
        self._sp_action = QComboBox()
        self._sp_action.addItems(["执行", "选择"])
        sp_layout.addWidget(self._sp_action, 1, 1)

        self._sp_btn = QPushButton("发送设点命令")
        self._sp_btn.clicked.connect(self._send_setpoint)
        sp_layout.addWidget(self._sp_btn, 1, 2, 1, 2)

        sp_group.setLayout(sp_layout)
        layout.addWidget(sp_group)

        layout.addStretch()

    def _send_single_command(self) -> None:
        self.command_ready.emit("single", {
            "ioa": self._sc_ioa.value(),
            "state": self._sc_state.currentIndex() == 1,
            "select": self._sc_action.currentIndex() == 1,
            "qu": self._sc_qu.value(),
        })

    def _send_double_command(self) -> None:
        self.command_ready.emit("double", {
            "ioa": self._dc_ioa.value(),
            "state": self._dc_state.currentIndex(),
            "select": False,
            "qu": 0,
        })

    def _send_setpoint(self) -> None:
        try:
            value = float(self._sp_value.text())
        except ValueError:
            return
        self.command_ready.emit("setpoint", {
            "ioa": self._sp_ioa.value(),
            "value": value,
            "select": self._sp_action.currentIndex() == 1,
        })
