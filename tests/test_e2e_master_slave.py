"""真 TCP 端到端联调：MasterEngine ↔ SlaveEngine.

在同一进程内启动子站与主站，验证:
- TCP 连接建立
- STARTDT / 数据传输
- 总召唤往返
- 自发上送
- 响应行为配置生效
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import PointTable, YkPointDef
from core.engine.master import MasterEngine, MasterEvent
from core.engine.slave import SlaveEngine, SlaveEvent
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.protocol.types import COT, TypeID


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_point_table() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=20, yc_count=10, yk_count=5, ym_count=5)
    pt.common_addr = 1
    pt.station_name = "E2E"
    return pt


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _wait_master_ready(master: MasterEngine, timeout: float = 8.0) -> bool:
    return await _wait_until(
        lambda: master.is_running or str(master.state).lower() == "running",
        timeout=timeout,
    )


@pytest.mark.asyncio
async def test_master_slave_connect_and_gi():
    """真连接：连接 + 总召唤收到数据."""
    port = _free_port()
    points = _demo_point_table()

    slave = SlaveEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        point_table=points,
    )
    slave.data_store.init_from_point_table(points)

    master_events: list[tuple[MasterEvent, dict]] = []
    slave_events: list[tuple[SlaveEvent, dict]] = []

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )
    master.set_event_callback(lambda e, d: master_events.append((e, d)))
    slave.set_event_callback(lambda e, d: slave_events.append((e, d)))

    await slave.start()
    try:
        await master.start()
        try:
            # 等待进入数据传输状态
            ok = await _wait_master_ready(master, timeout=8)
            assert ok, f"master not running, state={master.state}"

            # 等待至少一个客户端连上子站
            ok = await _wait_until(lambda: slave.client_count > 0, timeout=5)
            assert ok, "slave got no clients"

            # 总召唤
            await master.general_interrogation()
            ok = await _wait_until(
                lambda: (
                    master.data_store.stats.get("yx_count", 0) > 0
                    or master.data_store.stats.get("yc_count", 0) > 0
                ),
                timeout=8,
            )
            stats = master.data_store.stats
            assert ok and (stats.get("yx_count", 0) > 0 or stats.get("yc_count", 0) > 0), (
                f"GI produced no data: stats={stats}, events={[e.value for e,_ in master_events]}"
            )

            # 子站应收到过 GI
            assert any(e == SlaveEvent.GI_RECEIVED for e, _ in slave_events), (
                f"slave events={[e.value for e,_ in slave_events]}"
            )
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


@pytest.mark.asyncio
async def test_spontaneous_yx_reaches_master():
    """子站自发上送到主站."""
    port = _free_port()
    points = _demo_point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_master_ready(master, timeout=8)
            assert ok

            ioa = 1
            original = None
            yx = master.data_store.get_yx(ioa)
            if yx:
                original = yx.value

            await slave.send_spontaneous_yx(ioa, not original if original is not None else True)
            ok = await _wait_until(
                lambda: (
                    (m := master.data_store.get_yx(ioa)) is not None
                    and m.value != original
                ),
                timeout=8,
            )
            assert ok, "spontaneous YX did not update master data store"
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


@pytest.mark.asyncio
async def test_response_behavior_no_response_blocks_gi():
    """配置 no_response 后，主站总召唤拿不到数据."""
    port = _free_port()
    points = _demo_point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave.set_response_behavior({"errors": {"no_response": True}})

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_master_ready(master, timeout=8)
            assert ok

            # 清空主站数据后发 GI
            before = master.data_store.stats.get("yx_count", 0)
            await master.general_interrogation()
            await asyncio.sleep(1.0)
            after = master.data_store.stats.get("yx_count", 0)
            # no_response 应阻止数据上送（允许已有的连接初始化数据）
            assert after <= before + 1
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


@pytest.mark.asyncio
async def test_response_behavior_gi_delay():
    """GI 延迟配置应拉长响应时间."""
    port = _free_port()
    points = PointTable()
    points.generate_demo_points(yx_count=5, yc_count=2)
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave.set_response_behavior({"delays": {"gi": 0.8}})

    master = MasterEngine(
        host="127.0.0.1",
        port=port,
        common_addr=1,
        auto_start=True,
        auto_gi=False,
        reconnect=False,
    )

    await slave.start()
    try:
        await master.start()
        try:
            ok = await _wait_master_ready(master, timeout=8)
            assert ok
            t0 = asyncio.get_event_loop().time()
            await master.general_interrogation()
            ok = await _wait_until(
                lambda: master.data_store.stats.get("yx_count", 0) > 0,
                timeout=8,
            )
            elapsed = asyncio.get_event_loop().time() - t0
            assert ok
            assert elapsed >= 0.7, f"GI delay not applied, elapsed={elapsed:.3f}s"
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


# ── 错误 COT 注入（真 TCP 端到端） ────────────────────────────────

def _yk_point_table() -> PointTable:
    """SBO 点(100) + 直发点(101) + 若干遥信遥测，用于 COT 注入验证."""
    pt = PointTable()
    # 注意：generate_demo_points 会清空全部点表，必须先调用再追加自定义点
    pt.generate_demo_points(yx_count=3, yc_count=2)
    pt.common_addr = 1
    pt.station_name = "WRONG-COT"
    pt.add_yk(YkPointDef(ioa=100, name="YK_SBO", command_type="single",
                         select_before_execute=True))
    pt.add_yk(YkPointDef(ioa=101, name="YK_DIRECT", command_type="single",
                         select_before_execute=False))
    return pt


async def _start_pair(point_table: PointTable, *, wrong_cot: bool, t1: float = 0.6):
    """起真实主/子站，返回 (master, slave, slave_tx_frames, master_tx_frames)."""
    port = _free_port()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1,
                        point_table=point_table)
    slave.data_store.init_from_point_table(point_table)
    if wrong_cot:
        slave.set_response_behavior({"errors": {"wrong_cot": True}})

    slave_tx: list[bytes] = []
    master_tx: list[bytes] = []
    slave.set_raw_frame_callback(
        lambda data, direction, client="": slave_tx.append(data) if direction == "tx" else None
    )

    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=point_table, t1=t1)
    master.set_raw_frame_callback(
        lambda data, direction: master_tx.append(data) if direction == "tx" else None
    )

    await slave.start()
    await master.start()
    assert await _wait_master_ready(master, timeout=8), f"state={master.state}"
    assert await _wait_until(lambda: slave.client_count > 0, timeout=5)
    return master, slave, slave_tx, master_tx


def _i_frames(frames: list[bytes]) -> list[tuple[TypeID, int]]:
    """把原始帧列表解码为 [(type_id, cot), ...]（仅 I 帧）."""
    out: list[tuple[TypeID, int]] = []
    for frame in frames:
        if APCICodec.frame_type_of(frame) != "I":
            continue
        asdu = ASDU.decode(frame[6:])
        out.append((asdu.type_id, asdu.cot))
    return out


async def _stop_pair(master: MasterEngine, slave: SlaveEngine) -> None:
    for eng in (master, slave):
        try:
            await asyncio.wait_for(eng.stop(), timeout=6)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_wrong_cot_shifts_command_ack_cot():
    """真连接：wrong_cot=True 时命令确认/终止的 COT 各错位 +1."""
    points = _yk_point_table()
    master, slave, slave_tx, _ = await _start_pair(points, wrong_cot=True)
    try:
        slave_tx.clear()
        # 绕过主站自动 SBO，单发执行帧，直接看子站回什么 COT
        await master._send_single_command_raw(101, True, select=False, qu=0)
        await asyncio.sleep(0.5)

        cots = {cot for tid, cot in _i_frames(slave_tx) if tid == TypeID.C_SC_NA_1}
        assert cots == {int(COT.ACTCON) + 1, int(COT.ACTTERM) + 1}, (
            f"期望 COT 错位 +1，实测 {cots}"
        )
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_wrong_cot_shifts_gi_reply_cot():
    """真连接：wrong_cot=True 时召唤确认/数据/结束的 COT 各错位 +1."""
    points = _yk_point_table()
    master, slave, slave_tx, _ = await _start_pair(points, wrong_cot=True)
    try:
        slave_tx.clear()
        await master.general_interrogation()
        assert await _wait_until(
            lambda: any(tid == TypeID.M_SP_NA_1 for tid, _ in _i_frames(slave_tx)),
            timeout=5,
        ), "召唤数据未到达"

        decoded = _i_frames(slave_tx)
        ic_cots = {cot for tid, cot in decoded if tid == TypeID.C_IC_NA_1}
        data_cots = {cot for tid, cot in decoded if tid in (TypeID.M_SP_NA_1, TypeID.M_ME_NC_1)}
        assert ic_cots == {int(COT.ACTCON) + 1, int(COT.ACTTERM) + 1}, f"召唤确认/结束 COT={ic_cots}"
        assert data_cots == {int(COT.INTROGEN) + 1}, f"召唤数据 COT={data_cots}"
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_wrong_cot_select_ack_not_accepted_by_master():
    """严格校验：选择确认 COT 错位时主站不误判成功，超时中止且不发执行帧."""
    points = _yk_point_table()
    master, slave, _slave_tx, master_tx = await _start_pair(points, wrong_cot=True, t1=0.6)
    try:
        master_tx.clear()
        with pytest.raises(RuntimeError, match="SBO select failed"):
            await master.single_command(100, True, select=False, qu=0)
        await asyncio.sleep(0.3)

        cmds = [c for c in _i_frames(master_tx) if c[0] == TypeID.C_SC_NA_1]
        # 只应发出选择帧（S/E=1），不得发出执行帧
        selects = []
        for frame in master_tx:
            if APCICodec.frame_type_of(frame) != "I":
                continue
            asdu = ASDU.decode(frame[6:])
            if asdu.type_id != TypeID.C_SC_NA_1:
                continue
            obj = asdu.objects[0]
            selects.append(bool(getattr(obj.data, "select", False)))
        assert len(cmds) == 1 and selects == [True], (
            f"期望仅 1 个选择帧，实测 {list(zip(cmds, selects, strict=True))}"
        )
    finally:
        await _stop_pair(master, slave)


@pytest.mark.asyncio
async def test_wrong_cot_disabled_keeps_standard_cot():
    """对照组：未开启注入时命令确认为标准 COT（7/10）."""
    points = _yk_point_table()
    master, slave, slave_tx, _ = await _start_pair(points, wrong_cot=False)
    try:
        slave_tx.clear()
        await master._send_single_command_raw(101, True, select=False, qu=0)
        await asyncio.sleep(0.5)

        cots = {cot for tid, cot in _i_frames(slave_tx) if tid == TypeID.C_SC_NA_1}
        assert cots == {int(COT.ACTCON), int(COT.ACTTERM)}, f"实测 {cots}"
    finally:
        await _stop_pair(master, slave)
