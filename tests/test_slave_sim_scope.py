"""模拟改造（第二批 ⑤）单测：YC 量程内随机、scope 两模式点集、无量程回落.

覆盖：
- ``webui.session.set_simulation`` 的 scope/ioas 校验
- ``core.engine.slave_sim`` 的量程随机（不越界）与无量程回落
- ``simulation_loop`` 的 scope=selected / all 两种点集行为（点表外 IOA 跳过）
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.data.point_table import PointTable, YcPointDef, YxPointDef
from core.engine.slave import SlaveEngine
from core.engine.slave_sim import _next_yc_value
from webui.session import EngineSession

# ── YC 取值计算 ──────────────────────────────────────────────────

def test_next_yc_value_within_declared_range():
    """声明量程 [10, 20] → 随机值恒在量程内."""
    point = YcPointDef(ioa=101, min_value=10.0, max_value=20.0)
    for _ in range(500):
        v = _next_yc_value(point, current=15.0, yc_change_range=0.05)
        assert 10.0 <= v <= 20.0


def test_next_yc_value_fallback_without_range():
    """无量程点（缺省 ±99999）→ 回落「当前值 ± yc_change_range 比例」."""
    point = YcPointDef(ioa=102)  # 默认 min/max = ±99999
    current = 50.0
    rng = 0.1
    for _ in range(500):
        v = _next_yc_value(point, current=current, yc_change_range=rng)
        assert current * (1 - rng) - 1e-9 <= v <= current * (1 + rng) + 1e-9


def test_next_yc_value_invalid_range_falls_back():
    """量程非法（min >= max）→ 同样走回落，不产生 NaN/inf."""
    point = YcPointDef(ioa=103, min_value=30.0, max_value=10.0)
    for _ in range(100):
        v = _next_yc_value(point, current=15.0, yc_change_range=0.05)
        assert v == v  # 非 NaN


# ── session 校验 ─────────────────────────────────────────────────

class _FakeEngine:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start_simulation(self, **kwargs) -> None:
        self.calls.append(kwargs)

    async def stop_simulation(self) -> None:
        self.calls.append({"stopped": True})


def _session_with_engine() -> EngineSession:
    s = EngineSession.__new__(EngineSession)  # 绕过构造（只需 role/engine/simulation 字段）
    s.role = "slave"
    s.engine = _FakeEngine()
    s.simulation = False
    return s


@pytest.mark.asyncio
async def test_set_simulation_scope_selected_requires_ioas():
    s = _session_with_engine()
    r = await s.set_simulation(True, yx_scope="selected", yx_ioas=[], yc_scope="all")
    assert r["ok"] is False
    assert "ioas" in r["error"]


@pytest.mark.asyncio
async def test_set_simulation_scope_invalid():
    s = _session_with_engine()
    r = await s.set_simulation(True, yx_scope="part", yc_scope="all")
    assert r["ok"] is False
    assert "scope" in r["error"]


@pytest.mark.asyncio
async def test_set_simulation_passes_scope_and_ioas():
    s = _session_with_engine()
    r = await s.set_simulation(
        True, yx_scope="selected", yx_ioas=[1, 2], yc_scope="all", yx_change_rate=0.3,
    )
    assert r["ok"] is True
    call = s.engine.calls[0]
    assert call["yx_scope"] == "selected"
    assert call["yx_ioas"] == [1, 2]
    assert call["yc_scope"] == "all"
    assert call["yx_change_rate"] == pytest.approx(0.3)


# ── simulation_loop scope 点集 ───────────────────────────────────

def _engine_with_points() -> SlaveEngine:
    with patch("core.engine.slave.TCPServer") as MockServer:
        server = MockServer.return_value
        server.start = AsyncMock()
        server.stop = AsyncMock()
        server.is_running = True
        server.connection_count = 0
        server.connections = {}
        server.broadcast = AsyncMock()

    pt = PointTable()
    pt.add_yx(YxPointDef(ioa=1, name="YX1"))
    pt.add_yx(YxPointDef(ioa=2, name="YX2"))
    pt.add_yc(YcPointDef(ioa=101, name="YC1", initial_value=15.0,
                         min_value=10.0, max_value=20.0))
    pt.add_yc(YcPointDef(ioa=102, name="YC2", initial_value=50.0))  # 无量程
    return SlaveEngine(host="0.0.0.0", port=2404, common_addr=1,
                       point_table=pt, spontaneous_enabled=True)


async def _run_loop(engine: SlaveEngine, passes: int, **kwargs) -> None:
    """确定性地驱动 simulation_loop 跑满 ``passes`` 个周期后自然退出.

    通过对 asyncio.sleep 计数在固定周期数后置停（而不是按墙钟取消），
    避免取消落在 YX/YC 两段之间造成偶发失败。
    """
    # 实时库按点表初始化（模拟 YC 需要当前值存在）
    engine.data_store.init_from_point_table(engine._point_table)
    engine._sim.send_spontaneous_yx = AsyncMock(side_effect=engine._sim.send_spontaneous_yx)
    engine._sim.send_spontaneous_yc = AsyncMock(side_effect=engine._sim.send_spontaneous_yc)

    real_sleep = asyncio.sleep
    state = {"n": 0}

    async def counted_sleep(_seconds: float) -> None:
        state["n"] += 1
        if state["n"] >= passes:
            engine._simulation_running = False
        await real_sleep(0)

    import core.engine.slave_sim as sim_mod

    orig_sleep = sim_mod.asyncio.sleep
    sim_mod.asyncio.sleep = counted_sleep
    try:
        engine._simulation_running = True
        await engine._sim.simulation_loop(0.05, 0.05, 1.0, 0.1, **kwargs)
    finally:
        sim_mod.asyncio.sleep = orig_sleep
        engine._simulation_running = False


@pytest.mark.asyncio
async def test_scope_selected_only_selected_points():
    """scope=selected：YX 只翻 IOA 1；YC 只动 IOA 101（9999 不在点表 → 跳过）."""
    engine = _engine_with_points()
    await _run_loop(
        engine, 3,
        yx_scope="selected", yx_ioas=[1],
        yc_scope="selected", yc_ioas=[101, 9999],
    )
    yx_ioas = {c.args[0] for c in engine._sim.send_spontaneous_yx.await_args_list}
    yc_ioas = {c.args[0] for c in engine._sim.send_spontaneous_yc.await_args_list}
    assert yx_ioas == {1}
    assert yc_ioas == {101}
    # 量程随机不越界
    for c in engine._sim.send_spontaneous_yc.await_args_list:
        assert 10.0 <= c.args[1] <= 20.0


@pytest.mark.asyncio
async def test_scope_all_covers_all_table_points():
    """scope=all（默认）：全部 YX/YC 点都在范围内变化."""
    engine = _engine_with_points()
    await _run_loop(engine, 3)
    yx_ioas = {c.args[0] for c in engine._sim.send_spontaneous_yx.await_args_list}
    yc_ioas = {c.args[0] for c in engine._sim.send_spontaneous_yc.await_args_list}
    assert yx_ioas == {1, 2}  # rate=1.0，0.3s 内至少 3 个周期，全翻
    assert yc_ioas == {101, 102}
    # 无量程点回落：IOA 102 的值在初始值 ±10% 内
    for c in engine._sim.send_spontaneous_yc.await_args_list:
        if c.args[0] == 102:
            assert 50.0 * 0.9 - 1e-9 <= c.args[1] <= 50.0 * 1.1 + 1e-9
