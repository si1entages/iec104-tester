"""命令执行后的被控点联动测试（真机语义，真 TCP 端到端）.

真机行为（本项目以此为准）：
- 遥控（单/双命令）执行成功后，同 IOA 的遥信立即变位并带时标上送（COT=3）；
- 遥调（设点）执行成功后，同 IOA 的遥测更新并上报（COT=3）；
- 上送类型由点表声明决定：单点遥信 → M_SP_TB_1，双点遥信 → M_DP_TB_1，遥测 → M_ME_TF_1；
- 点表无该点、或值未变化时**不上送**（真机不做无变化的冗余上送）。
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import (
    PointTable,
    YcPointDef,
    YcType,
    YkPointDef,
    YxPointDef,
    YxType,
)
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.protocol.types import COT, TypeID

SPONT = COT.SPONT


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _point_table() -> PointTable:
    """遥控/遥调与同 IOA 遥信遥测配对的点表."""
    pt = PointTable()
    pt.common_addr = 1
    pt.station_name = "FEEDBACK"
    # 单命令(直发) ↔ 单点遥信
    pt.add_yx(YxPointDef(ioa=2001, name="YX_2001", group=1, point_type=YxType.SINGLE))
    pt.add_yk(YkPointDef(ioa=2001, name="YK_2001", group=1, command_type="single",
                         select_before_execute=False))
    # 双命令(SBO) ↔ 双点遥信
    pt.add_yx(YxPointDef(ioa=2002, name="YX_2002", group=1, point_type=YxType.DOUBLE))
    pt.add_yk(YkPointDef(ioa=2002, name="YK_2002", group=1, command_type="double",
                         select_before_execute=True))
    # 遥调(设点) ↔ 遥测；YK 表不含 4001 → 直发执行
    pt.add_yc(YcPointDef(ioa=4001, name="YC_4001", group=1, data_type=YcType.SHORT_FLOAT))
    # 无配对点的遥控（用于验证"不产生幽灵点"）
    pt.add_yk(YkPointDef(ioa=2100, name="YK_2100_NO_PAIR", group=1, command_type="single",
                         select_before_execute=False))
    return pt


def _decoded(frames: list[bytes]) -> list[tuple[TypeID, int, int, object]]:
    """解码为 [(type_id, cot, ioa, data), ...]（仅 I 帧）."""
    out = []
    for frame in frames:
        if APCICodec.frame_type_of(frame) != "I":
            continue
        asdu = ASDU.decode(frame[6:])
        for obj in asdu.objects:
            out.append((asdu.type_id, int(asdu.cot), obj.ioa, obj.data))
    return out


async def _start_pair():
    port = _free_port()
    points = _point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave_tx: list[bytes] = []
    slave.set_raw_frame_callback(
        lambda data, direction, client="": slave_tx.append(data) if direction == "tx" else None
    )
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=points)
    master_rx: list[bytes] = []
    master.set_raw_frame_callback(
        lambda data, direction: master_rx.append(data) if direction == "rx" else None
    )
    await slave.start()
    await master.start()
    assert await _wait_until(lambda: master.is_running, timeout=8), master.state
    assert await _wait_until(lambda: slave.client_count > 0, timeout=5)
    return master, slave, slave_tx, master_rx


async def _stop_pair(master: MasterEngine, slave: SlaveEngine) -> None:
    for eng in (master, slave):
        try:
            await asyncio.wait_for(eng.stop(), timeout=6)
        except Exception:
            pass


async def _wait_spont(master_rx: list[bytes], ioa: int, timeout: float = 3.0) -> list[tuple]:
    """等待主站收到针对 ioa 的突发上送（COT=3）."""
    await _wait_until(
        lambda: any(c == SPONT and o == ioa for _, c, o, _ in _decoded(master_rx)),
        timeout=timeout,
    )
    return [item for item in _decoded(master_rx) if item[1] == SPONT and item[2] == ioa]


@pytest.mark.asyncio
async def test_single_command_links_paired_single_yx():
    """单命令执行后：同 IOA 单点遥信变位并带时标上送（M_SP_TB_1, COT=3）."""
    master, slave, _slave_tx, master_rx = await _start_pair()
    try:
        master_rx.clear()
        await master.single_command(2001, True, select=False)
        spont = await _wait_spont(master_rx, 2001)

        assert spont, "未收到遥控变位的突发上送"
        type_id, cot, _ioa, _data = spont[0]
        assert (type_id, cot) == (TypeID.M_SP_TB_1, SPONT), f"实测 {type_id}, COT={cot}"
        assert master.data_store.get_yx(2001).value is True
        assert slave.data_store.get_yx(2001).value is True
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_double_command_links_paired_double_yx():
    """双命令(SBO)执行后：同 IOA 双点遥信变位并上送（M_DP_TB_1, COT=3, state=2）."""
    master, slave, _slave_tx, master_rx = await _start_pair()
    try:
        master_rx.clear()
        await master.double_command(2002, 2, select=False)   # 2=合
        spont = await _wait_spont(master_rx, 2002)

        assert spont, "未收到双命令变位的突发上送"
        type_id, cot, _ioa, data = spont[0]
        assert (type_id, cot) == (TypeID.M_DP_TB_1, SPONT), f"实测 {type_id}, COT={cot}"
        assert data.value == 2
        assert master.data_store.get_yx(2002).value is True
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_setpoint_links_paired_yc():
    """遥调执行后：同 IOA 遥测更新并上送（M_ME_TF_1, COT=3）."""
    master, slave, _slave_tx, master_rx = await _start_pair()
    try:
        master_rx.clear()
        await master.setpoint_shortfloat(4001, 123.5, select=False)
        spont = await _wait_spont(master_rx, 4001)

        assert spont, "未收到遥调结果的突发上送"
        type_id, cot, _ioa, data = spont[0]
        assert (type_id, cot) == (TypeID.M_ME_TF_1, SPONT), f"实测 {type_id}, COT={cot}"
        assert abs(data.value - 123.5) < 1e-3
        assert abs(master.data_store.get_yc(4001).value - 123.5) < 1e-3
        assert abs(slave.data_store.get_yc(4001).value - 123.5) < 1e-3
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_no_linkage_when_paired_point_absent():
    """点表无配对点时：正常应答但不上送，也不产生幽灵点."""
    master, slave, slave_tx, master_rx = await _start_pair()
    try:
        master_rx.clear()
        slave_tx.clear()
        await master.single_command(2100, True, select=False)
        await asyncio.sleep(0.6)

        acks = [item for item in _decoded(slave_tx) if item[0] == TypeID.C_SC_NA_1]
        assert sorted(cot for _, cot, _, _ in acks) == [int(COT.ACTCON), int(COT.ACTTERM)]
        assert not [item for item in _decoded(master_rx) if item[1] == SPONT], \
            "配对点不存在时不应上送突发帧"
        assert master.data_store.get_yx(2100) is None, "不应为主站创建幽灵遥信点"
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_no_linkage_when_value_unchanged():
    """同一命令重复执行且值未变：只上送一次（真机不做无变化上送）."""
    master, slave, _slave_tx, master_rx = await _start_pair()
    try:
        master_rx.clear()
        await master.single_command(2001, True, select=False)
        assert await _wait_spont(master_rx, 2001), "首次合位应上送"

        first_count = len([item for item in _decoded(master_rx) if item[1] == SPONT])
        await master.single_command(2001, True, select=False)
        await asyncio.sleep(0.6)
        second_count = len([item for item in _decoded(master_rx) if item[1] == SPONT])
        assert second_count == first_count, "值未变化不应重复上送"
    finally:
        await _stop_pair(master, slave)
