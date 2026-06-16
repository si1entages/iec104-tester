"""子站视图 — 子站模式的完整UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabWidget

from core.config import AppConfig
from core.engine.slave import SlaveEngine, SlaveEvent
from core.data.point_table import PointTable
from gui.slave.point_editor import PointEditorPanel
from gui.slave.response_cfg import ResponseConfigPanel

from .base_view import BaseView


class SlaveView(BaseView):
    """子站视图 — 包含点表编辑、响应配置."""

    # 信号
    point_table_changed = Signal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(config, parent)
        self._init_point_table()
        self._init_engine()

    def _init_ui(self) -> None:
        """初始化界面 — 子站模式。"""
        super()._init_ui()

        # 添加子站专用面板
        self._response_cfg = ResponseConfigPanel()
        self._func_tabs.insertTab(0, self._response_cfg, "响应配置")

    def _init_engine(self) -> None:
        """初始化子站引擎."""
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

    def _on_slave_event(self, event: SlaveEvent, data: dict) -> None:
        """子站事件回调."""
        self._on_event(event.value, data)

    def _on_raw_frame_slave(self, data: bytes, direction: str, client_id: str) -> None:
        """子站原始帧回调."""
        super()._on_raw_frame(data, direction, client_id)

    def _update_status(self) -> None:
        """更新状态面板。"""
        super()._update_status()

        if not self._engine:
            return

        connected = self._engine.is_running
        client_count = self._engine.client_count

        if client_count > 0:
            clients = self._engine.client_list
            client_str = ", ".join(clients[:3])
            if len(clients) > 3:
                client_str += f" (+{len(clients)-3})"
            self._status_panel.update_state(
                f"监听中 ({client_count} 连接)",
                connected
            )
            self._sidebar.set_connected(connected, client_str)
        else:
            self._status_panel.update_state(
                f"监听中 ({client_count} 连接)",
                connected
            )
            self._sidebar.set_connected(connected, f"端口: {self._config.connection.port}")

        # 更新通信统计
        stats = self._engine.connection_stats
        if stats:
            self._status_panel.update_stats(
                stats.frames_sent, stats.frames_received,
                stats.bytes_sent, stats.bytes_received,
                stats.errors, 0,
            )
            self._sidebar.update_stats(
                stats.frames_sent, stats.frames_received,
                stats.bytes_sent, stats.bytes_received,
                stats.errors,
            )

        # 更新序列号
        seq = self._engine.sequence_manager
        if seq:
            self._status_panel.update_sequences(
                seq.send_seq, seq.recv_seq,
                seq.unconfirmed_count, seq.k, seq.w
            )
            self._sidebar.update_sequence(
                seq.send_seq, seq.recv_seq,
                seq.unconfirmed_count, seq.k, seq.w
            )

    def _on_point_table_changed(self) -> None:
        """点表变更."""
        if self._engine:
            self._engine.data_store.init_from_point_table(self._point_table)
        self.point_table_changed.emit()

    # ── 方法供外部调用 ──────────────────────────────────────────────

    def start_engine(self, async_thread) -> None:
        """启动引擎."""
        if self._engine:
            async_thread.run_coroutine(self._engine.start())

    def stop_engine(self, async_thread) -> None:
        """停止引擎."""
        if self._engine:
            async_thread.run_coroutine(self._engine.stop())

    def send_test_data(self, async_thread) -> None:
        """发送测试数据（随机遥信变化）。"""
        if self._engine and self._engine.is_running:
            import random
            ioa = random.randint(1, 100)
            value = random.choice([True, False])
            async_thread.run_coroutine(
                self._engine.send_spontaneous_yx(ioa, value)
            )

    def get_response_cfg(self) -> ResponseConfigPanel:
        """获取响应配置面板."""
        return self._response_cfg

    def get_point_editor(self) -> PointEditorPanel:
        """获取点表编辑器."""
        return self._point_editor
