"""`core/capture/format.py` 录制文件格式单元测试.

覆盖 .i104 二进制格式的文件头/帧记录编解码、JSON 格式读写、自动格式识别，
以及畸形输入（头过短、magic 错误、数据截断、元数据非法 JSON）的降级行为。

此前该模块零覆盖；它是抓包录制/回放（recorder/player/analyzer）的公共基础。
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.capture.format import (
    DIRECTION_RX,
    DIRECTION_TX,
    HEADER_SIZE,
    MAGIC,
    CaptureFile,
    FileHeader,
    FrameEntry,
)

# ── FileHeader ───────────────────────────────────────────────────

def test_file_header_defaults_sets_created():
    """created=0 时 __post_init__ 自动填当前时间."""
    h = FileHeader()
    assert h.version == 1
    assert h.created > 0


def test_file_header_explicit_created_is_kept():
    h = FileHeader(description="会话 A", created=1234.5)
    assert h.created == 1234.5


def test_file_header_encode_decode_roundtrip():
    """编码固定 64 字节；解码后 version/flags/created/description 一致."""
    h = FileHeader(version=1, flags=3, created=1700000000.25, description="真机联调")
    raw = h.encode()

    assert len(raw) == HEADER_SIZE
    assert raw[0:4] == MAGIC
    assert raw[4] == 1
    assert raw[5] == 3

    back = FileHeader.decode(raw)
    assert back.version == 1
    assert back.flags == 3
    assert back.created == pytest.approx(1700000000.25)
    assert back.description == "真机联调"


def test_file_header_description_is_truncated_to_47_bytes():
    """描述最长 47 字节（留 NUL 终止空间），超长被截断."""
    h = FileHeader(created=1.0, description="x" * 100)
    raw = h.encode()

    assert len(raw) == HEADER_SIZE
    back = FileHeader.decode(raw)
    assert len(back.description.encode("utf-8")) <= 47


def test_file_header_decode_rejects_short_and_bad_magic():
    with pytest.raises(ValueError, match="Header too short"):
        FileHeader.decode(b"\x00" * 10)

    with pytest.raises(ValueError, match="Invalid magic"):
        FileHeader.decode(b"XXXX" + b"\x00" * 60)


# ── FrameEntry ───────────────────────────────────────────────────

def test_frame_entry_direction_str():
    assert FrameEntry(direction=DIRECTION_RX).direction_str == "RX"
    assert FrameEntry(direction=DIRECTION_TX).direction_str == "TX"


@pytest.mark.parametrize("frame,expected", [
    (b"\x68\x04\x07\x00\x00\x00", "U"),          # 控制域 bit0=1, bits1-2=11
    (b"\x68\x04\x01\x00\x00\x00", "S"),          # 控制域 bit0=1, bits1-2=01
    (b"\x68\x0e\x00\x00\x00\x00" + b"\x00" * 8, "I"),  # 控制域 bit0=0
])
def test_frame_entry_frame_type(frame, expected):
    assert FrameEntry(frame_data=frame).frame_type == expected


def test_frame_entry_frame_type_short_or_unknown():
    """帧长 <6 → '?'（数据不足无法判定帧型）."""
    assert FrameEntry(frame_data=b"\x68\x04").frame_type == "?"
    assert FrameEntry(frame_data=b"").frame_type == "?"


@pytest.mark.parametrize("cf,expected", [
    (0x00, "I"), (0x02, "I"),   # bit0=0 → I 帧
    (0x01, "S"), (0x05, "S"),   # bit0=1, bits1-2=01 → S 帧
    (0x03, "U"), (0x07, "U"),   # bit0=1, bits1-2=11 → U 帧
])
def test_frame_entry_frame_type_control_field_matrix(cf, expected):
    """控制域位组合 → 帧型判定（覆盖 I/S/U 三类的多组取值）."""
    frame = bytes([0x68, 0x04, cf, 0x00, 0x00, 0x00])
    assert FrameEntry(frame_data=frame).frame_type == expected


def test_frame_entry_frame_length():
    assert FrameEntry(frame_data=b"abc").frame_length == 3


def test_frame_entry_encode_decode_roundtrip_with_metadata():
    entry = FrameEntry(
        timestamp=1.25, direction=DIRECTION_TX, flags=2,
        frame_data=b"\x68\x04\x07\x00\x00\x00",
        metadata={"note": "手动下发", "n": 1},
    )
    raw = entry.encode()
    decoded, offset = FrameEntry.decode_from(raw)

    assert decoded is not None
    assert offset == len(raw)
    assert decoded.timestamp == pytest.approx(1.25)
    assert decoded.direction == DIRECTION_TX
    assert decoded.flags == 2
    assert decoded.frame_data == entry.frame_data
    assert decoded.metadata == {"note": "手动下发", "n": 1}


def test_frame_entry_encode_decode_without_metadata():
    """空 metadata 不写入元数据字节，长度 = 14 + 帧长."""
    entry = FrameEntry(timestamp=0.5, direction=DIRECTION_RX,
                       frame_data=b"\x68\x04\x0b\x00\x00\x00")
    raw = entry.encode()

    assert len(raw) == 14 + 6
    decoded, offset = FrameEntry.decode_from(raw)
    assert decoded is not None
    assert decoded.metadata == {}
    assert offset == len(raw)


def test_frame_entry_decode_from_insufficient_header():
    """头部不足 14 字节 → (None, 原 offset)，不做部分解码."""
    assert FrameEntry.decode_from(b"\x00" * 5) == (None, 0)
    assert FrameEntry.decode_from(b"\x00" * 5, offset=2) == (None, 2)


def test_frame_entry_decode_from_truncated_payload():
    """声明了元数据/帧长度但数据不足 → (None, 回退到该帧起始)."""
    raw = FrameEntry(timestamp=1.0, frame_data=b"\x01\x02\x03\x04").encode()
    truncated = raw[:-2]

    entry, offset = FrameEntry.decode_from(truncated)
    assert entry is None
    assert offset == 0


def test_frame_entry_decode_from_invalid_metadata_json_degrades_to_empty():
    """元数据不是合法 JSON/UTF-8 → 降级为 {}，不抛异常."""
    header = struct.pack("!dBBHH", 1.0, DIRECTION_RX, 0, 3, 0)
    raw = header + b"\xff\xfe\xfd"

    entry, offset = FrameEntry.decode_from(raw)
    assert entry is not None
    assert entry.metadata == {}
    assert offset == len(raw)


# ── CaptureFile：二进制 ──────────────────────────────────────────

def _sample_frames() -> list[FrameEntry]:
    return [
        FrameEntry(timestamp=0.0, direction=DIRECTION_RX,
                   frame_data=b"\x68\x04\x0b\x00\x00\x00"),
        FrameEntry(timestamp=0.5, direction=DIRECTION_TX,
                   frame_data=b"\x68\x04\x07\x00\x00\x00",
                   metadata={"cmd": "startdt"}),
    ]


def test_save_load_binary_roundtrip(tmp_path):
    """二进制保存/加载：帧数、字段、absolute_time 与目录自动创建."""
    path = tmp_path / "nested" / "session.i104"
    frames = _sample_frames()
    CaptureFile.save_binary(path, frames, description="二进制会话", created=1000.0)

    assert path.exists()

    header, loaded = CaptureFile.load_binary(path)
    assert header.description == "二进制会话"
    assert header.created == pytest.approx(1000.0)
    assert len(loaded) == 2
    assert loaded[0].frame_data == frames[0].frame_data
    assert loaded[1].metadata == {"cmd": "startdt"}
    assert loaded[1].absolute_time == pytest.approx(1000.5)


def test_load_binary_rejects_too_small_file(tmp_path):
    path = tmp_path / "broken.i104"
    path.write_bytes(b"I104")

    with pytest.raises(ValueError, match="File too small"):
        CaptureFile.load_binary(path)


def test_load_binary_stops_at_eof_marker(tmp_path):
    """EOF magic 之后的内容不被解析为帧."""
    path = tmp_path / "eof.i104"
    header = FileHeader(created=1.0)
    path.write_bytes(header.encode() + MAGIC + b"\xde\xad\xbe\xef")

    header_back, frames = CaptureFile.load_binary(path)
    assert header_back.created == pytest.approx(1.0)
    assert frames == []


def test_load_binary_stops_on_truncated_trailing_frame(tmp_path):
    """尾部残帧（声明长度大于实际数据）被安全丢弃，已解析帧保留."""
    path = tmp_path / "trunc.i104"
    header = FileHeader(created=1.0)
    good = FrameEntry(timestamp=0.1, frame_data=b"\x68\x04\x0b\x00\x00\x00").encode()
    # 帧头声明 frame_len=100 但后面没有任何数据 → decode_from 返回 None
    bogus_header = struct.pack("!dBBHH", 0.2, DIRECTION_RX, 0, 0, 100)
    path.write_bytes(header.encode() + good + bogus_header)

    _, loaded = CaptureFile.load_binary(path)
    assert len(loaded) == 1
    assert loaded[0].frame_data == b"\x68\x04\x0b\x00\x00\x00"


# ── CaptureFile：JSON ───────────────────────────────────────────

def test_save_load_json_roundtrip(tmp_path):
    path = tmp_path / "session.json"
    frames = _sample_frames()
    CaptureFile.save_json(path, frames, description="JSON 会话", created=2000.0)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format"] == "iec104-capture"
    assert raw["frame_count"] == 2
    assert raw["frames"][0]["direction"] == "RX"
    assert raw["frames"][1]["direction"] == "TX"
    assert raw["frames"][0]["hex"] == frames[0].frame_data.hex().upper()
    assert raw["frames"][1]["metadata"] == {"cmd": "startdt"}

    header, loaded = CaptureFile.load_json(path)
    assert header.description == "JSON 会话"
    assert header.created == pytest.approx(2000.0)
    assert [f.frame_data for f in loaded] == [f.frame_data for f in frames]
    assert loaded[1].absolute_time == pytest.approx(2000.5)


def test_load_json_with_missing_fields_uses_defaults(tmp_path):
    """JSON 缺少 header/frames 字段时使用默认值."""
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps({}), encoding="utf-8")

    header, frames = CaptureFile.load_json(path)
    assert frames == []
    assert header.description == ""


# ── 自动格式识别 ─────────────────────────────────────────────────

def test_save_and_load_dispatch_by_suffix(tmp_path):
    """save/load 按扩展名分派：.json → JSON，其它 → 二进制."""
    frames = _sample_frames()

    json_path = tmp_path / "a.json"
    CaptureFile.save(json_path, frames, created=1.0)
    assert json.loads(json_path.read_text(encoding="utf-8"))["format"] == "iec104-capture"
    _, from_json = CaptureFile.load(json_path)
    assert len(from_json) == 2

    bin_path = tmp_path / "a.i104"
    CaptureFile.save(bin_path, frames, created=1.0)
    assert bin_path.read_bytes()[:4] == MAGIC
    _, from_bin = CaptureFile.load(bin_path)
    assert len(from_bin) == 2

    # 大写扩展名同样识别
    upper_path = tmp_path / "b.JSON"
    CaptureFile.save(upper_path, frames, created=1.0)
    _, from_upper = CaptureFile.load(upper_path)
    assert len(from_upper) == 2
