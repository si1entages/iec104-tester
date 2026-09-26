"""帧过滤器 — 按条件筛选录制帧.

支持的过滤维度:
- 方向 (RX/TX)
- 帧类型 (I/S/U)
- 时间范围
- ASDU 类型标识
- 传送原因
- 公共地址
- 信息对象地址 (IOA)
- 帧长度范围
- 自定义条件
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.capture.format import FrameEntry

logger = logging.getLogger("iec104.capture.filter")


@dataclass
class FrameFilter:
    """帧过滤器.

    所有条件之间是 AND 关系。
    """

    # 方向过滤
    direction: str | None = None  # "rx" / "tx" / None(全部)

    # 帧类型过滤
    frame_type: str | None = None  # "I" / "S" / "U" / None(全部)

    # 时间范围（相对于录制开始的秒数）
    time_start: float | None = None
    time_end: float | None = None

    # ASDU 类型标识 (int)
    asdu_type: int | None = None

    # 传送原因 (int)
    cot: int | None = None

    # 公共地址 (int)
    common_addr: int | None = None

    # 信息对象地址 (int) — 检查帧中是否包含此 IOA
    ioa: int | None = None

    # 帧长度范围
    min_length: int | None = None
    max_length: int | None = None

    # 自定义过滤函数
    custom: Callable[[FrameEntry], bool] | None = None

    def apply(self, frames: list) -> list:
        """应用过滤器，返回匹配的帧列表."""
        result = []
        for frame in frames:
            if self._match(frame):
                result.append(frame)
        return result

    def _match(self, frame) -> bool:
        """检查单帧是否匹配所有条件."""
        # 方向
        if self.direction:
            if self.direction.upper() != frame.direction_str:
                return False

        # 帧类型
        if self.frame_type:
            if self.frame_type.upper() != frame.frame_type:
                return False

        # 时间范围
        if self.time_start is not None and frame.timestamp < self.time_start:
            return False
        if self.time_end is not None and frame.timestamp > self.time_end:
            return False

        # 帧长度
        if self.min_length is not None and frame.frame_length < self.min_length:
            return False
        if self.max_length is not None and frame.frame_length > self.max_length:
            return False

        # ASDU 层过滤（仅 I 帧）
        if self._has_asdu_filter():
            if frame.frame_type != "I" or frame.frame_length < 12:
                return False
            if not self._match_asdu(frame.frame_data):
                return False

        # 自定义
        if self.custom:
            if not self.custom(frame):
                return False

        return True

    def _has_asdu_filter(self) -> bool:
        return any([
            self.asdu_type is not None,
            self.cot is not None,
            self.common_addr is not None,
            self.ioa is not None,
        ])

    def _match_asdu(self, frame_data: bytes) -> bool:
        """检查 ASDU 层是否匹配."""
        try:
            # I帧: skip APCI(6 bytes) -> ASDU starts at offset 6
            if len(frame_data) < 12:
                return False

            asdu = frame_data[6:]
            type_id = asdu[0]
            cot = asdu[2] & 0x3F
            common_addr = asdu[4] | (asdu[5] << 8)

            if self.asdu_type is not None and type_id != self.asdu_type:
                return False
            if self.cot is not None and cot != self.cot:
                return False
            if self.common_addr is not None and common_addr != self.common_addr:
                return False
            if self.ioa is not None:
                # 检查信息对象中是否包含此 IOA
                # IOA 从 offset 6 开始，3 字节
                if len(asdu) >= 9:
                    ioa = asdu[6] | (asdu[7] << 8) | (asdu[8] << 16)
                    if ioa != self.ioa:
                        return False

            return True
        except (IndexError, ValueError):
            return False

    def describe(self) -> str:
        """返回过滤器描述."""
        parts = []
        if self.direction:
            parts.append(f"direction={self.direction}")
        if self.frame_type:
            parts.append(f"type={self.frame_type}")
        if self.time_start is not None:
            parts.append(f"t>={self.time_start:.3f}")
        if self.time_end is not None:
            parts.append(f"t<={self.time_end:.3f}")
        if self.asdu_type is not None:
            parts.append(f"asdu={self.asdu_type}")
        if self.cot is not None:
            parts.append(f"cot={self.cot}")
        if self.common_addr is not None:
            parts.append(f"addr={self.common_addr}")
        if self.ioa is not None:
            parts.append(f"ioa={self.ioa}")
        if self.min_length is not None:
            parts.append(f"len>={self.min_length}")
        if self.max_length is not None:
            parts.append(f"len<={self.max_length}")
        return " AND ".join(parts) if parts else "(no filter)"

    @classmethod
    def from_dict(cls, data: dict) -> FrameFilter:
        """从字典创建过滤器."""
        return cls(
            direction=data.get("direction"),
            frame_type=data.get("frame_type"),
            time_start=data.get("time_start"),
            time_end=data.get("time_end"),
            asdu_type=data.get("asdu_type"),
            cot=data.get("cot"),
            common_addr=data.get("common_addr"),
            ioa=data.get("ioa"),
            min_length=data.get("min_length"),
            max_length=data.get("max_length"),
        )
