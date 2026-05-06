"""报文录制器 — 实时捕获 IEC 104 通信帧.

用法:
    recorder = PacketRecorder()
    recorder.start("capture/session.i104")

    # 在引擎回调中调用
    recorder.record_frame(data, direction="rx")
    recorder.record_frame(data, direction="tx", metadata={"client_id": "192.168.1.100:2404"})

    recorder.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from .format import (
    CaptureFile, FrameEntry, FileHeader,
    DIRECTION_RX, DIRECTION_TX,
)

logger = logging.getLogger("iec104.capture.recorder")


class PacketRecorder:
    """报文录制器.

    特性:
    - 线程安全，可在 asyncio 回调中直接调用
    - 环形缓冲区，防止内存溢出
    - 自动定期刷盘
    - 支持暂停/恢复
    - 实时统计
    """

    def __init__(
        self,
        buffer_size: int = 100000,
        auto_flush_interval: float = 5.0,
        auto_flush_count: int = 1000,
    ):
        self._buffer: deque[FrameEntry] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._start_time: float = 0.0
        self._file_path: Optional[Path] = None
        self._file_format: str = "binary"  # binary / json
        self._description: str = ""

        # 状态
        self._recording: bool = False
        self._paused: bool = False

        # 统计
        self._total_frames: int = 0
        self._rx_frames: int = 0
        self._tx_frames: int = 0
        self._dropped_frames: int = 0

        # 自动刷盘
        self._auto_flush_interval = auto_flush_interval
        self._auto_flush_count = auto_flush_count
        self._last_flush_time: float = 0.0
        self._frames_since_flush: int = 0

        # 回调（用于实时通知）
        self._on_frame: Optional[Callable[[FrameEntry], None]] = None

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def total_frames(self) -> int:
        return self._total_frames

    @property
    def rx_frames(self) -> int:
        return self._rx_frames

    @property
    def tx_frames(self) -> int:
        return self._tx_frames

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def buffer_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def elapsed(self) -> float:
        if not self._recording:
            return 0.0
        return time.time() - self._start_time

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_on_frame(self, callback: Callable[[FrameEntry], None]) -> None:
        """设置帧录制回调（每录一帧触发，用于实时显示）."""
        self._on_frame = callback

    # ── 录制控制 ──────────────────────────────────────────────────

    def start(
        self,
        path: str | Path = None,
        description: str = "",
        format: str = "binary",
    ) -> None:
        """开始录制.

        Args:
            path: 保存路径。None 则仅在内存中录制。
            description: 录制描述
            format: "binary" 或 "json"
        """
        if self._recording:
            logger.warning("Already recording, stopping previous session")
            self.stop()

        self._file_path = Path(path) if path else None
        self._file_format = format
        self._description = description
        self._start_time = time.time()
        self._recording = True
        self._paused = False
        self._total_frames = 0
        self._rx_frames = 0
        self._tx_frames = 0
        self._dropped_frames = 0
        self._last_flush_time = time.time()
        self._frames_since_flush = 0

        with self._lock:
            self._buffer.clear()

        logger.info(
            f"Recording started: {self._file_path or 'memory-only'}, "
            f"format={format}, desc='{description}'"
        )

    def stop(self) -> int:
        """停止录制并保存.

        Returns:
            录制的总帧数
        """
        if not self._recording:
            return 0

        self._recording = False
        self._paused = False

        # 刷盘
        total = self._flush_to_file()

        logger.info(
            f"Recording stopped: {total} frames "
            f"(RX={self._rx_frames}, TX={self._tx_frames}, "
            f"dropped={self._dropped_frames})"
        )

        return total

    def pause(self) -> None:
        """暂停录制（不丢帧，只是不记录新帧）."""
        self._paused = True
        logger.info("Recording paused")

    def resume(self) -> None:
        """恢复录制."""
        self._paused = False
        logger.info("Recording resumed")

    # ── 帧记录 ──────────────────────────────────────────────────

    def record_frame(
        self,
        data: bytes,
        direction: str = "rx",
        metadata: dict = None,
        timestamp: float = 0.0,
    ) -> None:
        """录制一帧.

        Args:
            data: 原始帧字节
            direction: "rx" 或 "tx"
            metadata: 附加元数据（如 client_id, asdu_type 等）
            timestamp: 时间戳（0=自动取当前时间）
        """
        if not self._recording or self._paused:
            return

        now = timestamp or time.time()
        relative_time = now - self._start_time

        entry = FrameEntry(
            timestamp=relative_time,
            direction=DIRECTION_RX if direction == "rx" else DIRECTION_TX,
            frame_data=data,
            metadata=metadata or {},
        )

        with self._lock:
            if len(self._buffer) >= self._buffer.maxlen:
                self._dropped_frames += 1
            self._buffer.append(entry)

        self._total_frames += 1
        if direction == "rx":
            self._rx_frames += 1
        else:
            self._tx_frames += 1

        self._frames_since_flush += 1

        # 实时回调
        if self._on_frame:
            try:
                self._on_frame(entry)
            except Exception:
                pass

        # 自动刷盘检查
        if self._file_path:
            time_since_flush = now - self._last_flush_time
            if (time_since_flush >= self._auto_flush_interval or
                    self._frames_since_flush >= self._auto_flush_count):
                self._flush_to_file()

    def make_frame_callback(self, direction: str) -> Callable[[bytes], None]:
        """创建兼容引擎 set_raw_frame_callback 的回调函数."""
        def callback(data: bytes):
            self.record_frame(data, direction=direction)
        return callback

    def make_engine_callback(self, role: str = "master") -> Callable:
        """创建兼容引擎的回调函数（支持 metadata）."""
        if role == "master":
            def master_callback(data: bytes, direction: str):
                self.record_frame(data, direction=direction)
            return master_callback
        else:
            def slave_callback(data: bytes, direction: str, client_id: str = ""):
                self.record_frame(data, direction=direction, metadata={"client_id": client_id})
            return slave_callback

    # ── 刷盘 ──────────────────────────────────────────────────────

    def _flush_to_file(self) -> int:
        """将缓冲区数据写入文件."""
        if not self._file_path:
            return len(self._buffer)

        with self._lock:
            frames = list(self._buffer)

        if not frames:
            return 0

        try:
            CaptureFile.save(
                self._file_path,
                frames,
                description=self._description,
                created=self._start_time,
            )
            self._last_flush_time = time.time()
            self._frames_since_flush = 0
            logger.debug(f"Flushed {len(frames)} frames to {self._file_path}")
        except Exception as e:
            logger.error(f"Failed to flush to file: {e}")

        return len(frames)

    # ── 导出 ──────────────────────────────────────────────────────

    def export(
        self,
        path: str | Path,
        format: str = None,
    ) -> int:
        """导出当前缓冲区到文件（不停止录制）."""
        path = Path(path)
        if format is None:
            format = "json" if path.suffix.lower() == ".json" else "binary"

        with self._lock:
            frames = list(self._buffer)

        CaptureFile.save(path, frames, description=self._description, created=self._start_time)
        logger.info(f"Exported {len(frames)} frames to {path}")
        return len(frames)

    def get_stats(self) -> dict:
        """获取录制统计."""
        return {
            "recording": self._recording,
            "paused": self._paused,
            "elapsed_s": self.elapsed,
            "total_frames": self._total_frames,
            "rx_frames": self._rx_frames,
            "tx_frames": self._tx_frames,
            "dropped_frames": self._dropped_frames,
            "buffer_count": self.buffer_count,
            "file_path": str(self._file_path) if self._file_path else None,
        }
