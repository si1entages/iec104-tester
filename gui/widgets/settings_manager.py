"""窗口状态持久化管理."""

from __future__ import annotations

from PySide6.QtCore import QSettings, QByteArray
from PySide6.QtWidgets import QMainWindow, QSplitter


class SettingsManager:
    """窗口状态持久化管理器."""

    def __init__(self, org_name: str = "IEC104Tester", app_name: str = "IEC104Tester"):
        self._settings = QSettings(org_name, app_name)

    def save_window_state(self, window: QMainWindow, prefix: str = ""):
        """保存窗口状态."""
        key = f"{prefix}window_geometry"
        self._settings.setValue(key, window.saveGeometry())

        key = f"{prefix}window_state"
        self._settings.setValue(key, window.saveState())

    def restore_window_state(self, window: QMainWindow, prefix: str = ""):
        """恢复窗口状态."""
        key = f"{prefix}window_geometry"
        geometry = self._settings.value(key)
        if geometry:
            window.restoreGeometry(geometry)

        key = f"{prefix}window_state"
        state = self._settings.value(key)
        if state:
            window.restoreState(state)

    def save_splitter_state(self, splitter: QSplitter, name: str):
        """保存分割器状态."""
        self._settings.setValue(f"splitter_{name}", splitter.saveState())

    def restore_splitter_state(self, splitter: QSplitter, name: str):
        """恢复分割器状态."""
        state = self._settings.value(f"splitter_{name}")
        if state:
            splitter.restoreState(state)

    def save_value(self, key: str, value):
        """保存任意值."""
        self._settings.setValue(key, value)

    def load_value(self, key: str, default=None):
        """加载任意值."""
        return self._settings.value(key, default)

    def save_theme(self, theme: str):
        """保存主题设置."""
        self._settings.setValue("theme", theme)

    def load_theme(self) -> str:
        """加载主题设置."""
        return self._settings.value("theme", "dark")

    def save_sidebar_state(self, expanded: bool, width: int):
        """保存侧边栏状态."""
        self._settings.setValue("sidebar_expanded", expanded)
        self._settings.setValue("sidebar_width", width)

    def load_sidebar_state(self) -> tuple[bool, int]:
        """加载侧边栏状态."""
        expanded = self._settings.value("sidebar_expanded", True, type=bool)
        width = self._settings.value("sidebar_width", 200, type=int)
        return expanded, width

    def clear(self):
        """清除所有设置."""
        self._settings.clear()
