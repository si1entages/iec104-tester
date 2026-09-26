"""QA 独立符合性回归测试.

本文件由 QA 独立编写，**不复用工程师测试中的断言**：所有期望值由标准
(IEC 60870-5-104) 手工推算，帧级证据自造。覆盖本轮 9 项协议符合性修复。

约定（ASDU 字节布局）:
  [type(1)][vsq(1)][cot(1)][origin(1)][ca(2)][ioa(3)][data...]
  因此 QOI/第一个数据字节位于 index 9；COT 字节位于 index 2。
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import PointTable
from core.engine.master import MasterEngine, MasterEvent
from core.engine.slave import SlaveEngine
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    COT,
    CP24Time2a,
    CP56Time2a,
    GroupSinglePointWithStatus,
    ParameterCommandNormalizedNoQuality,
    ProtectionEvent,
    QualityDescriptor,
    SingleCommand,
    TypeID,
)

# ═══════════════════════════════════════════════════════════════════
#  帧级证据 (纯编解码，无网络)
# ═══════════════════════════════════════════════════════════════════


class TestClockSync:
    """修复 #1: 时钟同步 ASDU 不得双写时标 (须为 16 字节)."""

    def test_clock_sync_length_is_16(self):
        cmd = ASDUBuilder.build_clock_sync(1, CP56Time2a.now())
        ack = ASDUBuilder.build_clock_sync_ack(1, CP56Time2a.now())
        assert len(cmd) == 16
        assert len(ack) == 16

    def test_clock_sync_timestamp_appears_once(self):
        t = CP56Time2a.now()
        cmd = ASDUBuilder.build_clock_sync(1, t)
        tb = t.to_bytes()
        occurrences = sum(
            1 for i in range(len(cmd) - len(tb) + 1) if cmd[i:i + len(tb)] == tb
        )
        assert occurrences == 1

    def test_clock_sync_decode_roundtrip(self):
        t = CP56Time2a.now()
        d = ASDU.decode(ASDUBuilder.build_clock_sync(1, t))
        assert d.cot == COT.ACT
        assert getattr(d.objects[0].data, "time_tag", None) == t
        assert d.encode() == ASDUBuilder.build_clock_sync(1, t)


class TestGroupInterrogation:
    """修复 #2: 组召唤标准 QOI/COT (21-36) 与累计量响应 (37/38-41)."""

    def test_station_and_group_qoi(self):
        assert ASDUBuilder.build_general_interrogation(1, 20)[9] == 20
        assert ASDUBuilder.build_general_interrogation(1, 21)[9] == 21

    @pytest.mark.parametrize("group", range(1, 17))
    def test_group_qoi_range(self, group):
        assert ASDUBuilder.build_general_interrogation(1, 20 + group)[9] == 20 + group

    def test_group_response_cot(self):
        assert COT.group_response(1) == 21
        assert COT.group_response(16) == 36
        assert COT.is_group_response(21)
        assert not COT.is_group_response(20)

    def test_counter_response_cot(self):
        assert COT.COUNTER_REQ == 37
        assert COT.counter_group_response(1) == 38
        assert COT.counter_group_response(4) == 41


class TestPNBit6:
    """修复 #3: 否定确认 P/N 落到 COT bit6，且不篡改命令数据字节."""

    def test_pn_encodes_into_cot_bit6(self):
        a = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=1, cot=COT.ACTCON,
                 pn=True, common_addr=1)
        a.objects.append(InformationObject(ioa=100, data=SingleCommand(state=True)))
        enc = a.encode()
        assert enc[2] == (COT.ACTCON & 0x3F) | 0x40
        assert ASDU.decode(enc).pn is True

    def test_pn_preserves_select_bit(self):
        a = ASDU(type_id=TypeID.C_SC_NA_1, sq=False, num=1, cot=COT.ACTCON,
                 pn=True, common_addr=1)
        a.objects.append(InformationObject(
            ioa=100, data=SingleCommand(state=True, select=True)))
        enc = a.encode()
        # 数据字节位于 index 9; S/E = bit7 应保持为 1 (未被否定确认篡改)
        assert enc[9] & 0x80 == 0x80
        assert ASDU.decode(enc).objects[0].data.select is True


