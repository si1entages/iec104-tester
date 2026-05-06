"""子站界面 — 数据模拟面板."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QSpinBox, QCheckBox, QComboBox,
    QLineEdit, QGridLayout, QDoubleSpinBox,
)


class SimPanel(QWidget):
    """数据模拟面板 — 手动/自动数据变化."""

    yx_change = Signal(int, bool)       # ioa, value
    yc_change = Signal(int, float)      # ioa, value
    simulation_toggled = Signal(bool)   # enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        # ── 手动模拟 ──
        manual_group = QGroupBox("手动模拟")
        manual_layout = QGridLayout()

        # 遥信模拟
        manual_layout.addWidget(QLabel("遥信 IOA:"), 0, 0)
        self._yx_ioa = QSpinBox()
        self._yx_ioa.setRange(0, 16777215)
        self._yx_ioa.setValue(1)
        manual_layout.addWidget(self._yx_ioa, 0, 1)

        self._yx_btn_on = QPushButton("置 ON (合)")
        self._yx_btn_on.setObjectName("successButton")
        self._yx_btn_on.clicked.connect(lambda: self._set_yx(True))
        manual_layout.addWidget(self._yx_btn_on, 0, 2)

        self._yx_btn_off = QPushButton("置 OFF (分)")
        self._yx_btn_off.setObjectName("dangerButton")
        self._yx_btn_off.clicked.connect(lambda: self._set_yx(False))
        manual_layout.addWidget(self._yx_btn_off, 0, 3)

        # 遥测模拟
        manual_layout.addWidget(QLabel("遥测 IOA:"), 1, 0)
        self._yc_ioa = QSpinBox()
        self._yc_ioa.setRange(0, 16777215)
        self._yc_ioa.setValue(1001)
        manual_layout.addWidget(self._yc_ioa, 1, 1)

        manual_layout.addWidget(QLabel("值:"), 1, 2)
        self._yc_value = QDoubleSpinBox()
        self._yc_value.setRange(-999999, 999999)
        self._yc_value.setDecimals(4)
        self._yc_value.setValue(0.0)
        manual_layout.addWidget(self._yc_value, 1, 3)

        self._yc_btn = QPushButton("设置遥测值")
        self._yc_btn.clicked.connect(self._set_yc)
        manual_layout.addWidget(self._yc_btn, 2, 0, 1, 4)

        manual_group.setLayout(manual_layout)
        layout.addWidget(manual_group)

        # ── 自动模拟 ──
        auto_group = QGroupBox("自动模拟")
        auto_layout = QGridLayout()

        self._sim_enabled = QCheckBox("启用自动模拟")
        self._sim_enabled.stateChanged.connect(
            lambda s: self.simulation_toggled.emit(s == Qt.Checked)
        )
        auto_layout.addWidget(self._sim_enabled, 0, 0, 1, 2)

        auto_layout.addWidget(QLabel("遥信变化间隔(s):"), 1, 0)
        self._yx_interval = QDoubleSpinBox()
        self._yx_interval.setRange(0.5, 60)
        self._yx_interval.setValue(5.0)
        auto_layout.addWidget(self._yx_interval, 1, 1)

        auto_layout.addWidget(QLabel("遥测变化间隔(s):"), 2, 0)
        self._yc_interval = QDoubleSpinBox()
        self._yc_interval.setRange(0.5, 60)
        self._yc_interval.setValue(2.0)
        auto_layout.addWidget(self._yc_interval, 2, 1)

        auto_layout.addWidget(QLabel("遥信变化概率:"), 1, 2)
        self._yx_rate = QDoubleSpinBox()
        self._yx_rate.setRange(0.01, 1.0)
        self._yx_rate.setValue(0.1)
        self._yx_rate.setSingleStep(0.05)
        auto_layout.addWidget(self._yx_rate, 1, 3)

        auto_layout.addWidget(QLabel("遥测波动范围:"), 2, 2)
        self._yc_range = QDoubleSpinBox()
        self._yc_range.setRange(0.01, 1.0)
        self._yc_range.setValue(0.05)
        self._yc_range.setSingleStep(0.01)
        auto_layout.addWidget(self._yc_range, 2, 3)

        auto_group.setLayout(auto_layout)
        layout.addWidget(auto_group)

        layout.addStretch()

    def _set_yx(self, value: bool) -> None:
        ioa = self._yx_ioa.value()
        self.yx_change.emit(ioa, value)

    def _set_yc(self) -> None:
        ioa = self._yc_ioa.value()
        value = self._yc_value.value()
        self.yc_change.emit(ioa, value)

    @property
    def sim_config(self) -> dict:
        return {
            "yx_interval": self._yx_interval.value(),
            "yc_interval": self._yc_interval.value(),
            "yx_change_rate": self._yx_rate.value(),
            "yc_change_range": self._yc_range.value(),
        }
