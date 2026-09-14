"""IEC104 子站测试工具 — 服务端窗口（可独立工作，也可与主站窗口并开联调）."""

from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSettings, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPushButton, QLabel, QMessageBox, QFormLayout, QDoubleSpinBox, QComboBox,
    QSpinBox, QCheckBox, QGroupBox, QFileDialog, QTextEdit, QListWidget,
    QApplication, QDialog, QDialogButtonBox, QLineEdit,
)

from core.config import AppConfig
from core.data.point_table import PointTable
from core.engine.slave import SlaveEngine, SlaveEvent
from gui.common import AsyncThread, apply_theme, ListenBar, StatusStrip
from gui.widgets.hex_viewer import HexViewer
from gui.widgets.toast import show_success, show_error, show_info
from gui.slave.response_cfg import ResponseConfigPanel
from gui.slave.sim_panel import SimPanel

logger = logging.getLogger("iec104.slave_app")

POINT_TYPES = ["YX", "YC", "YK", "YM"]


class EventLog(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Code", 10))

    def append_line(self, text: str) -> None:
        self.append(text)
        if self.document().blockCount() > 2000:
            cursor = self.textCursor()
            cursor.movePosition(cursor.Start)
            cursor.movePosition(cursor.Down, cursor.KeepAnchor, 200)
            cursor.removeSelectedText()


class SlavePointTable(QTableWidget):
    """可编辑点表 — 点击 YX 切换，双击 YC 改值."""

    COLS = ["IOA", "类型", "名称", "组", "值", "品质", "启用"]
    value_edited = Signal(str, int, object)  # type, ioa, value
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
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for i in (0, 1, 3, 4, 5, 6):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.itemDoubleClicked.connect(self._on_double_click)

    def load_from_point_table(self, pt: PointTable, store=None) -> None:
        rows = []
        for p in pt.get_all_yx():
            val = "OFF"
            if store:
                d = store.get_yx(p.ioa)
                if d:
                    val = "ON" if d.value else "OFF"
            rows.append((p.ioa, "YX", p.name, p.group, val, "", p.enabled))
        for p in pt.get_all_yc():
            val = "0"
            if store:
                d = store.get_yc(p.ioa)
                if d:
                    val = f"{d.value:.4g}"
            rows.append((p.ioa, "YC", p.name, p.group, val, "", p.enabled))
        for p in pt.get_all_yk():
            rows.append((p.ioa, "YK", p.name, p.group, "—", "", p.enabled))
        for p in pt.get_all_ym():
            val = "0"
            if store:
                d = store.get_ym(p.ioa)
                if d:
                    val = str(d.value)
            rows.append((p.ioa, "YM", p.name, p.group, val, "", p.enabled))

        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                item = QTableWidgetItem(str(v))
                if c == 1:
                    item.setForeground(self.TYPE_COLORS.get(row[1], QColor("#cdd6f4")))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c == 0:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c == 4 and row[1] == "YX":
                    item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                self.setItem(r, c, item)

    def update_from_store(self, store) -> None:
        for r in range(self.rowCount()):
            try:
                ptype = self.item(r, 1).text()
                ioa = int(self.item(r, 0).text())
            except Exception:
                continue
            if ptype == "YX":
                d = store.get_yx(ioa)
                if d:
                    self.item(r, 4).setText("ON" if d.value else "OFF")
                    self.item(r, 5).setText(str(d.quality))
            elif ptype == "YC":
                d = store.get_yc(ioa)
                if d:
                    self.item(r, 4).setText(f"{d.value:.4g}")
                    self.item(r, 5).setText(str(d.quality))
            elif ptype == "YM":
                d = store.get_ym(ioa)
                if d:
                    self.item(r, 4).setText(str(d.value))

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        r, c = item.row(), item.column()
        if c != 4 or r < 0:
            return
        ptype = self.item(r, 1).text()
        ioa = int(self.item(r, 0).text())
        if ptype == "YX":
            new_val = "OFF" if item.text() == "ON" else "ON"
            item.setText(new_val)
            self.value_edited.emit("YX", ioa, new_val == "ON")
        elif ptype == "YC":
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getDouble(
                self, f"修改遥测 IOA={ioa}", "值:",
                float(item.text() or 0), -1e9, 1e9, 4,
            )
            if ok:
                item.setText(f"{text:.4g}")
                self.value_edited.emit("YC", ioa, float(text))


class ClientListPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("已连接客户端"))
        self.list = QListWidget()
        layout.addWidget(self.list)

    def set_clients(self, clients: list[str]) -> None:
        current = [self.list.item(i).text() for i in range(self.list.count())]
        if current != clients:
            self.list.clear()
            self.list.addItems(clients)


