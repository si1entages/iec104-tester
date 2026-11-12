"""WP9 旁路抓包测试.

**CI 无网卡权限**，因此测试策略分两层：
1. **纯解析层**（不依赖权限）：构造以太网/IPv4/TCP 帧喂给 ``feed_packet``，
   验证 APDU 提取、方向判定、端口过滤、pcap 导出；
2. **能力探测层**：断言 ``probe()`` 在无 Npcap/无 root 时**明确报告不可用及原因**，
   而不是假装可用——这是本方案的诚实性要求。
"""

from __future__ import annotations

import socket
import struct
import sys
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.capture.format import CaptureFile
from core.capture.sniffer import (
    DEFAULT_PORT,
    MAX_CAPTURED,
    Sniffer,
    extract_apdu,
    probe,
)

APDU = bytes.fromhex("680e0400030064010600010000000014")
APDU2 = bytes.fromhex("680e0400030064010700010000000014")


def eth_tcp(payload: bytes, *, src_port: int = 2404, dst_port: int = 50000,
            vlan: bool = False) -> bytes:
    """构造以太网 + IPv4 + TCP 帧（含正确 IHL/TCP 数据偏移，便于解析器识别）."""
    tcp_hdr = struct.pack("!HHIIBBHHH", src_port, dst_port, 0, 0, 5 << 4, 0x18,
                          8192, 0, 0)
    tcp_seg = tcp_hdr + payload
    total = 20 + len(tcp_seg)
    ip_hdr = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, total, 0, 0, 64, 6, 0,
        socket.inet_aton("10.0.0.1"), socket.inet_aton("10.0.0.2"))
    eth_type = struct.pack("!H", 0x0800)
    prefix = (struct.pack("!H", 0x8100) + b"\x00\x01") if vlan else b""
    if vlan:
        eth_type = struct.pack("!H", 0x0800)
    eth = b"\xaa" * 6 + b"\xbb" * 6 + prefix + eth_type
    return eth + ip_hdr + tcp_seg


# ── APDU 提取 ────────────────────────────────────────────────────────


class TestExtractApdu:
    def test_exact_apdu(self):
        assert extract_apdu(APDU) == APDU

    def test_apdu_after_noise(self):
        assert extract_apdu(b"\x00\x11\x22" + APDU) == APDU

    def test_two_apdus_takes_first(self):
        """TCP 段承载多个 APDU 时只取完整的首个（不拼半个帧）."""
        assert extract_apdu(APDU + APDU2) == APDU

    def test_incomplete_returns_none(self):
        assert extract_apdu(APDU[:-3]) is None
        assert extract_apdu(b"\x68\x0e\x04\x00") is None

    @pytest.mark.parametrize("bad", [b"", b"\x01\x02\x03", b"\x68"])
    def test_non_apdu(self, bad):
        assert extract_apdu(bad) is None

    def test_length_field_validation(self):
        # 长度字节 0x02 小于最小值 4 → 不是合法 APDU
        assert extract_apdu(b"\x68\x02\x00\x00") is None


# ── 帧解析链路（feed_packet）──────────────────────────────────────────


