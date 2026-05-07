"""配置对话框."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QComboBox, QGroupBox, QFormLayout, QPushButton, QDialogButtonBox
)
from PySide6.QtCore import Signal, Qt


class ConnectionConfigPage(QWidget):
    """连接配置页."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._setup_ui(config)

    def _setup_ui(self, config):
        layout = QFormLayout(self)
        layout.setSpacing(8)

        # 主机地址
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("127.0.0.1")
        if config:
            self._host_edit.setText(config.connection.host)
        layout.addRow("主机地址:", self._host_edit)

        # 端口
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(config.connection.port if config else 2404)
        layout.addRow("端口:", self._port_spin)

        # 公共地址
        self._common_addr_spin = QSpinBox()
        self._common_addr_spin.setRange(1, 65535)
        self._common_addr_spin.setValue(config.connection.common_addr if config else 1)
        layout.addRow("公共地址:", self._common_addr_spin)

        # 自动重连
        self._reconnect_check = QCheckBox("自动重连")
        self._reconnect_check.setChecked(config.connection.reconnect if config else True)
        layout.addRow("", self._reconnect_check)

        # 重连间隔
        self._reconnect_interval_spin = QDoubleSpinBox()
        self._reconnect_interval_spin.setRange(1, 60)
        self._reconnect_interval_spin.setValue(config.connection.reconnect_interval if config else 5.0)
        self._reconnect_interval_spin.setSuffix(" 秒")
        layout.addRow("重连间隔:", self._reconnect_interval_spin)

    def get_values(self) -> dict:
        """获取配置值."""
        return {
            "host": self._host_edit.text(),
            "port": self._port_spin.value(),
            "common_addr": self._common_addr_spin.value(),
            "reconnect": self._reconnect_check.isChecked(),
            "reconnect_interval": self._reconnect_interval_spin.value(),
        }


class TimerConfigPage(QWidget):
    """定时器配置页."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._setup_ui(config)

    def _setup_ui(self, config):
        layout = QFormLayout(self)
        layout.setSpacing(8)

        # T0 - 连接建立超时
        self._t0_spin = QDoubleSpinBox()
        self._t0_spin.setRange(1, 120)
        self._t0_spin.setValue(config.timers.t0 if config else 30)
        self._t0_spin.setSuffix(" 秒")
        layout.addRow("T0 (连接超时):", self._t0_spin)

        # T1 - 发送/测试超时
        self._t1_spin = QDoubleSpinBox()
        self._t1_spin.setRange(1, 60)
        self._t1_spin.setValue(config.timers.t1 if config else 15)
        self._t1_spin.setSuffix(" 秒")
        layout.addRow("T1 (发送超时):", self._t1_spin)

        # T2 - 无数据确认超时
        self._t2_spin = QDoubleSpinBox()
        self._t2_spin.setRange(1, 30)
        self._t2_spin.setValue(config.timers.t2 if config else 10)
        self._t2_spin.setSuffix(" 秒")
        layout.addRow("T2 (确认超时):", self._t2_spin)

        # T3 - 空闲测试超时
        self._t3_spin = QDoubleSpinBox()
        self._t3_spin.setRange(1, 120)
        self._t3_spin.setValue(config.timers.t3 if config else 20)
        self._t3_spin.setSuffix(" 秒")
        layout.addRow("T3 (空闲超时):", self._t3_spin)

    def get_values(self) -> dict:
        """获取配置值."""
        return {
            "t0": self._t0_spin.value(),
            "t1": self._t1_spin.value(),
            "t2": self._t2_spin.value(),
            "t3": self._t3_spin.value(),
        }


class FlowControlConfigPage(QWidget):
    """流控配置页."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._setup_ui(config)

    def _setup_ui(self, config):
        layout = QFormLayout(self)
        layout.setSpacing(8)

        # K - 发送窗口
        self._k_spin = QSpinBox()
        self._k_spin.setRange(1, 32767)
        self._k_spin.setValue(config.flow_control.k if config else 12)
        layout.addRow("K (发送窗口):", self._k_spin)

        # W - 确认阈值
        self._w_spin = QSpinBox()
        self._w_spin.setRange(1, 32767)
        self._w_spin.setValue(config.flow_control.w if config else 8)
        layout.addRow("W (确认阈值):", self._w_spin)

    def get_values(self) -> dict:
        """获取配置值."""
        return {
            "k": self._k_spin.value(),
            "w": self._w_spin.value(),
        }


class DisplayConfigPage(QWidget):
    """显示配置页."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._setup_ui(config)

    def _setup_ui(self, config):
        layout = QFormLayout(self)
        layout.setSpacing(8)

        # 主题
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["深色", "浅色"])
        self._theme_combo.setCurrentIndex(0 if config.display.theme == "dark" else 1)
        layout.addRow("主题:", self._theme_combo)

        # 刷新间隔
        self._refresh_spin = QSpinBox()
        self._refresh_spin.setRange(100, 5000)
        self._refresh_spin.setValue(config.display.refresh_interval if config else 500)
        self._refresh_spin.setSuffix(" 毫秒")
        layout.addRow("刷新间隔:", self._refresh_spin)

        # 自动滚动
        self._auto_scroll_check = QCheckBox("自动滚动")
        self._auto_scroll_check.setChecked(True)
        layout.addRow("", self._auto_scroll_check)

    def get_values(self) -> dict:
        """获取配置值."""
        theme = "dark" if self._theme_combo.currentIndex() == 0 else "light"
        return {
            "theme": theme,
            "refresh_interval": self._refresh_spin.value(),
            "auto_scroll": self._auto_scroll_check.isChecked(),
        }


class ConfigDialog(QDialog):
    """配置对话框."""

    config_changed = Signal(dict)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumSize(500, 400)
        self._config = config
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 标签页
        self._tab_widget = QTabWidget()

        # 连接配置
        self._connection_page = ConnectionConfigPage(self._config)
        self._tab_widget.addTab(self._connection_page, "连接")

        # 定时器配置
        self._timer_page = TimerConfigPage(self._config)
        self._tab_widget.addTab(self._timer_page, "定时器")

        # 流控配置
        self._flow_control_page = FlowControlConfigPage(self._config)
        self._tab_widget.addTab(self._flow_control_page, "流控")

        # 显示配置
        self._display_page = DisplayConfigPage(self._config)
        self._tab_widget.addTab(self._display_page, "显示")

        layout.addWidget(self._tab_widget)

        # 按钮
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.Apply).clicked.connect(self._on_apply)
        layout.addWidget(button_box)

    def _on_accept(self):
        """确定按钮."""
        self._emit_config()
        self.accept()

    def _on_apply(self):
        """应用按钮."""
        self._emit_config()

    def _emit_config(self):
        """发出配置变更信号."""
        config = {
            "connection": self._connection_page.get_values(),
            "timers": self._timer_page.get_values(),
            "flow_control": self._flow_control_page.get_values(),
            "display": self._display_page.get_values(),
        }
        self.config_changed.emit(config)

    def get_config(self) -> dict:
        """获取完整配置."""
        return {
            "connection": self._connection_page.get_values(),
            "timers": self._timer_page.get_values(),
            "flow_control": self._flow_control_page.get_values(),
            "display": self._display_page.get_values(),
        }
