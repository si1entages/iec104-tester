"""报文回放器 — 加载录制文件并回放帧.

支持:
- 原始时序回放
- 变速回放 (0.1x ~ 100x)
- 单步模式
- 帧过滤后回放
- 跳转到指定时间
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from .filter import FrameFilter
from .format import CaptureFile, FileHeader, FrameEntry

logger = logging.getLogger("iec104.capture.player")


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    STEPPING = "stepping"


class PacketPlayer:
    """报文回放器.

    用法:
        player = PacketPlayer()
        player.load("capture/session.i104")
        player.set_speed(2.0)  # 2倍速

        # 异步回放
        await player.play(on_frame=my_callback)

        # 单步模式
        frame = player.step_forward()
        frame = player.step_backward()

        # 迭代器模式
        for frame in player.iter_frames():
            process(frame)
    """

    def __init__(self):
        self._header: FileHeader | None = None
        self._frames: list[FrameEntry] = []
        self._filtered_frames: list[FrameEntry] = []
        self._state = PlaybackState.STOPPED
        self._speed: float = 1.0
        self._current_index: int = 0
        self._play_task: asyncio.Task | None = None
        self._on_frame: Callable[[FrameEntry, int], None] | None = None
        self._on_complete: Callable[[], None] | None = None
        self._filter: FrameFilter | None = None

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def is_loaded(self) -> bool:
        return len(self._frames) > 0

    @property
    def total_frames(self) -> int:
        return len(self._get_active_frames())

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def current_frame(self) -> FrameEntry | None:
        frames = self._get_active_frames()
        if 0 <= self._current_index < len(frames):
            return frames[self._current_index]
        return None

    @property
    def progress(self) -> float:
        """回放进度 0.0 ~ 1.0."""
        total = self.total_frames
        if total == 0:
            return 0.0
        return self._current_index / total

    @property
    def duration(self) -> float:
        """录制总时长(秒)."""
        if not self._frames:
            return 0.0
        return self._frames[-1].timestamp

    @property
    def header(self) -> FileHeader | None:
        return self._header

    # ── 加载 ──────────────────────────────────────────────────────

    def load(self, path: str | Path) -> int:
        """加载录制文件.

        Returns:
            加载的帧数
        """
        path = Path(path)
        self._header, self._frames = CaptureFile.load(path)
        self._filtered_frames = list(self._frames)
        self._current_index = 0
        self._state = PlaybackState.STOPPED
        logger.info(f"Loaded {len(self._frames)} frames from {path}")
        return len(self._frames)

    def load_frames(self, frames: list[FrameEntry], header: FileHeader = None) -> None:
        """直接加载帧列表."""
        self._header = header or FileHeader()
        self._frames = list(frames)
        self._filtered_frames = list(frames)
        self._current_index = 0
        self._state = PlaybackState.STOPPED

    # ── 过滤 ──────────────────────────────────────────────────────

    def set_filter(self, frame_filter: FrameFilter | None) -> None:
        """设置帧过滤器."""
        self._filter = frame_filter
        if frame_filter:
            self._filtered_frames = frame_filter.apply(self._frames)
            logger.info(
                f"Filter applied: {len(self._filtered_frames)}/{len(self._frames)} frames"
            )
        else:
            self._filtered_frames = list(self._frames)
        self._current_index = 0

    def clear_filter(self) -> None:
        self._filter = None
        self._filtered_frames = list(self._frames)
        self._current_index = 0

    def _get_active_frames(self) -> list[FrameEntry]:
        return self._filtered_frames

    # ── 速度控制 ──────────────────────────────────────────────────

    def set_speed(self, speed: float) -> None:
        """设置回放速度. 1.0=原始速度, 2.0=2倍速, 0.5=半速."""
        self._speed = max(0.01, min(speed, 1000.0))

    # ── 回放控制 ──────────────────────────────────────────────────

    async def play(
        self,
        on_frame: Callable[[FrameEntry, int], None] = None,
        on_complete: Callable[[], None] = None,
    ) -> None:
        """异步回放.

        Args:
            on_frame: 每帧回调 (frame, index)
            on_complete: 回放完成回调
        """
        if self._state == PlaybackState.PLAYING:
            return

        self._on_frame = on_frame or self._on_frame
        self._on_complete = on_complete or self._on_complete
        self._state = PlaybackState.PLAYING

        frames = self._get_active_frames()
        if not frames:
            self._state = PlaybackState.STOPPED
            return

        self._play_task = asyncio.current_task()

        try:
            prev_time = 0.0
            for i in range(self._current_index, len(frames)):
                if self._state != PlaybackState.PLAYING:
                    break

                frame = frames[i]
                self._current_index = i

                # 计算等待时间
                if i > 0 and self._speed > 0:
                    delay = (frame.timestamp - prev_time) / self._speed
                    if delay > 0:
                        # 限制最大等待，避免长时间阻塞
                        delay = min(delay, 10.0)
                        await asyncio.sleep(delay)

                prev_time = frame.timestamp

                # 回调
                if self._on_frame:
                    try:
                        self._on_frame(frame, i)
                    except Exception as e:
                        logger.error(f"Frame callback error: {e}")

            # 回放完成
            if self._state == PlaybackState.PLAYING:
                self._state = PlaybackState.STOPPED
                if self._on_complete:
                    try:
                        self._on_complete()
                    except Exception:
                        pass

        except asyncio.CancelledError:
            pass
        finally:
            self._play_task = None

    def stop(self) -> None:
        """停止回放."""
        self._state = PlaybackState.STOPPED
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()

    def pause(self) -> None:
        """暂停回放."""
        if self._state == PlaybackState.PLAYING:
            self._state = PlaybackState.PAUSED

    def resume(self) -> None:
        """恢复回放."""
        if self._state == PlaybackState.PAUSED:
            self._state = PlaybackState.PLAYING

    # ── 单步 ──────────────────────────────────────────────────────

    def step_forward(self) -> FrameEntry | None:
        """前进一帧."""
        frames = self._get_active_frames()
        if self._current_index < len(frames) - 1:
            self._current_index += 1
            return frames[self._current_index]
        return None

    def step_backward(self) -> FrameEntry | None:
        """后退一帧."""
        frames = self._get_active_frames()
        if self._current_index > 0:
            self._current_index -= 1
            return frames[self._current_index]
        return None

    def seek(self, index: int) -> FrameEntry | None:
        """跳转到指定帧索引."""
        frames = self._get_active_frames()
        if 0 <= index < len(frames):
            self._current_index = index
            return frames[self._current_index]
        return None

    def seek_time(self, timestamp: float) -> FrameEntry | None:
        """跳转到指定时间(秒)."""
        frames = self._get_active_frames()
        for i, f in enumerate(frames):
            if f.timestamp >= timestamp:
                self._current_index = i
                return f
        # 跳到最后一帧
        if frames:
            self._current_index = len(frames) - 1
            return frames[-1]
        return None

    # ── 迭代器 ────────────────────────────────────────────────────

    def iter_frames(
        self,
        start: int = 0,
        end: int = None,
        frame_filter: FrameFilter = None,
    ):
        """帧迭代器.

        Args:
            start: 起始帧索引
            end: 结束帧索引（不含）
            frame_filter: 临时过滤器
        """
        frames = self._get_active_frames()
        if frame_filter:
            frames = frame_filter.apply(frames)
        end = end or len(frames)
        return iter(frames[start:end])

    def get_frames_in_range(
        self,
        start_time: float,
        end_time: float,
    ) -> list[FrameEntry]:
        """获取时间范围内的帧."""
        return [
            f for f in self._get_active_frames()
            if start_time <= f.timestamp <= end_time
        ]

    # ── 统计 ──────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """获取回放统计."""
        frames = self._get_active_frames()
        rx_count = sum(1 for f in frames if f.direction == 0)
        tx_count = sum(1 for f in frames if f.direction == 1)

        type_counts = {}
        for f in frames:
            t = f.frame_type
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "loaded": self.is_loaded,
            "state": self.state.value,
            "total_frames": len(frames),
            "original_frames": len(self._frames),
            "filtered": len(frames) != len(self._frames),
            "rx_frames": rx_count,
            "tx_frames": tx_count,
            "duration_s": self.duration,
            "speed": self._speed,
            "current_index": self._current_index,
            "progress": self.progress,
            "frame_types": type_counts,
        }
