"""主窗口 — 组装所有组件."""

from __future__ import annotations

import asyncio
import sys
import time
import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot, QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget,
    QTabWidget, QStatusBar, QMenuBar, QToolBar,
    QMessageBox, QLabel, QApplication, QDockWidget,
)

from core.config import AppConfig, load_config
from core.data.point_table import PointTable
from core.data.data_store import RealtimeDB
from gui.themes import get_theme
from gui.widgets.point_table import (
    YxTableModel, YcTableModel, YkTableModel, YmTableModel,
    PointTablePanel,
)
from gui.widgets.hex_viewer import HexViewer
from gui.widgets.status_panel import StatusPanel, LogViewer
from gui.master.control_panel import ControlPanel
from gui.master.monitor import MonitorPanel
from gui.slave.sim_panel import SimPanel
from gui.slave.point_editor import PointEditorPanel
from gui.slave.response_cfg import ResponseConfigPanel
from gui.widgets.tool_bar import MainToolBar
from gui.widgets.sidebar import Sidebar
from gui.widgets.capture_panel import CapturePanel
from gui.shortcuts import register_shortcuts
from gui.widgets.config_dialog import ConfigDialog
from gui.widgets.toast import show_info, show_success, show_error
from gui.widgets.context_menu import ContextMenuFactory
from gui.widgets.export_utils import export_table_to_csv

logger = logging.getLogger("iec104.gui")


