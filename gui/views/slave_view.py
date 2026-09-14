"""子站视图 — 子站模式的完整UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabWidget

from core.config import AppConfig
from core.engine.slave import SlaveEngine, SlaveEvent
from core.engine.multi_station import (
    MultiStationManager, MultiStationConfig, StationConfig,
)
from core.data.point_table import PointTable
from gui.slave.point_editor import PointEditorPanel
from gui.slave.response_cfg import ResponseConfigPanel
from gui.slave.sim_panel import SimPanel
from gui.slave.multi_station_panel import MultiStationPanel
from gui.widgets.toast import show_info, show_success, show_error

from .base_view import BaseView


class SlaveView(BaseView):
    """子站视图 — 包含点表编辑、响应配置、数据模拟、多站管理."""

    # 信号
    point_table_changed = Signal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(config, parent)
        self._async_thread = None
        self._init_point_table()
        self._init_engine()

    def _init_ui(self) -> None:
        """初始化界面 — 子站模式。"""
        super()._init_ui()

        # 响应配置
        self._response_cfg = ResponseConfigPanel()
        self._func_tabs.insertTab(0, self._response_cfg, "响应配置")
        self._response_cfg.config_changed.connect(self._on_response_cfg_changed)

        # 点表编辑器
        self._point_editor = PointEditorPanel(self._point_table)
        self._point_editor.point_table_changed.connect(self._on_point_table_changed)
        self._func_tabs.insertTab(1, self._point_editor, "点表编辑")

        # 数据模拟面板
        self._sim_panel = SimPanel()
        self._func_tabs.insertTab(2, self._sim_panel, "数据模拟")

        # 多站并发面板
        self._multi_manager: MultiStationManager | None = None
        self._multi_panel = MultiStationPanel()
        self._func_tabs.insertTab(3, self._multi_panel, "多站模拟")
        self._wire_multi_station()

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

        # 连接数据模拟面板信号
        self._sim_panel.yx_change.connect(self._on_sim_yx_change)
        self._sim_panel.yc_change.connect(self._on_sim_yc_change)
        self._sim_panel.simulation_toggled.connect(self._on_sim_toggled)

    def _on_slave_event(self, event: SlaveEvent, data: dict) -> None:
        """子站事件回调."""
        self._on_event(event.value, data)

    def _on_raw_frame_slave(self, data: bytes, direction: str, client_id: str) -> None:
        """子站原始帧回调."""
        super()._on_raw_frame(data, direction, client_id)

    def _update_status(self) -> None:
        """定时更新状态面板。"""
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

        # 多站面板刷新
        if self._multi_manager and self._multi_manager.is_running:
            self._refresh_multi_station_status()

    def _on_point_table_changed(self) -> None:
        """点表变更."""
        if self._engine:
            self._engine.data_store.init_from_point_table(self._point_table)
        self._refresh_all_data()
        self.point_table_changed.emit()

    def _on_response_cfg_changed(self, cfg: dict) -> None:
        """响应配置变更 → 应用到 SlaveEngine."""
        if self._engine:
            self._engine.set_response_behavior(cfg)
            show_success(self, "响应配置已应用到子站引擎")
        self._on_event("response_config_changed", cfg)

    # ── 数据模拟 ──────────────────────────────────────────────────

    def _on_sim_yx_change(self, ioa: int, value: bool) -> None:
        """手动遥信变化 — 在 asyncio 线程发送."""
        if self._engine and self._engine.is_running:
            if self._async_thread:
                async def _apply():
                    self._engine.data_store.update_yx(ioa, value)
                    await self._engine.send_spontaneous_yx(ioa, value)
                self._async_thread.run_coroutine(_apply())
            else:
                self._engine.simulate_yx_change(ioa, value)
            show_success(self, f"遥信 IOA={ioa} → {'ON' if value else 'OFF'}")
        else:
            show_error(self, "子站未启动，无法模拟数据")

    def _on_sim_yc_change(self, ioa: int, value: float) -> None:
        """手动遥测变化 — 在 asyncio 线程发送."""
        if self._engine and self._engine.is_running:
            if self._async_thread:
                async def _apply():
                    self._engine.data_store.update_yc(ioa, value)
                    await self._engine.send_spontaneous_yc(ioa, value)
                self._async_thread.run_coroutine(_apply())
            else:
                self._engine.simulate_yc_change(ioa, value)
            show_success(self, f"遥测 IOA={ioa} → {value}")
        else:
            show_error(self, "子站未启动，无法模拟数据")

    def _on_sim_toggled(self, enabled: bool) -> None:
        """自动模拟开关."""
        if not self._engine:
            return
        if enabled:
            cfg = self._sim_panel.sim_config
            if self._engine.is_running and self._async_thread:
                self._async_thread.run_coroutine(self._engine.start_simulation(
                    yx_interval=cfg["yx_interval"],
                    yc_interval=cfg["yc_interval"],
                    yx_change_rate=cfg["yx_change_rate"],
                    yc_change_range=cfg["yc_change_range"],
                ))
                show_success(self, "自动模拟已启动")
            else:
                self._sim_panel._sim_enabled.setChecked(False)
                show_error(self, "子站未启动，无法启用自动模拟")
        else:
            if self._async_thread:
                self._async_thread.run_coroutine(self._engine.stop_simulation())
            show_info(self, "自动模拟已停止")

    # ── 多站管理 ──────────────────────────────────────────────────

    def _wire_multi_station(self) -> None:
        """连接多站面板信号."""
        self._multi_panel.start_all_requested.connect(self._on_multi_start_all)
        self._multi_panel.stop_all_requested.connect(self._on_multi_stop_all)
        self._multi_panel.add_station_requested.connect(self._on_multi_add_station)
        self._multi_panel.remove_station_requested.connect(self._on_multi_remove_station)
        self._multi_panel.start_simulation_requested.connect(self._on_multi_start_sim)
        self._multi_panel.stop_simulation_requested.connect(self._on_multi_stop_sim)

    def _ensure_multi_manager(self) -> MultiStationManager:
        """确保多站管理器存在."""
        if self._multi_manager is None:
            self._multi_manager = MultiStationManager(MultiStationConfig())
        return self._multi_manager

    def _on_multi_add_station(self, cfg: dict) -> None:
        """添加演示站."""
        manager = self._ensure_multi_manager()
        station = StationConfig(
            station_id=cfg.get("station_id", ""),
            station_name=cfg.get("station_name", ""),
            port=cfg.get("port", 2404),
            common_addr=cfg.get("common_addr", 1),
            auto_generate=True,
            yx_count=cfg.get("yx_count", 50),
            yc_count=cfg.get("yc_count", 30),
            simulation_enabled=cfg.get("simulation_enabled", True),
        )
        # 避免重复
        for existing in manager._config.stations:
            if existing.station_id == station.station_id:
                show_info(self, f"站点已存在: {station.station_id}")
                return
        manager._config.stations.append(station)
        self._refresh_multi_station_status()
        show_success(self, f"已添加站点: {station.station_name} (端口 {station.port})")

    def _on_multi_remove_station(self, station_id: str) -> None:
        """移除站点."""
        if not self._multi_manager:
            return
        stations = self._multi_manager._config.stations
        self._multi_manager._config.stations = [
            s for s in stations if s.station_id != station_id
        ]
        if self._multi_manager.get_engine(station_id):
            show_error(self, "站点运行中，请先停止所有站")
            return
        self._refresh_multi_station_status()
        show_success(self, f"已移除站点: {station_id}")

    def _on_multi_start_all(self) -> None:
        """启动所有多站."""
        manager = self._ensure_multi_manager()
        if not manager._config.stations:
            show_error(self, "请先创建站点")
            return

        if self._engine and self._engine.is_running:
            show_error(self, "请先停止单站监听，再启动多站模式")
            return

        if not self._async_thread:
            show_error(self, "异步循环未就绪")
            return

        self._multi_panel.set_running(True)
        future = self._async_thread.run_coroutine(manager.start_all())
        show_info(self, "多站启动中...")

        def _on_done():
            self._refresh_multi_station_status()
            if future.exception():
                show_error(self, f"多站启动失败: {future.exception()}")
                self._multi_panel.set_running(False)
            else:
                show_success(self, f"已启动 {manager.station_count} 个站点")

        # 轮询完成状态（Qt 定时器更安全）
        from PySide6.QtCore import QTimer

        def _poll():
            if future.done():
                timer.stop()
                _on_done()

        timer = QTimer(self)
        timer.timeout.connect(_poll)
        timer.start(200)

    def _on_multi_stop_all(self) -> None:
        """停止所有多站."""
        if not self._multi_manager or not self._async_thread:
            return

        future = self._async_thread.run_coroutine(self._multi_manager.stop_all())
        show_info(self, "多站停止中...")

        from PySide6.QtCore import QTimer

        def _poll():
            if future.done():
                timer.stop()
                self._multi_panel.set_running(False)
                self._refresh_multi_station_status()
                show_success(self, "所有站点已停止")

        timer = QTimer(self)
        timer.timeout.connect(_poll)
        timer.start(200)

    def _on_multi_start_sim(self, station_id: str) -> None:
        """启动指定站模拟."""
        if not self._multi_manager or not self._async_thread:
            return
        engine = self._multi_manager.get_engine(station_id)
        if not engine:
            show_error(self, f"站点未启动: {station_id}")
            return

        self._async_thread.run_coroutine(engine.start_simulation())
        show_success(self, f"站点 {station_id} 模拟已启动")

    def _on_multi_stop_sim(self, station_id: str) -> None:
        """停止指定站模拟."""
        if not self._multi_manager or not self._async_thread:
            return
        engine = self._multi_manager.get_engine(station_id)
        if not engine:
            return

        self._async_thread.run_coroutine(engine.stop_simulation())
        show_info(self, f"站点 {station_id} 模拟停止中")

    def _refresh_multi_station_status(self) -> None:
        """刷新多站面板状态."""
        if not self._multi_manager:
            return
        statuses = self._multi_manager.get_all_station_status()
        stations = []
        for s in statuses:
            stations.append({
                "id": s.station_id,
                "name": s.station_name,
                "port": s.port,
                "common_addr": s.common_addr,
                "running": s.running,
                "clients": s.client_count,
                "yx_count": s.yx_count,
                "yc_count": s.yc_count,
                "yk_count": s.yk_count,
                "ym_count": s.ym_count,
                "simulation": s.simulation_active,
            })
        # 未启动的配置站也显示
        if self._multi_manager:
            started_ids = {s.station_id for s in statuses}
            for cfg in self._multi_manager._config.stations:
                if cfg.station_id not in started_ids:
                    stations.append({
                        "id": cfg.station_id,
                        "name": cfg.station_name,
                        "port": cfg.port,
                        "common_addr": cfg.common_addr,
                        "running": False,
                        "clients": 0,
                        "yx_count": cfg.yx_count,
                        "yc_count": cfg.yc_count,
                        "yk_count": cfg.yk_count,
                        "ym_count": cfg.ym_count,
                        "simulation": False,
                    })
        self._multi_panel.update_station_list(stations)
        self._multi_panel.update_summary(self._multi_manager.get_summary())
        self._multi_panel.set_running(self._multi_manager.is_running)

    # ── 方法供外部调用 ──────────────────────────────────────────

    def start_engine(self, async_thread) -> None:
        """启动引擎."""
        self._async_thread = async_thread
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

    def get_sim_panel(self) -> SimPanel:
        """获取数据模拟面板."""
        return self._sim_panel

    def get_multi_station_panel(self) -> MultiStationPanel:
        """获取多站面板."""
        return self._multi_panel
