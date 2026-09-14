"""主题 — 复用全局 QSS 并附加双应用通用样式."""

from __future__ import annotations

from gui.themes import get_theme as _base_get_theme, DARK_THEME, LIGHT_THEME

# 双应用补充样式：连接栏、状态灯、定义表
APP_STYLES = """
QFrame#topBar {
    background-color: #181825;
    border-bottom: 1px solid #313244;
    padding: 6px 8px;
}
QFrame#statusStrip {
    background-color: #181825;
    border-top: 1px solid #313244;
}
QLabel#statusDot {
    font-size: 18px;
    color: #f38ba8;
}
QLabel#statusDot[connected="true"] {
    color: #a6e3a1;
}
QLabel#hint {
    color: #6c7086;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    min-height: 26px;
    padding: 2px 6px;
}
QPushButton#primaryButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
}
QPushButton#primaryButton:hover {
    background-color: #74c7ec;
}
QPushButton#primaryButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}
QPushButton#dangerButton {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
}
QPushButton#successButton {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
}
QTableWidget {
    gridline-color: #313244;
    selection-background-color: #45475a;
    selection-color: #cdd6f4;
}
QHeaderView::section {
    background-color: #181825;
    color: #a6adc8;
    border: none;
    border-right: 1px solid #313244;
    border-bottom: 1px solid #313244;
    padding: 4px 6px;
}
"""


def get_theme(name: str = "dark") -> str:
    # 仅深色主题（用户反馈浅色效果差）
    return _base_get_theme("dark") + "\n" + APP_STYLES


def apply_theme(app, name: str = "dark") -> None:
    app.setStyleSheet(get_theme("dark"))
