"""端到端文件上传测试: 主站请求 → 子站发送 → 主站接收完成.

验证 IEC 60870-5-104 文件传输握手闭环:
  主站 F_SC(请求) → 子站 F_FR → 主站 F_FR_NB(ack)
  → 子站 F_SR → 主站 F_SR_NB(ack)
  → 子站 F_SG(段) → 子站 F_LS(最后的节)
  → 主站 COMPLETED + 触发 _on_file_received + 回复 F_AF
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import PointTable
from core.engine.master import MasterEngine, MasterEvent
from core.engine.slave import SlaveEngine
from core.protocol.file_transfer import FileTransferState


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_point_table() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=2)
    pt.common_addr = 1
    pt.station_name = "FTP"
    return pt


async def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


@pytest.mark.asyncio
async def test_file_transfer_upload_completes():
    """完整上传流程应达到 COMPLETED 并触发 _on_file_received."""
    port = _free_port()
    points = _demo_point_table()

    file_name = 1
    payload = b"HELLO-IEC104-FILE-TRANSFER!" * 4  # 112 字节 → 单段

    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave._file_transfer.set_file_data(file_name, payload)

    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
    )

    received: list[tuple[MasterEvent, dict]] = []
    master.set_event_callback(lambda e, d: received.append((e, d)))

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_until(
                lambda: master.is_running or str(master.state).lower() == "running",
                timeout=8,
            )
            assert ok, f"master not running, state={master.state}"
            ok = await _wait_until(lambda: slave.client_count > 0, timeout=5)
            assert ok, "slave got no clients"

            # 主站请求文件（上传: 子站 → 主站）
            await master.request_file(0, file_name)

            ok = await _wait_until(
                lambda: any(d.get("type_id") == "file" for _, d in received),
                timeout=8,
            )
            assert ok, (
                f"file not received; state={master.file_transfer_state}, "
                f"events={[e.value for e, _ in received]}"
            )

            files = [d for _, d in received if d.get("type_id") == "file"]
            assert files[0]["file_name"] == file_name
            assert files[0]["data"] == payload
            assert master.file_transfer_state == FileTransferState.COMPLETED

            # 子站应在收到 F_AF 后也进入 COMPLETED
            ok = await _wait_until(
                lambda: slave._file_transfer.state == FileTransferState.COMPLETED,
                timeout=5,
            )
            assert ok, f"slave file transfer state={slave._file_transfer.state}"
        finally:
            try:
                await asyncio.wait_for(master.stop(), timeout=5)
            except Exception:
                pass
    finally:
        try:
            await asyncio.wait_for(slave.stop(), timeout=5)
        except Exception:
            pass
