"""多站并发模拟面板."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QGroupBox, QHeaderView, QSpinBox, QCheckBox,
    QComboBox, QMessageBox, QSplitter
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont


class StationTableWidget(QTableWidget):
    """站点状态表格."""

    COLUMNS = ["站ID", "站名称", "端口", "公共地址", "状态", "客户端数",
               "遥信", "遥测", "遥控", "遥脉", "模拟"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI."""
        self.setColumnCount(len(self.COLUMNS))
        self.setHorizontalHeaderLabels(self.COLUMNS)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

        # 设置列宽
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

    def update_stations(self, stations: list[dict]):
        """更新站点数据."""
        self.setRowCount(len(stations))

        for row, station in enumerate(stations):
            # 站ID
            self.setItem(row, 0, QTableWidgetItem(station.get('id', '')))

            # 站名称
            self.setItem(row, 1, QTableWidgetItem(station.get('name', '')))

            # 端口
            self.setItem(row, 2, QTableWidgetItem(str(station.get('port', 0))))

            # 公共地址
            self.setItem(row, 3, QTableWidgetItem(str(station.get('common_addr', 0))))

            # 状态
            status_item = QTableWidgetItem()
            if station.get('running', False):
                status_item.setText("运行中")
                status_item.setForeground(QColor("#a6e3a1"))
            else:
                status_item.setText("已停止")
                status_item.setForeground(QColor("#f38ba8"))
            self.setItem(row, 4, status_item)

            # 客户端数
            self.setItem(row, 5, QTableWidgetItem(str(station.get('clients', 0))))

            # 遥信
            self.setItem(row, 6, QTableWidgetItem(str(station.get('yx_count', 0))))

            # 遥测
            self.setItem(row, 7, QTableWidgetItem(str(station.get('yc_count', 0))))

            # 遥控
            self.setItem(row, 8, QTableWidgetItem(str(station.get('yk_count', 0))))

            # 遥脉
            self.setItem(row, 9, QTableWidgetItem(str(station.get('ym_count', 0))))

            # 模拟状态
            sim_item = QTableWidgetItem()
            if station.get('simulation_active', False):
                sim_item.setText("启用")
                sim_item.setForeground(QColor("#89b4fa"))
            else:
                sim_item.setText("禁用")
            self.setItem(row, 10, sim_item)


