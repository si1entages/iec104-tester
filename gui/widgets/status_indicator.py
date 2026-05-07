"""增强型状态指示灯组件."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont


class StatusIndicator(QWidget):
    """带脉冲动画的状态指示灯."""

    def __init__(self, text: str = "", size: int = 16, parent=None):
        super().__init__(parent)
        self._text = text
        self._size = size
        self._status = False
        self._pulse_value = 1.0
        self._pulse_animation = None
        self._color = QColor("#f38ba8")  # 默认红色

        self.setMinimumSize(size + 4, size + 4)
        self.setMaximumHeight(size + 4)

        self._setup_animation()

    def _setup_animation(self):
        """设置脉冲动画."""
        self._pulse_animation = QPropertyAnimation(self, b"pulseValue")
        self._pulse_animation.setDuration(1500)
        self._pulse_animation.setLoopCount(-1)  # 无限循环
        self._pulse_animation.setStartValue(1.0)
        self._pulse_animation.setKeyValueAt(0.5, 0.5)
        self._pulse_animation.setEndValue(1.0)
        self._pulse_animation.setEasingCurve(QEasingCurve.InOutQuad)

    def get_pulse_value(self) -> float:
        return self._pulse_value

    def set_pulse_value(self, value: float):
        self._pulse_value = value
        self.update()

    pulseValue = Property(float, get_pulse_value, set_pulse_value)

    def set_status(self, connected: bool, animate: bool = True):
        """设置连接状态."""
        self._status = connected
        if connected:
            self._color = QColor("#a6e3a1")  # 绿色
            if animate:
                self._pulse_animation.start()
        else:
            self._color = QColor("#f38ba8")  # 红色
            self._pulse_animation.stop()
            self._pulse_value = 1.0
        self.update()

    def set_color(self, color: QColor):
        """设置指示灯颜色."""
        self._color = color
        self.update()

    def set_text(self, text: str):
        """设置文字."""
        self._text = text
        self.update()

    def paintEvent(self, event):
        """绘制指示灯."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 计算绘制区域
        x = 2
        y = (self.height() - self._size) // 2
        size = self._size

        # 绘制外圈（脉冲效果）
        if self._status and self._pulse_animation.state() == QPropertyAnimation.Running:
            outer_size = int(size * (1 + (1 - self._pulse_value) * 0.3))
            outer_x = x - (outer_size - size) // 2
            outer_y = y - (outer_size - size) // 2
            outer_color = QColor(self._color)
            outer_color.setAlphaF(self._pulse_value * 0.5)
            painter.setBrush(QBrush(outer_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(outer_x, outer_y, outer_size, outer_size)

        # 绘制内圈
        painter.setBrush(QBrush(self._color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(x, y, size, size)

        # 绘制高光
        highlight_color = QColor(255, 255, 255, 80)
        painter.setBrush(QBrush(highlight_color))
        painter.drawEllipse(x + 2, y + 2, size // 2, size // 2)

        # 绘制文字
        if self._text:
            painter.setPen(QColor("#cdd6f4"))
            font = QFont("Microsoft YaHei", 9)
            painter.setFont(font)
            text_x = x + size + 6
            text_width = self.width() - text_x
            painter.drawText(text_x, 0, text_width, self.height(),
                             Qt.AlignVCenter | Qt.AlignLeft, self._text)

    def sizeHint(self):
        """返回建议大小."""
        from PySide6.QtCore import QSize
        font_metrics = self.fontMetrics()
        text_width = font_metrics.horizontalAdvance(self._text) if self._text else 0
        return QSize(self._size + 8 + text_width, self._size + 4)


class ConnectionStatusWidget(QWidget):
    """连接状态组合组件."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # 状态指示灯
        self._indicator = StatusIndicator("未连接", 12)
        layout.addWidget(self._indicator)

        # 状态文字
        self._status_label = QLabel("未连接")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(self._status_label)

        # 对端地址
        self._peer_label = QLabel("")
        self._peer_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        layout.addWidget(self._peer_label)

        # 添加弹性空间
        layout.addStretch()

    def set_connected(self, connected: bool, peer: str = ""):
        """设置连接状态."""
        self._indicator.set_status(connected)
        if connected:
            self._status_label.setText("已连接")
            self._status_label.setStyleSheet("color: #a6e3a1; font-size: 12px;")
            self._peer_label.setText(peer)
        else:
            self._status_label.setText("未连接")
            self._status_label.setStyleSheet("color: #f38ba8; font-size: 12px;")
            self._peer_label.setText("")


class DataFlowIndicator(QWidget):
    """数据流指示器."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rx_active = False
        self._tx_active = False
        self._rx_timer = QTimer()
        self._tx_timer = QTimer()
        self._rx_timer.timeout.connect(self._deactivate_rx)
        self._tx_timer.timeout.connect(self._deactivate_tx)

        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        # RX指示
        self._rx_indicator = StatusIndicator("RX", 10)
        self._rx_indicator.set_color(QColor("#94e2d5"))  # 青色
        layout.addWidget(self._rx_indicator)

        # TX指示
        self._tx_indicator = StatusIndicator("TX", 10)
        self._tx_indicator.set_color(QColor("#a6e3a1"))  # 绿色
        layout.addWidget(self._tx_indicator)

    def flash_rx(self):
        """闪烁RX指示."""
        self._rx_indicator.set_status(True)
        self._rx_timer.start(200)

    def flash_tx(self):
        """闪烁TX指示."""
        self._tx_indicator.set_status(True)
        self._tx_timer.start(200)

    def _deactivate_rx(self):
        """停止RX闪烁."""
        self._rx_indicator.set_status(False, animate=False)
        self._rx_timer.stop()

    def _deactivate_tx(self):
        """停止TX闪烁."""
        self._tx_indicator.set_status(False, animate=False)
        self._tx_timer.stop()
