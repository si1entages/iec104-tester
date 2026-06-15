"""主站视图 — 主站模式的完整UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabWidget

from core.config import AppConfig
from core.engine.master import MasterEngine, MasterEvent
from gui.master.control_panel import ControlPanel
from gui.master.monitor import MonitorPanel
from gui.widgets.toast import show_info

from .base_view import BaseView


class MasterView(BaseView):
    """主站视图 — 包含控制面板、监控面板."""

    # 信号
    gi_requested = Signal()
    ci_requested = Signal()
    clock_sync_requested = Signal()
    reset_requested = Signal()
    test_requested = Signal()
    startdt_requested = Signal()
    stopdt_requested = Signal()
    command_ready = Signal(str, dict)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(config, parent)
        self._init_engine()

    def _init_ui(self) -> None:
        """初始化界面 — 主站模式."""
        super()._init_ui()

        # 添加主站专用面板
        self._control_panel = ControlPanel()
        self._control_panel.command_ready.connect(self._on_command)
        self._func_tabs.insertTab(0, self._control_panel, "控制")

        self._monitor_panel = MonitorPanel()
        self._func_tabs.insertTab(1, self._monitor_panel, "监控")

        # 连接侧边栏信号
        self._connect_sidebar_signals()

    def _connect_sidebar_signals(self) -> None:
        """连接侧边栏信号."""
        self._sidebar.gi_clicked.connect(self.gi_requested.emit)
        self._sidebar.ci_clicked.connect(self.ci_requested.emit)
        self._sidebar.clock_clicked.connect(self.clock_sync_requested.emit)
        self._sidebar.reset_clicked.connect(self.reset_requested.emit)
        self._sidebar.test_clicked.connect(self.test_requested.emit)
        self._sidebar.startdt_clicked.connect(self.startdt_requested.emit)
        self._sidebar.stopdt_clicked.connect(self.stopdt_requested.emit)

    def _init_engine(self) -> None:
        """初始化主站引擎."""
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

    def _on_master_event(self, event: MasterEvent, data: dict) -> None:
        """主站事件回调."""
        self._on_event(event.value, data)

    def _on_raw_frame(self, data: bytes, direction: str) -> None:
        """原始帧回调."""
        super()._on_raw_frame(data, direction, "")

    def _update_status(self) -> None:
        """更新状态面板."""
        super()._update_status()

        if not self._engine:
            return

        state = self._engine.state
        connected = self._engine.is_running
        self._status_panel.update_state(state, connected)
        self._sidebar.set_connected(connected, f"{self._config.connection.host}:{self._config.connection.port}")

        # 更新序列号
        seq = self._engine.sequence_manager
        self._status_panel.update_sequences(
            seq.send_seq, seq.recv_seq,
            seq.unconfirmed_count, seq.k, seq.w
        )
        self._sidebar.update_sequence(
            seq.send_seq, seq.recv_seq,
            seq.unconfirmed_count, seq.k, seq.w
        )

        # 更新通信统计
        stats = self._engine.connection_stats
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

        # 更新监控面板
        store = self._engine.data_store
        s = store.stats
        self._monitor_panel.update_connection(state, connected)
        self._monitor_panel.update_data_stats(
            s['yx_count'], s['yc_count'], s['yk_count'], s['ym_count']
        )

    def _on_command(self, cmd_type: str, params: dict) -> None:
        """遥控命令."""
        if not self._engine or not self._engine.is_running:
            return

        self.command_ready.emit(cmd_type, params)

    # ── 命令方法（供外部调用）─────────────────────────────────────

    def start_engine(self, async_thread) -> None:
        """启动引擎."""
        if self._engine:
            async_thread.run_coroutine(self._engine.start())

    def stop_engine(self, async_thread) -> None:
        """停止引擎."""
        if self._engine:
            async_thread.run_coroutine(self._engine.stop())

    def general_interrogation(self, async_thread) -> None:
        """发送总召唤."""
        if self._engine and self._engine.is_running:
            async_thread.run_coroutine(self._engine.general_interrogation())

    def counter_interrogation(self, async_thread) -> None:
        """发送累计量召唤."""
        if self._engine and self._engine.is_running:
            async_thread.run_coroutine(self._engine.counter_interrogation())

    def clock_sync(self, async_thread) -> None:
        """发送时钟同步."""
        if self._engine and self._engine.is_running:
            async_thread.run_coroutine(self._engine.clock_sync())

    def reset_process(self, async_thread) -> None:
        """发送复位进程."""
        if self._engine and self._engine.is_running:
            async_thread.run_coroutine(self._engine.reset_process())

    def send_test_command(self, async_thread) -> None:
        """发送测试命令."""
        if self._engine and self._engine.is_running:
            async_thread.run_coroutine(self._engine.send_test_command())

    def send_startdt(self, async_thread) -> None:
        """发送STARTDT."""
        if self._engine:
            async_thread.run_coroutine(self._engine.send_startdt())

    def send_stopdt(self, async_thread) -> None:
        """发送STOPDT."""
        if self._engine:
            async_thread.run_coroutine(self._engine.send_stopdt())

    def send_command(self, async_thread, cmd_type: str, params: dict) -> None:
        """发送遥控命令."""
        if not self._engine or not self._engine.is_running:
            return

        if cmd_type == "single":
            async_thread.run_coroutine(
                self._engine.single_command(
                    params["ioa"], params["state"],
                    params["select"], params["qu"]
                )
            )
        elif cmd_type == "double":
            async_thread.run_coroutine(
                self._engine.double_command(
                    params["ioa"], params["state"],
                    params["select"], params["qu"]
                )
            )
        elif cmd_type == "setpoint":
            async_thread.run_coroutine(
                self._engine.setpoint_shortfloat(
                    params["ioa"], params["value"],
                    params["select"]
                )
            )

    def get_control_panel(self) -> ControlPanel:
        """获取控制面板."""
        return self._control_panel

    def get_monitor_panel(self) -> MonitorPanel:
        """获取监控面板."""
        return self._monitor_panel
