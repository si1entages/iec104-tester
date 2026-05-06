"""报文录制文件格式定义.

支持两种格式:
1. 二进制 (.i104) — 紧凑、高效，适合长时间录制
2. JSON (.json) — 人类可读，适合小规模分析

二进制格式:
┌─────────────────────────────────────────────────────┐
│ File Header (64 bytes)                              │
│   Magic:    "I104" (4B)                             │
│   Version:  uint8 (1B)                              │
│   Flags:    uint8 (1B)                              │
│   Reserved: 2B                                      │
│   Created:  int64 (8B) Unix timestamp (microseconds)│
│   Description: 48B UTF-8 (padded)                   │
├─────────────────────────────────────────────────────┤
│ Frame Entry (repeated)                              │
│   Timestamp:  float64 (8B) seconds since start      │
│   Direction:  uint8 (1B) 0=RX, 1=TX                │
│   Flags:      uint8 (1B)                            │
│   Metadata:   uint16 (2B) JSON metadata length      │
│   Frame Len:  uint16 (2B) frame data length         │
│   Metadata:   variable (JSON bytes)                 │
│   Frame Data: variable (raw APDU bytes)             │
├─────────────────────────────────────────────────────┤
│ EOF: 4 bytes "I104" magic                           │
└─────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# 格式常量
MAGIC = b"I104"
VERSION = 1
HEADER_SIZE = 64
DIRECTION_RX = 0
DIRECTION_TX = 1


@dataclass
class FileHeader:
    """文件头."""
    version: int = VERSION
    flags: int = 0
    created: float = 0.0       # Unix timestamp (seconds)
    description: str = ""

    def __post_init__(self):
        if self.created == 0.0:
            self.created = time.time()

    def encode(self) -> bytes:
        """编码为 64 字节."""
        buf = bytearray(HEADER_SIZE)
        buf[0:4] = MAGIC
        buf[4] = self.version
        buf[5] = self.flags
        # reserved 2 bytes: buf[6:8]
        struct.pack_into("!d", buf, 8, self.created)
        desc_bytes = self.description.encode("utf-8")[:47]
        buf[16:16 + len(desc_bytes)] = desc_bytes
        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes) -> FileHeader:
        """从 64 字节解码."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Header too short: {len(data)}")
        if data[0:4] != MAGIC:
            raise ValueError(f"Invalid magic: {data[0:4]}, expected {MAGIC}")

        version = data[4]
        flags = data[5]
        created = struct.unpack_from("!d", data, 8)[0]
        desc_raw = data[16:HEADER_SIZE].split(b'\x00')[0]
        description = desc_raw.decode("utf-8", errors="replace")

        return cls(version=version, flags=flags, created=created, description=description)


