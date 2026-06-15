"""批量编辑对话框 — 支持单选/多选编辑。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel,
    QSpinBox, QComboBox, QPushButton, QHBoxLayout,
)


class BatchEditDialog(QDialog):
    """批量编辑对话框。"""

    def __init__(self, point_type: str, count: int = 1, parent=None):
        super().__init__(parent)
        self._point_type = point_type
        self._count = count
        self._result = {}

        type_names = {"yx": "遥信", "yc": "遥测", "yk": "遥控", "ym": "遥脉"}
        self.setWindowTitle(f"编辑{type_names.get(point_type, point_type)}点 ({count}条)")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        info = QLabel(f"选中 {count} 条记录，修改以下属性：")
        info.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)

        # 组号
        self._group = QSpinBox()
        self._group.setRange(1, 16)
        self._group.setValue(1)
        form.addRow("组号:", self._group)

        # 类型
        if point_type == "yx":
            self._yx_type = QComboBox()
            self._yx_type.addItems(["不修改", "单点", "双点"])
            form.addRow("类型:", self._yx_type)
        elif point_type == "yc":
            self._yc_type = QComboBox()
            self._yc_type.addItems(["不修改", "归一化", "标度化", "短浮点"])
            form.addRow("类型:", self._yc_type)
        elif point_type == "yk":
            self._cmd_type = QComboBox()
            self._cmd_type.addItems(["不修改", "单命令", "双命令"])
            form.addRow("命令类型:", self._cmd_type)

        # 是否变化（仅YX）
        if point_type == "yx":
            self._is_changing = QComboBox()
            self._is_changing.addItems(["不修改", "是", "否"])
            form.addRow("是否变化:", self._is_changing)

            self._change_interval = QSpinBox()
            self._change_interval.setRange(1, 3600)
            self._change_interval.setValue(1)
            self._change_interval.setSuffix(" 秒")
            form.addRow("变化周期:", self._change_interval)

        # 状态（仅YX）
        if point_type == "yx":
            self._state = QComboBox()
            self._state.addItems(["不修改", "OFF (分)", "ON (合)"])
            form.addRow("状态:", self._state)

        # 品质
        self._quality = QComboBox()
        self._quality.addItems(["不修改", "正常", "无效", "闭锁", "取代"])
        form.addRow("品质:", self._quality)

        layout.addLayout(form)

        # 按钮
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primaryButton")
        ok_btn.clicked.connect(self._on_accept)
        btn_layout.addWidget(ok_btn)

        layout.addLayout(btn_layout)

    def _on_accept(self) -> None:
        """确定按钮。"""
        self._result = {"group": self._group.value()}

        if self._point_type == "yx":
            if self._yx_type.currentIndex() > 0:
                self._result["point_type"] = "single" if self._yx_type.currentIndex() == 1 else "double"

            if self._is_changing.currentIndex() > 0:
                self._result["is_changing"] = self._is_changing.currentIndex() == 1

            self._result["change_interval"] = self._change_interval.value()

            if self._state.currentIndex() > 0:
                self._result["state"] = self._state.currentIndex() == 2  # True=ON, False=OFF

        elif self._point_type == "yc":
            if self._yc_type.currentIndex() > 0:
                types = ["", "normalized", "scaled", "short_float"]
                self._result["data_type"] = types[self._yc_type.currentIndex()]

        elif self._point_type == "yk":
            if self._cmd_type.currentIndex() > 0:
                self._result["command_type"] = "single" if self._cmd_type.currentIndex() == 1 else "double"

        if self._quality.currentIndex() > 0:
            self._result["quality"] = self._quality.currentIndex() - 1

        self.accept()

    @property
    def result(self) -> dict:
        return self._result