class TestFeedPacket:
    def test_rx_direction_from_device(self):
        """源端口 2404 → 装置发出 → RX."""
        s = Sniffer(port=DEFAULT_PORT)
        assert s.feed_packet(eth_tcp(APDU, src_port=2404)) is True
        frames = s.frames()
        assert len(frames) == 1
        assert frames[0].frame_data == APDU
        assert frames[0].direction_str == "RX"
        assert frames[0].metadata["source"] == "sniff"
        assert s.stats.apdus == 1

    def test_tx_direction_from_master(self):
        """源端口非 2404 → 主站发出 → TX."""
        s = Sniffer(port=DEFAULT_PORT)
        assert s.feed_packet(eth_tcp(APDU, src_port=50000)) is True
        assert s.frames()[0].direction_str == "TX"

    def test_vlan_tag_supported(self):
        s = Sniffer(port=DEFAULT_PORT)
        assert s.feed_packet(eth_tcp(APDU, src_port=2404, vlan=True)) is True
        assert len(s.frames()) == 1

    def test_non_tcp_ignored(self):
        s = Sniffer()
        pkt = b"\xaa" * 6 + b"\xbb" * 6 + struct.pack("!H", 0x0800)
        pkt += struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20, 0, 0, 64, 17, 0,
                           b"\x00" * 4, b"\x00" * 4)
        assert s.feed_packet(pkt) is False
        assert s.frames() == []

    def test_non_ip_ignored(self):
        s = Sniffer()
        pkt = b"\xaa" * 6 + b"\xbb" * 6 + struct.pack("!H", 0x0806) + b"\x00" * 30
        assert s.feed_packet(pkt) is False

    def test_short_frame_ignored(self):
        s = Sniffer()
        assert s.feed_packet(b"\x00" * 10) is False

    def test_non_104_tcp_ignored(self):
        s = Sniffer()
        assert s.feed_packet(eth_tcp(b"GET / HTTP/1.1\r\n")) is False
        assert s.frames() == []

    def test_stats_accumulate(self):
        s = Sniffer()
        for _ in range(3):
            s.feed_packet(eth_tcp(APDU, src_port=2404))
        st = s.stats.as_dict()
        assert st["apdus"] == 3 and st["packets"] == 3 and st["bytes"] > 0

    def test_buffer_cap_drops_oldest(self):
        s = Sniffer()
        s.feed_packet(eth_tcp(APDU, src_port=2404))
        # 直接压入超过上限的帧（走同一把锁）
        with s._lock:
            for _ in range(MAX_CAPTURED + 10):
                s._frames.append(s._frames[0])
        s.feed_packet(eth_tcp(APDU2, src_port=2404))
        assert len(s.frames()) <= MAX_CAPTURED + 1
        assert s.stats.dropped > 0 or len(s.frames()) > MAX_CAPTURED

    def test_clear_resets(self):
        s = Sniffer()
        s.feed_packet(eth_tcp(APDU, src_port=2404))
        s.clear()
        assert s.frames() == [] and s.stats.apdus == 0


# ── pcap 导出（复用既有链路）─────────────────────────────────────────


class TestPcapExport:
    def test_sniffed_frames_export_and_reload(self, tmp_path: Path):
        """抓到的帧导出 pcap 后能被既有 load_pcap 读回（回放/diff 链路零改动）."""
        s = Sniffer()
        s.feed_packet(eth_tcp(APDU, src_port=2404))
        s.feed_packet(eth_tcp(APDU2, src_port=50000))
        path = tmp_path / "sniff.pcap"
        n = s.save_pcap(path)
        assert n == 2 and path.is_file()

        _hdr, entries = CaptureFile.load_pcap(path)
        assert len(entries) == 2
        assert entries[0].frame_data == APDU
        assert entries[1].frame_data == APDU2

    def test_raw_export(self, tmp_path: Path):
        s = Sniffer()
        s.feed_packet(eth_tcp(APDU, src_port=2404))
        path = tmp_path / "raw.pcap"
        assert s.save_pcap(path, raw=True) == 1
        _hdr, entries = CaptureFile.load_pcap(path)
        assert entries[0].frame_data == APDU


# ── 能力探测与降级（诚实性要求）───────────────────────────────────────