class SlaveMainWindow(QMainWindow):
    """IEC104 子站主窗口."""

    _sig_event = Signal(str, dict)
    _sig_frame = Signal(bytes, str)

    def __init__(self, config: Optional[AppConfig] = None):
        super().__init__()
        self._config = config or AppConfig()
        self._config.mode = "slave"
        self._settings = QSettings("IEC104Tester", "Slave")
        self._async_thread = AsyncThread(self)
        self._async_thread.start()
        self._pending_response: dict = {}

        self._point_table = PointTable()
        if self._point_table.yx_count == 0:
            self._point_table.generate_demo_points(yx_count=50, yc_count=30, yk_count=10, ym_count=10)
            self._point_table.common_addr = self._config.connection.common_addr
            self._point_table.station_name = "DemoSlave"

        self._engine: Optional[SlaveEngine] = None

        self._sig_event.connect(self._on_event_ui)
        self._sig_frame.connect(self._on_raw_frame_ui)

        self._init_ui()
        self._connect_signals()
        self._restore_layout()
        self._table.load_from_point_table(self._point_table)

    def _init_ui(self) -> None:
        self.setWindowTitle("IEC104 子站测试工具")
        self.setMinimumSize(1100, 750)
        self.resize(1360, 860)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._listen_bar = ListenBar(
            "0.0.0.0",
            self._config.connection.port,
            self._config.connection.common_addr,
        )
        root.addWidget(self._listen_bar)

        main_split = QSplitter(Qt.Horizontal)
        self._table = SlavePointTable()
        main_split.addWidget(self._table)

        side = QWidget()
        side_l = QVBoxLayout(side)
        side_l.setContentsMargins(4, 4, 4, 4)
        self._clients = ClientListPanel()
        side_l.addWidget(self._clients, 1)

        self._response_cfg = ResponseConfigPanel()
        side_l.addWidget(self._response_cfg, 2)

        self._sim = SimPanel()
        side_l.addWidget(self._sim, 2)

        ops = QHBoxLayout()
        demo_btn = QPushButton("生成演示点")
        demo_btn.clicked.connect(self._gen_demo)
        imp_btn = QPushButton("导入YAML")
        imp_btn.clicked.connect(self._import_yaml)
        exp_btn = QPushButton("导出YAML")
        exp_btn.clicked.connect(self._export_yaml)
        for b in (demo_btn, imp_btn, exp_btn):
            ops.addWidget(b)
        ops.addStretch()
        side_l.addLayout(ops)
        main_split.addWidget(side)
        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)

        bottom = QTabWidget()
        self._hex = HexViewer()
        bottom.addTab(self._hex, "报文监视")
        self._log = EventLog()
        bottom.addTab(self._log, "事件日志")

        vsplit = QSplitter(Qt.Vertical)
        vsplit.addWidget(main_split)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 2)
        root.addWidget(vsplit, 1)

        self._status = StatusStrip()
        root.addWidget(self._status)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(500)

    def _connect_signals(self) -> None:
        self._listen_bar.start_clicked.connect(self._on_start)
        self._listen_bar.stop_clicked.connect(self._on_stop)
        self._table.value_edited.connect(self._on_value_edited)
        self._response_cfg.config_changed.connect(self._on_response_cfg)
        self._sim.yx_change.connect(self._on_sim_yx)
        self._sim.yc_change.connect(self._on_sim_yc)
        self._sim.simulation_toggled.connect(self._on_sim_toggle)

        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件(&F)")
        quit_act = QAction("退出(&Q)", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = menubar.addMenu("视图(&V)")
        dark = QAction("深色主题", self)
        dark.triggered.connect(lambda: self._set_theme("dark"))
        light = QAction("浅色主题", self)
        light.triggered.connect(lambda: self._set_theme("light"))
        view_menu.addAction(dark)
        view_menu.addAction(light)

        help_menu = menubar.addMenu("帮助(&H)")
        about = QAction("关于", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _on_start(self) -> None:
        if self._engine:
            return
        p = self._listen_bar.params()
        engine = SlaveEngine(
            host=p["host"], port=p["port"], common_addr=p["common_addr"],
            point_table=self._point_table,
            spontaneous_enabled=p["spontaneous"],
        )
        engine.data_store.init_from_point_table(self._point_table)
        engine.set_event_callback(self._on_event)
        engine.set_raw_frame_callback(self._on_raw_frame)
        if self._pending_response:
            engine.set_response_behavior(self._pending_response)
        self._engine = engine
        fut = self._async_thread.run_coroutine(engine.start())
        if fut:
            try:
                fut.result(timeout=5)
            except Exception as e:
                show_error(self, f"启动失败: {e}")
                self._engine = None
                return
        self._listen_bar.set_running(True, 0)
        show_success(self, f"监听 {p['host']}:{p['port']}")
        self._table.load_from_point_table(self._point_table, engine.data_store)

    def _on_stop(self) -> None:
        engine = self._engine
        self._engine = None
        if engine:
            fut = self._async_thread.run_coroutine(engine.stop())
            if fut:
                try:
                    fut.result(timeout=8)
                except Exception:
                    pass
        self._listen_bar.set_running(False, 0)
        show_info(self, "已停止监听")

    def _on_event(self, event: SlaveEvent, data: dict) -> None:
        try:
            self._sig_event.emit(event.value, data)
        except Exception:
            pass

    def _on_raw_frame(self, data: bytes, direction: str, client_id: str = "") -> None:
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
        except Exception:
            pass

    async def _apply_yx_change(self, ioa: int, value: bool) -> None:
        """在 asyncio 线程更新并自发上送遥信."""
        if not self._engine:
            return
        self._engine.data_store.update_yx(ioa, value)
        await self._engine.send_spontaneous_yx(ioa, value)

    async def _apply_yc_change(self, ioa: int, value: float) -> None:
        if not self._engine:
            return
        self._engine.data_store.update_yc(ioa, value)
        await self._engine.send_spontaneous_yc(ioa, value)

    def _on_value_edited(self, ptype: str, ioa: int, value) -> None:
        if not self._engine:
            show_error(self, "未启动监听")
            return
        if ptype == "YX":
            self._async_thread.run_coroutine(self._apply_yx_change(ioa, bool(value)))
            show_success(self, f"YX {ioa} → {'ON' if value else 'OFF'}")
        elif ptype == "YC":
            self._async_thread.run_coroutine(self._apply_yc_change(ioa, float(value)))
            show_success(self, f"YC {ioa} → {value}")

    def _on_response_cfg(self, cfg: dict) -> None:
        self._pending_response = cfg
        if self._engine:
            self._engine.set_response_behavior(cfg)
            show_success(self, "响应配置已应用")
        else:
            show_info(self, "响应配置已保存，启动监听后生效")

    def _on_sim_yx(self, ioa: int, value: bool) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._apply_yx_change(ioa, value))

    def _on_sim_yc(self, ioa: int, value: float) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._apply_yc_change(ioa, value))

    def _on_sim_toggle(self, enabled: bool) -> None:
        if not self._engine:
            show_error(self, "请先启动监听")
            self._sim._sim_enabled.setChecked(False)
            return
        cfg = self._sim.sim_config
        if enabled:
            self._async_thread.run_coroutine(self._engine.start_simulation(
                yx_interval=cfg["yx_interval"],
                yc_interval=cfg["yc_interval"],
                yx_change_rate=cfg["yx_change_rate"],
                yc_change_range=cfg["yc_change_range"],
            ))
            show_success(self, "自动模拟已启动")
        else:
            self._async_thread.run_coroutine(self._engine.stop_simulation())
            show_info(self, "自动模拟已停止")

    def _gen_demo(self) -> None:
        self._point_table = PointTable()
        self._point_table.generate_demo_points(yx_count=50, yc_count=30, yk_count=10, ym_count=10)
        self._point_table.common_addr = self._listen_bar.addr_spin.value()
        self._point_table.station_name = "DemoSlave"
        self._table.load_from_point_table(self._point_table, self._engine.data_store if self._engine else None)
        show_success(self, "已生成演示点表")

    def _import_yaml(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入点表", "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            self._point_table.load_yaml(path)
            self._table.load_from_point_table(self._point_table)
            if self._engine:
                self._engine.data_store.init_from_point_table(self._point_table)
            show_success(self, f"已导入 {path}")
        except Exception as e:
            show_error(self, f"导入失败: {e}")

    def _export_yaml(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出点表", "slave_points.yaml", "YAML (*.yaml)")
        if path:
            try:
                self._point_table.save_yaml(path)
                show_success(self, f"已导出 {path}")
            except Exception as e:
                show_error(self, f"导出失败: {e}")

    def _refresh(self) -> None:
        if not self._engine:
            return
        try:
            self._table.update_from_store(self._engine.data_store)
            self._listen_bar.set_running(True, self._engine.client_count)
            self._clients.set_clients(self._engine.client_list)
            stats = self._engine.connection_stats
            if stats:
                self._status.update_traffic(
                    stats.frames_sent, stats.frames_received,
                    stats.bytes_sent, stats.bytes_received,
                )
                self._status.update_state(f"监听中 客户端={self._engine.client_count}")
            seq = self._engine.sequence_manager
            if seq:
                self._status.update_seq(seq.send_seq, seq.recv_seq, seq.unconfirmed_count, seq.k, seq.w)
        except Exception:
            pass

    def _set_theme(self, name: str) -> None:
        self._config.display.theme = name
        apply_theme(QApplication.instance(), name)

    def _about(self) -> None:
        QMessageBox.about(
            self, "关于 IEC104 子站",
            "IEC104 子站 — IEC 60870-5-104 子站服务端\n\n"
            "可独立供第三方主站连接；也可与「IEC104 主站」同时打开联调。\n"
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
        if self._engine:
            fut = self._async_thread.run_coroutine(self._engine.stop())
            if fut:
                try:
                    fut.result(timeout=6)
                except Exception:
                    pass
        self._async_thread.stop()
        event.accept()
