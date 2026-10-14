"""pcap / pcapng 导出结构与往返测试（T23）.

不依赖 Wireshark：自行解析回读，校验文件结构、合成头正确性与往返一致性。
"""

import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.capture.format import (
    DIRECTION_RX,
    DIRECTION_TX,
    LINKTYPE_ETHERNET,
    LINKTYPE_USER0,
    SYNTH_MASTER_IP,
    SYNTH_MASTER_PORT,
    SYNTH_SLAVE_IP,
    SYNTH_SLAVE_PORT,
    CaptureFile,
    FrameEntry,
)
from core.protocol.apci import APCICodec

ROOT = Path(__file__).parent.parent


def _frames() -> list[FrameEntry]:
    return [
        FrameEntry(timestamp=0.0, direction=DIRECTION_TX,
                   frame_data=APCICodec.startdt_act(),
                   absolute_time=1730000000.123456),
        FrameEntry(timestamp=0.5, direction=DIRECTION_RX,
                   frame_data=APCICodec.startdt_con(),
                   absolute_time=1730000000.623456),
        FrameEntry(timestamp=1.25, direction=DIRECTION_TX,
                   frame_data=APCICodec.testfr_act(),
                   absolute_time=1730000001.373456),
    ]


def _parse_pcap(data: bytes) -> tuple[int, list[tuple[int, int, bytes]]]:
    """返回 (linktype, [(sec, usec, packet), ...])（仅支持本模块写出的 LE µs 格式）."""
    magic = struct.unpack_from("<I", data, 0)[0]
    assert magic == 0xA1B2C3D4
    linktype = struct.unpack_from("<I", data, 20)[0]
    offset, out = 24, []
    while offset + 16 <= len(data):
        sec, usec, incl, orig = struct.unpack_from("<IIII", data, offset)
        offset += 16
        pkt = data[offset:offset + incl]
        offset += incl
        out.append((sec, usec, pkt))
        assert incl == orig
    return linktype, out


def _ip_checksum_ok(pkt: bytes) -> bool:
    """校验合成 IPv4 头校验和有效（重算应为 0）."""
    ihl = (pkt[14] & 0x0F) * 4
    ip = pkt[14:14 + ihl]

    def csum(b: bytes) -> int:
        if len(b) % 2:
            b += b"\x00"
        total = sum((b[i] << 8) | b[i + 1] for i in range(0, len(b), 2))
        while total >> 16:
            total = (total & 0xFFFF) + (total >> 16)
        return (~total) & 0xFFFF

    return csum(ip) == 0


# ── 合成头常量（诚实性）─────────────────────────────────────────

def test_synthetic_constants_are_documentation_range():
    assert SYNTH_SLAVE_PORT == 2404
    assert SYNTH_MASTER_IP.startswith("192.0.2.")   # TEST-NET-1 文档用地址
    assert SYNTH_SLAVE_IP.startswith("192.0.2.")
    assert SYNTH_MASTER_PORT != SYNTH_SLAVE_PORT


# ── 经典 pcap ────────────────────────────────────────────────────

class TestPcap:
    def test_roundtrip(self, tmp_path):
        frames = _frames()
        p = tmp_path / "s.pcap"
        assert CaptureFile.save_pcap(p, frames) == 3
        header, back = CaptureFile.load_pcap(p)
        assert len(back) == 3
        assert header.created == pytest.approx(frames[0].absolute_time, abs=1e-6)
        for a, b in zip(frames, back, strict=True):
            assert b.frame_data == a.frame_data
            assert b.direction == a.direction
            assert b.absolute_time == pytest.approx(a.absolute_time, abs=1e-6)
        # 时间戳单调（顺序一致）
        assert [f.absolute_time for f in back] == sorted(f.absolute_time for f in back)

    def test_global_header_and_synthetic_headers(self, tmp_path):
        frames = _frames()
        p = tmp_path / "s.pcap"
        CaptureFile.save_pcap(p, frames)
        linktype, records = _parse_pcap(p.read_bytes())
        assert linktype == LINKTYPE_ETHERNET
        assert len(records) == 3

        for frame, (sec, usec, pkt) in zip(frames, records, strict=True):
            apdu = frame.frame_data
            # 以太网 + IPv4 + TCP + APDU
            assert len(pkt) == 14 + 20 + 20 + len(apdu)
            assert pkt[12:14] == b"\x08\x00"                 # IPv4
            assert pkt[14] >> 4 == 4                          # version 4
            assert pkt[23] == 6                               # proto TCP
            assert _ip_checksum_ok(pkt)
            src_port, dst_port = struct.unpack_from("!HH", pkt, 34)
            if frame.direction == DIRECTION_TX:
                assert (src_port, dst_port) == (SYNTH_MASTER_PORT, SYNTH_SLAVE_PORT)
            else:
                assert (src_port, dst_port) == (SYNTH_SLAVE_PORT, SYNTH_MASTER_PORT)
            assert pkt[14 + 20 + 20:] == apdu                 # 载荷为真实 APDU
            # 时间戳与绝对时间一致（µs）
            assert sec == int(frame.absolute_time)
            assert usec == pytest.approx(
                round((frame.absolute_time - sec) * 1e6), abs=1)

    def test_raw_mode_linktype(self, tmp_path):
        p = tmp_path / "raw.pcap"
        CaptureFile.save_pcap(p, _frames(), raw=True)
        linktype, records = _parse_pcap(p.read_bytes())
        assert linktype == LINKTYPE_USER0
        for frame, (_s, _u, pkt) in zip(_frames(), records, strict=True):
            assert pkt == frame.frame_data   # 无合成头，裸 APDU

    def test_empty(self, tmp_path):
        p = tmp_path / "empty.pcap"
        assert CaptureFile.save_pcap(p, []) == 0
        _h, back = CaptureFile.load_pcap(p)
        assert back == []

    def test_save_dispatch_by_extension(self, tmp_path):
        p = tmp_path / "auto.pcap"
        CaptureFile.save(p, _frames())
        assert p.read_bytes()[:4] == b"\xd4\xc3\xb2\xa1"   # pcap 魔数（LE µs）
        _h, back = CaptureFile.load(p)
        assert len(back) == 3


