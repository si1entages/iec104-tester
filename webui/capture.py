"""Web 侧报文录制/回放服务（E2）.

- 录制：把 ``EngineBridge._on_raw_frame`` 的帧写入 ``PacketRecorder``，
  文件落在 ``data/captures/<role>_<timestamp>.i104``；
- 文件：列出/下载/导出 pcap/pcapng/json（复用 ``core.capture.CaptureFile``）；
- 回放：加载录制文件后按时间轴播放/暂停/单步，帧通过事件总线推给前端。
  回放只做**离线展示**，不会把帧注入实时引擎（避免破坏 VS/VR 序号）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.capture import CaptureFile, FrameEntry, PacketPlayer, PacketRecorder

logger = logging.getLogger("iec104.webui.capture")

_EXPORT_FORMATS = {
    "i104": "binary",
    "bin": "binary",
    "binary": "binary",
    "json": "json",
    "pcap": "pcap",
    "pcapng": "pcapng",
    "ntar": "pcapng",
}
_FILE_SUFFIXES = {".i104", ".json", ".pcap", ".pcapng"}


class CaptureService:
    """录制器 + 回放器的薄封装；所有文件操作限制在 capture_dir 内."""

    def __init__(
        self,
        directory: str | Path,
        role: str,
        publish: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.role = role
        self._publish = publish or (lambda kind, data: None)
        self._recorder = PacketRecorder(auto_flush_interval=5.0, auto_flush_count=5000)
        self._recording_file: Path | None = None
        self._player: PacketPlayer | None = None
        self._playback_file: str | None = None
        self._play_task: asyncio.Task | None = None

    # ── 录制 ─────────────────────────────────────────────────────

    @property
    def recording(self) -> bool:
        return self._recorder.is_recording

    def record_frame(self, data: bytes, direction: str, client_id: str = "") -> None:
        """由 bridge 的 raw frame 回调调用；未录制时立即返回."""
        if not self._recorder.is_recording or self._recorder.is_paused:
            return
        metadata = {"client_id": client_id} if client_id else None
        try:
            self._recorder.record_frame(data, direction=direction, metadata=metadata)
        except Exception as e:  # noqa: BLE001 — 录制不得影响报文主路径
            logger.warning("capture record failed: %s", e)

    def start(self, name: str | None = None) -> dict:
        if self._recorder.is_recording:
            return {"ok": False, "error": "already recording"}
        filename = self._new_filename(name)
        path = self.dir / filename
        try:
            self._recorder.start(path)
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"start failed: {e}"}
        self._recording_file = path
        return {"ok": True, "file": filename, **self._record_stats()}

    def stop(self) -> dict:
        if not self._recorder.is_recording:
            return {"ok": False, "error": "not recording"}
        frames = self._recorder.stop()
        name = self._recording_file.name if self._recording_file else None
        self._recording_file = None
        return {"ok": True, "frames": frames, "file": name}

    def pause(self) -> dict:
        if not self._recorder.is_recording:
            return {"ok": False, "error": "not recording"}
        self._recorder.pause()
        return {"ok": True}

    def resume(self) -> dict:
        if not self._recorder.is_recording:
            return {"ok": False, "error": "not recording"}
        self._recorder.resume()
        return {"ok": True}

    def _record_stats(self) -> dict:
        r = self._recorder
        return {
            "recording": r.is_recording,
            "paused": r.is_paused,
            "frames": r.total_frames,
            "rx": r.rx_frames,
            "tx": r.tx_frames,
            "dropped": r.dropped_frames,
            "elapsed": round(r.elapsed, 2),
            "file": self._recording_file.name if self._recording_file else None,
        }

    def _new_filename(self, name: str | None) -> str:
        if name:
            safe = self._safe_name(name)
            if safe is not None:
                return safe
        return f"{self.role}_{time.strftime('%Y%m%d-%H%M%S')}.i104"

    # ── 文件 ─────────────────────────────────────────────────────

    def _safe_name(self, name: str) -> str | None:
        """只允许 capture_dir 下的单层文件名；防路径穿越."""
        candidate = Path(name)
        if candidate.name != name or candidate.suffix.lower() not in _FILE_SUFFIXES:
            return None
        return name

    def _path(self, name: str) -> Path | None:
        safe = self._safe_name(name)
        if safe is None:
            return None
        path = (self.dir / safe).resolve()
        if path.parent != self.dir.resolve():
            return None
        return path

    def list_files(self) -> list[dict]:
        rows = []
        for path in sorted(self.dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() not in _FILE_SUFFIXES:
                continue
            st = path.stat()
            rows.append({
                "name": path.name,
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        return rows

    def export(self, name: str, fmt: str) -> dict:
        path = self._path(name)
        if path is None or not path.is_file():
            return {"ok": False, "error": "file not found"}
        target_format = _EXPORT_FORMATS.get(fmt.lower())
        if target_format is None:
            return {"ok": False, "error": f"unsupported format: {fmt}"}
        suffix = {"binary": ".i104", "json": ".json", "pcap": ".pcap", "pcapng": ".pcapng"}[target_format]
        target_name = f"{path.stem}_{target_format}{suffix}"
        target = self.dir / target_name
        try:
            header, frames = CaptureFile.load(path)
            CaptureFile.save(target, frames, description=header.description,
                             created=header.created, format=target_format)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"export failed: {e}"}
        return {"ok": True, "file": target_name, "frames": len(frames)}

    def download_path(self, name: str) -> Path | None:
        path = self._path(name)
        return path if path is not None and path.is_file() else None

    # ── 回放 ─────────────────────────────────────────────────────

    def load(self, name: str) -> dict:
        path = self._path(name)
        if path is None or not path.is_file():
            return {"ok": False, "error": "file not found"}
        player = PacketPlayer()
        try:
            count = player.load(path)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"load failed: {e}"}
        self.stop_playback()
        self._player = player
        self._playback_file = name
        return {"ok": True, "file": name, "frames": count, **self._player_status()}

    def _player_status(self) -> dict:
        player = self._player
        if player is None:
            return {"loaded": False}
        current = player.current_frame
        return {
            "loaded": True,
            "file": self._playback_file,
            "state": player.state.value,
            "index": player.current_index,
            "total": player.total_frames,
            "progress": round(player.progress, 4),
            "duration": round(player.duration, 3),
            "current": self._frame_dict(current) if current else None,
        }

    def frames(self, offset: int = 0, limit: int = 200) -> dict:
        if self._player is None:
            return {"ok": False, "error": "no file loaded"}
        rows = [self._frame_dict(f) for f in self._player.iter_frames()]
        total = len(rows)
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 1000))
        return {"ok": True, "total": total, "offset": offset,
                "rows": rows[offset:offset + limit]}

    @staticmethod
    def _frame_dict(frame: FrameEntry) -> dict:
        return {
            "timestamp": round(frame.timestamp, 6),
            "absolute_time": frame.absolute_time,
            "direction": frame.direction_str,
            "frame_type": frame.frame_type,
            "length": frame.frame_length,
            "hex": frame.frame_data.hex().upper(),
            "metadata": frame.metadata,
        }

    def play(self, speed: float = 1.0) -> dict:
        if self._player is None:
            return {"ok": False, "error": "no file loaded"}
        if self._play_task is not None and not self._play_task.done():
            return {"ok": False, "error": "already playing"}
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid speed"}
        if not 0.1 <= speed <= 100:
            return {"ok": False, "error": "speed 须在 0.1..100"}
        self._player.set_speed(speed)
        self._play_task = asyncio.create_task(self._run_playback())
        return {"ok": True, **self._player_status()}

    async def _run_playback(self) -> None:
        player = self._player
        if player is None:
            return

        def on_frame(frame: FrameEntry, index: int) -> None:
            self._publish("capture.frame", {
                "file": self._playback_file,
                "index": index,
                "frame": self._frame_dict(frame),
            })

        def on_complete() -> None:
            self._publish("capture.done", {"file": self._playback_file})

        try:
            await player.play(on_frame=on_frame, on_complete=on_complete)
        finally:
            self._play_task = None

    def stop_playback(self) -> dict:
        if self._player is not None:
            self._player.stop()
        if self._play_task is not None and not self._play_task.done():
            self._play_task.cancel()
        self._play_task = None
        return {"ok": True, **self._player_status()}

    def pause_playback(self) -> dict:
        if self._player is None:
            return {"ok": False, "error": "no file loaded"}
        self._player.pause()
        return {"ok": True, **self._player_status()}

    def step(self, direction: str = "forward") -> dict:
        if self._player is None:
            return {"ok": False, "error": "no file loaded"}
        if direction == "backward":
            self._player.step_backward()
        elif direction == "forward":
            self._player.step_forward()
        else:
            return {"ok": False, "error": "direction 须为 forward|backward"}
        return {"ok": True, **self._player_status()}

    def status(self) -> dict:
        return {"ok": True, **self._record_stats(), "files": self.list_files(),
                "playback": self._player_status()}

    def analyze(self, name: str) -> dict:
        """统计概览（帧数/方向/类型），供文件表展示."""
        path = self._path(name)
        if path is None or not path.is_file():
            return {"ok": False, "error": "file not found"}
        try:
            header, frames = CaptureFile.load(path)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"load failed: {e}"}
        rx = sum(1 for f in frames if f.direction_str == "RX")
        types: dict[str, int] = {}
        for f in frames:
            types[f.frame_type] = types.get(f.frame_type, 0) + 1
        return {
            "ok": True, "file": name, "frames": len(frames),
            "rx": rx, "tx": len(frames) - rx,
            "duration": round(frames[-1].timestamp, 3) if frames else 0.0,
            "types": types, "description": header.description,
        }


def frame_to_public(frame: FrameEntry) -> dict[str, Any]:
    """兼容导出（测试/诊断包）."""
    return CaptureService._frame_dict(frame)
