"""主窗口 — 组装所有组件."""

from __future__ import annotations

import asyncio
import sys
import time
import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QSplitter, QStatusBar, QMenuBar, QToolBar,
    QMessageBox, QLabel, QApplication,
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
from gui.master.control_panel import CommandBar, ControlPanel
from gui.master.monitor import MonitorPanel
from gui.slave.sim_panel import SimPanel
from gui.slave.point_editor import PointEditorPanel
from gui.slave.response_cfg import ResponseConfigPanel

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
        """初始化界面."""
        is_master = self._config.mode == "master"
        title = f"IEC 60870-5-104 {'主站' if is_master else '子站'}测试工具"
        self.setWindowTitle(title)
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)

        # 菜单栏
        self._create_menus()

        # 主布局
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # 命令栏（主站）
        if is_master:
            self._command_bar = CommandBar()
            self._command_bar.gi_requested.connect(self._on_gi)
            self._command_bar.ci_requested.connect(self._on_ci)
            self._command_bar.clock_sync_requested.connect(self._on_clock_sync)
            self._command_bar.reset_requested.connect(self._on_reset)
            self._command_bar.test_requested.connect(self._on_test)
            self._command_bar.startdt_requested.connect(self._on_startdt)
            self._command_bar.stopdt_requested.connect(self._on_stopdt)
            main_layout.addWidget(self._command_bar)

        # 主分割器（上下）
        main_splitter = QSplitter(Qt.Vertical)

        # 上部：数据表格
        upper_splitter = QSplitter(Qt.Horizontal)

        # 遥信表
        self._yx_model = YxTableModel()
        self._yx_panel = PointTablePanel(self._yx_model, "遥信 (YX)")
        upper_splitter.addWidget(self._yx_panel)

        # 遥测表
        self._yc_model = YcTableModel()
        self._yc_panel = PointTablePanel(self._yc_model, "遥测 (YC)")
        upper_splitter.addWidget(self._yc_panel)

        # 遥控表
        self._yk_model = YkTableModel()
        self._yk_panel = PointTablePanel(self._yk_model, "遥控 (YK)")
        upper_splitter.addWidget(self._yk_panel)

        upper_splitter.setSizes([400, 400, 300])
        main_splitter.addWidget(upper_splitter)

        # 下部：报文/日志/控制
        lower_splitter = QSplitter(Qt.Horizontal)

        # 左：报文查看器
        self._hex_viewer = HexViewer()
        lower_splitter.addWidget(self._hex_viewer)

        # 右下：标签页（日志 + 控制/模拟 + 状态 + 监控 + 遥脉 + 点表编辑）
        right_tabs = QTabWidget()

        # 日志
        self._log_viewer = LogViewer()
        right_tabs.addTab(self._log_viewer, "📋 日志")

        # 控制/模拟面板
        if is_master:
            self._control_panel = ControlPanel()
            self._control_panel.command_ready.connect(self._on_command)
            right_tabs.addTab(self._control_panel, "🎮 控制")

            # 主站监控总览
            self._monitor_panel = MonitorPanel()
            right_tabs.addTab(self._monitor_panel, "📊 监控")
        else:
            self._sim_panel = SimPanel()
            self._sim_panel.yx_change.connect(self._on_sim_yx)
            self._sim_panel.yc_change.connect(self._on_sim_yc)
            self._sim_panel.simulation_toggled.connect(self._on_sim_toggle)
            right_tabs.addTab(self._sim_panel, "🎮 模拟")

            # 子站响应配置
            self._response_cfg = ResponseConfigPanel()
            right_tabs.addTab(self._response_cfg, "⚙️ 响应配置")

            # 点表编辑器
            self._point_editor = PointEditorPanel(self._point_table)
            self._point_editor.point_table_changed.connect(self._on_point_table_changed)
            right_tabs.addTab(self._point_editor, "📝 点表编辑")

        # 状态面板
        self._status_panel = StatusPanel()
        right_tabs.addTab(self._status_panel, "📊 状态")

        # 遥脉表
        self._ym_model = YmTableModel()
        self._ym_panel = PointTablePanel(self._ym_model, "遥脉 (YM)")
        right_tabs.addTab(self._ym_panel, "📈 遥脉")

        lower_splitter.addWidget(right_tabs)
        lower_splitter.setSizes([700, 500])

        main_splitter.addWidget(lower_splitter)
        main_splitter.setSizes([500, 400])

        main_layout.addWidget(main_splitter)

        # 状态栏
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._mode_label = QLabel(f"模式: {'主站' if is_master else '子站'}")
        self._statusbar.addWidget(self._mode_label)
        self._conn_label = QLabel("连接: 未连接")
        self._statusbar.addPermanentWidget(self._conn_label)
        self._fps_label = QLabel("")
        self._statusbar.addPermanentWidget(self._fps_label)

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

            if hasattr(self, '_command_bar') and hasattr(self._command_bar, 'set_connected'):
                self._command_bar.set_connected(connected)

            # 序列号
            seq = engine.sequence_manager
            self._status_panel.update_sequences(
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
            self._status_panel.update_state(
                f"监听中 ({engine.client_count} 连接)",
                engine.is_running
            )
            self._conn_label.setText(f"连接: {engine.client_count} 客户端")

    # ── 主站事件 ──────────────────────────────────────────────────

    def _on_master_event(self, event, data: dict) -> None:
        """主站事件回调."""
        from core.engine.master import MasterEvent
        self._log_viewer.add_event(event.value, data)

        if hasattr(self, '_monitor_panel'):
            self._monitor_panel.add_event(
                event.value,
                str(data.get("type_id", "")),
                str(data)[:100],
            )

    def _on_raw_frame(self, data: bytes, direction: str) -> None:
        """原始帧回调."""
        self._hex_viewer.add_frame(data, direction)

    def _on_raw_frame_slave(self, data: bytes, direction: str, client_id: str) -> None:
        """子站原始帧回调."""
        self._hex_viewer.add_frame(data, direction)

    # ── 子站事件 ──────────────────────────────────────────────────

    def _on_slave_event(self, event, data: dict) -> None:
        """子站事件回调."""
        from core.engine.slave import SlaveEvent
        self._log_viewer.add_event(event.value, data)

    # ── 命令处理 ──────────────────────────────────────────────────

    def _on_gi(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.general_interrogation())

    def _on_ci(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.counter_interrogation())

    def _on_clock_sync(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.clock_sync())

    def _on_reset(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.reset_process())

    def _on_test(self) -> None:
        if self._engine and self._engine.is_running:
            self._async_thread.run_coroutine(self._engine.send_test_command())

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
                QMessageBox.information(self, "成功", f"点表已加载: {path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加载失败: {e}")

    def _save_point_table(self) -> None:
        """保存点表文件."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "保存点表", "point_table.yaml", "YAML Files (*.yaml)"
        )
        if path:
            try:
                self._point_table.save_yaml(path)
                QMessageBox.information(self, "成功", f"点表已保存: {path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {e}")

    # ── 主题 ──────────────────────────────────────────────────────

    def _apply_theme(self, theme: str) -> None:
        self._config.display.theme = theme
        QApplication.instance().setStyleSheet(get_theme(theme))

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

    # ── 关闭 ──────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """关闭窗口."""
        # 停止引擎
        if self._engine:
            self._async_thread.run_coroutine(self._engine.stop())

        # 停止异步线程
        self._async_thread.stop()

        event.accept()