class TestCP24Fidelity:
    """修复 #4: CP24 短时标解码保真，round-trip 不膨胀."""

    STANDARD = bytes([0x02, 0x01, 0x03, 0x00, 0x01, 0x00,
                      0x64, 0x00, 0x00, 0x01, 0xE8, 0x03, 0x05])

    def test_decode_keeps_cp24(self):
        d = ASDU.decode(self.STANDARD)
        tt = d.objects[0].time_tag
        assert isinstance(tt, CP24Time2a)
        assert tt.millisecond == 1000
        assert tt.minute == 5

    def test_roundtrip_no_inflation(self):
        d = ASDU.decode(self.STANDARD)
        assert len(d.encode()) == 13
        assert d.encode() == self.STANDARD


class TestLengths:
    """修复 #5/#6/#7/#8: 各类型编码长度与 round-trip."""

    def test_m_me_nd_1_is_11_bytes(self):
        a = ASDU(type_id=TypeID.M_ME_ND_1, sq=False, num=1, cot=COT.SPONT,
                 common_addr=1)
        a.objects.append(InformationObject(
            ioa=1, data=ParameterCommandNormalizedNoQuality(ioa=1, value=0.5)))
        assert len(a.encode()) == 11
        assert len(ASDUBuilder.build_normalized_value(1, 1, 0.5)) == 12

    @pytest.mark.parametrize("tid", [TypeID.M_EP_TA_1, TypeID.M_EP_TB_1,
                                     TypeID.M_EP_TC_1])
    def test_protection_event_short_time_15(self, tid):
        a = ASDU(type_id=tid, sq=False, num=1, cot=COT.SPONT, common_addr=1)
        ev = ProtectionEvent(ioa=1, event_value=0xBEEF, quality=QualityDescriptor())
        a.objects.append(InformationObject(
            ioa=1, data=ev, time_tag=CP24Time2a(millisecond=1, minute=2)))
        enc = a.encode()
        assert len(enc) == 15
        assert ASDU.decode(enc).objects[0].data.event_value == 0xBEEF

    @pytest.mark.parametrize("tid", [TypeID.M_EP_TD_1, TypeID.M_EP_TE_1,
                                     TypeID.M_EP_TF_1])
    def test_protection_event_long_time_19(self, tid):
        a = ASDU(type_id=tid, sq=False, num=1, cot=COT.SPONT, common_addr=1)
        ev = ProtectionEvent(ioa=1, event_value=0xBEEF, quality=QualityDescriptor())
        a.objects.append(InformationObject(ioa=1, data=ev, time_tag=CP56Time2a.now()))
        enc = a.encode()
        assert len(enc) == 19
        assert ASDU.decode(enc).objects[0].data.event_value == 0xBEEF

    @pytest.mark.parametrize("builder,expected", [
        (lambda: ASDUBuilder.build_single_command_with_time(1, 100, True), 17),
        (lambda: ASDUBuilder.build_double_command_with_time(1, 100, 2), 17),
        (lambda: ASDUBuilder.build_regulating_step_command_with_time(1, 100, 2), 17),
        (lambda: ASDUBuilder.build_setpoint_normalized_with_time(1, 100, 0.5), 19),
        (lambda: ASDUBuilder.build_setpoint_scaled_with_time(1, 100, 1000), 19),
        (lambda: ASDUBuilder.build_setpoint_shortfloat_with_time(1, 100, 1.5), 21),
        (lambda: ASDUBuilder.build_bitstring_command_with_time(1, 100, 0xDEADBEEF), 20),
    ])
    def test_typeid_58_64_lengths(self, builder, expected):
        enc = builder()
        assert len(enc) == expected
        d = ASDU.decode(enc)
        assert isinstance(d.objects[0].time_tag, CP56Time2a)
        assert len(d.encode()) == expected

    def test_m_ps_na_1_symmetric_11(self):
        a = ASDU(type_id=TypeID.M_PS_NA_1, sq=False, num=1, cot=COT.SPONT,
                 common_addr=1)
        g = GroupSinglePointWithStatus(ioa=1, points=[(True, False), (False, True)])
        a.objects.append(InformationObject(ioa=1, data=g))
        enc = a.encode()
        assert len(enc) == 11
        assert len(ASDU.decode(enc).encode()) == 11


