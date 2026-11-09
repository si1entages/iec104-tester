"""连接医生（T94）测试：分层自检的真连接验证.

场景：① 对本仓子站（标准实现）四层全绿、对端按标准确认；
② 对「回数据但从不确认」的对端 → 诊断点出对端不确认；
③ 对无人监听的端口 → TCP 层失败 + 人话结论；④ 无数据对端 → 周期召唤建议；
⑤ 自发流含可疑 COT/S 帧坏帧/超短 ASDU → 证据正确采集。
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.engine.doctor import run_doctor
from core.engine.slave import SlaveEngine
from core.protocol.apci import APCICodec
from core.protocol.constants import U_STARTDT_CON


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _startdt_con() -> bytes:
    return bytes([0x68, 0x04, U_STARTDT_CON, 0x00, 0x00, 0x00])


def _s_frame(vr: int) -> bytes:
    return bytes([0x68, 0x04, 0x01, 0x00, (vr << 1) & 0xFF, ((vr << 1) >> 8) & 0xFF])


@pytest.mark.asyncio
async def test_doctor_full_pass_against_own_slave():
    """对本仓子站：TCP/STARTDT/数据流全绿，且识别出对端按标准确认."""
    port = _free_port()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1)
    await slave.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        assert [s.key for s in report.steps] == ["tcp", "startdt", "dataflow"]
        assert all(s.ok for s in report.steps), [s.detail for s in report.steps]
        dataflow = report.steps[-1]
        assert dataflow.evidence["i_frames"] > 0
        # 子站按标准确认（响应 I 帧 N(R) 推进）→ 结论应是「全部通过」
        assert "全部通过" in report.conclusion
        assert report.ok is True
    finally:
        await asyncio.wait_for(slave.stop(), timeout=6)


class _AckByIFramePeer:
    """回数据但 N(R) 恒 0 的假对端（从不确认我方 I 帧）."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.vs = 0

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    i = 0
                    while i + 2 <= len(data):
                        if data[i] != 0x68:
                            i += 1
                            continue
                        length = data[i + 1]
                        frame = data[i:i + 2 + length]
                        if len(frame) < 6:
                            break
                        if frame[2] == 0x07:  # STARTDT ACT
                            writer.write(_startdt_con())
                            await writer.drain()
                        elif frame[2] & 0x01 == 0:  # I 帧（总召唤）：回响应但 N(R)=0
                            body = frame[6:]
                            if len(body) >= 10 and body[0] == 100:
                                for cot in (7, 10):
                                    asdu = bytes([100, 1, cot, 0, 1, 0, 0, 0, 0, 20])
                                    writer.write(APCICodec.encode_i(self.vs, 0, asdu))
                                    await writer.drain()
                                    self.vs += 1
                        i += 2 + length
            except Exception:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.mark.asyncio
async def test_doctor_flags_peer_that_never_acks():
    """对「回数据但 N(R) 恒 0」的对端：诊断必须给出对端不确认结论."""
    peer = _AckByIFramePeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        assert report.steps[-1].evidence["i_frames"] > 0
        assert report.steps[-1].evidence["peer_n_r_advanced"] is False
        assert "对端从不确认我方 I 帧" in report.conclusion
        assert "对端实现缺陷" in report.conclusion
    finally:
        await peer.stop()


