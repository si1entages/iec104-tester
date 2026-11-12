"""WP3c 主站上传方向（主站 → 子站）测试.

按 2026-11-12 新口径：本仓 master↔slave 真实 TCP 互测即可验收。
覆盖：上传 API 单测、真实 TCP 端到端落盘 + F_AF 确认、CHS 错误拒绝、
REST `/api/master/file` upload 分支参数校验。
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.protocol.file_transfer import (
    FileTransferMaster,
    FileTransferState,
    section_checksum,
)
from webui.bridge import EngineBridge
from webui.server import create_app

# ── 管理器级 ──────────────────────────────────────────────────────────


class TestUploadManager:
    def test_start_upload_emits_select_segments_lasts(self):
        sent: list[bytes] = []
        m = FileTransferMaster(1)
        m.set_callbacks(on_send_asdu=lambda d: sent.append(d))
        payload = b"UPLOAD-DATA" * 30  # 330 B → 2 段（200+130）
        m.start_upload(0, 7, payload, segment_size=200)

        tids = [f[0] for f in sent]
        assert tids[0] == 0x7A          # F_SC 选择文件
        assert tids.count(0x7D) == 2    # F_SG 两段（TypeID 125=0x7D）
        assert tids[-1] == 0x7B         # F_LS 最后的节
        assert m.state == FileTransferState.LAST_SECTION
        assert m.context.data == payload

    def test_upload_chs_is_over_whole_payload(self):
        sent: list[bytes] = []
        m = FileTransferMaster(1)
        m.set_callbacks(on_send_asdu=lambda d: sent.append(d))
        payload = bytes(range(256))
        m.start_upload(0, 1, payload, segment_size=64)
        ls = [f for f in sent if f[0] == 0x7B][-1]
        # ASDU: TypeID(0) VSQ(1) COT(2..3) CA(4..5) IOA(6..8) NOF(9..10) NOS(11) LSQ(12) CHS(13)
        assert ls[12] == 1  # LSQ_FILE_TRANSFER_WITHOUT_DEACT
        assert ls[13] == section_checksum(payload)

    def test_empty_upload_rejected(self):
        m = FileTransferMaster(1)
        with pytest.raises(ValueError, match="不能为空"):
            m.start_upload(0, 1, b"")

    def test_upload_ack_completes(self):
        from core.protocol.types import AckFileSection

        m = FileTransferMaster(1)
        m.set_callbacks(on_send_asdu=lambda _d: None)
        m.start_upload(0, 1, b"abc")
        assert m.handle_upload_ack(AckFileSection(
            file_name=1, section_name=1, qualifier=1)) is True
        assert m.state == FileTransferState.COMPLETED

        m2 = FileTransferMaster(1)
        m2.set_callbacks(on_send_asdu=lambda _d: None)
        m2.start_upload(0, 1, b"abc")
        assert m2.handle_upload_ack(AckFileSection(
            file_name=1, section_name=1, qualifier=2)) is False
        assert m2.state == FileTransferState.ERROR


# ── 真实 TCP 端到端 ───────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait(pred, timeout: float = 12.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return True
        await asyncio.sleep(interval)
    return pred()


@pytest.mark.asyncio
async def test_upload_over_real_tcp():
    """主站发、子站收：文件逐字节落盘 + F_AF 肯定 + 主站 COMPLETED."""
    port = _free_port()
    pt = PointTable()
    pt.generate_demo_points(yx_count=4, yc_count=2)
    pt.common_addr = 1
    payload = b"IEC104-UPLOAD-" * 40  # 560 B → 3 段

    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)
    await slave.start()
    try:
        await master.start()
        assert await _wait(lambda: master.is_running and slave.client_count > 0)

        await master.upload_file(0, 42, payload, segment_size=200)
        assert await _wait(
            lambda: slave._file_transfer._file_data.get(42) == payload,
            timeout=12), "子站未收到上传文件"

        # 子站回 F_AF 后主站管理器收到确认（走 handle_ack → COMPLETED）
        assert await _wait(
            lambda: master._file_transfer.state == FileTransferState.COMPLETED,
            timeout=8)
        assert slave._file_transfer._file_data[42] == payload
    finally:
        await master.stop()
        await slave.stop()


# ── REST 端点 ─────────────────────────────────────────────────────────


class TestUploadEndpoint:
    async def _client(self, tmp_path: Path):
        from core.data.audit import AuditStore
        from webui.audit import AuditService

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None,
                         data_dir=tmp_path)
        store = AuditStore(tmp_path / "a.db")
        store.open()
        b.audit = AuditService(store)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_upload_validation(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/master/file", json={"action": "upload"})
            assert r.status == 200 and (await r.json())["ok"] is False
            r = await c.post("/api/master/file",
                             json={"action": "upload", "data": "zz"})
            body = await r.json()
            assert body["ok"] is False and "data 非法 hex" in body["error"]
            r = await c.post("/api/master/file",
                             json={"action": "upload", "data": ""})
            assert (await r.json())["ok"] is False
            r = await c.post("/api/master/file",
                             json={"action": "upload", "data": "00" * 70000})
            assert (await r.json())["ok"] is False
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_upload_no_engine_returns_error(self, tmp_path: Path):
        """未连接引擎时 upload 应返回可读业务错误，不 500."""
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/master/file",
                             json={"action": "upload", "data": "01020304"})
            assert r.status == 200
            assert (await r.json())["ok"] is False
        await b.shutdown()