class TestCOTErrorConstants:
    """修复 #9: COT 42/43/44 常量."""

    def test_error_cots(self):
        assert COT.UNKNOWN_TYPE == 42
        assert COT.UNKNOWN_COT == 43
        assert COT.UNKNOWN_CA == 44


# ═══════════════════════════════════════════════════════════════════
#  真实 TCP 端到端 (主站 + 子站)
# ═══════════════════════════════════════════════════════════════════


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_pt() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=5, yc_count=2, yk_count=3, ym_count=3)
    pt.common_addr = 1
    return pt


async def _wait_until(pred, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if pred():
            return True
        await asyncio.sleep(interval)
    return pred()


def _parse_i(frame: bytes):
    apci, _ = APCICodec.decode(frame)
    if not apci.is_i_frame:
        return None
    a = frame[6:6 + apci.asdu_length]
    return {
        "type_id": a[0],
        "cot": a[2] & 0x3F,
        "pn": bool(a[2] & 0x40),
        "ca": a[4] | (a[5] << 8),
        "data": a[9:] if len(a) >= 9 else a[6:],
        "raw": a,
    }


@pytest.mark.asyncio
async def test_e2e_group_interrogation_and_negative_ack():
    """端到端: 组召唤 QOI=21/COT=21；未选择执行 → 否定确认 (COT bit6)."""
    port = _free_port()
    pt = _demo_pt()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)

    tx, rx = [], []
    master.set_raw_frame_callback(
        lambda f, d: (tx if d == "tx" else rx).append(f))

    await slave.start()
    try:
        await master.start()
        assert await _wait_until(lambda: master.is_running)
        assert await _wait_until(lambda: slave.client_count > 0)

        # 组召唤 (组 1)
        n_tx, n_rx = len(tx), len(rx)
        await master.general_interrogation(1)
        assert await _wait_until(
            lambda: any(p and p["type_id"] == TypeID.M_SP_NA_1
                        for p in (_parse_i(f) for f in rx[n_rx:])))
        gi_tx = [_parse_i(f) for f in tx[n_tx:]]
        gi_tx = [p for p in gi_tx if p and p["type_id"] == TypeID.C_IC_NA_1]
        assert gi_tx and gi_tx[0]["data"][0] == 21
        sp = [_parse_i(f) for f in rx[n_rx:]]
        sp = [p for p in sp if p and p["type_id"] == TypeID.M_SP_NA_1]
        assert any(p["cot"] == 21 for p in sp)

        # 未选择就执行 → 否定确认
        n_rx = len(rx)
        await master.single_command(2002, True, select=False)
        assert await _wait_until(
            lambda: any(p and p["type_id"] == TypeID.C_SC_NA_1 and p["pn"]
                        for p in (_parse_i(f) for f in rx[n_rx:])))
        rej = [_parse_i(f) for f in rx[n_rx:]]
        rej = [p for p in rej if p and p["type_id"] == TypeID.C_SC_NA_1 and p["pn"]]
        # 否定确认不得篡改数据字节 S/E (执行命令 select=False → bit7=0)
        assert all((p["data"][0] & 0x80) == 0 for p in rej)
    finally:
        await master.stop()
        await slave.stop()