class MultiStationPanel(QWidget):
    """多站并发模拟面板."""

    # 信号
    start_all_requested = Signal()
    stop_all_requested = Signal()
    start_simulation_requested = Signal(str)  # station_id
    stop_simulation_requested = Signal(str)   # station_id
    add_station_requested = Signal(dict)      # station_config
    remove_station_requested = Signal(str)    # station_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # 标题
        title_label = QLabel("多站并发模拟")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(title_label)

        # 汇总信息
        self._summary_group = QGroupBox("汇总信息")
        summary_layout = QHBoxLayout(self._summary_group)

        self._lbl_stations = QLabel("站点: 0")
        self._lbl_clients = QLabel("客户端: 0")
        self._lbl_yx = QLabel("遥信: 0")
        self._lbl_yc = QLabel("遥测: 0")
        self._lbl_uptime = QLabel("运行时间: 00:00:00")

        for lbl in [self._lbl_stations, self._lbl_clients, self._lbl_yx,
                    self._lbl_yc, self._lbl_uptime]:
            lbl.setStyleSheet("font-size: 12px; color: #a6adc8;")
            summary_layout.addWidget(lbl)

        summary_layout.addStretch()
        layout.addWidget(self._summary_group)

        # 控制按钮
        control_layout = QHBoxLayout()

        self._btn_start_all = QPushButton("▶ 启动所有站")
        self._btn_start_all.setObjectName("primaryButton")
        self._btn_start_all.clicked.connect(self.start_all_requested.emit)
        control_layout.addWidget(self._btn_start_all)

        self._btn_stop_all = QPushButton("⏹ 停止所有站")
        self._btn_stop_all.setObjectName("dangerButton")
        self._btn_stop_all.clicked.connect(self.stop_all_requested.emit)
        self._btn_stop_all.setEnabled(False)
        control_layout.addWidget(self._btn_stop_all)

        control_layout.addStretch()

        # 快速创建
        control_layout.addWidget(QLabel("快速创建:"))
        self._station_count_spin = QSpinBox()
        self._station_count_spin.setRange(1, 20)
        self._station_count_spin.setValue(3)
        control_layout.addWidget(self._station_count_spin)

        self._btn_quick_create = QPushButton("创建演示站")
        self._btn_quick_create.clicked.connect(self._on_quick_create)
        control_layout.addWidget(self._btn_quick_create)

        layout.addLayout(control_layout)

        # 站点表格
        self._table = StationTableWidget()
        layout.addWidget(self._table)

        # 站点操作按钮
        table_control_layout = QHBoxLayout()

        self._btn_start_sim = QPushButton("▶ 启动选中站模拟")
        self._btn_start_sim.clicked.connect(self._on_start_simulation)
        table_control_layout.addWidget(self._btn_start_sim)

        self._btn_stop_sim = QPushButton("⏹ 停止选中站模拟")
        self._btn_stop_sim.clicked.connect(self._on_stop_simulation)
        table_control_layout.addWidget(self._btn_stop_sim)

        table_control_layout.addStretch()

        self._btn_remove = QPushButton("🗑 移除选中站")
        self._btn_remove.setObjectName("dangerButton")
        self._btn_remove.clicked.connect(self._on_remove_station)
        table_control_layout.addWidget(self._btn_remove)

        layout.addLayout(table_control_layout)

        # 刷新定时器
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_summary)
        self._refresh_timer.start(1000)  # 每秒刷新

    def update_station_list(self, stations: list[dict]):
        """更新站点列表."""
        self._table.update_stations(stations)

    def update_summary(self, summary: dict):
        """更新汇总信息."""
        self._lbl_stations.setText(f"站点: {summary.get('station_count', 0)}")
        self._lbl_clients.setText(f"客户端: {summary.get('total_clients', 0)}")
        self._lbl_yx.setText(f"遥信: {summary.get('total_yx', 0)}")
        self._lbl_yc.setText(f"遥测: {summary.get('total_yc', 0)}")

        # 格式化运行时间
        uptime = summary.get('uptime', 0)
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        self._lbl_uptime.setText(f"运行时间: {hours:02d}:{minutes:02d}:{seconds:02d}")

    def set_running(self, running: bool):
        """设置运行状态."""
        self._btn_start_all.setEnabled(not running)
        self._btn_stop_all.setEnabled(running)
        self._btn_quick_create.setEnabled(not running)

    def _on_quick_create(self):
        """快速创建演示站."""
        count = self._station_count_spin.value()
        # 发送信号让外部处理
        for i in range(1, count + 1):
            self.add_station_requested.emit({
                'station_id': f'station_{i}',
                'station_name': f'演示变电站{i}',
                'port': 2403 + i,
                'common_addr': i,
            })

    def _on_start_simulation(self):
        """启动选中站模拟."""
        selected = self._table.selectedItems()
        if selected:
            row = selected[0].row()
            station_id = self._table.item(row, 0).text()
            self.start_simulation_requested.emit(station_id)

    def _on_stop_simulation(self):
        """停止选中站模拟."""
        selected = self._table.selectedItems()
        if selected:
            row = selected[0].row()
            station_id = self._table.item(row, 0).text()
            self.stop_simulation_requested.emit(station_id)

    def _on_remove_station(self):
        """移除选中站."""
        selected = self._table.selectedItems()
        if selected:
            row = selected[0].row()
            station_id = self._table.item(row, 0).text()
            reply = QMessageBox.question(
                self, "确认移除",
                f"确定要移除站点 {station_id} 吗？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.remove_station_requested.emit(station_id)

    def _refresh_summary(self):
        """刷新汇总信息(由外部定时器驱动)."""
        pass  # 由外部调用update_summary
