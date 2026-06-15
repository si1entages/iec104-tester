"""基础视图 — 主站/子站共享的UI组件和逻辑。"""

from __future__ import annotations

import time
from typing import Optional
from abc import abstractmethod

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QDockWidget, QSplitter,
    QPushButton,
)

from core.config import AppConfig
from core.data.point_table import PointTable
from core.data.data_store import RealtimeDB
from gui.widgets.point_table import (
    YxTableModel, YcTableModel, YkTableModel, YmTableModel, PointTablePanel,
)
from gui.widgets.hex_viewer import HexViewer
from gui.widgets.status_panel import StatusPanel, LogViewer
from gui.widgets.sidebar import Sidebar
from gui.widgets.toast import show_info, show_success, show_error


class BaseView(QWidget):
    """视图基类 — 提供共享的UI组件和数据刷新逻辑."""

    # 信号
    raw_frame_received = Signal(bytes, str, str)  # data, direction, client_id
    event_received = Signal(str, dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._point_table = PointTable()
        self._start_time = time.monotonic()

        # 引擎（子类初始化）
        self._engine = None

        # 数据模型
        self._yx_model = YxTableModel()
        self._yc_model = YcTableModel()
        self._yk_model = YkTableModel()
        self._ym_model = YmTableModel()

        # 数据刷新定时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(config.display.refresh_interval_ms)

        # 状态更新定时器
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(500)

        # 初始化UI
        self._init_ui()

    def _init_ui(self) -> None:
        """初始化界面 — 子类可覆盖。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 侧边栏
        mode_str = "master" if self._config.mode == "master" else "slave"
        self._sidebar = Sidebar(mode=mode_str)

        # 数据表格工具栏
        data_toolbar = QHBoxLayout()
        data_toolbar.setContentsMargins(4, 4, 4, 4)
        data_toolbar.setSpacing(8)

        self._add_btn = QPushButton("+ 添加")
        self._add_btn.setObjectName("primaryButton")
        self._add_btn.clicked.connect(self._on_add_point)
        data_toolbar.addWidget(self._add_btn)

        self._edit_btn = QPushButton("编辑")
        self._edit_btn.clicked.connect(self._on_edit_point)
        data_toolbar.addWidget(self._edit_btn)

        self._delete_btn = QPushButton("删除")
        self._delete_btn.setObjectName("dangerButton")
        self._delete_btn.clicked.connect(self._on_delete_point)
        data_toolbar.addWidget(self._delete_btn)

        data_toolbar.addStretch()

        self._import_btn = QPushButton("导入YAML")
        self._import_btn.clicked.connect(self._on_import_yaml)
        data_toolbar.addWidget(self._import_btn)

        self._export_btn = QPushButton("导出YAML")
        self._export_btn.clicked.connect(self._on_export_yaml)
        data_toolbar.addWidget(self._export_btn)

        # 数据表格（Tab切换）
        self._data_tabs = QTabWidget()
        self._yx_panel = PointTablePanel(self._yx_model, "遥信 (YX)")
        self._data_tabs.addTab(self._yx_panel, "遥信 (YX)")
        self._yc_panel = PointTablePanel(self._yc_model, "遥测 (YC)")
        self._data_tabs.addTab(self._yc_panel, "遥测 (YC)")
        self._yk_panel = PointTablePanel(self._yk_model, "遥控 (YK)")
        self._data_tabs.addTab(self._yk_panel, "遥控 (YK)")
        self._ym_panel = PointTablePanel(self._ym_model, "遥脉 (YM)")
        self._data_tabs.addTab(self._ym_panel, "遥脉 (YM)")

        # 报文查看器
        self._hex_viewer = HexViewer()

        # 功能面板（Tab切换）
        self._func_tabs = QTabWidget()
        self._log_viewer = LogViewer()
        self._func_tabs.addTab(self._log_viewer, "日志")
        self._status_panel = StatusPanel()

        # 使用分割器布局
        splitter_h = QSplitter(Qt.Horizontal)
        splitter_h.addWidget(self._sidebar)

        # 数据表格容器
        data_container = QWidget()
        data_layout = QVBoxLayout(data_container)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(0)
        data_layout.addLayout(data_toolbar)
        data_layout.addWidget(self._data_tabs)
        splitter_h.addWidget(data_container)

        splitter_h.setStretchFactor(0, 0)
        splitter_h.setStretchFactor(1, 1)
        splitter_h.setSizes([180, 1400])  # 侧边栏固定宽度

        splitter_v = QSplitter(Qt.Vertical)
        splitter_v.addWidget(splitter_h)

        bottom_tabs = QTabWidget()
        bottom_tabs.addTab(self._hex_viewer, "报文查看")
        bottom_tabs.addTab(self._func_tabs, "功能面板")
        bottom_tabs.setMinimumHeight(200)
        splitter_v.addWidget(bottom_tabs)
        splitter_v.setStretchFactor(0, 2)
        splitter_v.setStretchFactor(1, 3)
        splitter_v.setSizes([400, 500])  # 数据区:报文区 = 2:3

        layout.addWidget(splitter_v)

    def _init_point_table(self) -> None:
        """初始化点表."""
        if self._config.point_table.file:
            try:
                self._point_table.load_yaml(self._config.point_table.file)
            except Exception as e:
                pass

        if (not self._config.point_table.file or
                self._config.point_table.auto_generate and
                self._point_table.yx_count == 0):
            self._point_table.generate_demo_points(
                yx_count=self._config.point_table.yx_count,
                yc_count=self._config.point_table.yc_count,
                yk_count=self._config.point_table.yk_count,
                ym_count=self._config.point_table.ym_count,
            )
            self._point_table.station_name = "Demo Station"
            self._point_table.common_addr = self._config.connection.common_addr

    def _refresh_data(self) -> None:
        """定时刷新表格数据（增量更新）。"""
        if not self._engine:
            return

        store = self._engine.data_store
        changed_yx, changed_yc, changed_ym = store.get_changed_ioas()

        if changed_yx:
            self._yx_model.refresh_partial(changed_yx)
        if changed_yc:
            self._yc_model.refresh_partial(changed_yc)
        if changed_ym:
            self._ym_model.refresh_partial(changed_ym)

    def _refresh_all_data(self) -> None:
        """全量刷新所有数据。"""
        if not self._engine:
            return

        # 重新初始化数据存储
        self._engine.data_store.init_from_point_table(self._point_table)

        # 刷新UI
        store = self._engine.data_store
        self._yx_model.update_data(store.get_all_yx())
        self._yc_model.update_data(store.get_all_yc())
        self._yk_model.update_data(store.get_all_yk())
        self._ym_model.update_data(store.get_all_ym())

    def _update_status(self) -> None:
        """定时更新状态面板."""
        if not self._engine:
            return

        # 只有引擎运行时才更新运行时间
        if self._engine.is_running:
            self._status_panel.update_uptime(time.monotonic() - self._start_time)

            uptime_s = time.monotonic() - self._start_time
            hours, remainder = divmod(int(uptime_s), 3600)
            minutes, seconds = divmod(remainder, 60)
            self._sidebar.set_runtime(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            # 引擎停止时重置运行时间显示
            self._sidebar.set_runtime("00:00:00")

    def _on_raw_frame(self, data: bytes, direction: str, client_id: str = "") -> None:
        """原始帧回调 — 子类可覆盖."""
        self.raw_frame_received.emit(data, direction, client_id)

    def _on_event(self, event_type: str, data: dict) -> None:
        """事件回调 — 子类可覆盖."""
        self.event_received.emit(event_type, data)

    def _on_raw_frame_ui(self, data: bytes, direction: str, client_id: str) -> None:
        """在Qt主线程中更新报文UI."""
        self._hex_viewer.add_frame(data, direction)

    def _on_event_ui(self, event_type: str, data: dict) -> None:
        """在Qt主线程中更新事件UI."""
        self._log_viewer.add_event(event_type, data)

    def get_engine(self):
        """获取引擎实例."""
        return self._engine

    def get_point_table(self) -> PointTable:
        """获取点表."""
        return self._point_table

    def get_sidebar(self) -> Sidebar:
        """获取侧边栏."""
        return self._sidebar

    def get_status_panel(self) -> StatusPanel:
        """获取状态面板."""
        return self._status_panel

    def get_log_viewer(self) -> LogViewer:
        """获取日志查看器."""
        return self._log_viewer

    def get_hex_viewer(self) -> HexViewer:
        """获取报文查看器。"""
        return self._hex_viewer

    def get_yx_panel(self) -> PointTablePanel:
        """获取遥信面板。"""
        return self._yx_panel

    def get_yc_panel(self) -> PointTablePanel:
        """获取遥测面板。"""
        return self._yc_panel

    def get_yk_panel(self) -> PointTablePanel:
        """获取遥控面板。"""
        return self._yk_panel

    def get_ym_panel(self) -> PointTablePanel:
        """获取遥脉面板。"""
        return self._ym_panel

    def get_func_tabs(self) -> QTabWidget:
        """获取功能面板Tab。"""
        return self._func_tabs

    # ── 点表操作 ──────────────────────────────────────────────

    def _on_add_point(self) -> None:
        """添加点。"""
        from gui.slave.point_editor import PointEditorDialog

        # 获取当前选中的Tab
        current_tab = self._data_tabs.currentIndex()
        point_types = ["yx", "yc", "yk", "ym"]
        point_type = point_types[current_tab] if current_tab < len(point_types) else "yx"

        # 打开添加对话框
        dialog = PointEditorDialog(point_type, parent=self)
        if dialog.exec():
            points = dialog.result
            if points:
                # 批量添加到点表
                for point in points:
                    if point_type == "yx":
                        self._point_table.add_yx(point)
                    elif point_type == "yc":
                        self._point_table.add_yc(point)
                    elif point_type == "yk":
                        self._point_table.add_yk(point)
                    elif point_type == "ym":
                        self._point_table.add_ym(point)

                # 刷新数据
                self._refresh_all_data()
                show_success(self, f"已添加 {len(points)} 个{point_type.upper()}点")

    def _on_edit_point(self) -> None:
        """编辑选中的点。"""
        from gui.widgets.batch_edit_dialog import BatchEditDialog

        current_tab = self._data_tabs.currentIndex()
        point_types = ["yx", "yc", "yk", "ym"]
        point_type = point_types[current_tab] if current_tab < len(point_types) else "yx"

        panels = [self._yx_panel, self._yc_panel, self._yk_panel, self._ym_panel]
        panel = panels[current_tab] if current_tab < len(panels) else None

        if panel:
            selected_rows = [idx.row() for idx in panel.table.selectedIndexes()]
            if not selected_rows:
                show_info(self, "请先选择一个或多个点")
                return

            # 去重
            selected_rows = list(set(selected_rows))
            model = panel.model

            if len(selected_rows) == 1:
                # 单选：弹窗修改名称和其他属性
                row = selected_rows[0]
                if row < len(model._points):
                    point = model._points[row]
                    self._edit_single_point(point_type, point, model, row)
            else:
                # 多选：弹窗批量修改属性
                self._batch_edit_points(point_type, selected_rows, model)

    def _edit_single_point(self, point_type: str, point, model, row: int) -> None:
        """编辑单个点（弹窗修改名称和其他属性）。"""
        from PySide6.QtWidgets import QInputDialog, QDialog, QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QHBoxLayout
        from PySide6.QtCore import Qt

        dialog = QDialog(self)
        dialog.setWindowTitle(f"编辑{point_type.upper()}点 IOA={point.ioa}")
        dialog.setMinimumWidth(350)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        form.setSpacing(10)

        # 名称
        name_edit = QInputDialog()
        name_input = QLineEdit(point.name)
        form.addRow("名称:", name_input)

        # 组号
        group_spin = QSpinBox()
        group_spin.setRange(1, 16)
        group_spin.setValue(point.group)
        form.addRow("组号:", group_spin)

        # 类型（仅YX）
        if point_type == "yx":
            yx_type_combo = QComboBox()
            yx_type_combo.addItems(["单点", "双点"])
            yx_type_combo.setCurrentIndex(0 if point.point_type == "single" else 1)
            form.addRow("类型:", yx_type_combo)

            # 是否变化
            is_changing_combo = QComboBox()
            is_changing_combo.addItems(["否", "是"])
            is_changing_combo.setCurrentIndex(1 if point.is_changing else 0)
            form.addRow("是否变化:", is_changing_combo)

            # 变化周期
            change_interval_spin = QSpinBox()
            change_interval_spin.setRange(1, 3600)
            change_interval_spin.setValue(int(point.change_interval))
            change_interval_spin.setSuffix(" 秒")
            form.addRow("变化周期:", change_interval_spin)

            # 状态
            state_combo = QComboBox()
            state_combo.addItems(["OFF (分)", "ON (合)"])
            state_combo.setCurrentIndex(1 if point.value else 0)
            form.addRow("状态:", state_combo)

        layout.addLayout(form)

        # 按钮
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primaryButton")
        ok_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

        if dialog.exec():
            # 更新名称
            point.name = name_input.text()
            point.group = group_spin.value()

            if point_type == "yx":
                point.point_type = "single" if yx_type_combo.currentIndex() == 0 else "double"
                point.is_changing = is_changing_combo.currentIndex() == 1
                point.change_interval = float(change_interval_spin.value())
                point.value = state_combo.currentIndex() == 1

            model.dataChanged.emit(model.index(row, 0), model.index(row, len(model._points[0].__dataclass_fields__) - 1))
            show_success(self, f"已修改 IOA={point.ioa}")

    def _batch_edit_points(self, point_type: str, rows: list, model) -> None:
        """批量编辑多个点。"""
        from gui.widgets.batch_edit_dialog import BatchEditDialog

        dialog = BatchEditDialog(point_type, count=len(rows), parent=self)
        if dialog.exec():
            result = dialog.result
            updated = 0

            for row in rows:
                if row < len(model._points):
                    point = model._points[row]

                    if "group" in result:
                        point.group = result["group"]

                    if point_type == "yx":
                        if "point_type" in result:
                            point.point_type = result["point_type"]
                        if "is_changing" in result:
                            point.is_changing = result["is_changing"]
                        if "change_interval" in result:
                            point.change_interval = result["change_interval"]
                        if "state" in result:
                            point.value = result["state"]
                    elif point_type == "yc" and "data_type" in result:
                        pass  # YC type change not implemented yet
                    elif point_type == "yk" and "command_type" in result:
                        pass  # YK type change not implemented yet

                    if "quality" in result:
                        pass  # Quality change not implemented yet

                    updated += 1

            model.dataChanged.emit(model.index(0, 0), model.index(len(model._points) - 1, len(model._points[0].__dataclass_fields__) - 1))
            show_success(self, f"已修改 {updated} 个点")

    def _on_delete_point(self) -> None:
        """删除选中的点。"""
        from core.data.point_table import PointType

        current_tab = self._data_tabs.currentIndex()
        point_types = ["yx", "yc", "yk", "ym"]
        point_type = point_types[current_tab] if current_tab < len(point_types) else "yx"

        panels = [self._yx_panel, self._yc_panel, self._yk_panel, self._ym_panel]
        panel = panels[current_tab] if current_tab < len(panels) else None

        if panel:
            selected = panel.table.currentIndex()
            if selected.isValid():
                row = selected.row()
                model = panel.model
                if row < len(model._points):
                    point = model._points[row]
                    # 确认删除
                    from PySide6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self, "确认删除",
                        f"确定要删除{point_type.upper()}点 IOA={point.ioa} 吗？",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        pt_type = PointType(point_type)
                        if self._point_table.remove_point(pt_type, point.ioa):
                            self._refresh_all_data()
                            show_success(self, f"已删除{point_type.upper()}点: IOA={point.ioa}")
                        else:
                            show_error(self, "删除失败")
            else:
                show_info(self, "请先选择一个点")

    def _on_import_yaml(self) -> None:
        """导入点表YAML文件。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "导入点表", "", "YAML Files (*.yaml *.yml)"
        )
        if path:
            try:
                self._point_table.load_yaml(path)
                self._refresh_data()
                show_success(self, f"点表已导入: {path}")
            except Exception as e:
                show_error(self, f"导入失败: {e}")

    def _on_export_yaml(self) -> None:
        """导出点表YAML文件。"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出点表", "point_table.yaml", "YAML Files (*.yaml)"
        )
        if path:
            try:
                self._point_table.save_yaml(path)
                show_success(self, f"点表已导出: {path}")
            except Exception as e:
                show_error(self, f"导出失败: {e}")
