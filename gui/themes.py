"""主题与样式管理."""

from __future__ import annotations


DARK_THEME = """
/* ── IEC 104 Tester Dark Theme ── */

QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMenuBar {
    background-color: #181825;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
}
QMenuBar::item:selected {
    background-color: #45475a;
}
QMenu {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #313244;
}
QMenu::item:selected {
    background-color: #585b70;
}

QToolBar {
    background-color: #181825;
    border: none;
    spacing: 4px;
    padding: 2px;
}
QToolButton {
    background-color: transparent;
    color: #cdd6f4;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 60px;
}
QToolButton:hover {
    background-color: #313244;
    border-color: #585b70;
}
QToolButton:pressed {
    background-color: #45475a;
}
QToolButton:checked {
    background-color: #585b70;
    border-color: #89b4fa;
}

QStatusBar {
    background-color: #181825;
    color: #a6adc8;
    border-top: 1px solid #313244;
}

QTabWidget::pane {
    border: 1px solid #313244;
    background-color: #1e1e2e;
}
QTabBar::tab {
    background-color: #181825;
    color: #a6adc8;
    border: 1px solid #313244;
    padding: 6px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border-bottom-color: #1e1e2e;
}
QTabBar::tab:hover:!selected {
    background-color: #313244;
}

QTableView, QTreeView, QListView {
    background-color: #1e1e2e;
    alternate-background-color: #232336;
    color: #cdd6f4;
    gridline-color: #313244;
    border: 1px solid #313244;
    selection-background-color: #45475a;
    selection-color: #cdd6f4;
}
QHeaderView::section {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    padding: 4px;
    font-weight: bold;
}

QGroupBox {
    border: 1px solid #313244;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 16px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #89b4fa;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #89b4fa;
}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 28px;
    min-height: 16px;
    border: none;
    background-color: #45475a;
    border-radius: 3px;
    margin: 2px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #585b70;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background-color: #89b4fa;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 0;
    height: 0;
    border-left: 7px solid transparent;
    border-right: 7px solid transparent;
    border-bottom: 9px solid #cdd6f4;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 7px solid transparent;
    border-right: 7px solid transparent;
    border-top: 9px solid #cdd6f4;
}

QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #585b70;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    background-color: #1e1e2e;
    color: #585b70;
}
QPushButton#primaryButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border-color: #89b4fa;
    font-weight: bold;
}
QPushButton#primaryButton:hover {
    background-color: #74c7ec;
}
QPushButton#dangerButton {
    background-color: #f38ba8;
    color: #1e1e2e;
    border-color: #f38ba8;
}
QPushButton#dangerButton:hover {
    background-color: #eba0ac;
}
QPushButton#successButton {
    background-color: #a6e3a1;
    color: #1e1e2e;
    border-color: #a6e3a1;
}
QPushButton#successButton:hover {
    background-color: #94e2d5;
}

QTextEdit, QPlainTextEdit {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
}

QScrollBar:vertical {
    background-color: #181825;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background-color: #181825;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 5px;
    min-width: 20px;
}

QSplitter::handle {
    background-color: #313244;
}
QSplitter::handle:horizontal {
    width: 2px;
}
QSplitter::handle:vertical {
    height: 2px;
}

QLabel#statusConnected {
    color: #a6e3a1;
    font-weight: bold;
}
QLabel#statusDisconnected {
    color: #f38ba8;
    font-weight: bold;
}
QLabel#statusRunning {
    color: #a6e3a1;
    font-weight: bold;
}
QLabel#statusStopped {
    color: #f38ba8;
    font-weight: bold;
}

QProgressBar {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 4px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 3px;
}

QCheckBox {
    color: #cdd6f4;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #45475a;
    border-radius: 3px;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}

QToolTip {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    padding: 4px;
}

/* ── 报文颜色 ── */
QTextEdit[cssClass="rxFrame"] {
    color: #89dceb;
}
QTextEdit[cssClass="txFrame"] {
    color: #a6e3a1;
}
QTextEdit[cssClass="errorFrame"] {
    color: #f38ba8;
}
"""

LIGHT_THEME = """
/* ── IEC 104 Tester Light Theme ── */

QMainWindow, QWidget {
    background-color: #eff1f5;
    color: #4c4f69;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}

QMenuBar {
    background-color: #e6e9ef;
    color: #4c4f69;
    border-bottom: 1px solid #ccd0da;
}
QMenuBar::item:selected {
    background-color: #ccd0da;
}
QMenu {
    background-color: #eff1f5;
    color: #4c4f69;
    border: 1px solid #ccd0da;
}
QMenu::item:selected {
    background-color: #ccd0da;
}

QToolBar {
    background-color: #e6e9ef;
    border: none;
    spacing: 4px;
    padding: 2px;
}
QToolButton {
    background-color: transparent;
    color: #4c4f69;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 60px;
}
QToolButton:hover {
    background-color: #ccd0da;
    border-color: #bcc0cc;
}

QStatusBar {
    background-color: #e6e9ef;
    color: #6c6f85;
    border-top: 1px solid #ccd0da;
}

QTabWidget::pane {
    border: 1px solid #ccd0da;
    background-color: #eff1f5;
}
QTabBar::tab {
    background-color: #e6e9ef;
    color: #6c6f85;
    border: 1px solid #ccd0da;
    padding: 6px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #eff1f5;
    color: #4c4f69;
    border-bottom-color: #eff1f5;
}

QTableView, QTreeView, QListView {
    background-color: #eff1f5;
    alternate-background-color: #e6e9ef;
    color: #4c4f69;
    gridline-color: #ccd0da;
    border: 1px solid #ccd0da;
    selection-background-color: #8839ef;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #e6e9ef;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    padding: 4px;
    font-weight: bold;
}

QGroupBox {
    border: 1px solid #ccd0da;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 16px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #1e66f5;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 24px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #1e66f5;
}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 28px;
    min-height: 16px;
    border: none;
    background-color: #e6e9ef;
    border-radius: 3px;
    margin: 2px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #ccd0da;
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background-color: #1e66f5;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 0;
    height: 0;
    border-left: 7px solid transparent;
    border-right: 7px solid transparent;
    border-bottom: 9px solid #4c4f69;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 7px solid transparent;
    border-right: 7px solid transparent;
    border-top: 9px solid #4c4f69;
}

QPushButton {
    background-color: #e6e9ef;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    border-radius: 4px;
    padding: 6px 16px;
    min-width: 80px;
}
QPushButton:hover {
    background-color: #ccd0da;
}
QPushButton:pressed {
    background-color: #bcc0cc;
}
QPushButton#primaryButton {
    background-color: #1e66f5;
    color: #ffffff;
    border-color: #1e66f5;
    font-weight: bold;
}
QPushButton#primaryButton:hover {
    background-color: #2a7ae9;
}
QPushButton#dangerButton {
    background-color: #d20f39;
    color: #ffffff;
    border-color: #d20f39;
}

QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    color: #4c4f69;
    border: 1px solid #ccd0da;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
}

QProgressBar {
    background-color: #ccd0da;
    border: 1px solid #bcc0cc;
    border-radius: 4px;
    text-align: center;
    color: #4c4f69;
}
QProgressBar::chunk {
    background-color: #1e66f5;
    border-radius: 3px;
}

QCheckBox {
    color: #4c4f69;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #ccd0da;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #1e66f5;
    border-color: #1e66f5;
}
"""


def get_theme(theme_name: str) -> str:
    """获取主题样式表."""
    if theme_name == "light":
        return LIGHT_THEME
    return DARK_THEME
