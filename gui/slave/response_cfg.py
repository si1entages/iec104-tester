"""响应行为配置 — 子站响应参数配置.

配置子站对各种命令的响应行为:
- 响应延迟模拟
- 错误响应模拟
- 品质描述词注入
- 选择性不响应
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QCheckBox, QComboBox,
    QDoubleSpinBox, QGridLayout, QFormLayout,
)


class ResponseConfigPanel(QWidget):
    """子站响应行为配置面板.

    允许用户配置:
    - 响应延迟（模拟慢速设备）
    - 错误注入（模拟异常情况）
    - 品质强制（注入异常品质）
    - 选择性响应（忽略特定命令）
    """

    config_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # ── 响应延迟 ──
        delay_group = QGroupBox("响应延迟模拟")
        delay_layout = QGridLayout()

        self._gi_delay = QDoubleSpinBox()
        self._gi_delay.setRange(0, 10)
        self._gi_delay.setSuffix(" 秒")
        delay_layout.addWidget(QLabel("总召唤延迟:"), 0, 0)
        delay_layout.addWidget(self._gi_delay, 0, 1)

        self._cmd_delay = QDoubleSpinBox()
        self._cmd_delay.setRange(0, 10)
        self._cmd_delay.setSuffix(" 秒")
        delay_layout.addWidget(QLabel("命令响应延迟:"), 1, 0)
        delay_layout.addWidget(self._cmd_delay, 1, 1)

        self._data_delay = QDoubleSpinBox()
        self._data_delay.setRange(0, 60)
        self._data_delay.setSuffix(" 秒")
        delay_layout.addWidget(QLabel("数据上送延迟:"), 2, 0)
        delay_layout.addWidget(self._data_delay, 2, 1)

        delay_group.setLayout(delay_layout)
        layout.addWidget(delay_group)

        # ── 错误注入 ──
        error_group = QGroupBox("错误注入")
        error_layout = QGridLayout()

        self._drop_i_frames = QCheckBox("丢弃I帧 (模拟丢包)")
        error_layout.addWidget(self._drop_i_frames, 0, 0)

        self._drop_rate = QDoubleSpinBox()
        self._drop_rate.setRange(0, 1)
        self._drop_rate.setSingleStep(0.05)
        self._drop_rate.setDecimals(2)
        self._drop_rate.setPrefix("概率: ")
        error_layout.addWidget(self._drop_rate, 0, 1)

        self._corrupt_frames = QCheckBox("帧数据损坏")
        error_layout.addWidget(self._corrupt_frames, 1, 0)

        self._no_response = QCheckBox("不响应命令")
        error_layout.addWidget(self._no_response, 2, 0)

        self._wrong_cot = QCheckBox("返回错误COT")
        error_layout.addWidget(self._wrong_cot, 3, 0)

        error_group.setLayout(error_layout)
        layout.addWidget(error_group)

        # ── 品质注入 ──
        quality_group = QGroupBox("品质注入")
        quality_layout = QGridLayout()

        self._force_invalid = QCheckBox("强制无效 (IV)")
        quality_layout.addWidget(self._force_invalid, 0, 0)

        self._force_blocked = QCheckBox("强制闭锁 (BL)")
        quality_layout.addWidget(self._force_blocked, 0, 1)

        self._force_not_topical = QCheckBox("强制非当前 (NT)")
        quality_layout.addWidget(self._force_not_topical, 1, 0)

        self._force_overflow = QCheckBox("强制溢出 (OV)")
        quality_layout.addWidget(self._force_overflow, 1, 1)

        quality_group.setLayout(quality_layout)
        layout.addWidget(quality_group)

        # ── 连接行为 ──
        conn_group = QGroupBox("连接行为")
        conn_layout = QGridLayout()

        self._reject_startdt = QCheckBox("拒绝 STARTDT")
        conn_layout.addWidget(self._reject_startdt, 0, 0)

        self._auto_stopdt = QCheckBox("自动发送 STOPDT")
        conn_layout.addWidget(self._auto_stopdt, 0, 1)

        self._send_testfr = QCheckBox("主动发送 TESTFR")
        conn_layout.addWidget(self._send_testfr, 1, 0)

        self._testfr_interval = QDoubleSpinBox()
        self._testfr_interval.setRange(5, 120)
        self._testfr_interval.setValue(20)
        self._testfr_interval.setSuffix(" 秒")
        conn_layout.addWidget(self._testfr_interval, 1, 1)

        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # ── 应用按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._apply_btn = QPushButton("应用配置")
        self._apply_btn.setObjectName("primaryButton")
        self._apply_btn.clicked.connect(self._emit_config)
        btn_layout.addWidget(self._apply_btn)

        self._reset_btn = QPushButton("重置")
        self._reset_btn.clicked.connect(self._reset)
        btn_layout.addWidget(self._reset_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

    def _emit_config(self) -> None:
        """发射配置变更信号."""
        config = self.get_config()
        self.config_changed.emit(config)

    def _reset(self) -> None:
        """重置为默认值."""
        self._gi_delay.setValue(0)
        self._cmd_delay.setValue(0)
        self._data_delay.setValue(0)
        self._drop_i_frames.setChecked(False)
        self._drop_rate.setValue(0)
        self._corrupt_frames.setChecked(False)
        self._no_response.setChecked(False)
        self._wrong_cot.setChecked(False)
        self._force_invalid.setChecked(False)
        self._force_blocked.setChecked(False)
        self._force_not_topical.setChecked(False)
        self._force_overflow.setChecked(False)
        self._reject_startdt.setChecked(False)
        self._auto_stopdt.setChecked(False)
        self._send_testfr.setChecked(False)

    def get_config(self) -> dict:
        """获取当前配置."""
        return {
            "delays": {
                "gi": self._gi_delay.value(),
                "command": self._cmd_delay.value(),
                "data": self._data_delay.value(),
            },
            "errors": {
                "drop_frames": self._drop_i_frames.isChecked(),
                "drop_rate": self._drop_rate.value(),
                "corrupt": self._corrupt_frames.isChecked(),
                "no_response": self._no_response.isChecked(),
                "wrong_cot": self._wrong_cot.isChecked(),
            },
            "quality": {
                "invalid": self._force_invalid.isChecked(),
                "blocked": self._force_blocked.isChecked(),
                "not_topical": self._force_not_topical.isChecked(),
                "overflow": self._force_overflow.isChecked(),
            },
            "connection": {
                "reject_startdt": self._reject_startdt.isChecked(),
                "auto_stopdt": self._auto_stopdt.isChecked(),
                "send_testfr": self._send_testfr.isChecked(),
                "testfr_interval": self._testfr_interval.value(),
            },
        }

    def set_config(self, config: dict) -> None:
        """设置配置."""
        delays = config.get("delays", {})
        self._gi_delay.setValue(delays.get("gi", 0))
        self._cmd_delay.setValue(delays.get("command", 0))
        self._data_delay.setValue(delays.get("data", 0))

        errors = config.get("errors", {})
        self._drop_i_frames.setChecked(errors.get("drop_frames", False))
        self._drop_rate.setValue(errors.get("drop_rate", 0))
        self._corrupt_frames.setChecked(errors.get("corrupt", False))
        self._no_response.setChecked(errors.get("no_response", False))
        self._wrong_cot.setChecked(errors.get("wrong_cot", False))

        quality = config.get("quality", {})
        self._force_invalid.setChecked(quality.get("invalid", False))
        self._force_blocked.setChecked(quality.get("blocked", False))
        self._force_not_topical.setChecked(quality.get("not_topical", False))
        self._force_overflow.setChecked(quality.get("overflow", False))

        conn = config.get("connection", {})
        self._reject_startdt.setChecked(conn.get("reject_startdt", False))
        self._auto_stopdt.setChecked(conn.get("auto_stopdt", False))
        self._send_testfr.setChecked(conn.get("send_testfr", False))
        self._testfr_interval.setValue(conn.get("testfr_interval", 20))
