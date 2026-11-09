"""连接医生（T94）测试：分层自检的真连接验证.

三个场景：① 对本仓子站（标准实现）四层全绿、对端按标准确认；
② 对「回数据但从不确认」的对端（simulator4 形态）→ 诊断必须点出对端不确认；
③ 对无人监听的端口 → TCP 层失败 + 人话结论。
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


@pytest.mark.asyncio
async def test_doctor_full_pass_against_own_slave():
    """对本仓子站：TCP/STARTDT/数据流全绿，且识别出对端按标准确认."""
    port = _free_port()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1)
    await slave.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        assert report.to_dict()["steps"][0]["ok"] is True
        keys = [s.key for s in report.steps]
        assert keys == ["tcp", "startdt", "dataflow"]
        assert all(s.ok for s in report.steps), [s.detail for s in report.steps]
        dataflow = report.steps[-1]
        assert dataflow.evidence["i_frames"] > 0
        # 子站按标准确认（响应 I 帧 N(R) 推进）→ 结论应是「全部通过」
        assert "全部通过" in report.conclusion
        assert report.ok is True
    finally:
        await asyncio.wait_for(slave.stop(), timeout=6)


class _SilentAckPeer:
    """simulator4 形态假对端：应 STARTDT CON，回数据但 N(R) 恒 0（从不确认）."""

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
                        if frame[2] == 0x07:  # STARTDT ACT
                            writer.write(bytes([0x68, 0x04, U_STARTDT_CON, 0, 0, 0]))
                            await writer.drain()
                        elif frame[2] & 0x01 == 0:
                            # 收到 I 帧（总召唤）：回响应但 N(R)=0（不确认我方）
                            body = frame[6:]
                            if len(body) >= 10 and body[0] == 100:
                                for cot in (7, 10):
                                    asdu = bytes([100, 1, cot, 0, 1, 0, 0, 0, 0, 20])
                                    apci = APCICodec.encode_i(vs, 0, asdu)
                                    writer.write(apci)
                                    await writer.drain()
                                    vs += 1
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
    """对「回数据但 N(R) 恒 0」的对端（simulator4 形态）：诊断必须给出对端不确认结论."""
    peer = _SilentAckPeer()
    port = await peer.start()
    try:
        report = await run_doctor("127.0.0.1", port, observe_seconds=1.0)
        assert report.steps[-1].evidence["i_frames"] > 0
        assert report.steps[-1].evidence["peer_n_r_advanced"] is False
        assert "对端从不确认我方 I 帧" in report.conclusion
        assert "对端实现缺陷" in report.conclusion
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
