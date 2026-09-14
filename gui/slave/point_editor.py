"""点表编辑器 — 可视化编辑遥信/遥测/遥控/遥脉点表.

支持:
- 添加/删除/修改点
- YAML 导入导出
- 拖拽排序
- 批量操作
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QCheckBox, QComboBox,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QFormLayout, QDialog, QDialogButtonBox, QMessageBox,
    QDoubleSpinBox, QFileDialog, QTabWidget,
)

from core.data.point_table import (
    PointTable, PointType,
    YxPointDef, YcPointDef, YkPointDef, YmPointDef,
    YxType, YcType,
)


class PointEditorDialog(QDialog):
    """点定义编辑对话框。"""

    def __init__(self, point_type: str, point=None, parent=None):
        super().__init__(parent)
        self._point_type = point_type
        self._point = point
        self._result = None
        self._is_add_mode = (point is None)  # 添加模式

        type_names = {"yx": "遥信", "yc": "遥测", "yk": "遥控", "ym": "遥脉"}
        self.setWindowTitle(f"{'添加' if self._is_add_mode else '编辑'}{type_names.get(point_type, point_type)}点")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        self._ioa = QSpinBox()
        self._ioa.setRange(0, 16777215)
        self._ioa.setMinimumWidth(120)
        self._ioa.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        layout.addRow("起始IOA:", self._ioa)

        # 添加模式下显示个数
        if self._is_add_mode:
            self._count = QSpinBox()
            self._count.setRange(1, 1000)
            self._count.setValue(1)
            self._count.setMinimumWidth(120)
            self._count.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
            layout.addRow("个数:", self._count)

        self._group = QSpinBox()
        self._group.setRange(1, 16)
        self._group.setMinimumWidth(120)
        self._group.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
        layout.addRow("组号:", self._group)

        # 类型特定字段
        if point_type == "yx":
            self._yx_type = QComboBox()
            self._yx_type.addItems(["单点", "双点"])
            layout.addRow("类型:", self._yx_type)

            self._is_changing = QComboBox()
            self._is_changing.addItems(["否", "是"])
            layout.addRow("是否变化:", self._is_changing)

            self._change_interval = QSpinBox()
            self._change_interval.setRange(1, 3600)
            self._change_interval.setValue(1)
            self._change_interval.setSuffix(" 秒")
            self._change_interval.setMinimumWidth(120)
            self._change_interval.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows)
            self._change_interval.setEnabled(False)
            layout.addRow("变化周期:", self._change_interval)

            self._is_changing.currentIndexChanged.connect(self._on_changing_changed)

        elif point_type == "yc":
            self._yc_type = QComboBox()
            self._yc_type.addItems(["归一化", "标度化", "短浮点"])
            layout.addRow("类型:", self._yc_type)
            self._unit = QLineEdit()
            self._unit.setPlaceholderText("kV, A, MW ...")
            layout.addRow("单位:", self._unit)
            self._min_val = QDoubleSpinBox()
            self._min_val.setRange(-999999, 999999)
            self._min_val.setMinimumWidth(120)
            self._min_val.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
            layout.addRow("最小值:", self._min_val)
            self._max_val = QDoubleSpinBox()
            self._max_val.setRange(-999999, 999999)
            self._max_val.setValue(99999)
            self._max_val.setMinimumWidth(120)
            self._max_val.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
            layout.addRow("最大值:", self._max_val)

            self._yc_is_changing = QComboBox()
            self._yc_is_changing.addItems(["否", "是"])
            layout.addRow("是否变化:", self._yc_is_changing)

            self._yc_change_interval = QDoubleSpinBox()
            self._yc_change_interval.setRange(0.1, 3600)
            self._yc_change_interval.setValue(1.0)
            self._yc_change_interval.setSuffix(" 秒")
            self._yc_change_interval.setDecimals(1)
            self._yc_change_interval.setMinimumWidth(120)
            self._yc_change_interval.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.UpDownArrows)
            self._yc_change_interval.setEnabled(False)
            layout.addRow("变化周期:", self._yc_change_interval)

            self._yc_is_changing.currentIndexChanged.connect(self._on_yc_changing_changed)

        elif point_type == "yk":
            self._cmd_type = QComboBox()
            self._cmd_type.addItems(["单命令", "双命令"])
            layout.addRow("命令类型:", self._cmd_type)
            self._sbo = QCheckBox("选择-执行")
            self._sbo.setChecked(True)
            layout.addRow("", self._sbo)

        # 填充已有数据
        if point:
            self._ioa.setValue(point.ioa)
            self._group.setValue(point.group)

        # 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_changing_changed(self, index: int) -> None:
        """是否变化选项改变时，启用/禁用变化周期输入框."""
        if hasattr(self, '_change_interval'):
            self._change_interval.setEnabled(index == 1)

    def _on_yc_changing_changed(self, index: int) -> None:
        """YC是否变化选项改变时，启用/禁用变化周期输入框."""
        if hasattr(self, '_yc_change_interval'):
            self._yc_change_interval.setEnabled(index == 1)

    def _on_accept(self) -> None:
        """确定按钮。"""
        if self._is_add_mode:
            # 添加模式：返回多个点
            self._result = self._get_points_list()
        else:
            # 编辑模式：返回单个点
            self._result = self._get_point_def()
        self.accept()

    def _get_points_list(self) -> list:
        """获取点列表（批量添加）。"""
        start_ioa = self._ioa.value()
        count = self._count.value() if hasattr(self, '_count') else 1
        points = []

        for i in range(count):
            ioa = start_ioa + i
            name = f"{self._point_type.upper()}_{ioa:04d}"

            if self._point_type == "yx":
                points.append(YxPointDef(
                    ioa=ioa,
                    name=name,
                    group=self._group.value(),
                    enabled=True,
                    point_type=YxType.DOUBLE if self._yx_type.currentIndex() == 1 else YxType.SINGLE,
                    is_changing=self._is_changing.currentIndex() == 1 if hasattr(self, '_is_changing') else False,
                    change_interval=float(self._change_interval.value()) if hasattr(self, '_change_interval') else 1.0,
                ))
            elif self._point_type == "yc":
                types = [YcType.NORMALIZED, YcType.SCALED, YcType.SHORT_FLOAT]
                points.append(YcPointDef(
                    ioa=ioa,
                    name=name,
                    group=self._group.value(),
                    enabled=True,
                    data_type=types[self._yc_type.currentIndex()] if hasattr(self, '_yc_type') else YcType.SHORT_FLOAT,
                    unit=self._unit.text() if hasattr(self, '_unit') else "",
                    min_value=self._min_val.value() if hasattr(self, '_min_val') else -99999,
                    max_value=self._max_val.value() if hasattr(self, '_max_val') else 99999,
                    is_changing=self._yc_is_changing.currentIndex() == 1 if hasattr(self, '_yc_is_changing') else False,
                    change_interval=float(self._yc_change_interval.value()) if hasattr(self, '_yc_change_interval') else 1.0,
                ))
            elif self._point_type == "yk":
                points.append(YkPointDef(
                    ioa=ioa,
                    name=name,
                    group=self._group.value(),
                    enabled=True,
                    command_type="double" if self._cmd_type.currentIndex() == 1 else "single",
                    select_before_execute=self._sbo.isChecked() if hasattr(self, '_sbo') else True,
                ))
            else:
                points.append(YmPointDef(
                    ioa=ioa,
                    name=name,
                    group=self._group.value(),
                    enabled=True,
                ))

        return points

    def _get_point_def(self):
        """获取单个点定义（编辑模式）。"""
        if self._point_type == "yx":
            return YxPointDef(
                ioa=self._ioa.value(),
                name=f"{self._point_type.upper()}_{self._ioa.value():04d}",
                group=self._group.value(),
                enabled=True,
                point_type=YxType.DOUBLE if self._yx_type.currentIndex() == 1 else YxType.SINGLE,
                is_changing=self._is_changing.currentIndex() == 1 if hasattr(self, '_is_changing') else False,
                change_interval=float(self._change_interval.value()) if hasattr(self, '_change_interval') else 1.0,
            )
        elif self._point_type == "yc":
            types = [YcType.NORMALIZED, YcType.SCALED, YcType.SHORT_FLOAT]
            return YcPointDef(
                ioa=self._ioa.value(),
                name=f"{self._point_type.upper()}_{self._ioa.value():04d}",
                group=self._group.value(),
                enabled=True,
                data_type=types[self._yc_type.currentIndex()] if hasattr(self, '_yc_type') else YcType.SHORT_FLOAT,
                unit=self._unit.text() if hasattr(self, '_unit') else "",
                min_value=self._min_val.value() if hasattr(self, '_min_val') else -99999,
                max_value=self._max_val.value() if hasattr(self, '_max_val') else 99999,
                is_changing=self._yc_is_changing.currentIndex() == 1 if hasattr(self, '_yc_is_changing') else False,
                change_interval=float(self._yc_change_interval.value()) if hasattr(self, '_yc_change_interval') else 1.0,
            )
        elif self._point_type == "yk":
            return YkPointDef(
                ioa=self._ioa.value(),
                name=f"{self._point_type.upper()}_{self._ioa.value():04d}",
                group=self._group.value(),
                enabled=True,
                command_type="double" if self._cmd_type.currentIndex() == 1 else "single",
                select_before_execute=self._sbo.isChecked() if hasattr(self, '_sbo') else True,
            )
        else:
            return YmPointDef(
                ioa=self._ioa.value(),
                name=f"{self._point_type.upper()}_{self._ioa.value():04d}",
                group=self._group.value(),
                enabled=True,
            )

    @property
    def result(self):
        return self._result


class PointEditorPanel(QWidget):
    """点表编辑面板.

    提供完整的点表可视化编辑功能。
    """

    point_table_changed = Signal()  # 点表变更信号

    def __init__(self, point_table: PointTable, parent=None):
        super().__init__(parent)
        self._point_table = point_table

        layout = QVBoxLayout(self)

        # 工具栏
        toolbar = QHBoxLayout()

        self._add_btn = QPushButton("➕ 添加")
        self._add_btn.clicked.connect(self._add_point)
        toolbar.addWidget(self._add_btn)

        self._edit_btn = QPushButton("✏️ 编辑")
        self._edit_btn.clicked.connect(self._edit_point)
        toolbar.addWidget(self._edit_btn)

        self._del_btn = QPushButton("🗑️ 删除")
        self._del_btn.setObjectName("dangerButton")
        self._del_btn.clicked.connect(self._delete_point)
        toolbar.addWidget(self._del_btn)

        toolbar.addStretch()

        self._import_btn = QPushButton("📂 导入YAML")
        self._import_btn.clicked.connect(self._import_yaml)
        toolbar.addWidget(self._import_btn)

        self._export_btn = QPushButton("💾 导出YAML")
        self._export_btn.clicked.connect(self._export_yaml)
        toolbar.addWidget(self._export_btn)

        layout.addLayout(toolbar)

        # 标签页
        self._tabs = QTabWidget()

        # 遥信
        self._yx_table = self._create_table(["IOA", "名称", "组号", "类型", "启用", "取反"])
        self._tabs.addTab(self._yx_table, "遥信 (YX)")

        # 遥测
        self._yc_table = self._create_table(["IOA", "名称", "组号", "类型", "单位", "最小值", "最大值", "启用"])
        self._tabs.addTab(self._yc_table, "遥测 (YC)")

        # 遥控
        self._yk_table = self._create_table(["IOA", "名称", "类型", "SBO", "启用"])
        self._tabs.addTab(self._yk_table, "遥控 (YK)")

        # 遥脉
        self._ym_table = self._create_table(["IOA", "名称", "组号", "启用"])
        self._tabs.addTab(self._ym_table, "遥脉 (YM)")

        layout.addWidget(self._tabs)

        # 刷新
        self.refresh()

    def _create_table(self, headers: list[str]) -> QTableWidget:
        """创建表格."""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.doubleClicked.connect(self._edit_point)
        return table

    def refresh(self) -> None:
        """刷新所有表格."""
        # 遥信
        yx_points = self._point_table.get_all_yx()
        self._yx_table.setRowCount(len(yx_points))
        for i, p in enumerate(yx_points):
            self._yx_table.setItem(i, 0, QTableWidgetItem(str(p.ioa)))
            self._yx_table.setItem(i, 1, QTableWidgetItem(p.name))
            self._yx_table.setItem(i, 2, QTableWidgetItem(str(p.group)))
            self._yx_table.setItem(i, 3, QTableWidgetItem(p.point_type.value))
            self._yx_table.setItem(i, 4, QTableWidgetItem("✓" if p.enabled else ""))
            self._yx_table.setItem(i, 5, QTableWidgetItem("✓" if p.inverted else ""))

        # 遥测
        yc_points = self._point_table.get_all_yc()
        self._yc_table.setRowCount(len(yc_points))
        for i, p in enumerate(yc_points):
            self._yc_table.setItem(i, 0, QTableWidgetItem(str(p.ioa)))
            self._yc_table.setItem(i, 1, QTableWidgetItem(p.name))
            self._yc_table.setItem(i, 2, QTableWidgetItem(str(p.group)))
            self._yc_table.setItem(i, 3, QTableWidgetItem(p.data_type.value))
            self._yc_table.setItem(i, 4, QTableWidgetItem(p.unit))
            self._yc_table.setItem(i, 5, QTableWidgetItem(str(p.min_value)))
            self._yc_table.setItem(i, 6, QTableWidgetItem(str(p.max_value)))
            self._yc_table.setItem(i, 7, QTableWidgetItem("✓" if p.enabled else ""))

        # 遥控
        yk_points = self._point_table.get_all_yk()
        self._yk_table.setRowCount(len(yk_points))
        for i, p in enumerate(yk_points):
            self._yk_table.setItem(i, 0, QTableWidgetItem(str(p.ioa)))
            self._yk_table.setItem(i, 1, QTableWidgetItem(p.name))
            self._yk_table.setItem(i, 2, QTableWidgetItem(p.command_type))
            self._yk_table.setItem(i, 3, QTableWidgetItem("✓" if p.select_before_execute else ""))
            self._yk_table.setItem(i, 4, QTableWidgetItem("✓" if p.enabled else ""))

        # 遥脉
        ym_points = self._point_table.get_all_ym()
        self._ym_table.setRowCount(len(ym_points))
        for i, p in enumerate(ym_points):
            self._ym_table.setItem(i, 0, QTableWidgetItem(str(p.ioa)))
            self._ym_table.setItem(i, 1, QTableWidgetItem(p.name))
            self._ym_table.setItem(i, 2, QTableWidgetItem(str(p.group)))
            self._ym_table.setItem(i, 3, QTableWidgetItem("✓" if p.enabled else ""))

    def _current_point_type(self) -> str:
        """当前标签页对应的点类型."""
        idx = self._tabs.currentIndex()
        return ["yx", "yc", "yk", "ym"][idx]

    def _add_point(self) -> None:
        """添加点."""
        ptype = self._current_point_type()
        dlg = PointEditorDialog(ptype, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            result = dlg.result
            points = result if isinstance(result, list) else [result]
            for point in points:
                if ptype == "yx":
                    self._point_table.add_yx(point)
                elif ptype == "yc":
                    self._point_table.add_yc(point)
                elif ptype == "yk":
                    self._point_table.add_yk(point)
                elif ptype == "ym":
                    self._point_table.add_ym(point)
            self.refresh()
            self.point_table_changed.emit()

    def _edit_point(self) -> None:
        """编辑点."""
        ptype = self._current_point_type()
        table = [self._yx_table, self._yc_table, self._yk_table, self._ym_table][self._tabs.currentIndex()]
        row = table.currentRow()
        if row < 0:
            return

        ioa = int(table.item(row, 0).text())
        point = None
        if ptype == "yx":
            point = self._point_table.get_yx(ioa)
        elif ptype == "yc":
            point = self._point_table.get_yc(ioa)
        elif ptype == "yk":
            point = self._point_table.get_yk(ioa)
        elif ptype == "ym":
            point = self._point_table.get_ym(ioa)

        if not point:
            return

        dlg = PointEditorDialog(ptype, point, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.result:
            new_point = dlg.result
            if ptype == "yx":
                self._point_table.add_yx(new_point)
            elif ptype == "yc":
                self._point_table.add_yc(new_point)
            elif ptype == "yk":
                self._point_table.add_yk(new_point)
            elif ptype == "ym":
                self._point_table.add_ym(new_point)
            self.refresh()
            self.point_table_changed.emit()

    def _delete_point(self) -> None:
        """删除点."""
        ptype = self._current_point_type()
        table = [self._yx_table, self._yc_table, self._yk_table, self._ym_table][self._tabs.currentIndex()]
        row = table.currentRow()
        if row < 0:
            return

        ioa = int(table.item(row, 0).text())
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定删除 {ptype.upper()} IOA={ioa}？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._point_table.remove_point(PointType(ptype), ioa)
            self.refresh()
            self.point_table_changed.emit()

    def _import_yaml(self) -> None:
        """导入 YAML 点表."""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入点表", "", "YAML Files (*.yaml *.yml)"
        )
        if path:
            try:
                self._point_table.load_yaml(path)
                self.refresh()
                self.point_table_changed.emit()
                QMessageBox.information(self, "成功", f"点表已导入: {path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入失败: {e}")

    def _export_yaml(self) -> None:
        """导出 YAML 点表."""
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点表", "point_table.yaml", "YAML Files (*.yaml)"
        )
        if path:
            try:
                self._point_table.save_yaml(path)
                QMessageBox.information(self, "成功", f"点表已导出: {path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败: {e}")
