"""主窗口 — 精简为纯UI容器."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, Signal, Slot, QSettings
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStatusBar, QMessageBox, QLabel, QApplication,
)

from core.config import AppConfig
from gui.themes import get_theme
from gui.widgets.tool_bar import MainToolBar
from gui.shortcuts import register_shortcuts
from gui.widgets.toast import show_info, show_success, show_error
from gui.widgets.context_menu import ContextMenuFactory
from gui.widgets.export_utils import export_table_to_csv
from gui.dialogs import ConfigDialog
from gui.views.master_view import MasterView
from gui.views.slave_view import SlaveView

logger = logging.getLogger("iec104.gui")


class AsyncThread(QThread):
    """在独立线程运行asyncio事件循环."""

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
    """IEC 60870-5-104测试软件主窗口."""

    _sig_event = Signal(str, dict)
    _sig_raw_frame = Signal(bytes, str, str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._start_time = time.monotonic()

        # 异步线程
        self._async_thread = AsyncThread(self)
        self._async_thread.start()

        # 初始化UI
        self._init_ui()
        self._init_view()
        self._connect_signals()

        # 创建菜单（依赖view）
        self._create_menus()

        logger.info(f"MainWindow initialized in {config.mode} mode")

    def _init_ui(self) -> None:
        """初始化基础界面。"""
        is_master = self._config.mode == "master"
        title = f"IEC 60870-5-104 {'主站' if is_master else '子站'}测试工具"
        self.setWindowTitle(title)
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)
        self.showMaximized()  # 默认最大化

        # 空中央部件
        self.setCentralWidget(QWidget())

        # 工具栏
        mode_str = "master" if is_master else "slave"
        self._toolbar = MainToolBar(mode=mode_str)
        self.addToolBar(self._toolbar)

        # 状态栏
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._mode_label = QLabel(f"模式: {'主站' if is_master else '子站'}")
        self._statusbar.addWidget(self._mode_label)
        self._conn_label = QLabel("连接: 未连接")
        self._statusbar.addPermanentWidget(self._conn_label)

        # 设置窗口图标
        icon_path = os.path.join(os.path.dirname(__file__), "..", "resources", "icon.svg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _init_view(self) -> None:
        """初始化视图（主站或子站）."""
        if self._config.mode == "master":
            self._view = MasterView(self._config, self)
            self._view.start_engine(self._async_thread)
        else:
            self._view = SlaveView(self._config, self)
            self._view.start_engine(self._async_thread)

        # 将视图设置为中心部件
        self.setCentralWidget(self._view)

        # 连接视图信号
        self._view.raw_frame_received.connect(self._on_raw_frame_ui)
        self._view.event_received.connect(self._on_event_ui)

    def _connect_signals(self) -> None:
        """连接工具栏和视图信号."""
        is_master = self._config.mode == "master"

        # 通用信号
        self._toolbar.settings_clicked.connect(self._show_settings)

        if is_master:
            # 主站信号
            self._toolbar.connect_clicked.connect(lambda: self._view.start_engine(self._async_thread))
            self._toolbar.disconnect_clicked.connect(lambda: self._view.stop_engine(self._async_thread))
            self._toolbar.gi_clicked.connect(lambda: self._view.general_interrogation(self._async_thread))
            self._toolbar.ci_clicked.connect(lambda: self._view.counter_interrogation(self._async_thread))
            self._toolbar.clock_clicked.connect(lambda: self._view.clock_sync(self._async_thread))
            self._toolbar.reset_clicked.connect(lambda: self._view.reset_process(self._async_thread))
            self._toolbar.test_clicked.connect(lambda: self._view.send_test_command(self._async_thread))
            self._view.command_ready.connect(lambda ct, p: self._view.send_command(self._async_thread, ct, p))
            self._view.startdt_requested.connect(lambda: self._view.send_startdt(self._async_thread))
            self._view.stopdt_requested.connect(lambda: self._view.send_stopdt(self._async_thread))
        else:
            # 子站信号
            self._toolbar.start_listen_clicked.connect(lambda: self._view.start_engine(self._async_thread))
            self._toolbar.stop_listen_clicked.connect(lambda: self._view.stop_engine(self._async_thread))
            self._toolbar.send_data_clicked.connect(lambda: self._view.send_test_data(self._async_thread))

        # 状态更新定时器
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(500)

        # 注册快捷键
        self._register_shortcuts()

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
        clear_log.triggered.connect(self._view.get_log_viewer()._clear)
        tools_menu.addAction(clear_log)

        clear_hex = QAction("清空报文", self)
        clear_hex.triggered.connect(self._view.get_hex_viewer()._clear)
        tools_menu.addAction(clear_hex)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _register_shortcuts(self) -> None:
        """注册快捷键."""
        is_master = self._config.mode == "master"
        callbacks = {
            "clear_log": self._view.get_log_viewer()._clear,
            "clear_hex": self._view.get_hex_viewer()._clear,
            "about": self._show_about,
            "quit": self.close,
        }
        if is_master:
            callbacks.update({
                "general_interrogation": lambda: self._view.general_interrogation(self._async_thread),
                "counter_interrogation": lambda: self._view.counter_interrogation(self._async_thread),
                "clock_sync": lambda: self._view.clock_sync(self._async_thread),
                "reset_process": lambda: self._view.reset_process(self._async_thread),
                "test_command": lambda: self._view.send_test_command(self._async_thread),
                "startdt": lambda: self._view.send_startdt(self._async_thread),
                "stopdt": lambda: self._view.send_stopdt(self._async_thread),
            })
        register_shortcuts(self, callbacks)

    def _update_status_bar(self) -> None:
        """更新状态栏."""
        engine = self._view.get_engine()
        if engine:
            is_master = self._config.mode == "master"
            if is_master:
                state = engine.state
                self._conn_label.setText(f"连接: {state}")
                self._toolbar.set_connected(engine.is_running)
            else:
                self._conn_label.setText(f"连接: {engine.client_count} 客户端")
                self._toolbar.set_connected(engine.is_running)

    def _on_event_ui(self, event_type: str, data: dict) -> None:
        """在Qt主线程中更新事件UI."""
        self._view.get_log_viewer().add_event(event_type, data)

    def _on_raw_frame_ui(self, data: bytes, direction: str, client_id: str) -> None:
        """在Qt主线程中更新报文UI."""
        self._view.get_hex_viewer().add_frame(data, direction)

    def _load_point_table(self) -> None:
        """加载点表文件."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "加载点表", "", "YAML Files (*.yaml *.yml)"
        )
        if path:
            try:
                self._view.get_point_table().load_yaml(path)
                if hasattr(self._view, 'get_point_editor'):
                    self._view.get_point_editor().refresh()
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
                self._view.get_point_table().save_yaml(path)
                show_success(self, f"点表已保存: {path}")
            except Exception as e:
                show_error(self, f"保存失败: {e}")

    def _apply_theme(self, theme: str) -> None:
        """应用主题."""
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

        show_info(self, "配置已更新")

    def _show_about(self) -> None:
        """显示关于对话框."""
        QMessageBox.about(
            self, "关于",
            "IEC 60870-5-104 协议测试工具 v1.0\n\n"
            "功能特性:\n"
            "- 完整的 IEC 60870-5-104 协议实现\n"
            "- 主站/子站双模式\n"
            "- 遥信/遥测/遥控/遥脉表格\n"
            "- 实时数据刷新\n"
            "- 报文解析与 HEX 查看\n"
            "- 数据模拟器\n"
            "- 点表编辑器\n\n"
            "基于 PySide6 + asyncio 构建"
        )

    def _save_layout(self) -> None:
        """保存窗口布局."""
        settings = QSettings("IEC104Tester", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())

    def _restore_layout(self) -> None:
        """恢复窗口布局."""
        settings = QSettings("IEC104Tester", "MainWindow")
        geometry = settings.value("geometry")
        state = settings.value("windowState")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def closeEvent(self, event) -> None:
        """关闭窗口."""
        self._save_layout()

        # 停止引擎
        engine = self._view.get_engine()
        if engine:
            self._async_thread.run_coroutine(engine.stop())

        # 停止异步线程
        self._async_thread.stop()

        event.accept()
