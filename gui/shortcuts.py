"""快捷键定义与注册."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import Qt


# 快捷键定义
SHORTCUTS = {
    # 文件操作
    "open_config": QKeySequence("Ctrl+O"),
    "save_config": QKeySequence("Ctrl+S"),
    "quit": QKeySequence("Ctrl+Q"),

    # 编辑操作
    "clear_log": QKeySequence("Ctrl+L"),
    "clear_hex": QKeySequence("Ctrl+Shift+L"),
    "search": QKeySequence("Ctrl+F"),

    # 视图操作
    "toggle_sidebar": QKeySequence("Ctrl+B"),
    "toggle_toolbar": QKeySequence("Ctrl+Shift+T"),
    "refresh": QKeySequence("F5"),

    # 主站命令
    "startdt": QKeySequence("F2"),
    "stopdt": QKeySequence("F3"),
    "general_interrogation": QKeySequence("F6"),
    "counter_interrogation": QKeySequence("F7"),
    "clock_sync": QKeySequence("F8"),
    "reset_process": QKeySequence("F9"),
    "test_command": QKeySequence("F10"),

    # 子站命令
    "start_listen": QKeySequence("F2"),
    "stop_listen": QKeySequence("F3"),

    # 录制操作
    "start_record": QKeySequence("Ctrl+R"),
    "stop_record": QKeySequence("Ctrl+Shift+R"),

    # 帮助
    "about": QKeySequence("F1"),
}


def register_shortcuts(window, callbacks: dict[str, callable]):
    """
    为窗口注册快捷键.

    Args:
        window: QMainWindow 实例
        callbacks: 快捷键名称到回调函数的映射
    """
    for name, callback in callbacks.items():
        if name in SHORTCUTS:
            shortcut = QShortcut(SHORTCUTS[name], window)
            shortcut.activated.connect(callback)


def get_shortcut_text(name: str) -> str:
    """获取快捷键的显示文本."""
    if name in SHORTCUTS:
        return SHORTCUTS[name].toString()
    return ""