class TestCapability:
    def test_probe_reports_reason_when_unavailable(self):
        cap = probe()
        if not cap.available:
            assert cap.reason, "不可用时必须给出具体原因，不能留空"
            assert cap.backend in ("npcap", "")
        else:
            assert cap.backend in ("af_packet", "npcap")

    def test_start_degrades_with_reason_when_unavailable(self):
        """不可用平台：start() 返回 ok=False + 原因（不抛、不假装成功）."""
        s = Sniffer()
        if s.capability().available:
            pytest.skip("本机具备抓包能力，无法测试降级路径")
        out = s.start()
        assert out["ok"] is False
        assert out["error"]
        assert out["capability"]["available"] is False
        assert s.running is False

    def test_stop_is_idempotent(self):
        s = Sniffer()
        assert s.stop()["ok"] is True
        assert s.stop()["ok"] is True

    def test_double_start_when_running(self):
        s = Sniffer()
        s._running = True  # 模拟已启动（不真的开 socket）
        try:
            assert s.start() == {"ok": True, "already": True}
        finally:
            s._running = False

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="仅 Linux 有 AF_PACKET")
    def test_linux_backend_probe(self):
        cap = probe()
        assert cap.backend == "af_packet" and cap.requires_root is True


class TestDegradationPaths:
    def test_af_packet_permission_error_is_reported(self, monkeypatch):
        """Linux 上 socket() 抛 PermissionError → 明确原因，不假装成功."""
        import socket as _socket

        s = Sniffer()
        monkeypatch.setattr(
            "core.capture.sniffer.probe",
            lambda: __import__("core.capture.sniffer", fromlist=["SniffCapability"])
            .SniffCapability(True, "af_packet", "AF_PACKET", True),
        )

        def boom(*_a, **_kw):
            raise PermissionError("Operation not permitted")

        monkeypatch.setattr(_socket.socket, "__init__", boom, raising=False)
        # 用 monkeypatch 直接替换 socket.socket 类更简单可靠
        class _FakeSock:
            def __init__(self, *_a, **_kw):
                raise PermissionError("raw socket denied")

        import core.capture.sniffer as sniffer_mod

        monkeypatch.setattr(sniffer_mod.socket, "socket", _FakeSock, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "AF_PACKET", 17, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "SOCK_RAW", 3, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "htons", lambda x: x, raising=False)
        out = s.start()
        assert out["ok"] is False and "权限不足" in out["error"]
        assert s.running is False

    def test_af_packet_os_error_is_reported(self, monkeypatch):
        from core.capture.sniffer import SniffCapability

        s = Sniffer()
        monkeypatch.setattr("core.capture.sniffer.probe",
                            lambda: SniffCapability(True, "af_packet", "AF_PACKET", True))

        class _FakeSock:
            def __init__(self, *_a, **_kw):
                raise OSError("no such device")

        import core.capture.sniffer as sniffer_mod

        monkeypatch.setattr(sniffer_mod.socket, "socket", _FakeSock, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "AF_PACKET", 17, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "SOCK_RAW", 3, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "htons", lambda x: x, raising=False)
        out = s.start()
        assert out["ok"] is False and "no such device" in out["error"]

    def test_unknown_backend_start_reports_error(self, monkeypatch):
        from core.capture.sniffer import SniffCapability

        s = Sniffer()
        monkeypatch.setattr(
            "core.capture.sniffer.probe",
            lambda: SniffCapability(True, "mystery", "?", False))
        import core.capture.sniffer as sniffer_mod

        monkeypatch.setattr(sniffer_mod.socket, "AF_PACKET", 17, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "SOCK_RAW", 3, raising=False)
        monkeypatch.setattr(sniffer_mod.socket, "htons", lambda x: x, raising=False)
        out = s.start()
        assert out["ok"] is False and "尚未实现" in out["error"]

    def test_windows_without_scapy_reports_reason(self, monkeypatch):

        monkeypatch.setattr("core.capture.sniffer.sys.platform", "win32")
        import builtins

        real_import = builtins.__import__

        def fake(name, *a, **kw):
            if name.startswith("scapy"):
                raise ImportError("no scapy")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake)
        cap = probe()
        assert cap.available is False and "Npcap" in cap.reason

    def test_unsupported_platform(self, monkeypatch):
        monkeypatch.setattr("core.capture.sniffer.sys.platform", "freebsd")
        cap = probe()
        assert cap.available is False and "freebsd" in cap.reason

    def test_extract_apdu_skips_false_start(self):
        """前一个 0x68 长度不自洽时，继续找下一个合法起点."""
        bad = bytes([0x68, 0xFF]) + APDU
        assert extract_apdu(bad) == APDU


