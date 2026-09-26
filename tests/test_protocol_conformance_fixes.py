"""协议符合性修复回归测试 (P0/P1 批次).

覆盖:
- 时钟同步 ASDU 长度为标准 16 字节 (原 23 字节双写缺陷)
- 组召唤 QOI/COT 采用标准编号 (20 / 21-36)
- 累计量召唤响应 COT (37 / 38-41)
- P/N 否定确认落在 COT bit6 (而非命令数据字节 bit7)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    COT,
    CP56Time2a,
    InterrogationCommand,
    SingleCommand,
    TypeID,
)

# ── 时钟同步 ─────────────────────────────────────────────────────

def test_clock_sync_asdu_is_16_bytes():
    """C_CS_NA_1 应为标准 16 字节，时间戳不得双写."""
    raw = ASDUBuilder.build_clock_sync(1, CP56Time2a.now())
    assert len(raw) == 16
    decoded = ASDU.decode(raw)
    assert decoded.type_id == TypeID.C_CS_NA_1
    assert decoded.cot == COT.ACT
    assert decoded.objects[0].data.time_tag is not None


def test_clock_sync_ack_asdu_is_16_bytes():
    """时钟同步确认同样应为 16 字节."""
    raw = ASDUBuilder.build_clock_sync_ack(1, CP56Time2a.now())
    assert len(raw) == 16
    decoded = ASDU.decode(raw)
    assert decoded.type_id == TypeID.C_CS_NA_1
    assert decoded.cot == COT.ACTCON


# ── 组召唤 QOI / COT ─────────────────────────────────────────────

def test_group_response_cot_standard():
    assert COT.group_response(1) == 21
    assert COT.group_response(16) == 36
    assert COT.is_group_response(21)
    assert COT.is_group_response(36)
    assert not COT.is_group_response(20)
    assert not COT.is_group_response(41)
    assert COT.get_group_number(21) == 1
    assert COT.get_group_number(36) == 16
    with pytest.raises(ValueError):
        COT.group_response(0)
    with pytest.raises(ValueError):
        COT.group_response(17)


def test_counter_response_cot_standard():
    assert COT.COUNTER_REQ == 37
    assert COT.counter_group_response(1) == 38
    assert COT.counter_group_response(4) == 41
    assert COT.is_counter_group_response(38)
    assert COT.is_counter_group_response(41)
    assert not COT.is_counter_group_response(37)
    assert COT.is_counter_response(37)
    assert COT.is_counter_response(41)
    with pytest.raises(ValueError):
        COT.counter_group_response(5)


def test_interrogation_qoi_str_standard():
    assert InterrogationCommand(qoi=20).qoi_str == "站召唤"
    assert InterrogationCommand(qoi=21).qoi_str == "第1组召唤"
    assert InterrogationCommand(qoi=36).qoi_str == "第16组召唤"
    assert InterrogationCommand(qoi=5).qoi_str == "未知(5)"


def test_general_interrogation_builder_writes_standard_qoi():
    raw = ASDUBuilder.build_general_interrogation(1, 21)
    decoded = ASDU.decode(raw)
    assert decoded.objects[0].data[0] == 21


# ── P/N 否定确认 (COT bit6) ──────────────────────────────────────

def test_asdu_pn_roundtrip():
    asdu = ASDU(
        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
        cot=COT.ACTCON, pn=True, common_addr=1,
    )
    asdu.objects.append(
        InformationObject(ioa=100, data=SingleCommand(ioa=100, state=True))
    )
    decoded = ASDU.decode(asdu.encode())
    assert decoded.pn is True
    assert decoded.cot == COT.ACTCON


def test_asdu_pn_defaults_false():
    asdu = ASDU(
        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
        cot=COT.ACTCON, common_addr=1,
    )
    asdu.objects.append(
        InformationObject(ioa=100, data=SingleCommand(ioa=100, state=True))
    )
    decoded = ASDU.decode(asdu.encode())
    assert decoded.pn is False
    assert decoded.cot == COT.ACTCON


def test_slave_command_nack_uses_cot_pn_not_data_bit7():
    """子站否定确认应落在 COT bit6，命令数据字节不再被污染."""
    from core.engine.slave import SlaveEngine

    engine = SlaveEngine(common_addr=1)
    obj = InformationObject(ioa=100, data=SingleCommand(ioa=100, state=True, select=False))
    raw = engine._build_command_ack(TypeID.C_SC_NA_1, COT.ACTCON, obj, pn=True)

    decoded = ASDU.decode(raw)
    assert decoded.pn is True
    # 命令数据字节 bit7 (S/E 选择位) 保持原值 0，未被伪造为 P/N
    assert (decoded.objects[0].data.to_bytes()[0] & 0x80) == 0


def test_master_reads_nack_from_cot_pn():
    from core.engine.master import MasterEngine

    engine = MasterEngine()
    asdu = ASDU(
        type_id=TypeID.C_SC_NA_1, sq=False, num=1,
        cot=COT.ACTCON, pn=True, common_addr=1,
    )
    asdu.objects.append(
        InformationObject(ioa=100, data=SingleCommand(ioa=100, state=True))
    )
    engine._process_asdu(asdu)

    yk = engine._data_store.get_yk(100)
    assert yk is not None
    assert yk.last_command == "nack"
