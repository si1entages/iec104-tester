"""主站周期总召唤回归测试.

真机实测：部分装置**从不自发上送遥测**（静默 70s 内零遥测帧），只有收到
总召唤时才回遥测数据 —— 这类装置只能靠周期总召刷新遥测值。
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


class _GiCountSlave:
    """假子站：应 STARTDT，并统计主站发来的总召唤(C_IC_NA_1, type=100)帧数."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.gi_count = 0

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
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
                        if (len(frame) == 6 and frame[2] & 1
                                and ((frame[2] >> 1) & 3) == 3):
                            writer.write(bytes.fromhex("68040b000000"))  # STARTDT CON
                            await writer.drain()
                        elif (len(frame) > 10 and not (frame[2] & 1)
                              and not (frame[3] & 1) and len(frame) > 6
                              and frame[6] == 100):
                            self.gi_count += 1
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


async def _run(gi_interval: float):
    fake = _GiCountSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
        gi_interval=gi_interval,
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state
        await asyncio.sleep(1.2)   # interval=0.3 → 应至少 3 次
        return fake.gi_count
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()


@pytest.mark.asyncio
async def test_periodic_gi_sends_repeated_calls():
    """gi_interval>0 时应周期自动发总召唤."""
    count = await _run(0.3)
    assert count >= 3, f"周期总召次数={count}（期望 ≥3）"


@pytest.mark.asyncio
async def test_periodic_gi_disabled_by_default():
    """gi_interval=0 时不自动总召（对照组）."""
    count = await _run(0.0)
    assert count == 0, f"未配置周期总召时不应发总召，实测 {count} 次"
