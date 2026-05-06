"""报文录制/回放 GUI 面板.

功能:
- 实时录制控制（开始/暂停/停止）
- 录制文件加载与回放
- 回放控制（播放/暂停/单步/速度/跳转）
- 帧列表浏览
- 帧过滤
- 统计分析
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QSlider, QTextEdit, QFileDialog, QSplitter, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QLineEdit,
    QTabWidget, QGridLayout, QFrame, QProgressBar,
)

from core.capture import PacketRecorder, PacketPlayer, CaptureFile, CaptureAnalyzer, FrameFilter
from core.capture.format import FrameEntry


class CapturePanel(QWidget):
    """报文录制/回放面板."""

    # 信号
    recording_started = Signal()
    recording_stopped = Signal(str)  # file path
    playback_started = Signal()
    playback_stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._recorder = PacketRecorder()
        self._player = PacketPlayer()
        self._analyzer = CaptureAnalyzer()
        self._current_file: Optional[str] = None

        # 刷新定时器
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(500)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # 上部：录制/回放控制
        control_splitter = QSplitter(Qt.Horizontal)

        # 左：录制控制
        record_group = QGroupBox("🔴 录制")
        record_layout = QVBoxLayout()

        rec_btn_layout = QHBoxLayout()
        self._rec_start_btn = QPushButton("⏺ 开始")
        self._rec_start_btn.setObjectName("primaryButton")
        self._rec_start_btn.clicked.connect(self._on_record_start)
        rec_btn_layout.addWidget(self._rec_start_btn)

        self._rec_pause_btn = QPushButton("⏸ 暂停")
        self._rec_pause_btn.setCheckable(True)
        self._rec_pause_btn.clicked.connect(self._on_record_pause)
        rec_btn_layout.addWidget(self._rec_pause_btn)

        self._rec_stop_btn = QPushButton("⏹ 停止")
        self._rec_stop_btn.setObjectName("dangerButton")
        self._rec_stop_btn.clicked.connect(self._on_record_stop)
        self._rec_stop_btn.setEnabled(False)
        rec_btn_layout.addWidget(self._rec_stop_btn)
        record_layout.addLayout(rec_btn_layout)

        # 录制统计
        self._rec_stats_label = QLabel("就绪")
        record_layout.addWidget(self._rec_stats_label)

        self._rec_status_label = QLabel("")
        record_layout.addWidget(self._rec_status_label)

        record_group.setLayout(record_layout)
        control_splitter.addWidget(record_group)

        # 右：回放控制
        play_group = QGroupBox("▶ 回放")
        play_layout = QVBoxLayout()

        # 加载文件
        file_layout = QHBoxLayout()
        self._file_label = QLabel("未加载")
        file_layout.addWidget(self._file_label, 1)

        self._load_btn = QPushButton("📂 加载")
        self._load_btn.clicked.connect(self._on_load_file)
        file_layout.addWidget(self._load_btn)

        self._export_btn = QPushButton("💾 导出")
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setEnabled(False)
        file_layout.addWidget(self._export_btn)
        play_layout.addLayout(file_layout)

        # 回放按钮
        play_btn_layout = QHBoxLayout()
        self._play_btn = QPushButton("▶ 播放")
        self._play_btn.setObjectName("primaryButton")
        self._play_btn.clicked.connect(self._on_play)
        self._play_btn.setEnabled(False)
        play_btn_layout.addWidget(self._play_btn)

        self._pause_btn = QPushButton("⏸ 暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.clicked.connect(self._on_pause)
        self._pause_btn.setEnabled(False)
        play_btn_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.setEnabled(False)
        play_btn_layout.addWidget(self._stop_btn)

        self._step_btn = QPushButton("⏭ 单步")
        self._step_btn.clicked.connect(self._on_step)
        self._step_btn.setEnabled(False)
        play_btn_layout.addWidget(self._step_btn)
        play_layout.addLayout(play_btn_layout)

        # 速度控制
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("速度:"))
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.1, 100.0)
        self._speed_spin.setValue(1.0)
        self._speed_spin.setSingleStep(0.5)
        self._speed_spin.valueChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self._speed_spin)
        speed_layout.addWidget(QLabel("x"))

        speed_layout.addWidget(QLabel("帧:"))
        self._frame_spin = QSpinBox()
        self._frame_spin.setRange(0, 0)
        self._frame_spin.valueChanged.connect(self._on_seek_frame)
        speed_layout.addWidget(self._frame_spin)
        play_layout.addLayout(speed_layout)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        play_layout.addWidget(self._progress)

        play_group.setLayout(play_layout)
        control_splitter.addWidget(play_group)

        layout.addWidget(control_splitter)

        # 过滤器
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("过滤:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            "全部", "仅RX", "仅TX", "仅I帧", "仅S帧", "仅U帧",
        ])
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._filter_combo)

        filter_layout.addWidget(QLabel("ASDU:"))
        self._asdu_filter = QSpinBox()
        self._asdu_filter.setRange(0, 255)
        self._asdu_filter.setSpecialValueText("全部")
        self._asdu_filter.valueChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._asdu_filter)

        self._apply_filter_btn = QPushButton("🔍 应用")
        self._apply_filter_btn.clicked.connect(self._on_filter_changed)
        filter_layout.addWidget(self._apply_filter_btn)

        filter_layout.addStretch()
        self._filter_info_label = QLabel("")
        filter_layout.addWidget(self._filter_info_label)
        layout.addLayout(filter_layout)

        # 下部：帧列表 + 统计
        bottom_splitter = QSplitter(Qt.Vertical)

        # 帧列表表格
        self._frame_table = QTableWidget()
        self._frame_table.setColumnCount(6)
        self._frame_table.setHorizontalHeaderLabels(
            ["#", "时间", "方向", "类型", "长度", "HEX"]
        )
        self._frame_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._frame_table.horizontalHeader().setStretchLastSection(True)
        self._frame_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._frame_table.setAlternatingRowColors(True)
        self._frame_table.setSortingEnabled(True)
        bottom_splitter.addWidget(self._frame_table)

        # 统计/分析标签页
        info_tabs = QTabWidget()

        # 统计
        self._stats_text = QTextEdit()
        self._stats_text.setReadOnly(True)
        self._stats_text.setFont(QFont("Cascadia Code", 11))
        info_tabs.addTab(self._stats_text, "📊 统计")

        # 异常
        self._anomaly_text = QTextEdit()
        self._anomaly_text.setReadOnly(True)
        self._anomaly_text.setFont(QFont("Cascadia Code", 11))
        info_tabs.addTab(self._anomaly_text, "⚠️ 异常")

        bottom_splitter.addWidget(info_tabs)
        bottom_splitter.setSizes([400, 200])

        layout.addWidget(bottom_splitter)

    # ── 录制控制 ──────────────────────────────────────────────────

    def _on_record_start(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存录制文件", "capture.i104",
            "IEC104 Capture (*.i104);;JSON (*.json)",
        )
        if not path:
            return

        format = "json" if path.endswith(".json") else "binary"
        self._recorder.start(path, description="GUI capture", format=format)
        self._current_file = path

        self._rec_start_btn.setEnabled(False)
        self._rec_stop_btn.setEnabled(True)
        self._rec_status_label.setText(f"录制中: {path}")
        self.recording_started.emit()

    def _on_record_pause(self, checked):
        if checked:
            self._recorder.pause()
            self._rec_pause_btn.setText("▶ 恢复")
        else:
            self._recorder.resume()
            self._rec_pause_btn.setText("⏸ 暂停")

    def _on_record_stop(self):
        total = self._recorder.stop()
        self._rec_start_btn.setEnabled(True)
        self._rec_stop_btn.setEnabled(False)
        self._rec_pause_btn.setChecked(False)
        self._rec_pause_btn.setText("⏸ 暂停")
        self._rec_status_label.setText(f"已保存 {total} 帧")
        self.recording_stopped.emit(self._current_file or "")

    # ── 回放控制 ──────────────────────────────────────────────────

    def _on_load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载录制文件", "",
            "IEC104 Capture (*.i104 *.json);;All Files (*)",
        )
        if not path:
            return

        count = self._player.load(path)
        self._current_file = path
        self._file_label.setText(f"{Path(path).name} ({count} 帧)")
        self._frame_spin.setRange(0, max(0, count - 1))
        self._play_btn.setEnabled(True)
        self._step_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

        self._update_frame_table()
        self._update_stats()

    def _on_export(self):
        if not self._player.is_loaded:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出", "export.json",
            "JSON (*.json);;IEC104 Capture (*.i104)",
        )
        if path:
            from core.capture import CaptureFile
            frames = list(self._player.iter_frames())
            CaptureFile.save(path, frames, description="Exported from GUI")
            self._stats_text.append(f"\n✅ Exported {len(frames)} frames to {path}")

    def _on_play(self):
        if not self._player.is_loaded:
            return
        self._play_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        self._step_btn.setEnabled(False)
        self.playback_started.emit()

        import asyncio
        from PySide6.QtCore import QThread

        # 在后台线程运行回放
        class PlayThread(QThread):
            frame_signal = Signal(int)
            complete_signal = Signal()

            def __init__(self, player):
                super().__init__()
                self._player = player

            def run(self):
                loop = asyncio.new_event_loop()

                def on_frame(frame, index):
                    self.frame_signal.emit(index)

                def on_complete():
                    self.complete_signal.emit()

                loop.run_until_complete(
                    self._player.play(on_frame=on_frame, on_complete=on_complete)
                )

        self._play_thread = PlayThread(self._player)
        self._play_thread.frame_signal.connect(self._on_playback_frame)
        self._play_thread.complete_signal.connect(self._on_playback_complete)
        self._play_thread.start()

    def _on_pause(self, checked):
        if checked:
            self._player.pause()
            self._pause_btn.setText("▶ 恢复")
        else:
            self._player.resume()
            self._pause_btn.setText("⏸ 暂停")

    def _on_stop(self):
        self._player.stop()
        self._play_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._step_btn.setEnabled(True)
        self._pause_btn.setChecked(False)
        self._pause_btn.setText("⏸ 暂停")
        self.playback_stopped.emit()

    def _on_step(self):
        frame = self._player.step_forward()
        if frame:
            self._frame_spin.setValue(self._player.current_index)

    def _on_speed_changed(self, value):
        self._player.set_speed(value)

    def _on_seek_frame(self, index):
        self._player.seek(index)

    @Slot(int)
    def _on_playback_frame(self, index):
        self._frame_spin.setValue(index)
        self._progress.setValue(int(self._player.progress * 100))

    @Slot()
    def _on_playback_complete(self):
        self._on_stop()

    # ── 过滤 ──────────────────────────────────────────────────────

    def _on_filter_changed(self):
        if not self._player.is_loaded:
            return

        f = FrameFilter()
        filter_text = self._filter_combo.currentText()
        if filter_text == "仅RX":
            f.direction = "rx"
        elif filter_text == "仅TX":
            f.direction = "tx"
        elif filter_text == "仅I帧":
            f.frame_type = "I"
        elif filter_text == "仅S帧":
            f.frame_type = "S"
        elif filter_text == "仅U帧":
            f.frame_type = "U"

        asdu_type = self._asdu_filter.value()
        if asdu_type > 0:
            f.asdu_type = asdu_type

        self._player.set_filter(f)
        self._frame_spin.setRange(0, max(0, self._player.total_frames - 1))
        self._filter_info_label.setText(f"过滤: {f.describe()}")
        self._update_frame_table()

    # ── 刷新 ──────────────────────────────────────────────────────

    def _refresh(self):
        """定时刷新录制统计."""
        if self._recorder.is_recording:
            stats = self._recorder.get_stats()
            self._rec_stats_label.setText(
                f"帧数: {stats['total_frames']} "
                f"(RX={stats['rx_frames']}, TX={stats['tx_frames']}) "
                f"| 时间: {stats['elapsed_s']:.0f}s"
            )

    # ── 帧列表 ────────────────────────────────────────────────────

    def _update_frame_table(self):
        """更新帧列表表格."""
        frames = list(self._player.iter_frames())
        self._frame_table.setRowCount(min(len(frames), 5000))

        for i, frame in enumerate(frames[:5000]):
            hex_str = " ".join(f"{b:02X}" for b in frame.frame_data[:20])
            if len(frame.frame_data) > 20:
                hex_str += "..."

            self._frame_table.setItem(i, 0, QTableWidgetItem(str(i)))
            self._frame_table.setItem(i, 1, QTableWidgetItem(f"{frame.timestamp:.3f}"))

            dir_item = QTableWidgetItem(frame.direction_str)
            dir_item.setForeground(
                QColor("#89dceb") if frame.direction_str == "RX" else QColor("#a6e3a1")
            )
            self._frame_table.setItem(i, 2, dir_item)

            self._frame_table.setItem(i, 3, QTableWidgetItem(frame.frame_type))
            self._frame_table.setItem(i, 4, QTableWidgetItem(str(frame.frame_length)))
            self._frame_table.setItem(i, 5, QTableWidgetItem(hex_str))

        if len(frames) > 5000:
            self._filter_info_label.setText(f"显示前 5000/{len(frames)} 帧")

    def _update_stats(self):
        """更新统计信息."""
        frames = list(self._player.iter_frames())
        result = self._analyzer.analyze(frames)
        self._stats_text.setText(result.session_summary)

        # 异常
        self._anomaly_text.clear()
        if result.anomalies:
            for a in result.anomalies[:100]:
                icon = "❌" if a.severity == "error" else "⚠️"
                self._anomaly_text.append(
                    f"{icon} [{a.timestamp:.3f}s] {a.description}"
                )
        else:
            self._anomaly_text.setText("✅ 未检测到异常")
