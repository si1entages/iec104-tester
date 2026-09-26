"""子站召唤打包回归测试 — SQ=1 序列帧的 IOA 连续性.

背景（联合调试实测缺陷）：
点表遥信 IOA={1, 2001, 2002} 时，子站把三个点打包进**一帧** SQ=1 的
M_SP_NA_1（首 IOA=1, num=3）。按 IEC 60870-5-104，SQ=1 只发送首个对象 IOA，
其余由 +1 推得，于是主站解出 IOA=1/2/3 —— 2001/2002 的遥信被静默错址写入 2/3。

同时回归另一个缺陷：总召唤里曾有一块「SOE」把已上送的遥信再发一遍，
且用的是不带时标的 M_SP_NA_1（代码注释自认占位未实现），导致同一遥信重复出现。
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from core.data.point_table import PointTable, YcPointDef, YxPointDef, YxType
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine, _split_contiguous
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.protocol.types import COT, TypeID


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


def _sparse_point_table() -> PointTable:
    """非连续 IOA 点表：YX 1 / 2001 / 2002，YC 4001（真实现场点表几乎都非连续）."""
    pt = PointTable()
    pt.common_addr = 1
    for ioa in (1, 2001, 2002):
        pt.add_yx(YxPointDef(ioa=ioa, name=f"YX_{ioa}", group=1, enabled=True))
    pt.add_yc(YcPointDef(ioa=4001, name="YC_4001", group=1, enabled=True,
                         initial_value=3.5))
    return pt


# ── 单元：连续段切分 ──────────────────────────────────────────────

class TestSplitContiguous:
    """``_split_contiguous`` 单元测试."""

    def test_contiguous_single_chunk(self):
        batch = [(1, "a"), (2, "b"), (3, "c")]
        assert _split_contiguous(batch, 120) == [batch]

    def test_gap_starts_new_chunk(self):
        assert _split_contiguous([(1, "a"), (2001, "b"), (2002, "c")], 120) == [
            [(1, "a")], [(2001, "b"), (2002, "c")]
        ]

    def test_sorted_by_ioa_before_splitting(self):
        chunks = _split_contiguous([(2002, "c"), (1, "a"), (2001, "b")], 120)
        assert chunks == [[(1, "a")], [(2001, "b"), (2002, "c")]]

    def test_max_per_frame_respected(self):
        batch = [(i, i) for i in range(1, 8)]
        assert _split_contiguous(batch, 3) == [
            [(1, 1), (2, 2), (3, 3)],
            [(4, 4), (5, 5), (6, 6)],
            [(7, 7)],
        ]

    def test_empty(self):
        assert _split_contiguous([], 10) == []


# ── 真 TCP 端到端：召唤 IOA 必须与点表一致 ───────────────────────

def _decoded_i_frames(frames: list[bytes]) -> list[ASDU]:
    out = []
    for frame in frames:
        if APCICodec.frame_type_of(frame) != "I":
            continue
        out.append(ASDU.decode(frame[6:]))
    return out


@pytest.mark.asyncio
async def test_gi_keeps_sparse_ioa_addresses():
    """真连接：非连续 IOA 点表的总召唤应答，主站解出的 IOA 必须与点表一致."""
    port = _free_port()
    points = _sparse_point_table()

    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave_tx: list[bytes] = []
    slave.set_raw_frame_callback(
        lambda data, direction, client="": slave_tx.append(data) if direction == "tx" else None
    )

    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=points)

    await slave.start()
    try:
        await master.start()
        try:
            assert await _wait_until(lambda: master.is_running, timeout=8), master.state
            assert await _wait_until(lambda: slave.client_count > 0, timeout=5)

            slave_tx.clear()
            await master.general_interrogation()
            assert await _wait_until(
                lambda: any(a.type_id == TypeID.M_SP_NA_1
                            for a in _decoded_i_frames(slave_tx)),
                timeout=5,
            ), "召唤遥信未到达"

            yx_ioas = sorted(
                obj.ioa
                for a in _decoded_i_frames(slave_tx)
                if a.type_id == TypeID.M_SP_NA_1
                for obj in a.objects
            )
            assert yx_ioas == [1, 2001, 2002], (
                f"召唤遥信 IOA 错址: {yx_ioas}（期望 [1, 2001, 2002]；"
                f"出现 2/3 说明非连续点被打包进同一 SQ=1 帧）"
            )

            # 主站侧实时库也应落在正确 IOA 上
            assert master.data_store.get_yx(2001) is not None
            assert master.data_store.get_yx(2002) is not None
            assert master.data_store.get_yx(2) is None, "点表中不存在 IOA=2，却被写入（错址）"
        finally:
            await asyncio.wait_for(master.stop(), timeout=6)
    finally:
        await asyncio.wait_for(slave.stop(), timeout=6)


def _mixed_point_table() -> PointTable:
    """单点 + 双点遥信混排（双点分别处于"合"与"中间态"）."""
    pt = PointTable()
    pt.common_addr = 1
    pt.add_yx(YxPointDef(ioa=1, name="YX_1", group=1, point_type=YxType.SINGLE))
    pt.add_yx(YxPointDef(ioa=2002, name="YX_2002_DOUBLE_ON", group=1,
                         point_type=YxType.DOUBLE))
    pt.add_yx(YxPointDef(ioa=2003, name="YX_2003_DOUBLE_MID", group=1,
                         point_type=YxType.DOUBLE))
    return pt


async def _gi_frames(slave: SlaveEngine, master: MasterEngine,
                     slave_tx: list[bytes]) -> list[ASDU]:
    slave_tx.clear()
    await master.general_interrogation()
    assert await _wait_until(
        lambda: any(a.type_id in (TypeID.M_SP_NA_1, TypeID.M_DP_NA_1)
                    for a in _decoded_i_frames(slave_tx)),
        timeout=5,
    ), "召唤遥信未到达"
    return _decoded_i_frames(slave_tx)


@pytest.mark.asyncio
async def test_gi_encodes_double_point_by_declared_type_once():
    """双点遥信在召唤中只按声明类型上送一次（M_DP_NA_1），不得又当单点上送一次."""
    port = _free_port()
    points = _mixed_point_table()
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave_tx: list[bytes] = []
    slave.set_raw_frame_callback(
        lambda data, direction, client="": slave_tx.append(data) if direction == "tx" else None
    )
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=points)
    await slave.start()
    try:
        await master.start()
        try:
            assert await _wait_until(lambda: master.is_running, timeout=8), master.state
            assert await _wait_until(lambda: slave.client_count > 0, timeout=5)

            await slave.send_spontaneous_dp(2002, 2)                      # 双点=合
            slave.data_store.update_yx(2003, False, double_state=0)       # 双点=中间态
            await asyncio.sleep(0.3)

            frames = await _gi_frames(slave, master, slave_tx)
            singles = sorted(o.ioa for a in frames if a.type_id == TypeID.M_SP_NA_1
                             for o in a.objects)
            doubles = sorted(o.ioa for a in frames if a.type_id == TypeID.M_DP_NA_1
                             for o in a.objects)
            double_vals = {o.ioa: o.data.value for a in frames
                           if a.type_id == TypeID.M_DP_NA_1 for o in a.objects}

            assert singles == [1], f"单点遥信应为 IOA=1，实测 {singles}"
            assert doubles == [2002, 2003], (
                f"双点遥信应以 M_DP_NA_1 上送 IOA=[2002, 2003]，实测 {doubles}"
                f"（中间态 double_state=0 被漏掉或按单点上送即为缺陷）"
            )
            assert double_vals == {2002: 2, 2003: 0}, f"双点状态值异常: {double_vals}"
            # 同一 IOA 不得既出现在单点帧又出现在双点帧
            assert not (set(singles) & set(doubles))
            # 主站实时库应能读到双点状态
            assert master.data_store.get_yx(2002).double_state == 2
            assert master.data_store.get_yx(2003).double_state == 0
        finally:
            await asyncio.wait_for(master.stop(), timeout=6)
    finally:
        await asyncio.wait_for(slave.stop(), timeout=6)


@pytest.mark.asyncio
async def test_gi_has_no_duplicate_points_after_change():
    """真连接：遥信变位后再召唤，同一 IOA 不得重复上送，且只用 M_SP_NA_1/COT=20."""
    port = _free_port()
    points = _sparse_point_table()

    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave_tx: list[bytes] = []
    slave.set_raw_frame_callback(
        lambda data, direction, client="": slave_tx.append(data) if direction == "tx" else None
    )

    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=points)

    await slave.start()
    try:
        await master.start()
        try:
            assert await _wait_until(lambda: master.is_running, timeout=8), master.state
            assert await _wait_until(lambda: slave.client_count > 0, timeout=5)

            # 制造变位（change_count>0），历史实现会因此在召唤里重发该点
            await slave.send_spontaneous_yx(1, True)
            await asyncio.sleep(0.3)

            slave_tx.clear()
            await master.general_interrogation()
            assert await _wait_until(
                lambda: any(a.type_id == TypeID.M_SP_NA_1
                            for a in _decoded_i_frames(slave_tx)),
                timeout=5,
            )

            yx_pairs = [
                (a.type_id, a.cot, obj.ioa)
                for a in _decoded_i_frames(slave_tx)
                for obj in a.objects
                if a.type_id in (TypeID.M_SP_NA_1, TypeID.M_SP_TB_1)
            ]
            ioas = [ioa for _, _, ioa in yx_pairs]
            assert sorted(ioas) == [1, 2001, 2002], f"遥信应各出现 1 次，实测 {yx_pairs}"
            assert {(t, c) for t, c, _ in yx_pairs} == {(TypeID.M_SP_NA_1, COT.INTROGEN)}, (
                f"召唤遥信类型/COT 异常: {yx_pairs}（期望全部 M_SP_NA_1 + COT=20）"
            )
        finally:
            await asyncio.wait_for(master.stop(), timeout=6)
    finally:
        await asyncio.wait_for(slave.stop(), timeout=6)
