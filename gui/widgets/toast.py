"""Toast通知组件."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QFont


class Toast(QWidget):
    """Toast通知组件."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"

    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._setup_ui()
        self._setup_animation()

    def _setup_ui(self):
        """设置UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)

        self._icon_label = QLabel()
        self._icon_label.setFont(QFont("Segoe UI", 14))
        layout.addWidget(self._icon_label)

        self._message_label = QLabel()
        self._message_label.setFont(QFont("Microsoft YaHei", 10))
        self._message_label.setWordWrap(True)
        self._message_label.setMaximumWidth(300)
        layout.addWidget(self._message_label)

    def _setup_animation(self):
        """设置动画."""
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_in = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in.setDuration(300)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_out.setDuration(300)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self.hide)

    @classmethod
    def show_toast(cls, parent, message: str, toast_type: str = INFO,
                   duration: int = 3000):
        """显示Toast通知."""
        if cls._instance is None:
            cls._instance = cls(parent)

        toast = cls._instance
        toast._show_message(message, toast_type, duration)

    def _show_message(self, message: str, toast_type: str, duration: int):
        """显示消息."""
        # 设置图标和样式
        if toast_type == self.SUCCESS:
            icon = "✓"
            bg_color = "#1a472a"
            border_color = "#a6e3a1"
            text_color = "#a6e3a1"
        elif toast_type == self.ERROR:
            icon = "✗"
            bg_color = "#451a24"
            border_color = "#f38ba8"
            text_color = "#f38ba8"
        elif toast_type == self.WARNING:
            icon = "⚠"
            bg_color = "#453a1a"
            border_color = "#f9e2af"
            text_color = "#f9e2af"
        else:  # INFO
            icon = "ℹ"
            bg_color = "#1a2a3a"
            border_color = "#89b4fa"
            text_color = "#89b4fa"

        self._icon_label.setText(icon)
        self._icon_label.setStyleSheet(f"color: {text_color};")
        self._message_label.setText(message)
        self._message_label.setStyleSheet(f"color: {text_color};")

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 8px;
            }}
        """)

        # 调整大小
        self.adjustSize()

        # 定位到父窗口右下角
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.right() - self.width() - 20
            y = parent_rect.bottom() - self.height() - 20
            self.move(x, y)

        # 显示动画
        self.show()
        self._fade_in.start()

        # 自动隐藏定时器
        QTimer.singleShot(duration, self._start_fade_out)

    def _start_fade_out(self):
        """开始淡出动画."""
        self._fade_out.start()


def show_info(parent, message: str, duration: int = 3000):
    """显示信息Toast."""
    Toast.show_toast(parent, message, Toast.INFO, duration)


def show_success(parent, message: str, duration: int = 3000):
    """显示成功Toast."""
    Toast.show_toast(parent, message, Toast.SUCCESS, duration)


def show_warning(parent, message: str, duration: int = 3000):
    """显示警告Toast."""
    Toast.show_toast(parent, message, Toast.WARNING, duration)


def show_error(parent, message: str, duration: int = 5000):
    """显示错误Toast."""
    Toast.show_toast(parent, message, Toast.ERROR, duration)
