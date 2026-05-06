"""报文录制/回放引擎.

功能:
- 实时录制 IEC 104 通信帧
- 自定义二进制格式 (.i104) + JSON 格式
- 回放支持变速、单步、跳转
- 帧过滤（方向/类型/时间/ASDU）
- 报文统计分析

用法:
    from core.capture import PacketRecorder, PacketPlayer

    # 录制
    recorder = PacketRecorder()
    recorder.start("capture/session_001.i104")
    recorder.record_frame(data, direction="rx", metadata={...})
    recorder.stop()

    # 回放
    player = PacketPlayer()
    player.load("capture/session_001.i104")
    for frame in player.iter_frames():
        process(frame)
"""

from .recorder import PacketRecorder
from .player import PacketPlayer
from .format import CaptureFile, FrameEntry, FileHeader
from .filter import FrameFilter
from .analyzer import CaptureAnalyzer

__all__ = [
    "PacketRecorder",
    "PacketPlayer",
    "CaptureFile",
    "FrameEntry",
    "FileHeader",
    "FrameFilter",
    "CaptureAnalyzer",
]
