"""主站收到初始化结束(M_EI_NA_1, COT=4)后自动重总召唤的回归测试.

标准语义（真机为准）：子站初始化结束（上电/重启）后原实时数据可能失效，
主站应重新总召唤。真机实测：装置上电后会主动发 `M_EI_NA_1 COT=4 限定词=0`
（当地电源合上）——此前主站只记日志、不重新召唤。
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.engine.master import MasterEngine


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


class _InitSlave:
    """假子站：应 STARTDT CON，随后发一帧 M_EI_NA_1(COT=4)，记录主站发来的 I 帧类型."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.master_types: list[int] = []

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                sent_ei = False
                while True:
                    data = await reader.read(256)
                    if not data:
                        break
                    i = 0
                    while i + 6 <= len(data):
                        if data[i] != 0x68:
                            i += 1
                            continue
                        length = data[i + 1]
                        frame = data[i:i + 2 + length]
                        if len(frame) == 6 and frame[2] & 1 and ((frame[2] >> 1) & 3) == 3:
                            # STARTDT ACT → CON
                            writer.write(bytes.fromhex("68040b000000"))
                            await writer.drain()
                            if not sent_ei:
                                sent_ei = True
                                await asyncio.sleep(0.1)
                                # M_EI_NA_1（照抄真机原始帧）: type=70 VSQ=1 COT=4
                                # CA=1 IOA=0 限定词=0(当地电源合上)
                                writer.write(bytes.fromhex(
                                    "680e0000000046010400010000000000"))
                                await writer.drain()
                        elif len(frame) > 10 and not (frame[2] & 1) and not (frame[3] & 1):
                            # 主站发来的 I 帧：记录 ASDU 类型
                            body = frame[6:]
                            if len(body) >= 1:
                                self.master_types.append(body[0])
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
async def test_end_of_initialization_triggers_re_gi():
    """收到 M_EI_NA_1(COT=4) 后，主站应自动发一条 C_IC_NA_1(type=100) 总召唤."""
    fake = _InitSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
        auto_gi_on_init_end=True,   # 显式开启（默认关闭，见 master.py 参数注释）
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state
        # 假子站在 STARTDT 后推 EI 帧；主站应自动重总召唤
        ok = await _wait_until(
            lambda: any(t == 100 for t in fake.master_types), timeout=8)
        assert ok, f"未收到自动重总召唤（主站发出的 ASDU 类型={fake.master_types}）"
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()


@pytest.mark.asyncio
async def test_end_of_initialization_no_gi_by_default():
    """默认（不开 auto_gi_on_init_end）收到 EI 不应自动发 GI —— 真机兼容性默认."""
    fake = _InitSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state
        # 假子站在 STARTDT 后即推 EI；等 2.5s 确认主站没有自动 GI
        await asyncio.sleep(2.5)
        assert not any(t == 100 for t in fake.master_types), (
            f"默认不应自动重总召唤（主站发出={fake.master_types}）"
        )
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()
