"""机制层回归测试 — 审计发现的缺失/半实现项.

覆盖（均为审计结论，按真机行为实现）：
1. **T 试验位（COT bit7）**：原编码恒 0、解码丢弃 → 现在编码/解码保留，子站回显，
   主站不把 T=1 的监控报文当真实数据入库。
2. **读未知 IOA 回 COT=45**：原静默无应答 → 现在按标准回"未知信息对象地址"。
3. **M_ME_ND_1 品质污染**：原解码读第 3 字节当品质（实际是下一个对象的 IOA 最低字节）
   → 现在补 0 品质字节，品质恒为 GOOD。
4. **ASDU 长度上限**：`MAX_ASDU_LENGTH`(253) 原来定义了但未强制 → 现在编码时校验。
5. **主站累计量 CP24 变体 M_IT_TA_1**：原分支漏掉 → 现在与 NA/TB 一并处理。
6. **C_CD_NA_1 真机延时**：原固定回 100ms → 现在按请求延时应答并回显实际值。
"""

from __future__ import annotations

import asyncio

import pytest

from core.data.point_table import PointTable, YxPointDef
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import COT, NormalizedValue, QualityDescriptor, TypeID

# ── 1. T 试验位 ──────────────────────────────────────────────────

def test_test_bit_round_trip():
    """COT bit7 试验位必须编码进报文并能解回（与 P/N 位互不干扰）."""
    raw = ASDUBuilder.build_single_point(1, 100, True, cot=COT.SPONT)
    asdu = ASDU.decode(raw)
    asdu.test = True
    asdu.pn = True
    encoded = asdu.encode()

    # bit7=T, bit6=P/N, bit0-5=COT
    assert encoded[2] & 0x80, "T 位未置位"
    assert encoded[2] & 0x40, "P/N 位被破坏"
    assert encoded[2] & 0x3F == int(COT.SPONT)

    again = ASDU.decode(encoded)
    assert again.test is True and again.pn is True
    assert int(again.cot) == int(COT.SPONT)

    head = ASDU.decode_header(encoded)
    assert head.test is True and head.pn is True


@pytest.mark.asyncio
async def test_slave_echoes_test_bit():
    """子站对 T=1 的测试命令必须回显 T=1（一致性测试要点）."""
    sent: list[bytes] = []
    slave = SlaveEngine(port=0, point_table=PointTable())
    slave._common_addr = 1

    class _Conn:
        name = "fake"

    class _State:
        conn = _Conn()
        selected_commands: dict = {}

    async def fake_send(state, data: bytes) -> None:
        sent.append(data)

    slave._send_i_frame = fake_send        # type: ignore[assignment]
    asdu = ASDU(
        type_id=TypeID.C_TS_NA_1, sq=False, num=1,
        cot=COT.ACT, test=True, common_addr=1,
    )
    asdu.objects.append(InformationObject(ioa=0, data=b"\xaa\x55"))

    await slave._handle_test_command(_State(), asdu)

    assert sent, "未回送测试命令应答"
    ack = ASDU.decode(sent[0])
    assert ack.test is True, "应答未回显 T 试验位"
    assert int(ack.cot) == int(COT.ACTCON)


def test_master_skips_test_messages():
    """主站收到 T=1 的监控报文时不得写入实时库（标准：试验报文非真实数据）."""
    pt = PointTable()
    pt.common_addr = 1
    pt.add_yx(YxPointDef(ioa=1, name="YX1", group=1))

    master = MasterEngine(host="127.0.0.1", port=0, common_addr=1, point_table=pt)
    master.data_store.init_from_point_table(pt)

    # 真实报文（T=0）→ 入库
    real = ASDU.decode(ASDUBuilder.build_single_point(1, 1, True, cot=COT.SPONT))
    master._process_asdu(real)
    assert master.data_store.get_yx(1).value is True

    # 试验报文（T=1）→ 不入库
    test_frame = ASDU.decode(ASDUBuilder.build_single_point(1, 1, False, cot=COT.SPONT))
    test_frame.test = True
    master._process_asdu(ASDU.decode(test_frame.encode()))
    assert master.data_store.get_yx(1).value is True, "T=1 试验报文被错误写入实时库"