@dataclass
class FrameEntry:
    """单帧记录."""
    timestamp: float = 0.0        # 相对于录制开始的秒数
    direction: int = DIRECTION_RX  # 0=RX, 1=TX
    flags: int = 0
    frame_data: bytes = b""
    metadata: dict = field(default_factory=dict)
    # 以下字段在加载时由解析器填充
    absolute_time: float = 0.0    # Unix timestamp

    @property
    def direction_str(self) -> str:
        return "RX" if self.direction == DIRECTION_RX else "TX"

    @property
    def frame_type(self) -> str:
        """解析帧类型: I/S/U."""
        if len(self.frame_data) < 6:
            return "?"
        cf = self.frame_data[2]
        if (cf & 0x01) == 0:
            return "I"
        elif (cf & 0x03) == 0x01:
            return "S"
        elif (cf & 0x03) == 0x03:
            return "U"
        return "?"

    @property
    def frame_length(self) -> int:
        return len(self.frame_data)

    def encode(self) -> bytes:
        """编码为二进制."""
        meta_bytes = json.dumps(self.metadata, ensure_ascii=False).encode("utf-8") if self.metadata else b""
        header = struct.pack(
            "!dBBHH",
            self.timestamp,
            self.direction,
            self.flags,
            len(meta_bytes),
            len(self.frame_data),
        )
        return header + meta_bytes + self.frame_data

    @classmethod
    def decode_from(cls, data: bytes, offset: int = 0) -> tuple[Optional[FrameEntry], int]:
        """从二进制解码. 返回 (entry, new_offset) 或 (None, offset) 如果数据不足."""
        min_size = 14  # 8+1+1+2+2
        if len(data) - offset < min_size:
            return None, offset

        timestamp, direction, flags, meta_len, frame_len = struct.unpack_from(
            "!dBBHH", data, offset
        )
        offset += min_size

        total_data = meta_len + frame_len
        if len(data) - offset < total_data:
            return None, offset - min_size

        meta_bytes = data[offset:offset + meta_len]
        offset += meta_len

        frame_data = data[offset:offset + frame_len]
        offset += frame_len

        metadata = {}
        if meta_bytes:
            try:
                metadata = json.loads(meta_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        entry = cls(
            timestamp=timestamp,
            direction=direction,
            flags=flags,
            frame_data=frame_data,
            metadata=metadata,
        )
        return entry, offset


class CaptureFile:
    """录制文件读写器.

    支持二进制 (.i104) 和 JSON (.json) 两种格式。
    """

    @staticmethod
    def save_binary(
        path: str | Path,
        frames: list[FrameEntry],
        description: str = "",
        created: float = 0.0,
    ) -> None:
        """保存为二进制格式."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        header = FileHeader(description=description, created=created or time.time())

        with open(path, "wb") as f:
            f.write(header.encode())
            for frame in frames:
                f.write(frame.encode())
            # EOF marker
            f.write(MAGIC)

    @staticmethod
    def load_binary(path: str | Path) -> tuple[FileHeader, list[FrameEntry]]:
        """加载二进制格式."""
        path = Path(path)
        with open(path, "rb") as f:
            data = f.read()

        if len(data) < HEADER_SIZE:
            raise ValueError("File too small")

        header = FileHeader.decode(data[:HEADER_SIZE])
        frames = []
        offset = HEADER_SIZE

        while offset < len(data):
            # 检查 EOF marker
            if data[offset:offset + 4] == MAGIC:
                break

            entry, new_offset = FrameEntry.decode_from(data, offset)
            if entry is None:
                break
            entry.absolute_time = header.created + entry.timestamp
            frames.append(entry)
            offset = new_offset

        return header, frames

    @staticmethod
    def save_json(
        path: str | Path,
        frames: list[FrameEntry],
        description: str = "",
        created: float = 0.0,
    ) -> None:
        """保存为 JSON 格式."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        header = FileHeader(description=description, created=created or time.time())

        data = {
            "format": "iec104-capture",
            "version": 1,
            "header": {
                "created": header.created,
                "description": header.description,
            },
            "frame_count": len(frames),
            "frames": [
                {
                    "timestamp": f.timestamp,
                    "direction": f.direction_str,
                    "frame_type": f.frame_type,
                    "length": f.frame_length,
                    "hex": f.frame_data.hex().upper(),
                    "metadata": f.metadata,
                }
                for f in frames
            ],
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def load_json(path: str | Path) -> tuple[FileHeader, list[FrameEntry]]:
        """加载 JSON 格式."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        header_data = data.get("header", {})
        header = FileHeader(
            created=header_data.get("created", 0),
            description=header_data.get("description", ""),
        )

        frames = []
        for fd in data.get("frames", []):
            direction = DIRECTION_RX if fd.get("direction") == "RX" else DIRECTION_TX
            frame_data = bytes.fromhex(fd.get("hex", ""))
            entry = FrameEntry(
                timestamp=fd.get("timestamp", 0),
                direction=direction,
                frame_data=frame_data,
                metadata=fd.get("metadata", {}),
                absolute_time=header.created + fd.get("timestamp", 0),
            )
            frames.append(entry)

        return header, frames

    @staticmethod
    def load(path: str | Path) -> tuple[FileHeader, list[FrameEntry]]:
        """自动识别格式并加载."""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            return CaptureFile.load_json(path)
        else:
            return CaptureFile.load_binary(path)

    @staticmethod
    def save(
        path: str | Path,
        frames: list[FrameEntry],
        description: str = "",
        created: float = 0.0,
    ) -> None:
        """根据扩展名自动选择格式保存."""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            CaptureFile.save_json(path, frames, description, created)
        else:
            CaptureFile.save_binary(path, frames, description, created)