class _SilentPeer:
    """应 STARTDT CON 之后一言不发（装置只在周期召唤时上送的形态）."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    i = 0
                    while i + 2 <= len(data):
                        if data[i] == 0x68:
                            length = data[i + 1]
                            frame = data[i:i + 2 + length]
                            if len(frame) == 6 and frame[2] == 0x07:
                                writer.write(_startdt_con())
                                await writer.drain()
                            # I 帧一律不回应（连总召唤也不回）
                            i += 2 + length
                        else:
                            i += 1
            except Exception:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.mark.asyncio
async def test_doctor_reports_peer_without_any_data():
    """对端启动确认后完全无数据（含总召唤无响应）→ dataflow 失败 + 周期召唤建议."""
    peer = _SilentPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        assert [s.ok for s in report.steps] == [True, True, False]
        assert "没有发送任何数据" in report.conclusion
        assert report.ok is False
    finally:
        await peer.stop()


class _ChattyFlawedPeer:
    """覆盖面假对端：S 帧/坏帧/可疑 COT(47)/SQ=0 IOA/超短 ASDU/自发 7+ 帧."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                vs = 0
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    i = 0
                    while i + 2 <= len(data):
                        if data[i] != 0x68:
                            i += 1
                            continue
                        length = data[i + 1]
                        frame = data[i:i + 2 + length]
                        if len(frame) < 6:
                            break
                        if frame[2] == 0x07:  # STARTDT ACT → CON + 一波自发帧
                            writer.write(_startdt_con())
                            await writer.drain()
                            for k in range(7):
                                ioa = 100 + k
                                asdu = bytes([13, 1, 3, 0, 1, 0,
                                              ioa & 0xFF, (ioa >> 8) & 0xFF, 0,
                                              0, 0, 0, 0])
                                writer.write(APCICodec.encode_i(vs, 0, asdu))
                                await writer.drain()
                                vs += 1
                            # 可疑 COT=47 的 I 帧（保留 COT）
                            suspect = bytes([13, 1, 47, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0])
                            writer.write(APCICodec.encode_i(vs, 0, suspect))
                            await writer.drain()
                            vs += 1
                            # 超短 ASDU（len<6 → 解码跳过）
                            writer.write(APCICodec.encode_i(vs, 0, bytes([13, 1])))
                            await writer.drain()
                            vs += 1
                            # 坏帧（APCI 非法 → 解码 ValueError → 重同步）
                            writer.write(bytes([0x68, 0x04, 0xFF, 0xFF, 0xFF, 0xFF]))
                            await writer.drain()
                            # S 帧（确认我方）
                            writer.write(_s_frame(1))
                            await writer.drain()
                        i += 2 + length
            except Exception:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.mark.asyncio
async def test_doctor_observes_suspect_cots_and_peer_s_frames():
    """自发流含可疑 COT 与 S 帧：dataflow 证据正确采集."""
    peer = _ChattyFlawedPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        ev = report.steps[-1].evidence
        assert ev["i_frames"] >= 8
        assert ev["peer_s_frames"] >= 1
        assert ev["suspect_cots"] >= 1
        assert 13 in [int(k) for k in ev["types"]]
        assert ev["ioa_samples"], "SQ=0 IOA 样例应被采集"
    finally:
        await peer.stop()


@pytest.mark.asyncio
async def test_doctor_reports_unreachable_port():
    """无人监听的端口：TCP 层失败 + 人话结论，不抛异常."""
    port = _free_port()  # 已关闭，无人监听
    report = await run_doctor("127.0.0.1", port, observe_seconds=0.5, connect_timeout=2.0)
    assert report.steps[0].key == "tcp"
    assert report.steps[0].ok is False
    assert "TCP" in report.conclusion
    assert len(report.steps) == 1  # TCP 失败即止，不继续上层


class _ReconnectingEchoPeer:
    """STARTDT CON + 回显 I 帧 + 对方 S 帧（覆盖 S 帧/坏帧/N(R) 推进/短 ASDU 分支）.

    与 _ChattyFlawedPeer 的差异：回显我方 GI（N(R) 推进 → 全通过结论）、
    发 S 帧、发 U 帧（非 I 非 S → 226 行 continue）。
    """

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                vs = 0
                vr = 0
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    i = 0
                    while i + 2 <= len(data):
                        if data[i] != 0x68:
                            i += 1
                            continue
                        length = data[i + 1]
                        frame = data[i:i + 2 + length]
                        if len(frame) < 6:
                            break
                        if frame[2] == 0x07:  # STARTDT ACT → CON
                            writer.write(_startdt_con())
                            await writer.drain()
                        elif frame[2] & 0x01 == 0:  # I 帧：回显（N(R)=1 确认我方）
                            vr += 1
                            echo = bytes([0x68]) + bytes([frame[1]]) +                                 bytes([(vs << 1) & 0xFF, ((vs << 1) >> 8) & 0xFF,
                                       (vr << 1) & 0xFF, ((vr << 1) >> 8) & 0xFF])
                            writer.write(echo + frame[6:])
                            await writer.drain()
                            vs += 1
                            # 发 S 帧 + U 帧（TESTFR ACT）覆盖分类分支
                            writer.write(_s_frame(0))
                            await writer.drain()
                            writer.write(bytes([0x68, 0x04, 0x43, 0x00, 0x00, 0x00]))
                            await writer.drain()
                        i += 2 + length
            except Exception:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.mark.asyncio
async def test_doctor_echo_peer_full_conclusion():
    """回显对端（N(R) 推进 + S 帧 + U 帧）：结论为全部通过且证据齐全."""
    peer = _ReconnectingEchoPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        assert all(s.ok for s in report.steps)
        assert "全部通过" in report.conclusion
        ev = report.steps[-1].evidence
        assert ev["i_frames"] >= 1
    finally:
        await peer.stop()