# ── 2. 读未知 IOA 回 COT=45 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_read_unknown_ioa_replies_cot45():
    """读命令针对点表外的 IOA：必须回 COT=45（未知信息对象地址），而不是静默丢弃."""
    pt = PointTable()
    pt.common_addr = 1
    pt.add_yx(YxPointDef(ioa=1, name="YX1", group=1))

    slave = SlaveEngine(port=0, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    sent: list[bytes] = []

    class _Conn:
        name = "fake"

    class _State:
        conn = _Conn()

    async def fake_send(state, data: bytes) -> None:
        sent.append(data)

    slave._send_i_frame = fake_send        # type: ignore[assignment]

    known = ASDU.decode(ASDUBuilder.build_read_command(1, 1))
    await slave._handle_read_command(_State(), known)
    assert sent and int(ASDU.decode(sent[-1]).cot) == int(COT.REQ), "已知点未回送当前值"

    unknown = ASDU.decode(ASDUBuilder.build_read_command(1, 9999))
    await slave._handle_read_command(_State(), unknown)
    ack = ASDU.decode(sent[-1])
    assert int(ack.cot) == int(COT.UNKNOWN_IOA), (
        f"未知 IOA 应回 COT=45，实测 {int(ack.cot)}"
    )
    assert int(ack.type_id) == int(TypeID.C_RD_NA_1)


# ── 3. M_ME_ND_1 品质污染 ────────────────────────────────────────

def test_me_nd_1_quality_not_polluted():
    """M_ME_ND_1 不带品质：解码品质必须是 GOOD，而不是下一个对象的 IOA 字节."""
    asdu = ASDU(type_id=TypeID.M_ME_ND_1, sq=False, num=2, cot=COT.SPONT,
                common_addr=1)
    # 两个对象，第一个 IOA=100（最低字节 0x64 → 修复前会被当成品质位）
    for ioa, value in ((100, 0.5), (101, -0.5)):
        asdu.objects.append(InformationObject(
            ioa=ioa, data=NormalizedValue(value=value)))
    decoded = ASDU.decode(asdu.encode())

    assert len(decoded.objects) == 2
    for obj in decoded.objects:
        assert obj.data.quality == QualityDescriptor(), (
            f"IOA={obj.ioa} 品质被污染: {obj.data.quality}"
        )
    assert abs(decoded.objects[0].data.value - 0.5) < 1e-3
    assert abs(decoded.objects[1].data.value + 0.5) < 1e-3


# ── 4. ASDU 长度上限 ─────────────────────────────────────────────

def test_asdu_length_limit_enforced():
    """超过 253 字节的 ASDU 必须被拒绝（此前常量定义但未强制）."""
    asdu = ASDU(type_id=TypeID.M_SP_NA_1, sq=False, num=200, cot=COT.INTROGEN,
                common_addr=1)
    from core.protocol.types import SinglePoint

    for i in range(200):
        asdu.objects.append(InformationObject(ioa=i + 1, data=SinglePoint(value=True)))
    with pytest.raises(ValueError, match="ASDU too long"):
        asdu.encode()


# ── 5. 主站累计量 CP24 变体 ──────────────────────────────────────

def test_master_accepts_cp24_counter():
    """主站必须处理 M_IT_TA_1（CP24 短时标累计量），否则真机 CP24 电度被静默丢弃."""
    from core.data.point_table import YmPointDef

    pt = PointTable()
    pt.common_addr = 1
    pt.add_ym(YmPointDef(ioa=3001, name="YM", group=1))

    master = MasterEngine(host="127.0.0.1", port=0, common_addr=1, point_table=pt)
    master.data_store.init_from_point_table(pt)

    master._process_asdu(ASDU.decode(
        ASDUBuilder.build_counter_cp24(1, 3001, 12345, cot=COT.SPONT)))
    assert master.data_store.get_ym(3001).value == 12345


# ── 6. C_CD_NA_1 真实延时 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_delay_command_applies_requested_delay():
    """延时获得命令：应按请求延时推迟应答，并回显实际采用的延时值."""
    slave = SlaveEngine(port=0, point_table=PointTable())
    slave.data_store.init_from_point_table(PointTable())
    sent: list[bytes] = []

    class _Conn:
        name = "fake"

    class _State:
        conn = _Conn()

    async def fake_send(state, data: bytes) -> None:
        sent.append(data)

    slave._send_i_frame = fake_send        # type: ignore[assignment]
    asdu = ASDU.decode(ASDUBuilder.build_delay_command(1, 300))

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await slave._handle_delay_command(_State(), asdu)
    elapsed = loop.time() - t0

    assert elapsed >= 0.25, f"未按请求延时（实测 {elapsed:.3f}s）"
    ack = ASDU.decode(sent[-1])
    assert int(ack.type_id) == int(TypeID.C_CD_NA_1)
    assert ack.objects[0].data.delay_ms == 300, "应答未回显请求的延时值"
