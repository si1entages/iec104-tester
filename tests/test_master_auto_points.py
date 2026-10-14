"""主站点位自学习（按报文解析结果自动补充定义表）回归测试.

真机实测：设备的遥测在 IOA 16385+（0x4001 起），本地定义表没有这些点位，
值虽进了实时库但界面不显示 —— 主站应把数据帧中出现、定义表缺失的 IOA
自动补进定义表（遥信/遥测/遥脉）。
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import YcType, YxType
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


class _DataSlave:
    """假子站：应 STARTDT，随后推一帧归一化遥测 + 一帧双点遥信（定义表外 IOA）."""

    def __init__(self) -> None:
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                sent = False
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
                            if not sent:
                                sent = True
                                await asyncio.sleep(0.05)
                                # M_ME_NA_1: type=9 vsq=1 cot=3 ca=1,
                                # IOA=16385(0x4001), NVA=0x0050(80 → 80/32767), 品质=0
                                writer.write(bytes.fromhex(
                                    "681000000000090103000100014000500000"))
                                # M_DP_NA_1: type=3 vsq=1 cot=3 ca=1,
                                # IOA=3000(0x0BB8), 双点=2；tx_seq=1（第二帧）
                                writer.write(bytes.fromhex(
                                    "680e02000200030103000100b80b0002"))
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
async def test_auto_add_points_from_parsed_frames():
    """收到定义表外的遥测/遥信帧后，定义表应自动补点且实时值可读."""
    fake = _DataSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
        auto_add_points=True,
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state

        # 遥测：IOA 16385 自动补点，值 = 80/32767 ≈ 0.00244
        # （注意谓词要容忍 point_table 尚未创建的阶段，否则异常直接冒泡）
        assert await _wait_until(
            lambda: (master.point_table is not None
                     and master.point_table.get_yc(16385) is not None),
            timeout=8,
        ), "遥测 IOA 16385 未被自动补进定义表"
        yc = master.point_table.get_yc(16385)
        assert yc.name == "遥测16385"
        assert yc.data_type == YcType.NORMALIZED

        # 遥信（双点）：IOA 3000 自动补点
        assert await _wait_until(
            lambda: (master.point_table is not None
                     and master.point_table.get_yx(3000) is not None),
            timeout=8,
        ), "遥信 IOA 3000 未被自动补进定义表"
        assert master.point_table.get_yx(3000).point_type == YxType.DOUBLE

        # 实时库能读到值
        data = master.data_store.get_yc(16385)
        assert data is not None
        assert abs(data.value - 80 / 32767) < 1e-6
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()


@pytest.mark.asyncio
async def test_auto_add_points_disabled():
    """auto_add_points=False 时不自动补点（对照组）."""
    fake = _DataSlave()
    port = await fake.start()
    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
        auto_add_points=False,
    )
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running, timeout=8), master.state
        await asyncio.sleep(0.8)
        table = master.point_table
        assert table is None or table.get_yc(16385) is None, "关闭自学习后不应补点"
    finally:
        try:
            await asyncio.wait_for(master.stop(), timeout=6)
        except Exception:
            pass
        await fake.stop()
