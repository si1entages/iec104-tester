"""IEC104 主站测试工具 — 客户端窗口（可独立工作，也可与子站窗口并开联调）."""

from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSettings, Signal
from PySide6.QtGui import QAction, QKeySequence, QColor, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton, QLabel, QMessageBox, QFormLayout, QDoubleSpinBox, QComboBox,
    QSpinBox, QCheckBox, QGroupBox, QFileDialog, QTextEdit,
    QDialog, QDialogButtonBox, QLineEdit, QApplication,
)

from core.config import AppConfig
from core.data.point_table import PointTable
from core.engine.master import MasterEngine, MasterEvent
from gui.common import AsyncThread, apply_theme, ConnectionBar, StatusStrip
from gui.widgets.hex_viewer import HexViewer
from gui.widgets.toast import show_success, show_error, show_info
from gui.widgets.trend_chart import TrendChartPanel
from gui.widgets.capture_panel import CapturePanel

logger = logging.getLogger("iec104.master_app")

POINT_TYPES = ["YX", "YC", "YK", "YM"]


class EventLog(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Code", 10))
        self._max = 2000

    def append_line(self, text: str) -> None:
        self.append(text)
        if self.document().blockCount() > self._max:
            cursor = self.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, 200)
            cursor.removeSelectedText()


