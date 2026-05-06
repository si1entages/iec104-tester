"""高性能表格控件 — 虚拟滚动支持 10万+ 行.

使用 QTableView + QAbstractTableModel 实现，只渲染可见行。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    QTimer, Signal, QSize,
)
from PySide6.QtGui import QColor, QFont, QBrush, QIcon
from PySide6.QtWidgets import (
    QTableView, QVBoxLayout, QHBoxLayout, QWidget,
    QLineEdit, QLabel, QComboBox, QPushButton, QHeaderView,
    QStyledItemDelegate, QStyleOptionViewItem, QStyle,
)

from core.data.data_store import RealtimeDB, YxData, YcData, YmData


# ═══════════════════════════════════════════════════════════════════
#  遥信表格模型
# ═══════════════════════════════════════════════════════════════════

YX_HEADERS = ["序号", "IOA", "名称", "状态", "品质", "变化次数", "最后更新"]


class YxTableModel(QAbstractTableModel):
    """遥信表格模型 — 虚拟滚动."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[YxData] = []
        self._sort_column = 0
        self._sort_order = Qt.AscendingOrder

    def update_data(self, data: dict[int, YxData]) -> None:
        """批量更新数据."""
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self.endResetModel()

    def refresh_partial(self, changed_ioas: set[int]) -> None:
        """增量刷新（仅更新变化的行）."""
        for i, point in enumerate(self._points):
            if point.ioa in changed_ioas:
                idx_start = self.index(i, 0)
                idx_end = self.index(i, len(YX_HEADERS) - 1)
                self.dataChanged.emit(idx_start, idx_end)

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._points)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(YX_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return YX_HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._points):
            return None

        point = self._points[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return str(index.row() + 1)
            elif col == 1:
                return str(point.ioa)
            elif col == 2:
                return point.name
            elif col == 3:
                return point.state_str
            elif col == 4:
                q = point.quality
                return str(q) if not q.is_good else "正常"
            elif col == 5:
                return str(point.change_count)
            elif col == 6:
                return time.strftime("%H:%M:%S", time.localtime(point.timestamp))

        elif role == Qt.BackgroundRole:
            # 品质异常标红
            if point.quality.invalid:
                return QBrush(QColor(243, 139, 168, 40))
            if point.quality.blocked:
                return QBrush(QColor(249, 226, 175, 40))
            # 状态颜色
            if col == 3:
                return QBrush(QColor(166, 227, 161)) if point.value else QBrush(QColor(243, 139, 168))

        elif role == Qt.ForegroundRole:
            if col == 3:
                return QBrush(QColor(30, 30, 46)) if point.value else QBrush(QColor(205, 214, 244))
            if col == 4 and not point.quality.is_good:
                return QBrush(QColor(249, 226, 175))

        elif role == Qt.TextAlignmentRole:
            if col in (0, 1, 5):
                return Qt.AlignCenter

        elif role == Qt.FontRole:
            if col == 3:
                font = QFont()
                font.setBold(True)
                return font

        return None


# ═══════════════════════════════════════════════════════════════════
#  遥测表格模型
# ═══════════════════════════════════════════════════════════════════

YC_HEADERS = ["序号", "IOA", "名称", "当前值", "单位", "品质", "最小值", "最大值", "变化次数"]


class YcTableModel(QAbstractTableModel):
    """遥测表格模型."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[YcData] = []

    def update_data(self, data: dict[int, YcData]) -> None:
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self.endResetModel()

    def refresh_partial(self, changed_ioas: set[int]) -> None:
        for i, point in enumerate(self._points):
            if point.ioa in changed_ioas:
                idx_start = self.index(i, 0)
                idx_end = self.index(i, len(YC_HEADERS) - 1)
                self.dataChanged.emit(idx_start, idx_end)

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._points)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(YC_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return YC_HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._points):
            return None

        point = self._points[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return str(index.row() + 1)
            elif col == 1:
                return str(point.ioa)
            elif col == 2:
                return point.name
            elif col == 3:
                return f"{point.value:.4f}"
            elif col == 4:
                return point.unit
            elif col == 5:
                return str(point.quality) if not point.quality.is_good else "正常"
            elif col == 6:
                return f"{point.min_val:.4f}" if point.min_val != float('inf') else "-"
            elif col == 7:
                return f"{point.max_val:.4f}" if point.max_val != float('-inf') else "-"
            elif col == 8:
                return str(point.change_count)

        elif role == Qt.BackgroundRole:
            if point.quality.invalid:
                return QBrush(QColor(243, 139, 168, 40))
            if point.quality.blocked:
                return QBrush(QColor(249, 226, 175, 40))

        elif role == Qt.ForegroundRole:
            if col == 5 and not point.quality.is_good:
                return QBrush(QColor(249, 226, 175))

        elif role == Qt.TextAlignmentRole:
            if col in (0, 1, 3, 5, 6, 7, 8):
                return Qt.AlignCenter | Qt.AlignRight

        return None


# ═══════════════════════════════════════════════════════════════════
#  遥控表格模型
# ═══════════════════════════════════════════════════════════════════

YK_HEADERS = ["序号", "IOA", "名称", "类型", "最后命令", "状态", "选择中"]


class YkTableModel(QAbstractTableModel):
    """遥控表格模型."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []

    def update_data(self, data) -> None:
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._points)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(YK_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return YK_HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._points):
            return None

        point = self._points[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0: return str(index.row() + 1)
            elif col == 1: return str(point.ioa)
            elif col == 2: return point.name
            elif col == 3: return "单命令"
            elif col == 4: return point.last_command or "-"
            elif col == 5: return "ON" if point.last_state else "OFF"
            elif col == 6: return "是" if point.select_pending else "否"

        elif role == Qt.BackgroundRole:
            if col == 6 and point.select_pending:
                return QBrush(QColor(137, 180, 250, 60))

        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        return None


# ═══════════════════════════════════════════════════════════════════
#  遥脉表格模型
# ═══════════════════════════════════════════════════════════════════

YM_HEADERS = ["序号", "IOA", "名称", "当前值", "品质", "变化次数"]


class YmTableModel(QAbstractTableModel):
    """遥脉/电度表格模型."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[YmData] = []

    def update_data(self, data: dict[int, YmData]) -> None:
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._points)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(YM_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return YM_HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._points):
            return None

        point = self._points[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0: return str(index.row() + 1)
            elif col == 1: return str(point.ioa)
            elif col == 2: return point.name
            elif col == 3: return str(point.value)
            elif col == 4: return str(point.quality) if not point.quality.is_good else "正常"
            elif col == 5: return str(point.change_count)

        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        return None


# ═══════════════════════════════════════════════════════════════════
#  数值感知排序代理模型
# ═══════════════════════════════════════════════════════════════════

class _NumericSortProxyModel(QSortFilterProxyModel):
    """支持数值列正确排序的代理模型.

    默认 QSortFilterProxyModel 按字符串比较，导致 "10" < "2"。
    此子类对可转为数值的列使用数值比较。
    """

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """比较两列值，数值列用数值比较，其他用默认字符串比较."""
        left_data = self.sourceModel().data(left, Qt.DisplayRole)
        right_data = self.sourceModel().data(right, Qt.DisplayRole)

        if left_data is None:
            return True
        if right_data is None:
            return False

        # 尝试数值比较
        try:
            return float(left_data) < float(right_data)
        except (ValueError, TypeError):
            return str(left_data) < str(right_data)


# ═══════════════════════════════════════════════════════════════════
#  通用表格面板（带搜索和过滤）
# ═══════════════════════════════════════════════════════════════════

class PointTablePanel(QWidget):
    """点表面板 — 包含搜索栏 + 表格."""

    def __init__(self, model: QAbstractTableModel, title: str = "", parent=None):
        super().__init__(parent)
        self._model = model
        self._proxy = _NumericSortProxyModel(self)
        self._proxy.setSourceModel(model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # 全列搜索

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        toolbar = QHBoxLayout()

        if title:
            lbl = QLabel(title)
            lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
            toolbar.addWidget(lbl)

        toolbar.addStretch()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索 (IOA/名称)...")
        self._search_input.setMaximumWidth(300)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search)
        toolbar.addWidget(QLabel("🔍"))
        toolbar.addWidget(self._search_input)

        self._count_label = QLabel("0 条")
        toolbar.addWidget(self._count_label)

        layout.addLayout(toolbar)

        # 表格
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        self._table.setSelectionMode(QTableView.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.AscendingOrder)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.verticalHeader().setVisible(False)

        # 列宽
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)

        layout.addWidget(self._table)

        # 定时刷新计数
        self._count_timer = QTimer(self)
        self._count_timer.timeout.connect(self._update_count)
        self._count_timer.start(1000)

    @property
    def table(self) -> QTableView:
        return self._table

    @property
    def model(self) -> QAbstractTableModel:
        return self._model

    def _on_search(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def _update_count(self) -> None:
        total = self._model.rowCount()
        shown = self._proxy.rowCount()
        if total == shown:
            self._count_label.setText(f"{total} 条")
        else:
            self._count_label.setText(f"{shown}/{total} 条")