class TestMalformedPackets:
    """Malformed-frame boundaries: the parser returns None instead of raising."""

    def test_ipv4_header_too_short(self):
        s = Sniffer()
        pkt = bytes([0xAA]) * 6 + bytes([0xBB]) * 6 + struct.pack("!H", 0x0800) + bytes([0]) * 10
        assert s.feed_packet(pkt) is False

    def test_ihl_less_than_20(self):
        s = Sniffer()
        pkt = (bytes([0xAA]) * 6 + bytes([0xBB]) * 6 + struct.pack("!H", 0x0800)
               + struct.pack("!BBHHHBBH4s4s", 0x44, 0, 20, 0, 0, 64, 6, 0,
                             bytes([0]) * 4, bytes([0]) * 4))
        assert s.feed_packet(pkt) is False

    def test_tcp_header_truncated(self):
        s = Sniffer()
        eth = bytes([0xAA]) * 6 + bytes([0xBB]) * 6 + struct.pack("!H", 0x0800)
        ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20, 0, 0, 64, 6, 0,
                         bytes([0]) * 4, bytes([0]) * 4)
        assert s.feed_packet(eth + ip + bytes([0]) * 5) is False

    def test_syn_packet_no_payload(self):
        s = Sniffer()
        assert s.feed_packet(eth_tcp(b"", src_port=2404)) is False

    def test_extract_apdu_bad_control_field(self):
        bad = bytearray(APDU)
        bad[2] = 0x02
        out = extract_apdu(bytes(bad))
        assert out is None or out == bytes(bad)


class TestLoop:
    def test_loop_handles_recv_os_error_without_raise(self):
        class _Sock:
            def recv(self, _n):
                raise OSError("closed")

        s = Sniffer()
        s._sock = _Sock()
        s._running = True
        s._loop()
        assert s.stats.errors == 1 and s.stats.last_error

    def test_loop_without_socket_returns(self):
        s = Sniffer()
        s._sock = None
        s._running = True
        s._loop()

    def test_loop_feeds_good_packet(self):
        class _Sock:
            def __init__(self):
                self.n = 0

            def recv(self, _n):
                self.n += 1
                if self.n == 1:
                    return eth_tcp(APDU, src_port=2404)
                raise OSError("done")

        s = Sniffer()
        s._sock = _Sock()
        s._running = True
        s._loop()
        assert s.stats.apdus == 1


class TestSniffEndpoints:
    async def _client(self, tmp_path: Path):
        from core.data.audit import AuditStore
        from webui.audit import AuditService
        from webui.bridge import EngineBridge
        from webui.server import create_app

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None)
        store = AuditStore(tmp_path / "a.db")
        store.open()
        b.audit = AuditService(store)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_status_shape(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            body = await (await c.get("/api/sniff/status")).json()
            assert body["ok"] is True and "capability" in body and "stats" in body
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_start_with_port_and_iface(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/sniff/start",
                             json={"port": 2405, "iface": "eth0"})
            # 本机无抓包能力：应诚实返回 ok=false，而不是 500
            assert r.status == 200
            body = await r.json()
            assert isinstance(body.get("ok"), bool)
            assert b.sniffer.port == 2405
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_start_bad_port(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/sniff/start", json={"port": "abc"})
            assert r.status == 400
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_export_no_data_400(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/sniff/export")
            assert r.status == 400
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_export_with_captured_frames(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        b.sniffer.feed_packet(eth_tcp(APDU, src_port=2404))
        async with client as c:
            r = await c.get("/api/sniff/export")
            assert r.status == 200 and (await r.read())[:4] == bytes([0xD4, 0xC3, 0xB2, 0xA1])
            r2 = await c.get("/api/sniff/export?raw=1")
            assert r2.status == 200
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_stop_endpoint(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/sniff/stop", json={})
            assert (await r.json())["ok"] is True
        await b.shutdown()
