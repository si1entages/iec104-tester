"""历史数据趋势图表组件."""

from __future__ import annotations

import time
from collections import deque
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QCheckBox, QGroupBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont


class TrendDataPoint:
    """趋势数据点."""

    def __init__(self, timestamp: float, value: float, quality: int = 0):
        self.timestamp = timestamp
        self.value = value
        self.quality = quality


class TrendChart(QWidget):
    """趋势图表组件."""

    MAX_POINTS = 1000  # 最大显示点数

    def __init__(self, title: str = "趋势图", parent=None):
        super().__init__(parent)
        self._title = title
        self._data_series: dict[str, deque[TrendDataPoint]] = {}
        self._colors: dict[str, QColor] = {}
        self._visible_series: set[str] = set()
        self._time_range = 60  # 默认显示60秒
        self._auto_scroll = True
        self._show_grid = True

        self.setMinimumSize(400, 200)
        self._setup_ui()
        self._setup_timer()

    def _setup_ui(self):
        """设置UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 控制栏
        control_layout = QHBoxLayout()

        # 时间范围选择
        control_layout.addWidget(QLabel("时间范围:"))
        self._time_range_combo = QComboBox()
        self._time_range_combo.addItems(["10秒", "30秒", "60秒", "5分钟", "10分钟"])
        self._time_range_combo.setCurrentText("60秒")
        self._time_range_combo.currentTextChanged.connect(self._on_time_range_changed)
        control_layout.addWidget(self._time_range_combo)

        # 自动滚动
        self._auto_scroll_check = QCheckBox("自动滚动")
        self._auto_scroll_check.setChecked(True)
        self._auto_scroll_check.toggled.connect(self._on_auto_scroll_toggled)
        control_layout.addWidget(self._auto_scroll_check)

        # 显示网格
        self._grid_check = QCheckBox("显示网格")
        self._grid_check.setChecked(True)
        self._grid_check.toggled.connect(self._on_grid_toggled)
        control_layout.addWidget(self._grid_check)

        # 清空按钮
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.clear_data)
        control_layout.addWidget(btn_clear)

        control_layout.addStretch()
        layout.addLayout(control_layout)

        # 图表区域
        self._chart_widget = _ChartWidget()
        layout.addWidget(self._chart_widget)

    def _setup_timer(self):
        """设置刷新定时器."""
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_chart)
        self._refresh_timer.start(100)  # 100ms刷新

    def add_series(self, name: str, color: QColor = None):
        """添加数据系列."""
        if name not in self._data_series:
            self._data_series[name] = deque(maxlen=self.MAX_POINTS)
            self._colors[name] = color or QColor("#89b4fa")
            self._visible_series.add(name)
            self._chart_widget.set_series(
                self._data_series, self._colors, self._visible_series
            )

    def remove_series(self, name: str):
        """移除数据系列."""
        if name in self._data_series:
            del self._data_series[name]
            del self._colors[name]
            self._visible_series.discard(name)
            self._chart_widget.set_series(
                self._data_series, self._colors, self._visible_series
            )

    def add_data_point(self, series_name: str, value: float, quality: int = 0):
        """添加数据点."""
        if series_name not in self._data_series:
            self.add_series(series_name)

        point = TrendDataPoint(time.time(), value, quality)
        self._data_series[series_name].append(point)

    def clear_data(self):
        """清空所有数据."""
        for series in self._data_series.values():
            series.clear()
        self._chart_widget.update()

    def _refresh_chart(self):
        """刷新图表."""
        self._chart_widget.set_time_range(self._time_range)
        self._chart_widget.update()

    def _on_time_range_changed(self, text: str):
        """时间范围变更."""
        range_map = {
            "10秒": 10, "30秒": 30, "60秒": 60,
            "5分钟": 300, "10分钟": 600
        }
        self._time_range = range_map.get(text, 60)

    def _on_auto_scroll_toggled(self, checked: bool):
        """自动滚动切换."""
        self._auto_scroll = checked
        self._chart_widget.set_auto_scroll(checked)

    def _on_grid_toggled(self, checked: bool):
        """显示网格切换."""
        self._show_grid = checked
        self._chart_widget.set_show_grid(checked)


class _ChartWidget(QWidget):
    """图表绘制组件."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_series: dict[str, deque[TrendDataPoint]] = {}
        self._colors: dict[str, QColor] = {}
        self._visible_series: set[str] = set()
        self._time_range = 60
        self._auto_scroll = True
        self._show_grid = True

        self.setMinimumSize(300, 150)

    def set_series(self, data_series: dict, colors: dict, visible: set):
        """设置数据系列."""
        self._data_series = data_series
        self._colors = colors
        self._visible_series = visible

    def set_time_range(self, seconds: int):
        """设置时间范围."""
        self._time_range = seconds

    def set_auto_scroll(self, enabled: bool):
        """设置自动滚动."""
        self._auto_scroll = enabled

    def set_show_grid(self, enabled: bool):
        """设置显示网格."""
        self._show_grid = enabled

    def paintEvent(self, event):
        """绘制图表."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制背景
        bg_color = self.palette().color(self.backgroundRole())
        painter.fillRect(self.rect(), bg_color)

        # 计算绘图区域
        margin = 50
        chart_rect = self.rect().adjusted(margin, margin, -margin, -margin)

        if chart_rect.width() <= 0 or chart_rect.height() <= 0:
            return

        # 绘制网格
        if self._show_grid:
            self._draw_grid(painter, chart_rect)

        # 绘制坐标轴
        self._draw_axes(painter, chart_rect)

        # 绘制数据系列
        self._draw_series(painter, chart_rect)

        # 绘制图例
        self._draw_legend(painter, chart_rect)

    def _draw_grid(self, painter: QPainter, rect):
        """绘制网格."""
        pen = QPen(QColor("#313244"), 1, Qt.DotLine)
        painter.setPen(pen)

        # 垂直网格线
        for i in range(1, 10):
            x = rect.x() + int(rect.width() * i / 10)
            painter.drawLine(x, rect.y(), x, rect.bottom())

        # 水平网格线
        for i in range(1, 6):
            y = rect.y() + int(rect.height() * i / 5)
            painter.drawLine(rect.x(), y, rect.right(), y)

    def _draw_axes(self, painter: QPainter, rect):
        """绘制坐标轴."""
        pen = QPen(QColor("#a6adc8"), 2)
        painter.setPen(pen)

        # X轴
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        # Y轴
        painter.drawLine(rect.topLeft(), rect.bottomLeft())

        # X轴标签
        font = QFont("Cascadia Code", 8)
        painter.setFont(font)
        painter.setPen(QColor("#a6adc8"))

        for i in range(0, self._time_range + 1, self._time_range // 5):
            x = rect.x() + int(rect.width() * i / self._time_range)
            label = f"-{self._time_range - i}s"
            painter.drawText(x - 15, rect.bottom() + 15, 30, 20,
                             Qt.AlignCenter, label)

    def _draw_series(self, painter: QPainter, rect):
        """绘制数据系列."""
        now = time.time()
        start_time = now - self._time_range

        for name in self._visible_series:
            if name not in self._data_series:
                continue

            points = self._data_series[name]
            if not points:
                continue

            color = self._colors.get(name, QColor("#89b4fa"))
            pen = QPen(color, 2)
            painter.setPen(pen)

            # 过滤时间范围内的点
            visible_points = [
                p for p in points
                if p.timestamp >= start_time
            ]

            if len(visible_points) < 2:
                continue

            # 计算值范围
            values = [p.value for p in visible_points]
            min_val = min(values)
            max_val = max(values)
            val_range = max_val - min_val if max_val != min_val else 1

            # 绘制线条
            path_points = []
            for point in visible_points:
                x = rect.x() + int(rect.width() * (point.timestamp - start_time) / self._time_range)
                y = rect.bottom() - int(rect.height() * (point.value - min_val) / val_range)
                path_points.append((x, y))

            for i in range(len(path_points) - 1):
                painter.drawLine(
                    path_points[i][0], path_points[i][1],
                    path_points[i + 1][0], path_points[i + 1][1]
                )

    def _draw_legend(self, painter: QPainter, rect):
        """绘制图例."""
        font = QFont("Microsoft YaHei", 9)
        painter.setFont(font)

        x = rect.x() + 10
        y = rect.y() + 10

        for name in self._visible_series:
            if name not in self._colors:
                continue

            color = self._colors[name]
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRect(x, y, 12, 12)

            painter.setPen(QColor("#cdd6f4"))
            painter.drawText(x + 16, y, 100, 12, Qt.AlignVCenter, name)

            y += 18


class TrendChartPanel(QWidget):
    """趋势图表面板."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 遥测趋势图
        self._yc_trend = TrendChart("遥测趋势")
        self._yc_trend.add_series("遥测值", QColor("#89b4fa"))
        layout.addWidget(self._yc_trend)

        # 遥信变化统计
        self._yx_trend = TrendChart("遥信变化统计")
        self._yx_trend.add_series("变化次数", QColor("#a6e3a1"))
        layout.addWidget(self._yx_trend)

    def update_yc_trend(self, ioa: int, value: float):
        """更新遥测趋势."""
        series = f"IOA-{ioa}"
        if series not in getattr(self._yc_trend, "_data_series", {}):
            self._yc_trend.add_series(series)
        self._yc_trend.add_data_point(series, value)

    def update_yx_trend(self, ioa: int, change_count: int):
        """更新遥信变化统计."""
        series = f"IOA-{ioa}"
        if series not in getattr(self._yx_trend, "_data_series", {}):
            self._yx_trend.add_series(series)
        self._yx_trend.add_data_point(series, float(change_count))