# ── pcapng ───────────────────────────────────────────────────────

def _iter_blocks(data: bytes):
    """产出 (block_type, block_body)。校验首尾长度一致且 4 字节对齐."""
    offset = 0
    while offset + 12 <= len(data):
        btype, blen = struct.unpack_from("<II", data, offset)
        assert blen % 4 == 0, "块长度须为 4 的倍数"
        assert offset + blen <= len(data)
        tail = struct.unpack_from("<I", data, offset + blen - 4)[0]
        assert tail == blen, "块首尾长度不一致"
        yield btype, data[offset + 8:offset + blen - 4]
        offset += blen


class TestPcapng:
    def test_block_structure(self, tmp_path):
        frames = _frames()
        p = tmp_path / "s.pcapng"
        assert CaptureFile.save_pcapng(p, frames) == 3
        blocks = list(_iter_blocks(p.read_bytes()))

        assert blocks[0][0] == 0x0A0D0D0A                       # SHB
        bom = struct.unpack_from("<I", blocks[0][1], 0)[0]
        assert bom == 0x1A2B3C4D

        idb = next(b for b in blocks if b[0] == 1)
        assert struct.unpack_from("<H", idb[1], 0)[0] == LINKTYPE_ETHERNET

        epbs = [b for b in blocks if b[0] == 6]
        assert len(epbs) == 3
        for frame, (_btype, body) in zip(frames, epbs, strict=True):
            iface, ts_high, ts_low, caplen, origlen = struct.unpack_from("<IIIII", body, 0)
            assert iface == 0 and caplen == origlen
            assert ((ts_high << 32) | ts_low) / 1e6 == pytest.approx(
                frame.absolute_time, abs=1e-6)
            pkt = body[20:20 + caplen]
            assert pkt[14 + 20 + 20:] == frame.frame_data        # TCP 载荷 = APDU

    def test_roundtrip(self, tmp_path):
        frames = _frames()
        p = tmp_path / "s.pcapng"
        CaptureFile.save_pcapng(p, frames)
        header, back = CaptureFile.load_pcapng(p)
        assert len(back) == 3
        assert header.created == pytest.approx(frames[0].absolute_time, abs=1e-6)
        for a, b in zip(frames, back, strict=True):
            assert b.frame_data == a.frame_data
            assert b.direction == a.direction
            assert b.absolute_time == pytest.approx(a.absolute_time, abs=1e-6)

    def test_raw_mode_roundtrip(self, tmp_path):
        frames = _frames()
        p = tmp_path / "raw.pcapng"
        CaptureFile.save_pcapng(p, frames, raw=True)
        blocks = list(_iter_blocks(p.read_bytes()))
        assert struct.unpack_from("<H", next(b for b in blocks if b[0] == 1)[1], 0)[0] \
            == LINKTYPE_USER0
        _h, back = CaptureFile.load_pcapng(p)
        assert [f.frame_data for f in back] == [f.frame_data for f in frames]

    def test_empty(self, tmp_path):
        p = tmp_path / "empty.pcapng"
        assert CaptureFile.save_pcapng(p, []) == 0
        _h, back = CaptureFile.load_pcapng(p)
        assert back == []


# ── 与 .i104 互转 + CLI ──────────────────────────────────────────

def test_i104_to_pcap_keeps_bytes_and_time(tmp_path):
    frames = _frames()
    src = tmp_path / "s.i104"
    CaptureFile.save_binary(src, frames, created=frames[0].absolute_time)
    header, loaded = CaptureFile.load_binary(src)
    out = tmp_path / "s.pcap"
    CaptureFile.save_pcap(out, loaded, created=header.created)
    _h, back = CaptureFile.load_pcap(out)
    assert [f.frame_data for f in back] == [f.frame_data for f in frames]


def test_cli_convert_to_pcap(tmp_path):
    src = tmp_path / "cli.i104"
    CaptureFile.save_binary(src, _frames(), created=_frames()[0].absolute_time)
    out = tmp_path / "cli.pcap"
    r = subprocess.run(
        [sys.executable, str(ROOT / "capture_tool.py"), "convert", str(src), "-o", str(out)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert out.is_file()
    assert "合成" in r.stdout          # CLI 明确标注合成头
    _h, back = CaptureFile.load_pcap(out)
    assert len(back) == 3


def test_recorder_sets_absolute_time():
    from core.capture import PacketRecorder

    rec = PacketRecorder()
    rec.start(description="t", format="binary")
    rec.record_frame(APCICodec.startdt_act(), direction="tx")
    with rec._lock:
        entry = rec._buffer[-1]
    rec.stop()
    assert entry.absolute_time > 0
