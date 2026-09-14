"""按类型分页的点表 + 批量操作（主站/子站共用）."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton,
    QSpinBox, QInputDialog, QLabel,
)

TYPE_COLORS = {
    "YX": QColor("#89b4fa"),
    "YC": QColor("#a6e3a1"),
    "YK": QColor("#f9e2af"),
    "YM": QColor("#cba6f7"),
}

TYPE_LABELS = {"YX": "遥信 YX", "YC": "遥测 YC", "YK": "遥控 YK", "YM": "遥脉 YM"}

COLS = {
    "YX": ["IOA", "名称", "组", "值", "品质", "时标", "启用"],
    "YC": ["IOA", "名称", "组", "值", "品质", "时标", "启用"],
    "YK": ["IOA", "名称", "组", "值", "启用"],
    "YM": ["IOA", "名称", "组", "值", "品质", "启用"],
}


class TypedPointTable(QTableWidget):
    def __init__(self, ptype: str, parent=None):
        super().__init__(parent)
        self.ptype = ptype
        cols = COLS[ptype]
        self.setColumnCount(len(cols))
        self.setHorizontalHeaderLabels(cols)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        for i in range(len(cols)):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(cols.index("名称"), QHeaderView.Stretch)

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectedIndexes()})


class PointWorkspace(QWidget):
    """YX/YC/YK/YM 分页 + 批量删除/改组/启用."""

    value_edited = Signal(str, int, object)
    rows_deleted = Signal(str, list)
    batch_group = Signal(str, list, int)
    batch_enabled = Signal(str, list, bool)

    def __init__(self, parent=None, editable_values: bool = True):
        super().__init__(parent)
        self._editable_values = editable_values
        self._data: dict[str, list[dict]] = {k: [] for k in COLS}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("dangerButton")
        del_btn.clicked.connect(self._batch_delete)
        bar.addWidget(del_btn)

        self._group_spin = QSpinBox()
        self._group_spin.setRange(1, 23)
        self._group_spin.setPrefix("组 ")
        bar.addWidget(self._group_spin)
        group_btn = QPushButton("改组号")
        group_btn.clicked.connect(self._batch_group)
        bar.addWidget(group_btn)

        en_btn = QPushButton("批量启用")
        en_btn.clicked.connect(lambda: self._batch_enabled(True))
        bar.addWidget(en_btn)
        dis_btn = QPushButton("批量禁用")
        dis_btn.clicked.connect(lambda: self._batch_enabled(False))
        bar.addWidget(dis_btn)

        bar.addStretch()
        self._count_label = QLabel("0 点")
        bar.addWidget(self._count_label)
        layout.addLayout(bar)

        self._tabs = QTabWidget()
        self._tables: dict[str, TypedPointTable] = {}
        for ptype in ("YX", "YC", "YK", "YM"):
            t = TypedPointTable(ptype)
            if editable_values:
                t.itemDoubleClicked.connect(self._on_double_click)
            self._tables[ptype] = t
            self._tabs.addTab(t, TYPE_LABELS[ptype])
        layout.addWidget(self._tabs)

    def current_type(self) -> str:
        return list(COLS.keys())[self._tabs.currentIndex()]

    def current_table(self) -> TypedPointTable:
        return self._tables[self.current_type()]

    def tabs(self) -> QTabWidget:
        return self._tabs

    def current_point(self) -> Optional[dict]:
        """主站：当前选中行的点定义."""
        ptype = self.current_type()
        rows = self.current_table().selected_rows()
        if not rows:
            return None
        r = rows[0]
        if 0 <= r < len(self._data[ptype]):
            return dict(self._data[ptype][r], type=ptype)
        return None

    def add_point(self, ioa: int, ptype: str, name: str = "", group: int = 1,
                  enabled: bool = True, value: object = "—",
                  quality: str = "", ts: str = "") -> None:
        if ptype not in self._data:
            return
        self._data[ptype].append({
            "ioa": ioa, "name": name or f"{ptype}_{ioa:04d}", "group": group,
            "value": value, "quality": quality, "ts": ts, "enabled": enabled,
        })
        self._rebuild(ptype)

    def clear_all(self) -> None:
        for k in list(self._data):
            self._data[k].clear()
            self._rebuild(k)

    def points(self, ptype: Optional[str] = None) -> list[dict]:
        if ptype:
            return list(self._data.get(ptype, []))
        out: list[dict] = []
        for v in self._data.values():
            out.extend(v)
        return out

    def update_from_store(self, store) -> None:
        changed = False
        for ptype, rows in self._data.items():
            for row in rows:
                ioa = row["ioa"]
                if ptype == "YX":
                    d = store.get_yx(ioa)
                    if d:
                        val = "ON" if d.value else "OFF"
                        if row["value"] != val:
                            row["value"] = val
                            row["quality"] = str(d.quality)
                            changed = True
                elif ptype == "YC":
                    d = store.get_yc(ioa)
                    if d:
                        val = f"{d.value:.4g}"
                        if row["value"] != val:
                            row["value"] = val
                            row["quality"] = str(d.quality)
                            changed = True
                elif ptype == "YM":
                    d = store.get_ym(ioa)
                    if d:
                        val = str(d.value)
                        if row["value"] != val:
                            row["value"] = val
                            row["quality"] = str(d.quality)
                            changed = True
        if changed:
            for ptype in self._data:
                self._refresh_values(ptype)

    def _rebuild(self, ptype: str) -> None:
        table = self._tables[ptype]
        rows = self._data[ptype]
        table.setRowCount(len(rows))
        cols = COLS[ptype]
        for r, row in enumerate(rows):
            mapping = {
                "IOA": str(row["ioa"]),
                "名称": row["name"],
                "组": str(row["group"]),
                "值": str(row["value"]),
                "品质": str(row.get("quality", "")),
                "时标": str(row.get("ts", "")),
                "启用": "是" if row.get("enabled", True) else "否",
            }
            for c, title in enumerate(cols):
                item = QTableWidgetItem(mapping.get(title, ""))
                if title in ("IOA", "启用"):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if title == "值":
                    item.setForeground(TYPE_COLORS[ptype])
                table.setItem(r, c, item)
        total = sum(len(v) for v in self._data.values())
        self._count_label.setText(f"{total} 点 · 当前 {TYPE_LABELS[ptype]} {len(rows)}")

    def _refresh_values(self, ptype: str) -> None:
        table = self._tables[ptype]
        cols = COLS[ptype]
        vi = cols.index("值")
        qi = cols.index("品质") if "品质" in cols else -1
        ti = cols.index("时标") if "时标" in cols else -1
        for r, row in enumerate(self._data[ptype]):
            if r < table.rowCount():
                if table.item(r, vi):
                    table.item(r, vi).setText(str(row["value"]))
                if qi >= 0 and table.item(r, qi):
                    table.item(r, qi).setText(str(row.get("quality", "")))
                if ti >= 0 and table.item(r, ti):
                    table.item(r, ti).setText(str(row.get("ts", "")))

    def _selected_ioas(self) -> tuple[str, list[int]]:
        ptype = self.current_type()
        table = self.current_table()
        ioas = []
        for r in table.selected_rows():
            if 0 <= r < len(self._data[ptype]):
                ioas.append(self._data[ptype][r]["ioa"])
        return ptype, ioas

    def _batch_delete(self) -> None:
        ptype, ioas = self._selected_ioas()
        if not ioas:
            return
        gone = set(ioas)
        self._data[ptype] = [r for r in self._data[ptype] if r["ioa"] not in gone]
        self._rebuild(ptype)
        self.rows_deleted.emit(ptype, ioas)

    def _batch_group(self) -> None:
        ptype, ioas = self._selected_ioas()
        if not ioas:
            return
        g = self._group_spin.value()
        gone = set(ioas)
        for row in self._data[ptype]:
            if row["ioa"] in gone:
                row["group"] = g
        self._rebuild(ptype)
        self.batch_group.emit(ptype, ioas, g)

    def _batch_enabled(self, enabled: bool) -> None:
        ptype, ioas = self._selected_ioas()
        if not ioas:
            return
        gone = set(ioas)
        for row in self._data[ptype]:
            if row["ioa"] in gone:
                row["enabled"] = enabled
        self._rebuild(ptype)
        self.batch_enabled.emit(ptype, ioas, enabled)

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        table = self.current_table()
        ptype = table.ptype
        cols = COLS[ptype]
        if item.column() != cols.index("值"):
            return
        r = item.row()
        if r < 0 or r >= len(self._data[ptype]):
            return
        row = self._data[ptype][r]
        ioa = row["ioa"]
        if ptype == "YX":
            new_val = "OFF" if str(row["value"]) == "ON" else "ON"
            row["value"] = new_val
            item.setText(new_val)
            self.value_edited.emit("YX", ioa, new_val == "ON")
        elif ptype == "YC":
            text, ok = QInputDialog.getDouble(
                self, f"修改遥测 IOA={ioa}", "值:",
                float(str(row["value"]).replace("—", "0") or 0), -1e9, 1e9, 4,
            )
            if ok:
                row["value"] = f"{text:.4g}"
                item.setText(row["value"])
                self.value_edited.emit("YC", ioa, float(text))
