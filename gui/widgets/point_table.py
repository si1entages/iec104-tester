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
    QSpinBox, QDoubleSpinBox,
)

from core.data.data_store import RealtimeDB, YxData, YcData, YmData


# ═══════════════════════════════════════════════════════════════════
#  遥信表格模型
# ═══════════════════════════════════════════════════════════════════

YX_HEADERS = ["序号", "IOA", "名称", "组号", "类型", "变化", "周期", "状态", "品质", "变化次数", "最后变化时间"]


class YxTableModel(QAbstractTableModel):
    """遥信表格模型 — 虚拟滚动."""

    data_edited = Signal(int, str, object)  # ioa, field, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[YxData] = []
        self._ioa_to_row: dict[int, int] = {}
        self._sort_column = 0
        self._sort_order = Qt.AscendingOrder

    def update_data(self, data: dict[int, YxData]) -> None:
        """批量更新数据。"""
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self._ioa_to_row = {p.ioa: i for i, p in enumerate(self._points)}
        self.endResetModel()

    def refresh_partial(self, changed_ioas: set[int]) -> None:
        """增量刷新（O(1)查找变化的行）。"""
        for ioa in changed_ioas:
            row = self._ioa_to_row.get(ioa)
            if row is not None:
                idx_start = self.index(row, 0)
                idx_end = self.index(row, len(YX_HEADERS) - 1)
                self.dataChanged.emit(idx_start, idx_end)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        """设置单元格标志，某些列可编辑。"""
        if not index.isValid():
            return Qt.NoItemFlags

        flags = super().flags(index)
        col = index.column()

        # 名称(2)、组号(3)、类型(4)、变化(5)、周期(6)、状态(7)、品质(8) 列可编辑
        if col in (2, 3, 4, 5, 6, 7, 8):
            flags |= Qt.ItemIsEditable

        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        """设置单元格数据。"""
        if not index.isValid() or role != Qt.EditRole:
            return False

        row = index.row()
        col = index.column()

        if row >= len(self._points):
            return False

        point = self._points[row]
        ioa = point.ioa

        try:
            if col == 2:  # 名称
                point.name = str(value)
                self.data_edited.emit(ioa, "name", str(value))
            elif col == 3:  # 组号
                point.group = int(value)
                self.data_edited.emit(ioa, "group", int(value))
            elif col == 4:  # 类型
                new_type = "single" if str(value) == "单点" else "double"
                point.point_type = new_type
                self.data_edited.emit(ioa, "point_type", new_type)
            elif col == 5:  # 变化
                new_val = str(value) == "是"
                point.is_changing = new_val
                self.data_edited.emit(ioa, "is_changing", new_val)
            elif col == 6:  # 周期
                new_val = float(str(value).replace("s", ""))
                point.change_interval = new_val
                self.data_edited.emit(ioa, "change_interval", new_val)
            elif col == 7:  # 状态
                new_val = str(value) in ("合(ON)", "ON (合)")
                point.value = new_val
                self.data_edited.emit(ioa, "state", new_val)
            elif col == 8:  # 品质
                self.data_edited.emit(ioa, "quality", str(value))

            # 发送dataChanged信号更新UI
            self.dataChanged.emit(index, index)
            return True
        except (ValueError, TypeError):
            return False

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
                return str(point.group)
            elif col == 4:
                return "单点" if point.point_type == "single" else "双点"
            elif col == 5:
                return "是" if point.is_changing else "否"
            elif col == 6:
                return f"{point.change_interval:.1f}s"
            elif col == 7:
                return point.state_str
            elif col == 8:
                q = point.quality
                return str(q) if not q.is_good else "正常"
            elif col == 9:
                return str(point.change_count)
            elif col == 10:
                return time.strftime("%H:%M:%S", time.localtime(point.timestamp))

        elif role == Qt.BackgroundRole:
            # 品质异常标红
            if point.quality.invalid:
                return QBrush(QColor(243, 139, 168, 40))
            if point.quality.blocked:
                return QBrush(QColor(249, 226, 175, 40))
            # 状态颜色
            if col == 7:
                return QBrush(QColor(166, 227, 161)) if point.value else QBrush(QColor(243, 139, 168))

        elif role == Qt.ForegroundRole:
            if col == 7:
                return QBrush(QColor(30, 30, 46)) if point.value else QBrush(QColor(205, 214, 244))
            if col == 8 and not point.quality.is_good:
                return QBrush(QColor(249, 226, 175))

        elif role == Qt.TextAlignmentRole:
            if col in (0, 1, 3, 5, 6, 9):
                return Qt.AlignCenter

        elif role == Qt.FontRole:
            if col == 7:
                font = QFont()
                font.setBold(True)
                return font

        return None


# ═══════════════════════════════════════════════════════════════════
#  遥测表格模型
# ═══════════════════════════════════════════════════════════════════

