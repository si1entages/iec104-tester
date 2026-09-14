"""顶部连接/监听工具栏."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QCheckBox, QDoubleSpinBox,
)


class ConnectionBar(QFrame):
    """主站连接栏."""

    connect_clicked = Signal()
    disconnect_clicked = Signal()
    local_clicked = Signal()

    def __init__(self, host: str = "127.0.0.1", port: int = 2404,
                 common_addr: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("topBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setObjectName("statusDot")
        self.setProperty("connected", False)
        self._dot.setProperty("connected", False)
        layout.addWidget(self._dot)

        layout.addWidget(QLabel("主机:"))
        self.host_edit = QLineEdit(host)
        self.host_edit.setMaximumWidth(160)
        layout.addWidget(self.host_edit)

        layout.addWidget(QLabel("端口:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(port)
        self.port_spin.setMaximumWidth(90)
        layout.addWidget(self.port_spin)

        layout.addWidget(QLabel("公共地址:"))
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(0, 65534)
        self.addr_spin.setValue(common_addr)
        self.addr_spin.setMaximumWidth(90)
        layout.addWidget(self.addr_spin)

        self.reconnect_check = QCheckBox("自动重连")
        self.reconnect_check.setChecked(True)
        layout.addWidget(self.reconnect_check)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self.connect_clicked.emit)
        layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setObjectName("dangerButton")
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self.disconnect_clicked.emit)
        layout.addWidget(self.disconnect_btn)

        self.local_btn = QPushButton("连本地子站")
        self.local_btn.clicked.connect(self.local_clicked.emit)
        layout.addWidget(self.local_btn)

        layout.addStretch()

        # 轮询
        layout.addWidget(QLabel("GI 周期(s):"))
        self.gi_interval = QDoubleSpinBox()
        self.gi_interval.setRange(0, 3600)
        self.gi_interval.setValue(0)
        self.gi_interval.setSpecialValueText("关闭")
        self.gi_interval.setMaximumWidth(100)
        layout.addWidget(self.gi_interval)

        self.gi_now_btn = QPushButton("立即总召")
        self.gi_now_btn.setEnabled(False)
        layout.addWidget(self.gi_now_btn)

        self.ci_btn = QPushButton("累计量召")
        self.ci_btn.setEnabled(False)
        layout.addWidget(self.ci_btn)

        self.clock_btn = QPushButton("时钟同步")
        self.clock_btn.setEnabled(False)
        layout.addWidget(self.clock_btn)

    def set_connected(self, connected: bool) -> None:
        self._dot.setProperty("connected", connected)
        self._dot.style().unpolish(self._dot)
        self._dot.style().polish(self._dot)
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.gi_now_btn.setEnabled(connected)
        self.ci_btn.setEnabled(connected)
        self.clock_btn.setEnabled(connected)
        for w in (self.host_edit, self.port_spin, self.addr_spin):
            w.setEnabled(not connected)

    def params(self) -> dict:
        return {
            "host": self.host_edit.text().strip() or "127.0.0.1",
            "port": self.port_spin.value(),
            "common_addr": self.addr_spin.value(),
            "reconnect": self.reconnect_check.isChecked(),
            "gi_interval": self.gi_interval.value(),
        }


class ListenBar(QFrame):
    """Slave 子站监听栏."""

    start_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, host: str = "0.0.0.0", port: int = 2404,
                 common_addr: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("topBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setObjectName("statusDot")
        self._dot.setProperty("connected", False)
        layout.addWidget(self._dot)

        layout.addWidget(QLabel("绑定:"))
        self.host_edit = QLineEdit(host)
        self.host_edit.setMaximumWidth(140)
        layout.addWidget(self.host_edit)

        layout.addWidget(QLabel("端口:"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(port)
        self.port_spin.setMaximumWidth(90)
        layout.addWidget(self.port_spin)

        layout.addWidget(QLabel("公共地址:"))
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(0, 65534)
        self.addr_spin.setValue(common_addr)
        self.addr_spin.setMaximumWidth(90)
        layout.addWidget(self.addr_spin)

        self.spont_check = QCheckBox("变化上送")
        self.spont_check.setChecked(True)
        layout.addWidget(self.spont_check)

        self.start_btn = QPushButton("启动监听")
        self.start_btn.setObjectName("successButton")
        self.start_btn.clicked.connect(self.start_clicked.emit)
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_btn)

        layout.addStretch()
        self.client_label = QLabel("客户端: 0")
        layout.addWidget(self.client_label)

    def set_running(self, running: bool, client_count: int = 0) -> None:
        self._dot.setProperty("connected", running)
        self._dot.style().unpolish(self._dot)
        self._dot.style().polish(self._dot)
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (self.host_edit, self.port_spin, self.addr_spin):
            w.setEnabled(not running)
        self.client_label.setText(f"客户端: {client_count}")

    def params(self) -> dict:
        return {
            "host": self.host_edit.text().strip() or "0.0.0.0",
            "port": self.port_spin.value(),
            "common_addr": self.addr_spin.value(),
            "spontaneous": self.spont_check.isChecked(),
        }