class DefinitionTable(QTableWidget):
    COLS = ["IOA", "类型", "名称", "组", "值", "品质", "时标"]
    TYPE_COLORS = {
        "YX": QColor("#89b4fa"),
        "YC": QColor("#a6e3a1"),
        "YK": QColor("#f9e2af"),
        "YM": QColor("#cba6f7"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for i in (0, 1, 3, 4, 5, 6):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._rows: list[dict] = []

    def add_point(self, ioa: int, ptype: str, name: str = "", group: int = 1) -> None:
        name = name or f"{ptype}_{ioa:04d}"
        self._rows.append({
            "ioa": ioa, "type": ptype, "name": name, "group": group,
            "value": "—", "quality": "", "ts": "",
        })
        self._rebuild()

    def remove_selected(self) -> list[int]:
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        removed = []
        for r in rows:
            if 0 <= r < len(self._rows):
                removed.append(self._rows[r]["ioa"])
                del self._rows[r]
        if removed:
            self._rebuild()
        return removed

    def selected_point(self) -> Optional[dict]:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        r = rows[0].row()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def points(self) -> list[dict]:
        return list(self._rows)

    def clear_points(self) -> None:
        self._rows.clear()
        self._rebuild()

    def update_values_from_store(self, store) -> None:
        changed = False
        for row in self._rows:
            ioa, ptype = row["ioa"], row["type"]
            if ptype == "YX":
                d = store.get_yx(ioa)
                if d:
                    val = "ON" if d.value else "OFF"
                    if row["value"] != val:
                        row["value"] = val
                        row["quality"] = str(d.quality)
                        row["ts"] = time.strftime("%H:%M:%S")
                        changed = True
            elif ptype == "YC":
                d = store.get_yc(ioa)
                if d:
                    val = f"{d.value:.4g}"
                    if row["value"] != val:
                        row["value"] = val
                        row["quality"] = str(d.quality)
                        row["ts"] = time.strftime("%H:%M:%S")
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
            self._refresh_values()

    def _rebuild(self) -> None:
        self.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            self._fill_row(r, row)

    def _refresh_values(self) -> None:
        for r, row in enumerate(self._rows):
            if r < self.rowCount() and self.item(r, 4):
                self.item(r, 4).setText(str(row["value"]))
                self.item(r, 5).setText(str(row.get("quality", "")))
                self.item(r, 6).setText(str(row.get("ts", "")))

    def _fill_row(self, r: int, row: dict) -> None:
        for c, key in enumerate(["ioa", "type", "name", "group", "value", "quality", "ts"]):
            item = QTableWidgetItem(str(row.get(key, "")))
            if c == 1:
                item.setForeground(self.TYPE_COLORS.get(row["type"], QColor("#cdd6f4")))
            if c in (0, 1, 3):
                item.setTextAlignment(Qt.AlignCenter)
            self.setItem(r, c, item)


class CommandPanel(QWidget):
    command_ready = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        yk_group = QGroupBox("遥控 (YK)")
        yk_form = QFormLayout(yk_group)
        self.yk_ioa = QSpinBox()
        self.yk_ioa.setRange(0, 16777215)
        yk_form.addRow("IOA:", self.yk_ioa)
        self.yk_type = QComboBox()
        self.yk_type.addItems(["单命令 C_SC", "双命令 C_DC"])
        yk_form.addRow("类型:", self.yk_type)
        self.yk_state = QComboBox()
        self.yk_state.addItems(["分 OFF / 1", "合 ON / 2"])
        yk_form.addRow("状态:", self.yk_state)
        self.yk_select = QCheckBox("选择 (SBO)")
        yk_form.addRow("", self.yk_select)
        exec_btn = QPushButton("执行")
        exec_btn.setObjectName("primaryButton")
        exec_btn.clicked.connect(self._send_yk)
        yk_form.addRow(exec_btn)
        layout.addWidget(yk_group)

        sp_group = QGroupBox("设点 (YC)")
        sp_form = QFormLayout(sp_group)
        self.sp_ioa = QSpinBox()
        self.sp_ioa.setRange(0, 16777215)
        sp_form.addRow("IOA:", self.sp_ioa)
        self.sp_type = QComboBox()
        self.sp_type.addItems(["短浮点 C_SE_NC", "归一化 C_SE_NA", "标度化 C_SE_NB"])
        sp_form.addRow("类型:", self.sp_type)
        self.sp_value = QDoubleSpinBox()
        self.sp_value.setRange(-1e9, 1e9)
        self.sp_value.setDecimals(4)
        sp_form.addRow("值:", self.sp_value)
        self.sp_select = QCheckBox("选择 (SBO)")
        sp_form.addRow("", self.sp_select)
        sp_btn = QPushButton("下发设点")
        sp_btn.setObjectName("primaryButton")
        sp_btn.clicked.connect(self._send_sp)
        sp_form.addRow(sp_btn)
        layout.addWidget(sp_group)
        layout.addStretch()

    def load_from_point(self, point: Optional[dict]) -> None:
        if not point:
            return
        if point["type"] == "YK":
            self.yk_ioa.setValue(point["ioa"])
        elif point["type"] == "YC":
            self.sp_ioa.setValue(point["ioa"])

    def _send_yk(self) -> None:
        cmd = "single" if self.yk_type.currentIndex() == 0 else "double"
        state = 0 if self.yk_state.currentIndex() == 0 else 1
        if cmd == "double":
            state = 1 if state == 0 else 2
        self.command_ready.emit(cmd, {
            "ioa": self.yk_ioa.value(), "state": state,
            "select": self.yk_select.isChecked(), "qu": 0,
        })

    def _send_sp(self) -> None:
        self.command_ready.emit("setpoint", {
            "ioa": self.sp_ioa.value(), "value": self.sp_value.value(),
            "select": self.sp_select.isChecked(), "kind": self.sp_type.currentIndex(),
        })


class MasterMainWindow(QMainWindow):
    """IEC104 主站主窗口."""

    # 引擎线程 → UI 线程信号
    _sig_event = Signal(str, dict)
    _sig_frame = Signal(bytes, str)

    def __init__(self, config: Optional[AppConfig] = None):
        super().__init__()
        self._config = config or AppConfig()
        self._config.mode = "master"
        self._settings = QSettings("IEC104Tester", "Master")
        self._gi_timer = QTimer(self)
        self._gi_timer.timeout.connect(self._do_gi)

        self._async_thread = AsyncThread(self)
        self._async_thread.start()

        self._point_table = PointTable()
        self._engine: Optional[MasterEngine] = None

        self._sig_event.connect(self._on_event_ui)
        self._sig_frame.connect(self._on_raw_frame_ui)

        self._init_ui()
        self._connect_signals()
        self._restore_layout()

        if self._point_table.yx_count == 0:
            self._point_table.generate_demo_points(yx_count=20, yc_count=10, yk_count=5, ym_count=5)
            for p in self._point_table.get_all_yx():
                self._def_table.add_point(p.ioa, "YX", p.name, p.group)
            for p in self._point_table.get_all_yc():
                self._def_table.add_point(p.ioa, "YC", p.name, p.group)
            for p in self._point_table.get_all_yk():
                self._def_table.add_point(p.ioa, "YK", p.name, p.group)
            for p in self._point_table.get_all_ym():
                self._def_table.add_point(p.ioa, "YM", p.name, p.group)

    def _init_ui(self) -> None:
        self.setWindowTitle("IEC104 主站测试工具")
        self.setMinimumSize(1200, 800)
        self.resize(1440, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._conn_bar = ConnectionBar(
            self._config.connection.host,
            self._config.connection.port,
            self._config.connection.common_addr,
        )
        root.addWidget(self._conn_bar)

        main_split = QSplitter(Qt.Horizontal)
        self._def_table = DefinitionTable()
        main_split.addWidget(self._def_table)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        self._cmd_panel = CommandPanel()
        right_l.addWidget(self._cmd_panel)
        ops = QHBoxLayout()
        add_btn = QPushButton("+ 添加点")
        add_btn.clicked.connect(self._add_point_dialog)
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("dangerButton")
        del_btn.clicked.connect(self._remove_point)
        imp_btn = QPushButton("导入YAML")
        imp_btn.clicked.connect(self._import_yaml)
        exp_btn = QPushButton("导出YAML")
        exp_btn.clicked.connect(self._export_yaml)
        for b in (add_btn, del_btn, imp_btn, exp_btn):
            ops.addWidget(b)
        ops.addStretch()
        right_l.addLayout(ops)
        right_l.addStretch()
        main_split.addWidget(right)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)

        bottom = QTabWidget()
        self._hex = HexViewer()
        bottom.addTab(self._hex, "报文监视")
        self._log = EventLog()
        bottom.addTab(self._log, "事件日志")
        self._trend = TrendChartPanel()
        bottom.addTab(self._trend, "趋势")
        self._capture = CapturePanel()
        bottom.addTab(self._capture, "录制回放")

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(main_split)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        root.addWidget(vsplit, 1)

        self._status = StatusStrip()
        root.addWidget(self._status)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_values)
        self._refresh_timer.start(self._config.display.refresh_interval_ms)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(400)

    def _connect_signals(self) -> None:
        self._conn_bar.connect_clicked.connect(self._on_connect)
        self._conn_bar.disconnect_clicked.connect(self._on_disconnect)
        self._conn_bar.local_clicked.connect(self._on_connect_local)
        self._conn_bar.gi_now_btn.clicked.connect(self._do_gi)
        self._conn_bar.ci_btn.clicked.connect(self._do_ci)
        self._conn_bar.clock_btn.clicked.connect(self._do_clock)
        self._cmd_panel.command_ready.connect(self._on_command)
        self._def_table.itemSelectionChanged.connect(self._on_select_point)

        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件(&F)")
        act_quit = QAction("退出(&Q)", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        view_menu = menubar.addMenu("视图(&V)")
        act_dark = QAction("深色主题", self)
        act_dark.triggered.connect(lambda: self._set_theme("dark"))
        act_light = QAction("浅色主题", self)
        act_light.triggered.connect(lambda: self._set_theme("light"))
        view_menu.addAction(act_dark)
        view_menu.addAction(act_light)

        help_menu = menubar.addMenu("帮助(&H)")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._about)
        help_menu.addAction(act_about)

    def _on_connect(self) -> None:
        p = self._conn_bar.params()
        if self._engine:
            show_info(self, "已连接，请先断开")
            return
        engine = MasterEngine(
            host=p["host"], port=p["port"], common_addr=p["common_addr"],
            auto_start=True, auto_gi=False, reconnect=p["reconnect"],
            reconnect_interval=5.0,
        )
        engine.set_event_callback(self._on_event)
        engine.set_raw_frame_callback(self._on_raw_frame)
        self._engine = engine
        fut = self._async_thread.run_coroutine(engine.start())
        if fut:
            try:
                fut.result(timeout=5)
            except Exception as e:
                show_error(self, f"连接失败: {e}")
                self._engine = None
                return
        self._conn_bar.set_connected(True)
        self._status.update_state(f"连接中 {p['host']}:{p['port']}")
        show_success(self, f"正在连接 {p['host']}:{p['port']}")
        if p["gi_interval"] > 0:
            self._gi_timer.start(int(p["gi_interval"] * 1000))

    def _on_connect_local(self) -> None:
        """快捷填本地地址 — 需用户另开 IEC104 Slave 窗口."""
        self._conn_bar.host_edit.setText("127.0.0.1")
        if self._conn_bar.port_spin.value() in (0, None):
            self._conn_bar.port_spin.setValue(2404)
        show_info(self, "已填入 127.0.0.1，请确认 IEC104 Slave 已监听后点「连接」")
        self._on_connect()

    def _on_disconnect(self) -> None:
        self._gi_timer.stop()
        engine = self._engine
        self._engine = None
        if engine:
            fut = self._async_thread.run_coroutine(engine.stop())
            if fut:
                try:
                    fut.result(timeout=6)
                except Exception:
                    pass
        self._conn_bar.set_connected(False)
        self._status.update_state("已断开")
        show_info(self, "已断开连接")

    def _on_event(self, event: MasterEvent, data: dict) -> None:
        """引擎线程回调 — 仅 emit 信号."""
        try:
            self._sig_event.emit(event.value, data)
        except Exception:
            pass

    def _on_raw_frame(self, data: bytes, direction: str) -> None:
        """引擎线程回调 — 仅 emit 信号."""
        try:
            self._sig_frame.emit(data, direction)
        except Exception:
            pass

    def _on_event_ui(self, event_type: str, data: dict) -> None:
        try:
            self._log.append_line(f"[{event_type}] {data}")
        except Exception:
            pass

    def _on_raw_frame_ui(self, data: bytes, direction: str) -> None:
        try:
            self._hex.add_frame(data, direction)
            self._capture.feed_frame(data, direction)
        except Exception:
            pass

    def _do_gi(self) -> None:
        if not self._engine or not self._engine.is_running:
            show_error(self, "未连接")
            return
        self._async_thread.run_coroutine(self._engine.general_interrogation())
        show_info(self, "总召唤已发送")

    def _do_ci(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.counter_interrogation())

    def _do_clock(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.clock_sync())
            show_success(self, "时钟同步已发送")

    def _on_command(self, cmd_type: str, params: dict) -> None:
        if not self._engine or not self._engine.is_running:
            show_error(self, "未连接")
            return
        eng = self._engine
        if cmd_type == "single":
            self._async_thread.run_coroutine(eng.single_command(
                params["ioa"], params["state"], params["select"], params.get("qu", 0)
            ))
            show_success(self, f"单命令 IOA={params['ioa']}")
        elif cmd_type == "double":
            self._async_thread.run_coroutine(eng.double_command(
                params["ioa"], params["state"], params["select"], params.get("qu", 0)
            ))
            show_success(self, f"双命令 IOA={params['ioa']}")
        elif cmd_type == "setpoint":
            kind = params.get("kind", 0)
            if kind == 0:
                self._async_thread.run_coroutine(eng.setpoint_shortfloat(
                    params["ioa"], params["value"], params["select"]
                ))
            elif kind == 1:
                self._async_thread.run_coroutine(eng.setpoint_normalized(
                    params["ioa"], params["value"], params["select"]
                ))
            else:
                self._async_thread.run_coroutine(eng.setpoint_scaled(
                    params["ioa"], int(params["value"]), params["select"]
                ))
            show_success(self, f"设点 IOA={params['ioa']} → {params['value']}")

    def _on_select_point(self) -> None:
        self._cmd_panel.load_from_point(self._def_table.selected_point())

    def _add_point_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("添加点")
        form = QFormLayout(dlg)
        ioa = QSpinBox()
        ioa.setRange(0, 16777215)
        ioa.setValue(1)
        form.addRow("IOA:", ioa)
        ptype = QComboBox()
        ptype.addItems(POINT_TYPES)
        form.addRow("类型:", ptype)
        name = QLineEdit()
        name.setPlaceholderText("可选")
        form.addRow("名称:", name)
        group = QSpinBox()
        group.setRange(1, 23)
        form.addRow("组:", group)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec():
            self._def_table.add_point(ioa.value(), ptype.currentText(), name.text().strip(), group.value())

    def _remove_point(self) -> None:
        removed = self._def_table.remove_selected()
        if removed:
            show_info(self, f"已删除 {len(removed)} 个点")

    def _import_yaml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入点表", "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            self._point_table.load_yaml(path)
            self._def_table.clear_points()
            for p in self._point_table.get_all_yx():
                self._def_table.add_point(p.ioa, "YX", p.name, p.group)
            for p in self._point_table.get_all_yc():
                self._def_table.add_point(p.ioa, "YC", p.name, p.group)
            for p in self._point_table.get_all_yk():
                self._def_table.add_point(p.ioa, "YK", p.name, p.group)
            for p in self._point_table.get_all_ym():
                self._def_table.add_point(p.ioa, "YM", p.name, p.group)
            show_success(self, f"已导入 {path}")
        except Exception as e:
            show_error(self, f"导入失败: {e}")

    def _export_yaml(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出点表", "points.yaml", "YAML (*.yaml)")
        if path:
            try:
                self._point_table.save_yaml(path)
                show_success(self, f"已导出 {path}")
            except Exception as e:
                show_error(self, f"导出失败: {e}")

    def _refresh_values(self) -> None:
        if not self._engine:
            return
        try:
            self._def_table.update_values_from_store(self._engine.data_store)
            store = self._engine.data_store
            for row in self._def_table.points()[:8]:
                if row["type"] == "YC":
                    d = store.get_yc(row["ioa"])
                    if d:
                        self._trend.update_yc_trend(row["ioa"], float(d.value))
        except Exception:
            pass

    def _update_status(self) -> None:
        if not self._engine:
            self._status.update_state("未连接")
            return
        eng = self._engine
        running = eng.is_running
        self._conn_bar.set_connected(True)
        self._status.update_state(str(eng.state) + ("" if running else " (等待连接…)"))
        if running:
            seq = eng.sequence_manager
            if seq:
                self._status.update_seq(seq.send_seq, seq.recv_seq, seq.unconfirmed_count, seq.k, seq.w)
        stats = eng.connection_stats
        if stats:
            self._status.update_traffic(stats.frames_sent, stats.frames_received, stats.bytes_sent, stats.bytes_received)

    def _set_theme(self, name: str) -> None:
        self._config.display.theme = name
        apply_theme(QApplication.instance(), name)

    def _about(self) -> None:
        QMessageBox.about(
            self, "关于 IEC104 主站",
            "IEC104 主站 — IEC 60870-5-104 主站客户端\n\n"
            "可独立连接第三方子站；也可与「IEC104 子站」同时打开联调。\n"
            "PySide6 + asyncio",
        )

    def _save_layout(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())

    def _restore_layout(self) -> None:
        g = self._settings.value("geometry")
        s = self._settings.value("windowState")
        if g is not None:
            self.restoreGeometry(g)
        if s is not None:
            self.restoreState(s)

    def closeEvent(self, event) -> None:
        self._save_layout()
        self._gi_timer.stop()
        if self._engine:
            fut = self._async_thread.run_coroutine(self._engine.stop())
            if fut:
                try:
                    fut.result(timeout=5)
                except Exception:
                    pass
        self._async_thread.stop()
        event.accept()