class _SilentEvenToStartdtPeer:
    """接受连接但对 STARTDT 也一言不发（启动超时路径）."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    if not await reader.read(4096):
                        break
            except Exception:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


class _RstOnStartdtPeer:
    """接受连接后立刻关闭（STARTDT 发送失败 → ConnectionResetError 路径）."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            # SO_LINGER(timeout=0) → 关闭时发 RST（而非 FIN）：主站侧 send 才会真报错
            import struct as _struct

            sock = writer.get_extra_info('socket')
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                            _struct.pack('ii', 1, 0))
            writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


class _GarbageDuringStartdtPeer:
    """对 STARTDT 回一堆坏帧（解码 ValueError → continue）后回 CON."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    i = 0
                    while i + 2 <= len(data):
                        if data[i] == 0x68:
                            length = data[i + 1]
                            frame = data[i:i + 2 + length]
                            if len(frame) == 6 and frame[2] == 0x07:
                                # 坏帧：asdu_length=1 → APCICodec.decode 抛 ValueError
                                writer.write(bytes([0x68, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00]))
                                await writer.drain()
                                writer.write(_startdt_con())
                                await writer.drain()
                            i += 2 + length
                        else:
                            i += 1
            except Exception:
                pass
            finally:
                writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.mark.asyncio
async def test_doctor_startdt_timeout_path(monkeypatch):
    """对端对 STARTDT 无响应：startdt 层失败 + 早期返回（194/199-200/114）."""
    peer = _SilentEvenToStartdtPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=0.5,
                                  startdt_timeout=1.0)
        assert [s.ok for s in report.steps] == [True, False]
        assert "未在超时内确认 STARTDT" in report.steps[1].detail
        assert report.ok is False
    finally:
        await peer.stop()


@pytest.mark.asyncio
async def test_doctor_startdt_reset_path():
    """对端接受连接后立即断开：STARTDT 发送失败（188-189）。"""
    peer = _RstOnStartdtPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=0.5,
                                  startdt_timeout=1.0)
        assert report.steps[0].ok is True   # TCP 已建立
        assert report.steps[1].ok is False  # STARTDT 失败
    finally:
        await peer.stop()


@pytest.mark.asyncio
async def test_doctor_garbage_frames_during_startdt():
    """对端回坏帧（ValueError → continue）后回 CON：诊断不受影响（182-183）."""
    peer = _GarbageDuringStartdtPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=0.5,
                                  startdt_timeout=2.0)
        assert report.steps[1].ok is True
    finally:
        await peer.stop()


@pytest.mark.asyncio
async def test_doctor_tcp_error_branches(monkeypatch):
    """TCP 层异常分支：ConnectionRefusedError（155）与 OSError（160-161）."""

    async def refused(host, port):
        raise ConnectionRefusedError("refused")

    async def oserror(host, port):
        raise OSError("some os error")

    monkeypatch.setattr("core.engine.doctor.asyncio.open_connection", refused)
    report = await run_doctor("127.0.0.1", 2404, observe_seconds=0.5, connect_timeout=1.0)
    assert "没有服务在监听" in report.steps[0].detail

    monkeypatch.setattr("core.engine.doctor.asyncio.open_connection", oserror)
    report2 = await run_doctor("127.0.0.1", 2404, observe_seconds=0.5, connect_timeout=1.0)
    assert "TCP 连接失败" in report2.steps[0].detail


@pytest.mark.asyncio
async def test_doctor_report_to_dict_shape(monkeypatch):
    """to_dict 形状（53）与尾部 close 异常吞噬（293-294）——用 mock 连接走全流程."""

    class _FakeReader:
        def __init__(self) -> None:
            self.sent = 0

        async def read(self, n: int) -> bytes:
            self.sent += 1
            if self.sent == 1:
                return _startdt_con()
            return b""

    class _FakeWriter:
        def __init__(self) -> None:
            self.closed = False

        def write(self, data: bytes) -> None:
            pass

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            raise OSError("mock close failure")

        def get_extra_info(self, name: str):  # noqa: ARG002
            return None

    async def fake_open(host, port):
        return _FakeReader(), _FakeWriter()

    monkeypatch.setattr("core.engine.doctor.asyncio.open_connection", fake_open)
    report = await run_doctor("127.0.0.1", 2404, observe_seconds=0.5)
    d = report.to_dict()
    assert d["ok"] is False  # 无数据
    assert [s["key"] for s in d["steps"]] == ["tcp", "startdt", "dataflow"]
    assert isinstance(d["duration_ms"], int)
