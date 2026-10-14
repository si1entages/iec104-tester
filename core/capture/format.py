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
    def decode_from(cls, data: bytes, offset: int = 0) -> tuple[FrameEntry | None, int]:
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


# ═══════════════════════════════════════════════════════════════════
#  pcap / pcapng 导出（供 Wireshark 打开）
# ═══════════════════════════════════════════════════════════════════
#
# ⚠️ 诚实性声明（必读）：.i104 / .json 录制保存的是**裸 APDU 字节流**，不含真实的
# 链路层 / IP / TCP 头。而 Wireshark 的 IEC 60870-5-104 解析器**依赖 TCP 上下文**
# （端口 2404 或 IP/TCP 头）才能识别。为使导出文件能被 Wireshark **原生识别**，
# 本模块默认在每条报文前**合成**一个以太网 + IPv4 + TCP 头（目的端口固定 2404）。
#
# 这些头是**伪造的、非真实网络层信息**：
#   * 源/目的 IP 恒为 TEST-NET-1 文档用地址段 192.0.2.0/24；
#   * 端口、序号、MAC 均为合成值，**与真实抓包的拓扑/时序无关**；
#   * 仅 APDU 载荷（TCP payload）是真实录制内容。
# 因此**不得**据此推断真实网络行为。若需保留原始 APDU（不做任何合成），
# 使用 ``raw=True`` → LINKTYPE_USER0，Wireshark 需手工 "Decode As" 或用外部工具解析。
#
# 方向约定（使 Wireshark 把两侧归入同一条 TCP 会话）：
#   TX（主站→子站）：src=192.0.2.1:40000 → dst=192.0.2.2:2404
#   RX（主站←子站）：src=192.0.2.2:2404  → dst=192.0.2.1:40000

LINKTYPE_ETHERNET = 1
LINKTYPE_USER0 = 147          # 裸载荷（无链路层/IP/TCP 头）

SYNTH_MASTER_IP = "192.0.2.1"  # TEST-NET-1，文档用地址（合成，非真实）
SYNTH_SLAVE_IP = "192.0.2.2"
SYNTH_MASTER_PORT = 40000
SYNTH_SLAVE_PORT = 2404        # IEC 104 标准端口（合成）

_MAC_MASTER = bytes.fromhex("020000000001")
_MAC_SLAVE = bytes.fromhex("020000000002")

PCAP_MAGIC_US = 0xA1B2C3D4     # 经典 pcap 魔数（微秒时间戳）
PCAP_SNAPLEN = 65535


def _ip_bytes(dotted: str) -> bytes:
    return bytes(int(x) for x in dotted.split("."))


def _checksum(data: bytes) -> int:
    """16 位反码校验和（RFC 1071）."""
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        total += (data[i] << 8) | data[i + 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def _synth_packet(payload: bytes, is_tx: bool, ident: int = 0) -> bytes:
    """合成以太网 + IPv4 + TCP 头并拼上 APDU 载荷.

    ``is_tx=True`` 表示主站→子站方向，否则为子站→主站。
    详见模块内「诚实性声明」——合成头非真实网络信息。
    """
    src_ip_s, dst_ip_s = (SYNTH_MASTER_IP, SYNTH_SLAVE_IP) if is_tx \
        else (SYNTH_SLAVE_IP, SYNTH_MASTER_IP)
    src_port, dst_port = (SYNTH_MASTER_PORT, SYNTH_SLAVE_PORT) if is_tx \
        else (SYNTH_SLAVE_PORT, SYNTH_MASTER_PORT)
    src_mac, dst_mac = (_MAC_MASTER, _MAC_SLAVE) if is_tx else (_MAC_SLAVE, _MAC_MASTER)
    src_ip, dst_ip = _ip_bytes(src_ip_s), _ip_bytes(dst_ip_s)

    eth = dst_mac + src_mac + b"\x08\x00"           # EtherType IPv4

    tcp_len = 20 + len(payload)
    ip_total = 20 + tcp_len
    ip_hdr = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0x00, ip_total,
        ident & 0xFFFF, 0x4000,                      # flags=DF
        64, 6, 0,                                    # ttl=64, proto=TCP, csum=0(占位)
        src_ip, dst_ip,
    )
    ip_csum = _checksum(ip_hdr)
    ip_hdr = ip_hdr[:10] + struct.pack("!H", ip_csum) + ip_hdr[12:]

    tcp_hdr = struct.pack(
        "!HHIIBBHHH",
        src_port, dst_port,
        ident & 0xFFFFFFFF, 0,                       # seq / ack（合成值）
        0x50, 0x18, 65535, 0, 0,                     # data offset=5, PSH|ACK, window, csum, urg
    )
    pseudo = src_ip + dst_ip + struct.pack("!BBH", 0, 6, tcp_len)
    tcp_csum = _checksum(pseudo + tcp_hdr + payload)
    tcp_hdr = tcp_hdr[:16] + struct.pack("!H", tcp_csum) + tcp_hdr[18:]

    return eth + ip_hdr + tcp_hdr + payload


