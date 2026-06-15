"""QSS热重载 — 修改样式实时生效。"""

import os
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


class QSSReloader:
    """监控QSS文件变更并自动重载。"""

    def __init__(self, app: QApplication, qss_path: str, interval_ms: int = 500):
        self._app = app
        self._qss_path = Path(qss_path)
        self._last_mtime = self._get_mtime()

        self._timer = QTimer()
        self._timer.timeout.connect(self._check)
        self._timer.start(interval_ms)

        print(f"[QSS] 监控: {self._qss_path}")

    def _get_mtime(self) -> float:
        try:
            return self._qss_path.stat().st_mtime
        except FileNotFoundError:
            return 0

    def _check(self):
        mtime = self._get_mtime()
        if mtime > self._last_mtime:
            self._last_mtime = mtime
            self._reload()

    def _reload(self):
        try:
            with open(self._qss_path, "r", encoding="utf-8") as f:
                qss = f.read()
            self._app.setStyleSheet(qss)
            print(f"[QSS] 已重载: {self._qss_path.name}")
        except Exception as e:
            print(f"[QSS] 重载失败: {e}")
