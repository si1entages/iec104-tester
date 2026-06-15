"""主工具栏 — 快速操作按钮."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QToolBar, QToolButton, QWidget, QHBoxLayout, QFrame
)
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QAction, QFont


class ToolButton(QToolButton):
    """增强型工具按钮."""

    def __init__(self, text: str, icon_text: str = "", tooltip: str = "",
                 parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tooltip or text)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setMinimumHeight(32)
        self.setMinimumWidth(60)

        # 设置图标文本（emoji）
        if icon_text:
            self._icon_label = icon_text
        else:
            self._icon_label = ""


class MainToolBar(QToolBar):
    """主工具栏."""

    # 主站信号
    connect_clicked = Signal()
    disconnect_clicked = Signal()
    gi_clicked = Signal()           # 总召唤
    ci_clicked = Signal()           # 累计量召唤
    clock_clicked = Signal()        # 时钟同步
    reset_clicked = Signal()        # 复位进程
    test_clicked = Signal()         # 测试命令

    # 子站信号
    start_listen_clicked = Signal()
    stop_listen_clicked = Signal()
    send_data_clicked = Signal()

    # 通用信号
    record_clicked = Signal()
    stop_record_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, mode: str = "master", parent=None):
        super().__init__(parent)
        self._mode = mode
        self.setObjectName("mainToolBar")
        self.setMovable(False)
        self.setIconSize(QSize(16, 16))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._setup_ui()

    def _setup_ui(self):
        """设置工具栏UI。"""
        if self._mode == "master":
            self._setup_master_ui()
        else:
            self._setup_slave_ui()

        # 通用按钮
        self.addSeparator()
        self._add_settings_button()

    def _setup_master_ui(self):
        """设置主站模式工具栏."""
        # 连接控制
        btn_connect = self._create_button("连接", "▶", "建立TCP连接")
        btn_connect.clicked.connect(self.connect_clicked.emit)
        self.addWidget(btn_connect)

        btn_disconnect = self._create_button("断开", "⏹", "断开TCP连接")
        btn_disconnect.clicked.connect(self.disconnect_clicked.emit)
        self.addWidget(btn_disconnect)

        self.addSeparator()

        # 命令按钮
        btn_gi = self._create_button("总召", "📡", "总召唤命令")
        btn_gi.clicked.connect(self.gi_clicked.emit)
        self.addWidget(btn_gi)

        btn_ci = self._create_button("累计召", "📊", "累计量召唤")
        btn_ci.clicked.connect(self.ci_clicked.emit)
        self.addWidget(btn_ci)

        btn_clock = self._create_button("时钟", "🕐", "时钟同步")
        btn_clock.clicked.connect(self.clock_clicked.emit)
        self.addWidget(btn_clock)

        btn_reset = self._create_button("复位", "🔄", "复位进程")
        btn_reset.clicked.connect(self.reset_clicked.emit)
        self.addWidget(btn_reset)

        btn_test = self._create_button("测试", "🧪", "测试命令")
        btn_test.clicked.connect(self.test_clicked.emit)
        self.addWidget(btn_test)

    def _setup_slave_ui(self):
        """设置子站模式工具栏."""
        btn_start = self._create_button("开始监听", "▶", "开始监听端口")
        btn_start.clicked.connect(self.start_listen_clicked.emit)
        self.addWidget(btn_start)

        btn_stop = self._create_button("停止", "⏹", "停止监听")
        btn_stop.clicked.connect(self.stop_listen_clicked.emit)
        self.addWidget(btn_stop)

        self.addSeparator()

        btn_send = self._create_button("发送数据", "📡", "发送测试数据")
        btn_send.clicked.connect(self.send_data_clicked.emit)
        self.addWidget(btn_send)

    def _add_record_buttons(self):
        """添加录制按钮."""
        btn_record = self._create_button("录制", "⏺", "开始录制报文")
        btn_record.clicked.connect(self.record_clicked.emit)
        self.addWidget(btn_record)

        btn_stop_record = self._create_button("停录", "⏹", "停止录制")
        btn_stop_record.clicked.connect(self.stop_record_clicked.emit)
        self.addWidget(btn_stop_record)

    def _add_settings_button(self):
        """添加设置按钮."""
        btn_settings = self._create_button("设置", "⚙", "打开设置")
        btn_settings.clicked.connect(self.settings_clicked.emit)
        self.addWidget(btn_settings)

        # 添加弹性空间
        spacer = QWidget()
        spacer.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy()
        )
        self.addWidget(spacer)

    def _create_button(self, text: str, icon_text: str = "",
                        tooltip: str = "") -> QToolButton:
        """创建工具按钮."""
        btn = QToolButton()
        btn.setText(f"{icon_text} {text}" if icon_text else text)
        btn.setToolTip(tooltip or text)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setMinimumHeight(32)
        btn.setMinimumWidth(70)
        return btn

    def set_connected(self, connected: bool):
        """设置连接状态，更新按钮启用状态."""
        if self._mode == "master":
            # 主站模式：连接后启用命令按钮
            for btn in self.findChildren(QToolButton):
                text = btn.text()
                if "连接" in text and "断开" not in text:
                    btn.setEnabled(not connected)
                elif "断开" in text:
                    btn.setEnabled(connected)
                elif any(cmd in text for cmd in ["总召", "累计召", "时钟", "复位", "测试"]):
                    btn.setEnabled(connected)
        else:
            # 子站模式
            for btn in self.findChildren(QToolButton):
                text = btn.text()
                if "开始监听" in text:
                    btn.setEnabled(not connected)
                elif "停止" in text:
                    btn.setEnabled(connected)