def _extract_synth_packet(pkt: bytes) -> tuple[bytes, int]:
    """从合成的以太网帧中取出 (APDU 载荷, TCP 源端口).

    仅用于回读自身导出的文件；对真实抓包不做保证。
    """
    if len(pkt) < 14:
        return pkt, 0
    ihl = (pkt[14] & 0x0F) * 4 if len(pkt) > 14 else 20
    ip_off = 14
    tcp_off = ip_off + ihl
    if len(pkt) < tcp_off + 20:
        return pkt, 0
    src_port = struct.unpack_from("!H", pkt, tcp_off)[0]
    doff = ((pkt[tcp_off + 12] >> 4) & 0x0F) * 4
    payload = pkt[tcp_off + doff:]
    return payload, src_port


def _decode_packet(pkt: bytes, linktype: int) -> tuple[bytes, int]:
    """按 linktype 解出 (APDU 载荷, 方向常量)."""
    if linktype == LINKTYPE_USER0:
        return pkt, DIRECTION_RX
    payload, src_port = _extract_synth_packet(pkt)
    # 合成约定：src=slave:2404 为 RX（主站收到），否则为 TX（主站发出）
    direction = DIRECTION_RX if src_port == SYNTH_SLAVE_PORT else DIRECTION_TX
    return payload, direction


def _frame_abs_time(frame: FrameEntry, created: float) -> float:
    """取帧的绝对（Unix）时间：优先 absolute_time，否则 created + 相对时间."""
    if frame.absolute_time:
        return frame.absolute_time
    return (created or 0.0) + frame.timestamp


def _pcapng_block(btype: int, body: bytes) -> bytes:
    total = 8 + len(body) + 4
    pad = (4 - len(body) % 4) % 4
    return struct.pack("<II", btype, total) + body + b"\x00" * pad + \
        struct.pack("<I", total)


def _pcapng_shb() -> bytes:
    body = struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
    return _pcapng_block(0x0A0D0D0A, body)


def _pcapng_idb(linktype: int) -> bytes:
    body = struct.pack("<HHI", linktype, 0, PCAP_SNAPLEN)
    body += struct.pack("<HH", 0, 0)                 # opt_endofopt
    return _pcapng_block(1, body)


