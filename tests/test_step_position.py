"""升降步位置点 (M_ST_NA_1) 建模与联动测试.

覆盖:
- 点表步位置点的 YAML 导入/导出往返
- 增删查接口与演示点生成
- 升降命令 (C_RC_NA_1) 执行成功后联动更新同 IOA 档位并自发上送
- 上送帧类型 (M_ST_TB_1) 与值正确
- 限幅边界（升到上限不再增、降到下限不再减）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.data.point_table import PointTable, PointType, StepPointDef
from core.engine.slave import SlaveEngine
from core.protocol.asdu import ASDU, InformationObject
from core.protocol.types import COT, RegulatingStepCommand, TypeID

# ── Fixtures / helpers ───────────────────────────────────────────

@pytest.fixture
def mock_tcp_server():
    with patch("core.engine.slave.TCPServer") as MockServer:
        server = MockServer.return_value
        server.start = AsyncMock()
        server.stop = AsyncMock()
        server.is_running = True
        server.connection_count = 0
        server.connections = {}
        server.broadcast = AsyncMock()
        yield server


def _make_engine(step_points: list[StepPointDef] | None = None,
                 **kwargs) -> SlaveEngine:
    pt = PointTable()
    for sp in (step_points or []):
        pt.add_step(sp)
    return SlaveEngine(
        host="0.0.0.0", port=2404, common_addr=1, point_table=pt, **kwargs
    )


def _connect(engine: SlaveEngine):
    conn = MagicMock()
    conn.name = "127.0.0.1:12345"
    conn.is_connected = True
    conn.send_frame = AsyncMock()
    conn.stop = AsyncMock()
    engine._on_client_connected(conn)
    state = engine._client_states[conn.name]
    state.data_transfer_enabled = True
    return conn, state


def _regulating_asdu(ioa: int, state: int, select: bool = False) -> ASDU:
    asdu = ASDU(type_id=TypeID.C_RC_NA_1, sq=False, num=1,
                cot=COT.ACT, common_addr=1)
    asdu.objects.append(InformationObject(
        ioa=ioa,
        data=RegulatingStepCommand(ioa=ioa, state=state, select=select, qu=0),
    ))
    return asdu


def _step_frames(conn) -> list:
    """返回 conn 已发送帧中所有 M_ST_* ASDU 的解码结果."""
    out = []
    for call in conn.send_frame.call_args_list:
        frame = call[0][0]
        try:
            dec = ASDU.decode(frame[6:])
        except Exception:
            continue
        if dec.type_id in (TypeID.M_ST_NA_1, TypeID.M_ST_TB_1):
            out.append(dec)
    return out


# ── 点表建模 ─────────────────────────────────────────────────────

class TestStepPointDef:
    def test_defaults(self):
        sp = StepPointDef(ioa=4001)
        assert sp.min_value == -64
        assert sp.max_value == 63
        assert sp.step_size == 1
        assert sp.initial_value == 0
        assert sp.transient is False

    def test_add_get_remove(self):
        pt = PointTable()
        pt.add_step(StepPointDef(ioa=4001, name="G1", group=2))
        assert pt.step_count == 1
        assert pt.get_step(4001).name == "G1"
        assert pt.get_step(9999) is None
        assert pt.remove_point(PointType.STEP, 4001) is True
        assert pt.get_step(4001) is None

    def test_get_all_and_by_group(self):
        pt = PointTable()
        pt.add_step(StepPointDef(ioa=4002, group=2))
        pt.add_step(StepPointDef(ioa=4001, group=1))
        pt.add_step(StepPointDef(ioa=4003, group=2))
        assert [p.ioa for p in pt.get_all_step()] == [4001, 4002, 4003]
        assert [p.ioa for p in pt.get_step_by_group(2)] == [4002, 4003]

    def test_yaml_roundtrip(self, tmp_path):
        pt = PointTable()
        pt.station_name = "S1"
        pt.common_addr = 7
        pt.add_step(StepPointDef(
            ioa=4001, name="G1", group=2, enabled=True,
            initial_value=1, min_value=-5, max_value=5,
            step_size=2, transient=True,
        ))
        path = tmp_path / "pt.yaml"
        pt.save_yaml(path)

        pt2 = PointTable()
        pt2.load_yaml(path)
        assert pt2.step_count == 1
        sp = pt2.get_step(4001)
        assert sp is not None
        assert sp.name == "G1"
        assert sp.group == 2
        assert sp.initial_value == 1
        assert sp.min_value == -5
        assert sp.max_value == 5
        assert sp.step_size == 2
        assert sp.transient is True

    def test_generate_demo_points_includes_step(self):
        pt = PointTable()
        pt.generate_demo_points(
            yx_count=1, yc_count=1, yk_count=1, ym_count=1, step_count=3
        )
        assert pt.step_count == 3
        assert pt.get_step(4001) is not None
        assert pt.get_step(4003) is not None


# ── 实时库 ───────────────────────────────────────────────────────

class TestStepDataStore:
    @pytest.mark.asyncio
    async def test_init_from_point_table(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(
            ioa=300, initial_value=2, min_value=-3, max_value=3, step_size=1,
        )])
        await engine.start()
        sd = engine._data_store.get_step(300)
        assert sd is not None
        assert sd.value == 2
        assert sd.min_val == -3
        assert sd.max_val == 3
        assert sd.step_size == 1

    @pytest.mark.asyncio
    async def test_update_step_change_flag(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(ioa=300)])
        await engine.start()
        assert engine._data_store.update_step(300, 1) is True
        assert engine._data_store.update_step(300, 1) is False


# ── 升降命令联动 ─────────────────────────────────────────────────

class TestRegulatingLinkage:
    @pytest.mark.asyncio
    async def test_execute_up_updates_and_uploads(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(
            ioa=300, initial_value=0, min_value=-3, max_value=3, step_size=1,
        )])
        await engine.start()
        conn, state = _connect(engine)

        # 先选择再执行（升降命令要求 SBO 选择）
        state.selected_commands[300] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(300, 2))

        sd = engine._data_store.get_step(300)
        assert sd.value == 1

        steps = _step_frames(conn)
        assert len(steps) == 1
        assert steps[0].type_id == TypeID.M_ST_TB_1
        assert steps[0].objects[0].data.value == 1

    @pytest.mark.asyncio
    async def test_execute_down_updates_and_uploads(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(
            ioa=300, initial_value=0, min_value=-3, max_value=3, step_size=1,
        )])
        await engine.start()
        conn, state = _connect(engine)

        state.selected_commands[300] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(300, 1))

        assert engine._data_store.get_step(300).value == -1
        steps = _step_frames(conn)
        assert len(steps) == 1
        assert steps[0].objects[0].data.value == -1

    @pytest.mark.asyncio
    async def test_step_size_applied(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(
            ioa=300, initial_value=0, min_value=-10, max_value=10, step_size=3,
        )])
        await engine.start()
        conn, state = _connect(engine)

        state.selected_commands[300] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(300, 2))
        assert engine._data_store.get_step(300).value == 3

    @pytest.mark.asyncio
    async def test_clamp_upper_no_change_no_upload(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(
            ioa=300, initial_value=1, min_value=-3, max_value=1, step_size=1,
        )])
        await engine.start()
        conn, state = _connect(engine)

        state.selected_commands[300] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(300, 2))

        # 已到上限，升一步应限幅且不上送
        assert engine._data_store.get_step(300).value == 1
        assert _step_frames(conn) == []

    @pytest.mark.asyncio
    async def test_clamp_lower_no_change_no_upload(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(
            ioa=300, initial_value=-3, min_value=-3, max_value=3, step_size=1,
        )])
        await engine.start()
        conn, state = _connect(engine)

        state.selected_commands[300] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(300, 1))

        assert engine._data_store.get_step(300).value == -3
        assert _step_frames(conn) == []

    @pytest.mark.asyncio
    async def test_select_does_not_link(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(ioa=300, initial_value=0)])
        await engine.start()
        conn, state = _connect(engine)

        await engine._handle_regulating_command(state, _regulating_asdu(300, 2, select=True))
        # 仅选择，不应改变档位，也不应上送步位置
        assert engine._data_store.get_step(300).value == 0
        assert _step_frames(conn) == []
        assert 300 in state.selected_commands

    @pytest.mark.asyncio
    async def test_command_for_unmodeled_ioa_no_link(self, mock_tcp_server):
        """命令 IOA 无步位置点时，命令仍被确认但无联动上送。"""
        engine = _make_engine([StepPointDef(ioa=300)])
        await engine.start()
        conn, state = _connect(engine)

        state.selected_commands[999] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(999, 2))

        assert engine._data_store.get_step(999) is None
        assert _step_frames(conn) == []

    @pytest.mark.asyncio
    async def test_linkage_disabled_spontaneous_still_updates(self, mock_tcp_server):
        engine = _make_engine(
            [StepPointDef(ioa=300, initial_value=0, min_value=-3, max_value=3)],
            spontaneous_enabled=False,
        )
        await engine.start()
        conn, state = _connect(engine)
        state.selected_commands[300] = (MagicMock(), 0.0)
        await engine._handle_regulating_command(state, _regulating_asdu(300, 2))

        # 实时库更新但不上送
        assert engine._data_store.get_step(300).value == 1
        assert _step_frames(conn) == []


# ── 自发上送 ─────────────────────────────────────────────────────

class TestSendSpontaneousStep:
    @pytest.mark.asyncio
    async def test_frame_type_and_value(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(ioa=4001)])
        conn, _state = _connect(engine)

        await engine.send_spontaneous_step(4001, 5, transient=True)

        sd = engine._data_store.get_step(4001)
        assert sd.value == 5
        assert sd.transient is True

        dec = ASDU.decode(conn.send_frame.call_args[0][0][6:])
        assert dec.type_id == TypeID.M_ST_TB_1
        assert dec.objects[0].data.value == 5
        assert dec.objects[0].data.transient is True

    @pytest.mark.asyncio
    async def test_disabled_no_upload(self, mock_tcp_server):
        engine = _make_engine([StepPointDef(ioa=4001)], spontaneous_enabled=False)
        conn, _state = _connect(engine)

        await engine.send_spontaneous_step(4001, 7)
        assert engine._data_store.get_step(4001).value == 7
        conn.send_frame.assert_not_called()