class AsyncThread(QThread):
    """在独立线程运行 asyncio 事件循环."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.wait(3000)

    def run_coroutine(self, coro):
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        return None


class MainWindow(QMainWindow):
    """IEC 60870-5-104 测试软件主窗口."""

    # 线程安全信号：从 asyncio 线程发射，Qt 主线程接收
    _sig_event = Signal(str, dict)
    _sig_raw_frame = Signal(bytes, str, str)  # data, direction, client_id

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._start_time = time.monotonic()

        # 异步线程
        self._async_thread = AsyncThread(self)
        self._async_thread.start()

        # 点表和数据
        self._point_table = PointTable()
        self._init_point_table()

        # 引擎（延迟初始化）
        self._engine = None

        # 数据刷新定时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_data)
        self._refresh_timer.start(config.display.refresh_interval_ms)

        # 状态更新定时器
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start(500)

        # 初始化 UI
        self._init_ui()
        self._init_engine()

        # 线程安全信号 → Qt 主线程更新 UI
        self._sig_event.connect(self._on_event_ui)
        self._sig_raw_frame.connect(self._on_raw_frame_ui)

        logger.info(f"MainWindow initialized in {config.mode} mode")

    def _init_point_table(self) -> None:
        """初始化点表."""
        if self._config.point_table.file:
            try:
                self._point_table.load_yaml(self._config.point_table.file)
            except Exception as e:
                logger.error(f"Failed to load point table: {e}")

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

    def _init_ui(self) -> None:
        """初始化界面 — 使用 QDockWidget 布局，支持自由拖拽/浮动/标签化."""
        is_master = self._config.mode == "master"
        mode_str = "master" if is_master else "slave"
        title = f"IEC 60870-5-104 {'主站' if is_master else '子站'}测试工具"
        self.setWindowTitle(title)
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)

        # 空中央部件（所有内容由 DockWidget 承载）
        self.setCentralWidget(QWidget())

        # 工具栏
        self._toolbar = MainToolBar(mode=mode_str)
        self.addToolBar(self._toolbar)

        # ── 创建各个内容组件 ──────────────────────────────────

        # 侧边栏
        self._sidebar = Sidebar(mode=mode_str)

        # 数据表格（Tab 切换）
        self._data_tabs = QTabWidget()

        self._yx_model = YxTableModel()
        self._yx_panel = PointTablePanel(self._yx_model, "遥信 (YX)")
        self._data_tabs.addTab(self._yx_panel, "遥信 (YX)")

        self._yc_model = YcTableModel()
        self._yc_panel = PointTablePanel(self._yc_model, "遥测 (YC)")
        self._data_tabs.addTab(self._yc_panel, "遥测 (YC)")

        self._yk_model = YkTableModel()
        self._yk_panel = PointTablePanel(self._yk_model, "遥控 (YK)")
        self._data_tabs.addTab(self._yk_panel, "遥控 (YK)")

        # 报文查看器
        self._hex_viewer = HexViewer()

        # 功能面板（Tab 切换）
        self._func_tabs = QTabWidget()

        self._log_viewer = LogViewer()
        self._func_tabs.addTab(self._log_viewer, "📋 日志")

        if is_master:
            self._control_panel = ControlPanel()
            self._control_panel.command_ready.connect(self._on_command)
            self._func_tabs.addTab(self._control_panel, "🎮 控制")

            self._monitor_panel = MonitorPanel()
            self._func_tabs.addTab(self._monitor_panel, "📊 监控")
        else:
            self._sim_panel = SimPanel()
            self._sim_panel.yx_change.connect(self._on_sim_yx)
            self._sim_panel.yc_change.connect(self._on_sim_yc)
            self._sim_panel.simulation_toggled.connect(self._on_sim_toggle)
            self._func_tabs.addTab(self._sim_panel, "🎮 模拟")

            self._response_cfg = ResponseConfigPanel()
            self._func_tabs.addTab(self._response_cfg, "⚙️ 响应配置")

            self._point_editor = PointEditorPanel(self._point_table)
            self._point_editor.point_table_changed.connect(self._on_point_table_changed)
            self._func_tabs.addTab(self._point_editor, "📝 点表编辑")

        self._status_panel = StatusPanel()
        self._func_tabs.addTab(self._status_panel, "📊 状态")

        self._ym_model = YmTableModel()
        self._ym_panel = PointTablePanel(self._ym_model, "遥脉 (YM)")
        self._func_tabs.addTab(self._ym_panel, "📈 遥脉")

        self._capture_panel = CapturePanel()
        self._func_tabs.addTab(self._capture_panel, "🔴 录制")

        # 设置右键菜单
        self._setup_context_menus()

        # ── 创建 QDockWidget ──────────────────────────────────

        dock_features = (
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetFloatable
        )

        # 侧边栏 Dock
        self._dock_sidebar = QDockWidget("侧边栏", self)
        self._dock_sidebar.setObjectName("dock_sidebar")
        self._dock_sidebar.setFeatures(dock_features)
        self._dock_sidebar.setWidget(self._sidebar)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock_sidebar)

        # 数据表格 Dock
        self._dock_data = QDockWidget("数据表格", self)
        self._dock_data.setObjectName("dock_data")
        self._dock_data.setFeatures(dock_features)
        self._dock_data.setWidget(self._data_tabs)
        self.addDockWidget(Qt.TopDockWidgetArea, self._dock_data)

        # 报文查看 Dock
        self._dock_hex = QDockWidget("报文查看", self)
        self._dock_hex.setObjectName("dock_hex")
        self._dock_hex.setFeatures(dock_features)
        self._dock_hex.setWidget(self._hex_viewer)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_hex)

        # 功能面板 Dock
        self._dock_func = QDockWidget("功能面板", self)
        self._dock_func.setObjectName("dock_func")
        self._dock_func.setFeatures(dock_features)
        self._dock_func.setWidget(self._func_tabs)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_func)

        # 将报文查看和功能面板左右并排
        self.splitDockWidget(self._dock_hex, self._dock_func, Qt.Horizontal)

        # 菜单栏
        self._create_menus()

        # 状态栏
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._mode_label = QLabel(f"模式: {'主站' if is_master else '子站'}")
        self._statusbar.addWidget(self._mode_label)
        self._conn_label = QLabel("连接: 未连接")
        self._statusbar.addPermanentWidget(self._conn_label)
        self._fps_label = QLabel("")
        self._statusbar.addPermanentWidget(self._fps_label)

        # 连接工具栏信号
        self._connect_toolbar_signals()

        # 连接侧边栏信号
        self._connect_sidebar_signals()

        # 注册快捷键
        self._register_shortcuts()

        # 恢复上次布局
        self._restore_layout()

    def _create_menus(self) -> None:
        """创建菜单栏."""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        load_action = QAction("加载点表(&L)", self)
        load_action.triggered.connect(self._load_point_table)
        file_menu.addAction(load_action)

        save_action = QAction("保存点表(&S)", self)
        save_action.triggered.connect(self._save_point_table)
        file_menu.addAction(save_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&X)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 视图菜单
        view_menu = menubar.addMenu("视图(&V)")

        dark_action = QAction("深色主题", self)
        dark_action.triggered.connect(lambda: self._apply_theme("dark"))
        view_menu.addAction(dark_action)

        light_action = QAction("浅色主题", self)
        light_action.triggered.connect(lambda: self._apply_theme("light"))
        view_menu.addAction(light_action)

        view_menu.addSeparator()

        # DockWidget 显示/隐藏
        view_menu.addAction(self._dock_sidebar.toggleViewAction())
        view_menu.addAction(self._dock_data.toggleViewAction())
        view_menu.addAction(self._dock_hex.toggleViewAction())
        view_menu.addAction(self._dock_func.toggleViewAction())

        view_menu.addSeparator()

        reset_layout_action = QAction("重置布局", self)
        reset_layout_action.triggered.connect(self._reset_layout)
        view_menu.addAction(reset_layout_action)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")

        clear_log = QAction("清空日志", self)
        clear_log.triggered.connect(self._log_viewer._clear)
        tools_menu.addAction(clear_log)

        clear_hex = QAction("清空报文", self)
        clear_hex.triggered.connect(self._hex_viewer._clear)
        tools_menu.addAction(clear_hex)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _connect_toolbar_signals(self) -> None:
        """连接工具栏信号."""
        is_master = self._config.mode == "master"
        if is_master:
            self._toolbar.gi_clicked.connect(self._on_gi)
            self._toolbar.ci_clicked.connect(self._on_ci)
            self._toolbar.clock_clicked.connect(self._on_clock_sync)
            self._toolbar.reset_clicked.connect(self._on_reset)
            self._toolbar.test_clicked.connect(self._on_test)
        self._toolbar.record_clicked.connect(self._capture_panel._on_record_start)
        self._toolbar.stop_record_clicked.connect(self._capture_panel._on_record_stop)
        self._toolbar.settings_clicked.connect(self._show_settings)

    def _connect_sidebar_signals(self) -> None:
        """连接侧边栏信号."""
        is_master = self._config.mode == "master"
        if is_master:
            self._sidebar.gi_clicked.connect(self._on_gi)
            self._sidebar.ci_clicked.connect(self._on_ci)
            self._sidebar.clock_clicked.connect(self._on_clock_sync)
            self._sidebar.reset_clicked.connect(self._on_reset)
            self._sidebar.test_clicked.connect(self._on_test)
            self._sidebar.startdt_clicked.connect(self._on_startdt)
            self._sidebar.stopdt_clicked.connect(self._on_stopdt)

    def _register_shortcuts(self) -> None:
        """注册快捷键."""
        is_master = self._config.mode == "master"
        callbacks = {
            "clear_log": self._log_viewer._clear,
            "clear_hex": self._hex_viewer._clear,
            "refresh": self._refresh_data,
            "about": self._show_about,
            "quit": self.close,
        }
        if is_master:
            callbacks.update({
                "general_interrogation": self._on_gi,
                "counter_interrogation": self._on_ci,
                "clock_sync": self._on_clock_sync,
                "reset_process": self._on_reset,
                "test_command": self._on_test,
                "startdt": self._on_startdt,
                "stopdt": self._on_stopdt,
            })
        register_shortcuts(self, callbacks)

    def _setup_context_menus(self) -> None:
        """为数据表格设置右键菜单."""
        is_master = self._config.mode == "master"

        for panel, name in [
            (self._yx_panel, "遥信"),
            (self._yc_panel, "遥测"),
            (self._ym_panel, "遥脉"),
        ]:
            ctx = ContextMenuFactory(self)
            ctx.export_csv_triggered.connect(
                lambda p=panel, n=name: export_table_to_csv(self, p.table, n)
            )
            panel.table.setContextMenuPolicy(Qt.CustomContextMenu)
            panel.table.customContextMenuRequested.connect(
                lambda pos, t=panel.table, c=ctx: c.create_table_menu().exec(t.viewport().mapToGlobal(pos))
            )

    def _init_engine(self) -> None:
        """初始化协议引擎."""
        is_master = self._config.mode == "master"

        if is_master:
            from core.engine.master import MasterEngine, MasterEvent
            self._engine = MasterEngine(
                host=self._config.connection.host,
                port=self._config.connection.port,
                common_addr=self._config.connection.common_addr,
                k=self._config.flow_control.k,
                w=self._config.flow_control.w,
                t0=self._config.timers.t0,
                t1=self._config.timers.t1,
                t2=self._config.timers.t2,
                t3=self._config.timers.t3,
                auto_start=self._config.master.auto_start,
                auto_gi=self._config.master.auto_gi,
                reconnect=self._config.connection.reconnect,
                reconnect_interval=self._config.connection.reconnect_interval,
            )
            self._engine.set_event_callback(self._on_master_event)
            self._engine.set_raw_frame_callback(self._on_raw_frame)

            # 启动引擎
            self._async_thread.run_coroutine(self._engine.start())
        else:
            from core.engine.slave import SlaveEngine, SlaveEvent
            self._engine = SlaveEngine(
                host="0.0.0.0",
                port=self._config.connection.port,
                common_addr=self._config.connection.common_addr,
                k=self._config.flow_control.k,
                w=self._config.flow_control.w,
                t0=self._config.timers.t0,
                t1=self._config.timers.t1,
                t2=self._config.timers.t2,
                t3=self._config.timers.t3,
                max_connections=self._config.connection.max_connections,
                point_table=self._point_table,
                spontaneous_enabled=self._config.slave.spontaneous_enabled,
            )
            self._engine.set_event_callback(self._on_slave_event)
            self._engine.set_raw_frame_callback(self._on_raw_frame_slave)

            # 初始化数据
            self._engine.data_store.init_from_point_table(self._point_table)

            # 启动引擎
            self._async_thread.run_coroutine(self._engine.start())

    # ── 数据刷新 ──────────────────────────────────────────────────

    def _refresh_data(self) -> None:
        """定时刷新表格数据."""
        if not self._engine:
            return

        store = self._engine.data_store

        self._yx_model.update_data(store.get_all_yx())
        self._yc_model.update_data(store.get_all_yc())
        self._yk_model.update_data(store.get_all_yk())
        self._ym_model.update_data(store.get_all_ym())

    def _update_status(self) -> None:
        """定时更新状态面板."""
        if not self._engine:
            return

        # 运行时间
        self._status_panel.update_uptime(time.monotonic() - self._start_time)

        is_master = self._config.mode == "master"

        if is_master:
            engine = self._engine
            state = engine.state
            connected = engine.is_running
            self._status_panel.update_state(state, connected)
            self._conn_label.setText(f"连接: {state}")

            # 更新工具栏和侧边栏连接状态
            self._toolbar.set_connected(connected)
            self._sidebar.set_connected(connected, f"{self._config.connection.host}:{self._config.connection.port}")

            # 运行时间
            uptime_s = time.monotonic() - self._start_time
            hours, remainder = divmod(int(uptime_s), 3600)
            minutes, seconds = divmod(remainder, 60)
            self._sidebar.set_runtime(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

            # 序列号
            seq = engine.sequence_manager
            self._status_panel.update_sequences(
                seq.send_seq, seq.recv_seq,
                seq.unconfirmed_count, seq.k, seq.w
            )
            self._sidebar.update_sequence(
                seq.send_seq, seq.recv_seq,
                seq.unconfirmed_count, seq.k, seq.w
            )

            # 通信统计
            stats = engine.connection_stats
            if stats:
                self._status_panel.update_stats(
                    stats.frames_sent, stats.frames_received,
                    stats.bytes_sent, stats.bytes_received,
                    stats.errors, stats.reconnections,
                )
                self._sidebar.update_stats(
                    stats.frames_sent, stats.frames_received,
                    stats.bytes_sent, stats.bytes_received,
                    stats.errors,
                )

            # 监控面板
            if hasattr(self, '_monitor_panel'):
                store = engine.data_store
                s = store.stats
                self._monitor_panel.update_connection(state, connected)
                self._monitor_panel.update_data_stats(
                    s['yx_count'], s['yc_count'], s['yk_count'], s['ym_count']
                )
        else:
            engine = self._engine
            connected = engine.is_running
            self._status_panel.update_state(
                f"监听中 ({engine.client_count} 连接)",
                connected
            )
            self._conn_label.setText(f"连接: {engine.client_count} 客户端")
            self._toolbar.set_connected(connected)

            # 运行时间
            uptime_s = time.monotonic() - self._start_time
            hours, remainder = divmod(int(uptime_s), 3600)
            minutes, seconds = divmod(remainder, 60)
            self._sidebar.set_runtime(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    # ── 主站事件（asyncio 线程 → 信号 → Qt 主线程）────────────────

    def _on_master_event(self, event, data: dict) -> None:
        """主站事件回调（从 asyncio 线程调用）."""
        self._sig_event.emit(event.value, data)

    def _on_raw_frame(self, data: bytes, direction: str) -> None:
        """原始帧回调（从 asyncio 线程调用）."""
        self._sig_raw_frame.emit(data, direction, "")

    def _on_raw_frame_slave(self, data: bytes, direction: str, client_id: str) -> None:
        """子站原始帧回调（从 asyncio 线程调用）."""
        self._sig_raw_frame.emit(data, direction, client_id)

    # ── UI 更新槽（Qt 主线程执行）────────────────────────────────

    def _on_event_ui(self, event_type: str, data: dict) -> None:
        """在 Qt 主线程中更新事件 UI."""
        self._log_viewer.add_event(event_type, data)
        if hasattr(self, '_monitor_panel'):
            self._monitor_panel.add_event(
                event_type,
                str(data.get("type_id", "")),
                str(data)[:100],
            )

    def _on_raw_frame_ui(self, data: bytes, direction: str, client_id: str) -> None:
        """在 Qt 主线程中更新报文 UI."""
        self._hex_viewer.add_frame(data, direction)

    # ── 子站事件 ──────────────────────────────────────────────────

    def _on_slave_event(self, event, data: dict) -> None:
        """子站事件回调（从 asyncio 线程调用）."""
        self._sig_event.emit(event.value, data)

    # ── 命令处理 ──────────────────────────────────────────────────

    def _on_gi(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.general_interrogation())
            show_info(self, "总召唤命令已发送")

    def _on_ci(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.counter_interrogation())
            show_info(self, "累计量召唤命令已发送")

    def _on_clock_sync(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.clock_sync())
            show_info(self, "时钟同步命令已发送")

    def _on_reset(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.reset_process())
            show_info(self, "复位进程命令已发送")

    def _on_test(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.send_test_command())
            show_info(self, "测试命令已发送")

    def _on_startdt(self) -> None:
        if self._engine:
            self._async_thread.run_coroutine(self._engine.send_startdt())

    def _on_stopdt(self) -> None:
        if self._engine:
            self._async_thread.run_coroutine(self._engine.send_stopdt())

    def _on_command(self, cmd_type: str, params: dict) -> None:
        """遥控命令."""
        if not self._engine or not self._engine.is_running:
            return

        if cmd_type == "single":
            self._async_thread.run_coroutine(
                self._engine.single_command(
                    params["ioa"], params["state"],
                    params["select"], params["qu"]
                )
            )
        elif cmd_type == "double":
            self._async_thread.run_coroutine(
                self._engine.double_command(
                    params["ioa"], params["state"],
                    params["select"], params["qu"]
                )
            )
        elif cmd_type == "setpoint":
            self._async_thread.run_coroutine(
                self._engine.setpoint_shortfloat(
                    params["ioa"], params["value"],
                    params["select"]
                )
            )

    # ── 子站模拟 ──────────────────────────────────────────────────

    def _on_sim_yx(self, ioa: int, value: bool) -> None:
        if self._engine:
            self._engine.simulate_yx_change(ioa, value)

    def _on_sim_yc(self, ioa: int, value: float) -> None:
        if self._engine:
            self._engine.simulate_yc_change(ioa, value)

    def _on_sim_toggle(self, enabled: bool) -> None:
        if not self._engine:
            return
        if enabled:
            cfg = self._sim_panel.sim_config
            self._async_thread.run_coroutine(
                self._engine.start_simulation(**cfg)
            )
        else:
            self._async_thread.run_coroutine(
                self._engine.stop_simulation()
            )

    def _on_point_table_changed(self) -> None:
        """点表变更后重新初始化数据."""
        if self._engine and self._config.mode == "slave":
            self._engine.data_store.init_from_point_table(self._point_table)

    # ── 点表文件操作 ──────────────────────────────────────────────

    def _load_point_table(self) -> None:
        """加载点表文件."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "加载点表", "", "YAML Files (*.yaml *.yml)"
        )
        if path:
            try:
                self._point_table.load_yaml(path)
                if self._engine and self._config.mode == "slave":
                    self._engine.data_store.init_from_point_table(self._point_table)
                if hasattr(self, '_point_editor'):
                    self._point_editor.refresh()
                show_success(self, f"点表已加载: {path}")
            except Exception as e:
                show_error(self, f"加载失败: {e}")

    def _save_point_table(self) -> None:
        """保存点表文件."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存点表", "point_table.yaml", "YAML Files (*.yaml)"
        )
        if path:
            try:
                self._point_table.save_yaml(path)
                show_success(self, f"点表已保存: {path}")
            except Exception as e:
                show_error(self, f"保存失败: {e}")

    # ── 主题 ──────────────────────────────────────────────────────

    def _apply_theme(self, theme: str) -> None:
        self._config.display.theme = theme
        QApplication.instance().setStyleSheet(get_theme(theme))

    def _show_settings(self) -> None:
        """打开设置对话框."""
        dlg = ConfigDialog(self._config, parent=self)
        dlg.config_changed.connect(self._on_config_changed)
        dlg.exec()

    def _on_config_changed(self, config: dict) -> None:
        """设置变更回调."""
        conn = config.get("connection", {})
        if conn.get("host"):
            self._config.connection.host = conn["host"]
        if conn.get("port"):
            self._config.connection.port = conn["port"]
        if conn.get("common_addr"):
            self._config.connection.common_addr = conn["common_addr"]
        self._config.connection.reconnect = conn.get("reconnect", True)
        self._config.connection.reconnect_interval = conn.get("reconnect_interval", 5.0)

        timers = config.get("timers", {})
        self._config.timers.t0 = timers.get("t0", 30)
        self._config.timers.t1 = timers.get("t1", 15)
        self._config.timers.t2 = timers.get("t2", 10)
        self._config.timers.t3 = timers.get("t3", 20)

        display = config.get("display", {})
        if display.get("theme"):
            self._apply_theme(display["theme"])

        from gui.widgets.toast import show_info
        show_info(self, "配置已更新")

    # ── 关于 ──────────────────────────────────────────────────────

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "关于",
            "IEC 60870-5-104 协议测试工具 v1.0\n\n"
            "功能特性:\n"
            "• 完整的 IEC 60870-5-104 协议实现\n"
            "• 主站/子站双模式\n"
            "• 遥信/遥测/遥控/遥脉表格\n"
            "• 实时数据刷新\n"
            "• 报文解析与 HEX 查看\n"
            "• 数据模拟器\n"
            "• 点表编辑器\n"
            "• 响应行为配置\n"
            "• 主站监控总览\n\n"
            "基于 PySide6 + asyncio 构建"
        )

    # ── 布局管理 ──────────────────────────────────────────────────

    def _save_layout(self) -> None:
        """使用 QSettings 保存 dock 布局."""
        settings = QSettings("IEC104Tester", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

    def _restore_layout(self) -> None:
        """从 QSettings 恢复 dock 布局."""
        settings = QSettings("IEC104Tester", "MainWindow")
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def _reset_layout(self) -> None:
        """重置为默认 dock 布局."""
        self._dock_sidebar.show()
        self._dock_data.show()
        self._dock_hex.show()
        self._dock_func.show()

        self.removeDockWidget(self._dock_sidebar)
        self.removeDockWidget(self._dock_data)
        self.removeDockWidget(self._dock_hex)
        self.removeDockWidget(self._dock_func)

        self.addDockWidget(Qt.LeftDockWidgetArea, self._dock_sidebar)
        self.addDockWidget(Qt.TopDockWidgetArea, self._dock_data)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_hex)
        self.addDockWidget(Qt.BottomDockWidgetArea, self._dock_func)
        self.splitDockWidget(self._dock_hex, self._dock_func, Qt.Horizontal)

        self.resize(1600, 1000)

    # ── 关闭 ──────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """关闭窗口."""
        self._save_layout()

        # 停止引擎
        if self._engine:
            self._async_thread.run_coroutine(self._engine.stop())

        # 停止异步线程
        self._async_thread.stop()

        event.accept()