YC_HEADERS = ["序号", "IOA", "名称", "组号", "类型", "当前值", "最小值", "最大值", "是否变化", "变化周期", "品质", "变化次数", "最后变化时间"]


class YcTableModel(QAbstractTableModel):
    """遥测表格模型。"""

    data_edited = Signal(int, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[YcData] = []
        self._ioa_to_row: dict[int, int] = {}

    def update_data(self, data: dict[int, YcData]) -> None:
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self._ioa_to_row = {p.ioa: i for i, p in enumerate(self._points)}
        self.endResetModel()

    def refresh_partial(self, changed_ioas: set[int]) -> None:
        for ioa in changed_ioas:
            row = self._ioa_to_row.get(ioa)
            if row is not None:
                idx_start = self.index(row, 0)
                idx_end = self.index(row, len(YC_HEADERS) - 1)
                self.dataChanged.emit(idx_start, idx_end)

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        if not index.isValid():
            return Qt.NoItemFlags
        flags = super().flags(index)
        col = index.column()
        # 名称(2)、组号(3)、类型(4)、是否变化(8)、变化周期(9) 列可编辑
        if col in (2, 3, 4, 8, 9):
            flags |= Qt.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or role != Qt.EditRole:
            return False
        row = index.row()
        col = index.column()
        if row >= len(self._points):
            return False

        point = self._points[row]
        ioa = point.ioa

        try:
            if col == 2:  # 名称
                point.name = str(value)
                self.data_edited.emit(ioa, "name", str(value))
            elif col == 3:  # 组号
                point.group = int(value)
                self.data_edited.emit(ioa, "group", int(value))
            elif col == 4:  # 类型
                types = ["normalized", "scaled", "short_float"]
                new_type = types[types.index(str(value))] if str(value) in types else "short_float"
                point.data_type = new_type
                self.data_edited.emit(ioa, "data_type", new_type)
            elif col == 8:  # 是否变化
                new_val = str(value) == "是"
                point.is_changing = new_val
                self.data_edited.emit(ioa, "is_changing", new_val)
            elif col == 9:  # 变化周期
                new_val = float(str(value).replace("s", ""))
                point.change_interval = new_val
                self.data_edited.emit(ioa, "change_interval", new_val)

            self.dataChanged.emit(index, index)
            return True
        except (ValueError, TypeError):
            return False

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._points)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(YC_HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return YC_HEADERS[section]
        return None

    @staticmethod
    def _fmt_time(ts: float) -> str:
        if ts <= 0:
            return "-"
        return time.strftime("%H:%M:%S", time.localtime(ts))

    def data(self, index: QModelIndex, role=Qt.DisplayRole) -> Any:
        if not index.isValid() or index.row() >= len(self._points):
            return None

        point = self._points[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0: return str(index.row() + 1)
            elif col == 1: return str(point.ioa)
            elif col == 2: return point.name
            elif col == 3: return str(point.group)
            elif col == 4:
                type_names = {"normalized": "归一化", "scaled": "标度化", "short_float": "短浮点"}
                return type_names.get(point.data_type, point.data_type)
            elif col == 5: return f"{point.value:.4f}"
            elif col == 6: return f"{point.min_val:.4f}" if point.min_val != float('inf') else "-"
            elif col == 7: return f"{point.max_val:.4f}" if point.max_val != float('-inf') else "-"
            elif col == 8: return "是" if point.is_changing else "否"
            elif col == 9: return f"{point.change_interval:.1f}s"
            elif col == 10:
                q = point.quality
                return str(q) if not q.is_good else "正常"
            elif col == 11: return str(point.change_count)
            elif col == 12: return self._fmt_time(point.last_change_time)

        elif role == Qt.BackgroundRole:
            if point.quality.invalid:
                return QBrush(QColor(243, 139, 168, 40))
            if point.quality.blocked:
                return QBrush(QColor(249, 226, 175, 40))

        elif role == Qt.ForegroundRole:
            if col == 10 and not point.quality.is_good:
                return QBrush(QColor(249, 226, 175))

        elif role == Qt.TextAlignmentRole:
            if col in (0, 1, 3, 5, 6, 7, 8, 9, 11, 12):
                return Qt.AlignCenter

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
    """遥脉/电度表格模型。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[YmData] = []
        self._ioa_to_row: dict[int, int] = {}

    def update_data(self, data: dict[int, YmData]) -> None:
        self.beginResetModel()
        self._points = sorted(data.values(), key=lambda p: p.ioa)
        self._ioa_to_row = {p.ioa: i for i, p in enumerate(self._points)}
        self.endResetModel()

    def refresh_partial(self, changed_ioas: set[int]) -> None:
        for ioa in changed_ioas:
            row = self._ioa_to_row.get(ioa)
            if row is not None:
                idx_start = self.index(row, 0)
                idx_end = self.index(row, len(YM_HEADERS) - 1)
                self.dataChanged.emit(idx_start, idx_end)

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
#  自定义委托 — 支持各列不同编辑器
# ═══════════════════════════════════════════════════════════════════

class _ComboDelegate(QStyledItemDelegate):
    """下拉选框委托。"""

    def __init__(self, items: list[str], parent=None):
        super().__init__(parent)
        self._items = items

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self._items)
        return combo

    def setEditorData(self, editor, index):
        value = index.data(Qt.DisplayRole)
        idx = self._items.index(value) if value in self._items else 0
        editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


class _SpinBoxDelegate(QStyledItemDelegate):
    """数字输入框委托（带增减按钮）。"""

    def __init__(self, min_val: int, max_val: int, suffix: str = "", parent=None):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._suffix = suffix

    def createEditor(self, parent, option, index):
        spin = QSpinBox(parent)
        spin.setRange(self._min, self._max)
        if self._suffix:
            spin.setSuffix(self._suffix)
        return spin

    def setEditorData(self, editor, index):
        value = index.data(Qt.DisplayRole)
        if value:
            try:
                num = float(str(value).replace(self._suffix, "").strip())
                editor.setValue(int(num))
            except (ValueError, TypeError):
                editor.setValue(0)

    def setModelData(self, editor, model, index):
        model.setData(index, str(editor.value()))


class _DoubleSpinBoxDelegate(QStyledItemDelegate):
    """浮点数输入框委托。"""

    def __init__(self, min_val: float, max_val: float, decimals: int = 1, suffix: str = "", parent=None):
        super().__init__(parent)
        self._min = min_val
        self._max = max_val
        self._decimals = decimals
        self._suffix = suffix

    def createEditor(self, parent, option, index):
        from PySide6.QtWidgets import QDoubleSpinBox
        spin = QDoubleSpinBox(parent)
        spin.setRange(self._min, self._max)
        spin.setDecimals(self._decimals)
        if self._suffix:
            spin.setSuffix(self._suffix)
        return spin

    def setEditorData(self, editor, index):
        value = index.data(Qt.DisplayRole)
        if value:
            try:
                num = float(str(value).replace(self._suffix, "").strip())
                editor.setValue(num)
            except (ValueError, TypeError):
                editor.setValue(0.0)

    def setModelData(self, editor, model, index):
        model.setData(index, str(editor.value()))


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
        self._table.setSelectionMode(QTableView.ExtendedSelection)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(0, Qt.AscendingOrder)
        self._table.setWordWrap(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableView.DoubleClicked | QTableView.SelectedClicked)

        # 列宽
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)

        # 设置自定义委托（仅YX表格）
        self._setup_delegates()

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

    @property
    def proxy(self) -> QSortFilterProxyModel:
        return self._proxy

    def _on_search(self, text: str) -> None:
        self._proxy.setFilterFixedString(text)

    def _update_count(self) -> None:
        total = self._model.rowCount()
        shown = self._proxy.rowCount()
        if total == shown:
            self._count_label.setText(f"{total} 条")
        else:
            self._count_label.setText(f"{shown}/{total} 条")

    def _setup_delegates(self) -> None:
        """为表格设置自定义委托。"""
        if not hasattr(self._model, 'data_edited'):
            return

        # 判断是YX还是YC模型
        is_yx = isinstance(self._model, YxTableModel)
        is_yc = isinstance(self._model, YcTableModel)

        if is_yx:
            # YX表格委托
            self._table.setItemDelegateForColumn(3, _SpinBoxDelegate(1, 16, parent=self))
            self._table.setItemDelegateForColumn(4, _ComboDelegate(["单点", "双点"], parent=self))
            self._table.setItemDelegateForColumn(5, _ComboDelegate(["否", "是"], parent=self))
            self._table.setItemDelegateForColumn(6, _SpinBoxDelegate(1, 3600, " 秒", parent=self))
            self._table.setItemDelegateForColumn(7, _ComboDelegate(["分(OFF)", "合(ON)"], parent=self))
            self._table.setItemDelegateForColumn(8, _ComboDelegate(["正常", "无效", "闭锁", "取代"], parent=self))
        elif is_yc:
            # YC表格委托
            self._table.setItemDelegateForColumn(3, _SpinBoxDelegate(1, 16, parent=self))
            self._table.setItemDelegateForColumn(4, _ComboDelegate(["归一化", "标度化", "短浮点"], parent=self))
            self._table.setItemDelegateForColumn(8, _ComboDelegate(["否", "是"], parent=self))
            self._table.setItemDelegateForColumn(9, _DoubleSpinBoxDelegate(0.1, 3600.0, 1, " 秒", parent=self))