@pytest.mark.asyncio
async def test_e2e_unknown_type_ca_cot_replies():
    """端到端: 未知类型/CA/COT 注入 → 子站按 42/44/43 应答且连接不中断."""
    port = _free_port()
    pt = _demo_pt()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False)
    rx = []
    master.set_raw_frame_callback(lambda f, d: rx.append(f) if d == "rx" else None)

    async def send_raw(asdu_bytes):
        await master._await_send_window()
        frame = APCICodec.encode_i(master._seq.get_send_seq(),
                                   master._seq.get_recv_seq(), asdu_bytes)
        master._state_machine.on_i_frame_sent()
        await master._send_frame(frame)

    await slave.start()
    try:
        await master.start()
        assert await _wait_until(lambda: master.is_running)

        cases = [
            (ASDU(type_id=55, sq=False, num=0, cot=COT.SPONT, common_addr=1).encode(), 42),
            (ASDU(type_id=TypeID.C_IC_NA_1, sq=False, num=1, cot=COT.ACT,
                  common_addr=99).encode(), 44),
            (ASDU(type_id=TypeID.M_SP_NA_1, sq=False, num=0, cot=60,
                  common_addr=1).encode(), 43),
        ]
        for asdu_bytes, expected_cot in cases:
            n = len(rx)
            await send_raw(asdu_bytes)

            def _match(cot=expected_cot, start=n):
                return any(p and p["cot"] == cot
                           for p in (_parse_i(f) for f in rx[start:]))

            got = await _wait_until(_match)
            assert got, f"no COT={expected_cot} reply"
            assert master.is_running and slave.client_count == 1
    finally:
        await master.stop()
        await slave.stop()


async def _serve_bad_seq_once(port: int, seen: dict) -> asyncio.AbstractServer:
    """测试用 TCP 服务端: 首连回 STARTDT CON 后发一个失序 I 帧; 后续连接正常."""
    async def _handler(reader, writer):
        seen["n"] = seen.get("n", 0) + 1
        me = seen["n"]
        try:
            hdr = await reader.readexactly(2)
            await reader.readexactly(hdr[1])
            writer.write(bytes([0x68, 0x04, 0x0B, 0, 0, 0]))
            await writer.drain()
            if me == 1:
                await asyncio.sleep(0.2)
                writer.write(APCICodec.encode_i(
                    9, 0, ASDUBuilder.build_single_point(1, 1, True)))
                await writer.drain()
            while True:
                data = await reader.read(256)
                if not data:
                    break
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    return await asyncio.start_server(_handler, "127.0.0.1", port)


@pytest.mark.asyncio
async def test_e2e_out_of_order_no_reconnect_leaves_running():
    """失序(reconnect=False): 主站须离开 Running 且触发 DISCONNECTED (Bug B)."""
    port = _free_port()
    seen: dict = {}
    srv = await _serve_bad_seq_once(port, seen)
    master = MasterEngine(host="127.0.0.1", port=port, reconnect=False,
                          auto_start=True, auto_gi=False)
    events: list = []
    master.set_event_callback(lambda e, d: events.append(e))
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running)
        assert await _wait_until(lambda: not master.is_running)
        assert master.state != "Running"
        assert MasterEvent.DISCONNECTED in events
    finally:
        await master.stop()
        srv.close()


@pytest.mark.asyncio
async def test_e2e_out_of_order_reconnects_when_enabled():
    """失序(reconnect=True): 主站须自动重建连接并恢复 Running."""
    port = _free_port()
    seen: dict = {}
    srv = await _serve_bad_seq_once(port, seen)
    master = MasterEngine(host="127.0.0.1", port=port, reconnect=True,
                          reconnect_interval=0.5, auto_start=True, auto_gi=False)
    await master.start()
    try:
        assert await _wait_until(lambda: master.is_running)
        recovered = await _wait_until(
            lambda: master.is_running and seen.get("n", 0) >= 2, timeout=8)
        assert recovered, f"conns={seen.get('n')} state={master.state}"
    finally:
        await master.stop()
        srv.close()
