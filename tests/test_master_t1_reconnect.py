"""主站 t1 超时后的自动重连回归测试.

真机实测缺陷：读命令发到设备不认识的 IOA → 设备不回 ACK → t1 超时断开 →
主站**永久停在 Stopped**（`_on_timer_expired` 用了 `client.stop()`，把重连循环
也一起取消了）。正确做法是 `disconnect()` 仅重建连接、保留重连循环。

本测试用"假子站"精确复现：只应 STARTDT CON，**忽略一切 I 帧**（不回 ACK）。
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


class _SilentSlave:
    """假子站：应 STARTDT CON，忽略一切 I 帧（不回 ACK、不发 S 帧）."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.startdt_count = 0

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(256)
                    if not data:
                        break
                    # 逐帧扫描 U 帧（STARTDT ACT：控制域首字节 bit0=1 且 bits1-2=11）
                    i = 0
                    while i + 6 <= len(data):
                        if data[i] == 0x68:
                            length = data[i + 1]
                            frame = data[i:i + 2 + length]
                            if (len(frame) == 6 and frame[2] & 1
                                    and ((frame[2] >> 1) & 3) == 3):
                                self.startdt_count += 1
                                writer.write(bytes.fromhex("68040b000000"))  # STARTDT CON
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


class _AckByIFrameSlave:
    """假子站：应 STARTDT CON；收到 I 帧后**用 I 帧的 N(R) 隐式确认**（不发 S 帧）.

    对应真机联调发现的缺陷（2026-11-10，simulator4）：主站只把 S 帧当确认，
    I 帧 N(R) 的隐式确认不停 t1 —— 对「用 N(R) 确认、少发 S 帧」的设备，
    每发一条命令都会 t1 超时断链。
    """

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None
        self.startdt_count = 0
        self.i_frame_count = 0

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(256)
                    if not data:
                        break
                    i = 0
                    while i + 6 <= len(data):
                        if data[i] == 0x68:
                            length = data[i + 1]
                            frame = data[i:i + 2 + length]
                            if len(frame) == 6 and frame[2] & 1 and ((frame[2] >> 1) & 3) == 3:
                                self.startdt_count += 1
                                writer.write(bytes.fromhex("68040b000000"))  # STARTDT CON
                                await writer.drain()
                            elif len(frame) > 6 and (frame[2] & 1) == 0:
                                # I 帧：以 N(R)=1 隐式确认（VS=0, VR=1），
                                # ASDU = M_SP_NA_1(1) ×1, COT=3, CA=1, IOA=1, 值 ON
                                asdu = bytes.fromhex("010103000100" + "010000" + "01")
                                vs = self.i_frame_count
                                vr = 1
                                ctrl = bytes([
                                    (vs << 1) & 0xFF, ((vs << 1) >> 8) & 0xFF,
                                    (vr << 1) & 0xFF, ((vr << 1) >> 8) & 0xFF,
                                ])
                                body = ctrl + asdu
                                writer.write(bytes([0x68, len(body)]) + body)
                                await writer.drain()
                                self.i_frame_count += 1
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
async def test_i_frame_implicit_ack_stops_t1():
    """I 帧携带的 N(R) 必须和 S 帧一样停掉 t1.

    假子站只回「VS=0, VR=1 的 I 帧」（隐式确认），从不发 S 帧：
    主站发命令后 t1 不得超时 —— 连接保持、STARTDT 只发生一次。
    """
    fake = _AckByIFrameSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=True, reconnect_interval=0.5,
        t1=0.5,  # 若隐式确认未停 t1，命令后 0.5s 即超时断链
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state

        await master.clock_sync()  # I 帧：等确认
        await asyncio.sleep(1.5)   # 远超 t1(0.5s)：确认应已通过 N(R) 到达

        assert fake.startdt_count == 1, (
            f"隐式确认未停 t1（STARTDT 次数={fake.startdt_count}，发生了重连）"
        )
        assert master.is_running, f"连接未保持（state={master.state}）"
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()


@pytest.mark.asyncio
async def test_t1_timeout_reconnects_and_recovers_running():
    """t1 超时断开后，reconnect=True 的主站必须自动重连并恢复 Running（而非永久 Stopped）."""
    fake = _SilentSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=True, reconnect_interval=0.5,
        t1=0.5,  # 加速超时
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state

        # 发一条设备必然不回 ACK 的 I 帧（真机场景：未知 IOA 的读命令）。
        # 发送本身不报错（首帧窗口空闲），但 t1 超时后连接会被断开。
        await master.clock_sync()

        # t1(0.5s) 超时 → 断开 → **自动重连** → 再次 STARTDT → 恢复 Running。
        # 以 STARTDT 次数 ≥2 作为重连证据（is_running 短暂离开可能被轮询错过）
        assert await _wait_until(lambda: fake.startdt_count >= 2, timeout=15), (
            f"t1 超时后未能自动重连（state={master.state}，"
            f"STARTDT 次数={fake.startdt_count}）"
        )
        assert await _wait_until(lambda: master.is_running, timeout=10), (
            f"重连后未恢复 Running（state={master.state}）"
        )
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()
