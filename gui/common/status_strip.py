"""底部状态条."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


class StatusStrip(QFrame):
    """统一状态栏：连接态 / 序列号 / 流量."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(16)

        self.state_label = QLabel("状态: 未连接")
        self.seq_label = QLabel("VS/VR: -/-  窗口: 0")
        self.traffic_label = QLabel("TX: 0  RX: 0")
        self.error_label = QLabel("")

        for w in (self.state_label, self.seq_label, self.traffic_label, self.error_label):
            layout.addWidget(w)
        layout.addStretch()

    def update_state(self, text: str) -> None:
        self.state_label.setText(f"状态: {text}")

    def update_seq(self, send: int, recv: int, unconfirmed: int, k: int, w: int) -> None:
        self.seq_label.setText(f"VS/VR: {send}/{recv}  窗口: {unconfirmed}/{k}")

    def update_traffic(self, tx: int, rx: int, bytes_tx: int = 0, bytes_rx: int = 0) -> None:
        self.traffic_label.setText(
            f"TX: {tx} ({bytes_tx}B)  RX: {rx} ({bytes_rx}B)"
        )

    def update_error(self, text: str) -> None:
        self.error_label.setText(text)
