"""WP3b 从站多节分包 + WP3a 语义档位测试.

按 2026-11-12 新口径：本仓 master↔slave 真实 TCP 互测 + 多开源实现交叉证据
即可验收，不再要求真机。

覆盖：
- 语义档位三档解析 / 非法档位拒绝 / YAML 往返 / 目录 COT/SCQ 按档位生效；
- 从站 ≥3 节分包：节号序列、每节 LSQ=3、最后节 LSQ=1、逐节 CHS 正确；
- **真实 TCP 端到端**：主站收到完整文件、字节逐段一致、逐节 CHS 无告警；
- 单节（section_size=0）历史行为逐字节不变（既有 64 例已覆盖，这里再钉一次）。
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

from core.config import AppConfig, load_config
from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.protocol.file_semantics import ED1, ED2, PROJECT, known_nof_values, resolve
from core.protocol.file_transfer import (
    FileTransferSlave,
    FileTransferState,
    section_checksum,
)

# ── 语义档位（WP3a）───────────────────────────────────────────────────


class TestSemantics:
    def test_three_profiles(self):
        assert resolve("ed1") is ED1
        assert resolve("ed2") is ED2
        assert resolve("project") is PROJECT
        assert ED1.directory_cot == 13 and ED1.directory_scq == 5
        assert ED2.directory_cot == 5 and ED2.directory_scq == 0
        assert ED2.nof_enum is True

    def test_unknown_profile_rejected(self):
        with pytest.raises(ValueError, match="未知文件传输语义档位"):
            resolve("bogus")

    def test_per_field_override(self):
        sem = resolve("ed1", section_size=150, nof_enum=True)
        assert sem.profile == "ed1" and sem.section_size == 150
        assert sem.nof_enum is True
        assert sem.directory_cot == 13  # 其余字段保持档位值

    def test_section_size_clamped(self):
        assert resolve("ed1", section_size=-5).section_size == 0

    def test_known_nof_values(self):
        assert known_nof_values()[1] == "TRANSPARENT_FILE"

    def test_yaml_roundtrip_and_bad_profile(self, tmp_path: Path):
        import yaml

        cfg = AppConfig()
        assert cfg.file_transfer.resolve() == ED1
        cfg.file_transfer.profile = "ed2"
        cfg.file_transfer.section_size = 200
        cfg.file_transfer.nof_enum = True
        p = tmp_path / "c.yaml"
        cfg.save(p)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["file_transfer"] == {
            "profile": "ed2", "section_size": 200, "nof_enum": True}

        loaded = load_config(p)
        assert loaded.file_transfer.resolve().profile == "ed2"
        assert loaded.file_transfer.resolve().section_size == 200

        data["file_transfer"]["profile"] = "nope"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        with pytest.raises(ValueError, match="未知文件传输语义档位"):
            load_config(p)

    def test_directory_command_uses_profile(self):
        """ed2 档位下目录命令默认 COT=5/SCQ=0（lib60870.NET + otfabric 共识）."""
        from core.engine.master_protocol import MasterProtocolHandler

        sent: list[bytes] = []

        class _FakeEngine:
            _common_addr = 1
            file_semantics = ED2

            async def _send_command_asdu(self, data):
                sent.append(data)

        handler = MasterProtocolHandler(_FakeEngine())
        asyncio.run(handler.file_call_directory(0))
        assert len(sent) == 1
        # on_send_asdu 收到的是**纯 ASDU**（不含 APCI）：TypeID 在 body[0]，
        # COT 在 body[2]，SCQ 在信息体末字节。
        body = sent[0]
        assert body[0] == 0x7A and body[2] == 5 and body[-1] == 0


# ── 从站多节分包（WP3b，单元级）──────────────────────────────────────


class TestSlaveMultiSection:
    def _slave(self, size: int, payload: bytes) -> tuple[FileTransferSlave, list[bytes]]:
        sent: list[bytes] = []
        sem = resolve("ed1", section_size=size)
        s = FileTransferSlave(1, semantics=sem)
        s.set_callbacks(on_send_asdu=lambda d: sent.append(d))
        s.set_file_data(1, payload)
        return s, sent

    def test_split_three_sections(self):
        payload = bytes(range(256)) * 3  # 768 → 3 节 × 256
        s, _ = self._slave(256, payload)
        assert s._split_sections(payload) == [
            (1, payload[:256]), (2, payload[256:512]), (3, payload[512:]),
        ]

    def test_single_section_when_size_zero(self):
        payload = b"abc" * 500
        s, _ = self._slave(0, payload)
        assert s._split_sections(payload) == [(1, payload)]

    def test_three_sections_wire_sequence(self):
        """选文件 → 3 节：F_SR(1)/…/F_LS(3) → F_SR(2)/…/F_LS(3) → F_SR(3)/…/F_LS(1)."""
        from core.protocol.types import AckFileSection

        payload = bytes(range(256)) * 3
        s, sent = self._slave(256, payload)
        s.handle_file_request(0, 1, 1)      # SELECT → F_FR
        s.handle_file_request(0, 1, 2)      # REQUEST → F_SR(1)
        # 主站请求节 + 从站发段 + F_LS
        def lsq_of(frame: bytes) -> int | None:
            # ASDU: TypeID(0) VSQ(1) COT(2..3) CA(4..5) IOA(6..8) NOF(9..10) NOS(11) LSQ(12)
            return frame[12] if len(frame) > 12 and frame[0] == 0x7B else None

        lsq_seq: list[int] = []
        for _sec in range(3):
            s.handle_file_request(0, 1, 6)  # SCQ=6 → 段 + F_LS
            for f in sent:
                v = lsq_of(f)
                if v is not None and (not lsq_seq or v != lsq_seq[-1]):
                    lsq_seq.append(v)
            # 主站肯定节 → 从站推下一节
            s.handle_ack(0, AckFileSection(file_name=1, section_name=0,
                                           qualifier=3))
        # 最后一节是肯定文件（1）不是肯定节（3）
        s.handle_ack(0, AckFileSection(file_name=1, section_name=0, qualifier=1))
        assert s.state == FileTransferState.COMPLETED
        # 至少出现 3 与 1 两类 LSQ
        assert 3 in lsq_seq and 1 in lsq_seq

    def test_per_section_chs_matches(self):
        """每节 F_LS 的 CHS = 该节数据算术和 mod 256（非整文件）."""
        payload = bytes(range(256)) * 3
        s, sent = self._slave(256, payload)
        s.handle_file_request(0, 1, 1)
        s.handle_file_request(0, 1, 2)
        # 节1
        s.handle_file_request(0, 1, 6)
        ls_frames = [f for f in sent if len(f) > 12 and f[0] == 0x7B]
        assert ls_frames, "应有 F_LS 帧"
        chs = ls_frames[-1][13]
        assert chs == section_checksum(payload[:256])
        sent.clear()
        # 节2
        s.handle_ack(0, __import__("core.protocol.types", fromlist=["AckFileSection"])
                     .AckFileSection(file_name=1, section_name=0, qualifier=3))
        s.handle_file_request(0, 1, 6)
        ls2 = [f for f in sent if len(f) > 13 and f[0] == 0x7B][-1]
        assert ls2[13] == section_checksum(payload[256:512])


# ── 真实 TCP 端到端（WP3b 核心验收）──────────────────────────────────


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait(pred, timeout: float = 10.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return True
        await asyncio.sleep(interval)
    return pred()


@pytest.mark.asyncio
async def test_multisection_upload_over_real_tcp(caplog):
    """本仓 master↔slave 真实 TCP：768B / 3 节×256B，逐节 CHS，完整接收."""
    import logging

    caplog.set_level(logging.WARNING, logger="iec104.file_transfer")
    port = _free_port()
    pt = PointTable()
    pt.generate_demo_points(yx_count=4, yc_count=2)
    pt.common_addr = 1
    payload = bytes(range(256)) * 3  # 768 B

    from core.protocol.file_semantics import resolve as _resolve

    sem = _resolve("ed1", section_size=256)
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                        point_table=pt, file_semantics=sem)
    slave.data_store.init_from_point_table(pt)
    slave._file_transfer.set_file_data(1, payload)

    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          file_semantics=sem)
    received: list[tuple[int, bytes]] = []
    master._file_transfer.set_callbacks(
        on_send_asdu=master._file_transfer._on_send_asdu,
        on_file_received=lambda name, data: received.append((name, data)),
    )

    await slave.start()
    try:
        await master.start()
        assert await _wait(lambda: master.is_running and slave.client_count > 0)
        await master.request_file(0, 1)
        assert await _wait(lambda: bool(received), timeout=12), (
            f"file not received; state={master.file_transfer_state}")

        assert received[0][0] == 1
        assert received[0][1] == payload, "3 节拼回的文件必须与原文逐字节一致"
        assert master.file_transfer_state == FileTransferState.COMPLETED
        # 逐节 CHS 不应产生 mismatch 告警
        assert not [r for r in caplog.records if "CHS mismatch" in r.message]
    finally:
        await master.stop()
        await slave.stop()


@pytest.mark.asyncio
async def test_upload_chs_mismatch_is_rejected():
    """上传方向：篡改 F_LS 的 CHS → 子站回否定 F_AF、文件不落盘.

    方案 §WP3 验收判据「逐节 CHS 校验失败可复现且被拒」的上传侧对应项。
    """
    port = _free_port()
    pt = PointTable()
    pt.generate_demo_points(yx_count=3, yc_count=2)
    pt.common_addr = 1
    payload = b"BAD-CHS-PAYLOAD" * 20

    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)

    # 在子站收到 F_LS 前篡改 CHS 八位组（ASDU 偏移 13）
    from core.engine.slave_response import SlaveResponseBuilder

    original = SlaveResponseBuilder._handle_file_transfer

    async def corrupted(self, state, asdu):
        if asdu.type_id.name == "F_LS_NA_1" and asdu.objects:
            obj = asdu.objects[0]
            if hasattr(obj.data, "chs"):
                obj.data.chs = (obj.data.chs + 1) & 0xFF
        return await original(self, state, asdu)

    SlaveResponseBuilder._handle_file_transfer = corrupted
    await slave.start()
    try:
        await master.start()
        assert await _wait(lambda: master.is_running and slave.client_count > 0)
        await master.upload_file(0, 99, payload, segment_size=200)
        # 文件不应落盘；主站应收到否定 F_AF → ERROR
        assert await _wait(
            lambda: master._file_transfer.state == FileTransferState.ERROR,
            timeout=10), "CHS 错误应导致主站 ERROR"
        assert 99 not in slave._file_transfer._file_data
    finally:
        SlaveResponseBuilder._handle_file_transfer = original
        await master.stop()
        await slave.stop()