def _pcapng_epb(iface_id: int, ts_us: int, data: bytes) -> bytes:
    pad = (4 - len(data) % 4) % 4
    body = struct.pack(
        "<IIIII", iface_id,
        (ts_us >> 32) & 0xFFFFFFFF, ts_us & 0xFFFFFFFF,
        len(data), len(data),
    ) + data + b"\x00" * pad
    body += struct.pack("<HH", 0, 0)                 # opt_endofopt
    return _pcapng_block(6, body)


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
        with open(path, encoding="utf-8") as f:
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

    # ── pcap / pcapng（Wireshark 可打开）───────────────────────────

    @staticmethod
    def save_pcap(
        path: str | Path,
        frames: list[FrameEntry],
        description: str = "",
        created: float = 0.0,
        *,
        raw: bool = False,
    ) -> int:
        """导出为经典 pcap（.pcap）.

        ``raw=False``（默认）**合成**以太网/IP/TCP 头（目的端口 2404），使 Wireshark
        能原生识别为 IEC 60870-5-104；``raw=True`` 使用 LINKTYPE_USER0 直接放裸
        APDU（Wireshark 需手工 Decode As）。**合成头非真实网络信息**，详见模块内
        「诚实性声明」。

        Returns:
            导出的帧数。
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if created == 0.0 and frames:
            created = _frame_abs_time(frames[0], 0.0)
        linktype = LINKTYPE_USER0 if raw else LINKTYPE_ETHERNET

        with open(path, "wb") as f:
            f.write(struct.pack("<IHHiIII", PCAP_MAGIC_US, 2, 4, 0, 0,
                                PCAP_SNAPLEN, linktype))
            for i, frame in enumerate(frames):
                data = frame.frame_data if raw else \
                    _synth_packet(frame.frame_data, frame.direction == DIRECTION_TX, i)
                abs_t = _frame_abs_time(frame, created)
                sec = int(abs_t)
                usec = int(round((abs_t - sec) * 1_000_000))
                if usec >= 1_000_000:
                    sec += 1
                    usec -= 1_000_000
                f.write(struct.pack("<IIII", sec, usec, len(data), len(data)))
                f.write(data)
        return len(frames)

    @staticmethod
    def load_pcap(path: str | Path) -> tuple[FileHeader, list[FrameEntry]]:
        """回读 pcap（支持 LE/BE、µs/ns 时间戳；载荷按 linktype 还原）."""
        data = Path(path).read_bytes()
        if len(data) < 24:
            raise ValueError("pcap too small")
        magic = data[0:4]
        if magic == b"\xd4\xc3\xb2\xa1":
            endian, scale = "<", 1_000_000
        elif magic == b"\xa1\xb2\xc3\xd4":
            endian, scale = ">", 1_000_000
        elif magic == b"\x4d\x3c\xb2\xa1":
            endian, scale = "<", 1_000_000_000
        elif magic == b"\xa1\xb2\x3c\x4d":
            endian, scale = ">", 1_000_000_000
        else:
            raise ValueError(f"Invalid pcap magic: {magic!r}")

        linktype = struct.unpack_from(endian + "I", data, 20)[0]
        offset = 24
        frames: list[FrameEntry] = []
        abs_times: list[float] = []
        while offset + 16 <= len(data):
            sec, frac, incl, _orig = struct.unpack_from(endian + "IIII", data, offset)
            offset += 16
            if incl > len(data) - offset:
                break
            pkt = data[offset:offset + incl]
            offset += incl
            payload, direction = _decode_packet(pkt, linktype)
            abs_t = sec + frac / scale
            frames.append(FrameEntry(timestamp=0.0, direction=direction,
                                     frame_data=payload, absolute_time=abs_t))
            abs_times.append(abs_t)

        created = min(abs_times) if abs_times else time.time()
        for fr in frames:
            fr.timestamp = fr.absolute_time - created
        return FileHeader(created=created, description=""), frames

    @staticmethod
    def save_pcapng(
        path: str | Path,
        frames: list[FrameEntry],
        description: str = "",
        created: float = 0.0,
        *,
        raw: bool = False,
    ) -> int:
        """导出为 pcapng（.pcapng，EPB 结构，µs 时间戳，4 字节对齐）.

        与 :meth:`save_pcap` 相同的合成头约定与 ``raw`` 语义。
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if created == 0.0 and frames:
            created = _frame_abs_time(frames[0], 0.0)
        linktype = LINKTYPE_USER0 if raw else LINKTYPE_ETHERNET

        out = bytearray()
        out += _pcapng_shb()
        out += _pcapng_idb(linktype)
        for i, frame in enumerate(frames):
            data = frame.frame_data if raw else \
                _synth_packet(frame.frame_data, frame.direction == DIRECTION_TX, i)
            abs_t = _frame_abs_time(frame, created)
            out += _pcapng_epb(0, int(round(abs_t * 1_000_000)), data)
        path.write_bytes(bytes(out))
        return len(frames)

    @staticmethod
    def load_pcapng(path: str | Path) -> tuple[FileHeader, list[FrameEntry]]:
        """回读 pcapng（解析 SHB/IDB/EPB，载荷按 linktype 还原）."""
        data = Path(path).read_bytes()
        offset = 0
        endian = "<"
        linktype = LINKTYPE_ETHERNET
        frames: list[FrameEntry] = []
        abs_times: list[float] = []
        while offset + 12 <= len(data):
            btype, blen = struct.unpack_from(endian + "II", data, offset)
            if btype == 0x0A0D0D0A:
                bom = struct.unpack_from("<I", data, offset + 8)[0]
                endian = "<" if bom == 0x1A2B3C4D else ">"
                btype, blen = struct.unpack_from(endian + "II", data, offset)
            if blen < 12 or offset + blen > len(data):
                break
            if btype == 1:                       # IDB
                linktype = struct.unpack_from(endian + "H", data, offset + 8)[0]
            elif btype == 6:                     # EPB
                (_iface, ts_high, ts_low, caplen, _origlen) = struct.unpack_from(
                    endian + "IIIII", data, offset + 8)
                pkt = data[offset + 28:offset + 28 + caplen]
                abs_t = ((ts_high << 32) | ts_low) / 1_000_000
                payload, direction = _decode_packet(pkt, linktype)
                frames.append(FrameEntry(timestamp=0.0, direction=direction,
                                         frame_data=payload, absolute_time=abs_t))
                abs_times.append(abs_t)
            offset += blen

        created = min(abs_times) if abs_times else time.time()
        for fr in frames:
            fr.timestamp = fr.absolute_time - created
        return FileHeader(created=created, description=""), frames

    @staticmethod
    def load(path: str | Path) -> tuple[FileHeader, list[FrameEntry]]:
        """自动识别格式并加载."""
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            return CaptureFile.load_json(path)
        if suffix == ".pcap":
            return CaptureFile.load_pcap(path)
        if suffix in (".pcapng", ".ntar"):
            return CaptureFile.load_pcapng(path)
        return CaptureFile.load_binary(path)

    @staticmethod
    def save(
        path: str | Path,
        frames: list[FrameEntry],
        description: str = "",
        created: float = 0.0,
        *,
        raw: bool = False,
    ) -> None:
        """根据扩展名自动选择格式保存（.i104/.json/.pcap/.pcapng）.

        ``raw`` 仅对 pcap/pcapng 生效：True 时导出裸 APDU（LINKTYPE_USER0），
        否则**合成**以太网/IP/TCP 头以便 Wireshark 原生识别（见模块诚实性声明）。
        """
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            CaptureFile.save_json(path, frames, description, created)
        elif suffix == ".pcap":
            CaptureFile.save_pcap(path, frames, description, created, raw=raw)
        elif suffix in (".pcapng", ".ntar"):
            CaptureFile.save_pcapng(path, frames, description, created, raw=raw)
        else:
            CaptureFile.save_binary(path, frames, description, created)
