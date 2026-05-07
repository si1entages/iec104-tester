"""数据变化视觉反馈效果."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QWidget, QTableView


class FlashEffect:
    """数据变化闪烁效果."""

    def __init__(self, parent: QWidget = None):
        self._parent = parent
        self._flash_cells: dict[tuple[int, int], QTimer] = {}
        self._flash_duration = 500  # 闪烁持续时间（毫秒）
        self._flash_color = QColor("#a6e3a1")  # 绿色闪烁

    def flash_cell(self, row: int, col: int, color: QColor = None):
        """闪烁指定单元格."""
        key = (row, col)

        # 如果已经在闪烁，重置定时器
        if key in self._flash_cells:
            self._flash_cells[key].stop()

        # 创建定时器
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._stop_flash(row, col))
        self._flash_cells[key] = timer

        # 应用闪烁样式
        if self._parent and hasattr(self._parent, 'model'):
            model = self._parent.model()
            if model:
                index = model.index(row, col)
                model.setData(index, color or self._flash_color, Qt.BackgroundRole)

        # 启动定时器
        timer.start(self._flash_duration)

    def _stop_flash(self, row: int, col: int):
        """停止闪烁."""
        key = (row, col)
        if key in self._flash_cells:
            del self._flash_cells[key]

        # 恢复原始背景
        if self._parent and hasattr(self._parent, 'model'):
            model = self._parent.model()
            if model:
                index = model.index(row, col)
                model.setData(index, QBrush(), Qt.BackgroundRole)

    def flash_row(self, row: int, color: QColor = None):
        """闪烁整行."""
        if self._parent and hasattr(self._parent, 'model'):
            model = self._parent.model()
            if model:
                for col in range(model.columnCount()):
                    self.flash_cell(row, col, color)

    def clear_all(self):
        """清除所有闪烁."""
        for timer in self._flash_cells.values():
            timer.stop()
        self._flash_cells.clear()


class DataChangeTracker:
    """数据变化追踪器."""

    def __init__(self, flash_effect: FlashEffect):
        self._flash_effect = flash_effect
        self._last_values: dict[tuple[int, int], any] = {}

    def check_and_flash(self, row: int, col: int, new_value: any,
                        color: QColor = None):
        """检查值是否变化，如果变化则闪烁."""
        key = (row, col)
        old_value = self._last_values.get(key)

        if old_value is not None and old_value != new_value:
            self._flash_effect.flash_cell(row, col, color)

        self._last_values[key] = new_value

    def update_value(self, row: int, col: int, value: any):
        """更新值（不触发闪烁）."""
        self._last_values[(row, col)] = value

    def clear(self):
        """清除所有追踪数据."""
        self._last_values.clear()
