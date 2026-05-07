"""可折叠侧边栏 — 连接状态、统计、快捷操作."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QGridLayout, QGroupBox, QSizePolicy
)
from PySide6.QtCore import Signal, Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont


class StatusIndicator(QWidget):
    """状态指示灯组件."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._status = False
        self._text = text

    def set_status(self, connected: bool):
        """设置连接状态."""
        self._status = connected
        self.update()

    def paintEvent(self, event):
        """绘制状态指示灯."""
        from PySide6.QtGui import QPainter, QColor, QBrush
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制圆形指示灯
        size = min(self.width(), self.height())
        circle_size = min(size - 4, 16)
        x = (self.width() - circle_size) / 2
        y = (self.height() - circle_size) / 2

        if self._status:
            painter.setBrush(QBrush(QColor("#a6e3a1")))  # 绿色
        else:
            painter.setBrush(QBrush(QColor("#f38ba8")))  # 红色

        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(x), int(y), circle_size, circle_size)

        # 绘制文字
        if self._text:
            painter.setPen(QColor("#cdd6f4"))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(
                int(x + circle_size + 4), int(y),
                int(self.width() - x - circle_size - 4), circle_size,
                Qt.AlignVCenter | Qt.AlignLeft, self._text
            )

    def sizeHint(self):
        return super().sizeHint()


class StatItem(QWidget):
    """统计项组件."""

    def __init__(self, label: str, value: str = "0", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)

        self._label = QLabel(label)
        self._label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self._label)

        self._value = QLabel(value)
        self._value.setStyleSheet("color: #cdd6f4; font-size: 11px; font-weight: bold;")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._value)

    def set_value(self, value: str):
        """设置值."""
        self._value.setText(value)


class SidebarSection(QGroupBox):
    """侧边栏分区."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setObjectName("sidebarSection")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 12, 8, 8)
        self._layout.setSpacing(4)

    def add_widget(self, widget: QWidget):
        """添加组件."""
        self._layout.addWidget(widget)

    def add_layout(self, layout):
        """添加布局."""
        self._layout.addLayout(layout)


class Sidebar(QWidget):
    """可折叠侧边栏."""

    # 信号
    gi_clicked = Signal()
    ci_clicked = Signal()
    clock_clicked = Signal()
    reset_clicked = Signal()
    test_clicked = Signal()
    startdt_clicked = Signal()
    stopdt_clicked = Signal()

    def __init__(self, mode: str = "master", parent=None):
        super().__init__(parent)
        self._mode = mode
        self._expanded = True
        self._setup_ui()

    def _setup_ui(self):
        """设置UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 折叠按钮
        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setObjectName("sidebarToggle")
        self._toggle_btn.setFixedWidth(20)
        self._toggle_btn.clicked.connect(self._toggle)
        main_layout.addWidget(self._toggle_btn)

        # 内容区域
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(8)

        # 连接状态区
        self._status_section = SidebarSection("连接状态")
        self._status_indicator = StatusIndicator("未连接")
        self._status_section.add_widget(self._status_indicator)

        self._peer_label = QLabel("对端: -")
        self._peer_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        self._status_section.add_widget(self._peer_label)

        self._runtime_label = QLabel("运行: 00:00:00")
        self._runtime_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        self._status_section.add_widget(self._runtime_label)

        content_layout.addWidget(self._status_section)

        # 通信统计区
        self._stats_section = SidebarSection("通信统计")
        self._stat_tx = StatItem("发送帧:", "0")
        self._stat_rx = StatItem("接收帧:", "0")
        self._stat_tx_bytes = StatItem("发送字节:", "0 B")
        self._stat_rx_bytes = StatItem("接收字节:", "0 B")
        self._stat_errors = StatItem("错误:", "0")

        self._stats_section.add_widget(self._stat_tx)
        self._stats_section.add_widget(self._stat_rx)
        self._stats_section.add_widget(self._stat_tx_bytes)
        self._stats_section.add_widget(self._stat_rx_bytes)
        self._stats_section.add_widget(self._stat_errors)
        content_layout.addWidget(self._stats_section)

        # 序列号/流控区
        self._seq_section = SidebarSection("序列号/流控")
        self._stat_vs = StatItem("V(S):", "0")
        self._stat_vr = StatItem("V(R):", "0")
        self._stat_unack = StatItem("未确认:", "0/12")
        self._stat_kw = StatItem("k:w", "12:8")

        self._seq_section.add_widget(self._stat_vs)
        self._seq_section.add_widget(self._stat_vr)
        self._seq_section.add_widget(self._stat_unack)
        self._seq_section.add_widget(self._stat_kw)
        content_layout.addWidget(self._seq_section)

        # 快捷操作区
        if self._mode == "master":
            self._actions_section = SidebarSection("快捷操作")
            self._add_action_button("▶ STARTDT", "启动数据传输", self.startdt_clicked)
            self._add_action_button("⏹ STOPDT", "停止数据传输", self.stopdt_clicked)
            self._add_action_button("📡 总召唤", "总召唤命令", self.gi_clicked)
            self._add_action_button("📊 累计召", "累计量召唤", self.ci_clicked)
            self._add_action_button("🕐 时钟同步", "时钟同步命令", self.clock_clicked)
            self._add_action_button("🔄 复位进程", "复位进程命令", self.reset_clicked)
            self._add_action_button("🧪 测试命令", "发送测试命令", self.test_clicked)
            content_layout.addWidget(self._actions_section)

        # 添加弹性空间
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout.addWidget(spacer)

        main_layout.addWidget(self._content)

    def _add_action_button(self, text: str, tooltip: str, signal: Signal):
        """添加操作按钮."""
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setObjectName("sidebarActionButton")
        btn.setMinimumHeight(28)
        btn.clicked.connect(signal.emit)
        self._actions_section.add_widget(btn)

    def _toggle(self):
        """折叠/展开侧边栏."""
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle_btn.setText("◀" if self._expanded else "▶")

    def set_connected(self, connected: bool, peer: str = ""):
        """设置连接状态."""
        self._status_indicator.set_status(connected)
        if connected:
            self._status_indicator._text = "已连接"
            self._peer_label.setText(f"对端: {peer}")
        else:
            self._status_indicator._text = "未连接"
            self._peer_label.setText("对端: -")
        self._status_indicator.update()

    def set_runtime(self, runtime: str):
        """设置运行时间."""
        self._runtime_label.setText(f"运行: {runtime}")

    def update_stats(self, tx_frames: int = 0, rx_frames: int = 0,
                     tx_bytes: int = 0, rx_bytes: int = 0,
                     errors: int = 0):
        """更新通信统计."""
        self._stat_tx.set_value(str(tx_frames))
        self._stat_rx.set_value(str(rx_frames))
        self._stat_tx_bytes.set_value(self._format_bytes(tx_bytes))
        self._stat_rx_bytes.set_value(self._format_bytes(rx_bytes))
        self._stat_errors.set_value(str(errors))

    def update_sequence(self, vs: int = 0, vr: int = 0,
                        unconfirmed: int = 0, k: int = 12, w: int = 8):
        """更新序列号信息."""
        self._stat_vs.set_value(str(vs))
        self._stat_vr.set_value(str(vr))
        self._stat_unack.set_value(f"{unconfirmed}/{k}")
        self._stat_kw.set_value(f"{k}:{w}")

    @staticmethod
    def _format_bytes(size: int) -> str:
        """格式化字节数."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
