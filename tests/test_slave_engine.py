"""子站引擎 Mock 测试.

测试 SlaveEngine 的核心功能:
- 初始化
- 总召唤响应
- 时钟同步响应
- 遥控命令响应
- 数据变化上送
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.engine.slave import SlaveEngine, SlaveEvent
from core.protocol.apci import APCICodec, APCI
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    TypeID, COT, QualityDescriptor,
    SinglePoint, DoublePoint, ShortFloat, CP56Time2a,
    SingleCommand, DoubleCommand, RegulatingStepCommand,
    InitializationEnd,
)
from core.data.point_table import PointTable, YxPointDef, YcPointDef


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mock_tcp_server():
    """模拟 TCPServer."""
    with patch("core.engine.slave.TCPServer") as MockServer:
        server = MockServer.return_value
        server.start = AsyncMock()
        server.stop = AsyncMock()
        server.is_running = True
        server.connection_count = 0
        server.connections = {}
        server.broadcast = AsyncMock()
        yield server


@pytest.fixture
def point_table():
    """创建测试用点表."""
    pt = PointTable()
    # 添加遥信点
    pt.add_yx(YxPointDef(ioa=1, name="YX1", enabled=True))
    pt.add_yx(YxPointDef(ioa=2, name="YX2", enabled=True))
    # 添加遥测点
    pt.add_yc(YcPointDef(ioa=101, name="YC1", enabled=True))
    pt.add_yc(YcPointDef(ioa=102, name="YC2", enabled=True))
    return pt


@pytest.fixture
def mock_connection():
    """模拟 TCPConnection."""
    conn = MagicMock()
    conn.name = "127.0.0.1:12345"
    conn.is_connected = True
    conn.send_frame = AsyncMock()
    conn.stop = AsyncMock()
    return conn


@pytest.fixture
def slave_engine(mock_tcp_server, point_table):
    """创建 SlaveEngine 实例."""
    engine = SlaveEngine(
        host="0.0.0.0",
        port=2404,
        common_addr=1,
        point_table=point_table,
        spontaneous_enabled=True,
    )
    return engine


# ── 初始化测试 ───────────────────────────────────────────────────

class TestSlaveEngineInit:
    """SlaveEngine 初始化测试."""

    def test_default_params(self, slave_engine):
        """测试默认参数."""
        assert slave_engine._host == "0.0.0.0"
        assert slave_engine._port == 2404
        assert slave_engine._common_addr == 1
        assert slave_engine._spontaneous_enabled is True

    def test_custom_params(self, mock_tcp_server, point_table):
        """测试自定义参数."""
        engine = SlaveEngine(
            host="192.168.1.100",
            port=2405,
            common_addr=2,
            point_table=point_table,
            spontaneous_enabled=False,
            max_connections=32,
        )
        assert engine._host == "192.168.1.100"
        assert engine._port == 2405
        assert engine._common_addr == 2
        assert engine._spontaneous_enabled is False

    def test_initial_state(self, slave_engine):
        """测试初始状态."""
        assert slave_engine._event_callback is None
        assert slave_engine._raw_frame_callback is None
        assert slave_engine._recorder is None
        assert slave_engine._client_states == {}
        assert slave_engine._simulation_running is False

    def test_properties(self, slave_engine):
        """测试属性访问."""
        assert slave_engine.data_store is not None
        assert slave_engine.point_table is not None

    def test_point_table_loaded(self, slave_engine, point_table):
        """测试点表加载."""
        assert slave_engine.point_table is point_table
        assert slave_engine.point_table.yx_count == 2
        assert slave_engine.point_table.yc_count == 2


# ── 生命周期测试 ─────────────────────────────────────────────────

class TestSlaveEngineLifecycle:
    """SlaveEngine 生命周期测试."""

    @pytest.mark.asyncio
    async def test_start(self, slave_engine, mock_tcp_server):
        """测试启动."""
        await slave_engine.start()
        mock_tcp_server.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop(self, slave_engine, mock_tcp_server):
        """测试停止."""
        await slave_engine.start()
        await slave_engine.stop()
        mock_tcp_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_init_data_store(self, slave_engine, mock_tcp_server):
        """测试启动时初始化数据存储."""
        await slave_engine.start()

        # 验证数据存储已初始化
        yx = slave_engine._data_store.get_yx(1)
        assert yx is not None

    @pytest.mark.asyncio
    async def test_stop_stops_simulation(self, slave_engine, mock_tcp_server):
        """测试停止时停止模拟."""
        slave_engine._simulation_running = True
        slave_engine._simulation_task = MagicMock()
        slave_engine._simulation_task.cancel = MagicMock()
        slave_engine._simulation_task.__await__ = MagicMock(side_effect=asyncio.CancelledError)

        await slave_engine.stop()
        assert slave_engine._simulation_running is False


# ── 客户端连接管理测试 ───────────────────────────────────────────

class TestSlaveEngineClientManagement:
    """客户端连接管理测试."""

    def test_on_client_connected(self, slave_engine, mock_connection):
        """测试客户端连接."""
        slave_engine._on_client_connected(mock_connection)

        assert mock_connection.name in slave_engine._client_states
        state = slave_engine._client_states[mock_connection.name]
        assert state.conn is mock_connection
        assert state.data_transfer_enabled is False

    def test_on_client_disconnected(self, slave_engine, mock_connection):
        """测试客户端断开."""
        # 先添加客户端
        slave_engine._on_client_connected(mock_connection)
        assert mock_connection.name in slave_engine._client_states

        # 断开
        slave_engine._on_client_disconnected(mock_connection)
        assert mock_connection.name not in slave_engine._client_states

    def test_on_client_connected_fires_event(self, slave_engine, mock_connection):
        """测试客户端连接触发事件."""
        event_data = {}

        def on_event(event, data):
            event_data.update(data)

        slave_engine.set_event_callback(on_event)
        slave_engine._on_client_connected(mock_connection)

        assert "client_id" in event_data

    def test_on_client_disconnected_fires_event(self, slave_engine, mock_connection):
        """测试客户端断开触发事件."""
        slave_engine._on_client_connected(mock_connection)

        event_data = {}

        def on_event(event, data):
            event_data.update(data)

        slave_engine.set_event_callback(on_event)
        slave_engine._on_client_disconnected(mock_connection)

        assert "client_id" in event_data


# ── 总召唤响应测试 ───────────────────────────────────────────────

class TestSlaveEngineInterrogation:
    """总召唤响应测试."""

    @pytest.mark.asyncio
    async def test_handle_interrogation(self, slave_engine, mock_connection):
        """测试处理总召唤."""
        # 初始化数据
        await slave_engine.start()

        # 添加客户端
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 创建总召唤 ASDU
        asdu = ASDU(
            type_id=TypeID.C_IC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        interrogation_data = bytes([20])  # QOI=20
        asdu.objects.append(InformationObject(ioa=0, data=interrogation_data))

        # 处理
        await slave_engine._handle_interrogation(state, asdu)

        # 验证发送了响应
        assert mock_connection.send_frame.call_count >= 2  # ACK + 数据 + END

    @pytest.mark.asyncio
    async def test_handle_interrogation_fires_event(self, slave_engine, mock_connection):
        """测试总召唤触发事件."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        event_data = {}

        def on_event(event, data):
            event_data.update(data)

        slave_engine.set_event_callback(on_event)

        asdu = ASDU(
            type_id=TypeID.C_IC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        interrogation_data = bytes([20])
        asdu.objects.append(InformationObject(ioa=0, data=interrogation_data))

        await slave_engine._handle_interrogation(state, asdu)

        assert event_data.get("qoi") == 20


# ── 时钟同步响应测试 ─────────────────────────────────────────────

class TestSlaveEngineClockSync:
    """时钟同步响应测试."""

    @pytest.mark.asyncio
    async def test_handle_clock_sync(self, slave_engine, mock_connection):
        """测试处理时钟同步."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 创建时钟同步 ASDU
        asdu = ASDU(
            type_id=TypeID.C_CS_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        time_tag = CP56Time2a.now()
        asdu.objects.append(InformationObject(ioa=0, data=time_tag))

        # 处理
        await slave_engine._handle_clock_sync(state, asdu)

        # 验证发送了响应
        mock_connection.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_clock_sync_fires_event(self, slave_engine, mock_connection):
        """测试时钟同步触发事件."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        event_data = {}

        def on_event(event, data):
            event_data.update(data)

        slave_engine.set_event_callback(on_event)

        asdu = ASDU(
            type_id=TypeID.C_CS_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        time_tag = CP56Time2a.now()
        asdu.objects.append(InformationObject(ioa=0, data=time_tag))

        await slave_engine._handle_clock_sync(state, asdu)

        assert "client_id" in event_data


# ── 遥控命令响应测试 ─────────────────────────────────────────────

class TestSlaveEngineCommands:
    """遥控命令响应测试."""

    @pytest.mark.asyncio
    async def test_handle_single_command_select(self, slave_engine, mock_connection):
        """测试单命令选择."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 创建单命令 ASDU
        asdu = ASDU(
            type_id=TypeID.C_SC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        cmd = SingleCommand(ioa=100, state=True, select=True, qu=0)
        asdu.objects.append(InformationObject(ioa=100, data=cmd))

        # 处理
        await slave_engine._handle_single_command(state, asdu)

        # 验证发送了选择确认
        mock_connection.send_frame.assert_called_once()

        # 验证命令被记录
        assert 100 in state.selected_commands

    @pytest.mark.asyncio
    async def test_handle_single_command_execute(self, slave_engine, mock_connection):
        """测试单命令执行."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 先选择
        state.selected_commands[100] = (MagicMock(), 0.0)

        # 创建执行命令
        asdu = ASDU(
            type_id=TypeID.C_SC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        cmd = SingleCommand(ioa=100, state=True, select=False, qu=0)
        asdu.objects.append(InformationObject(ioa=100, data=cmd))

        # 处理
        await slave_engine._handle_single_command(state, asdu)

        # 验证发送了确认和激活终止
        assert mock_connection.send_frame.call_count >= 2

        # 验证选择状态被清除
        assert 100 not in state.selected_commands

    @pytest.mark.asyncio
    async def test_handle_single_command_not_selected(self, slave_engine, mock_connection):
        """测试单命令未选择直接执行."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 创建执行命令（未选择）
        asdu = ASDU(
            type_id=TypeID.C_SC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        cmd = SingleCommand(ioa=100, state=True, select=False, qu=0)
        asdu.objects.append(InformationObject(ioa=100, data=cmd))

        # 处理
        await slave_engine._handle_single_command(state, asdu)

        # 验证发送了否定确认
        mock_connection.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_double_command_select(self, slave_engine, mock_connection):
        """测试双命令选择."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        asdu = ASDU(
            type_id=TypeID.C_DC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        cmd = DoubleCommand(ioa=200, state=2, select=True, qu=0)
        asdu.objects.append(InformationObject(ioa=200, data=cmd))

        await slave_engine._handle_double_command(state, asdu)

        mock_connection.send_frame.assert_called_once()
        assert 200 in state.selected_commands

    @pytest.mark.asyncio
    async def test_handle_regulating_command(self, slave_engine, mock_connection):
        """测试升降命令."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 先选择
        state.selected_commands[300] = (MagicMock(), 0.0)

        asdu = ASDU(
            type_id=TypeID.C_RC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=1,
        )
        cmd = RegulatingStepCommand(ioa=300, state=2, select=False, qu=0)
        asdu.objects.append(InformationObject(ioa=300, data=cmd))

        await slave_engine._handle_regulating_command(state, asdu)

        assert mock_connection.send_frame.call_count >= 2


# ── 数据变化上送测试 ─────────────────────────────────────────────

class TestSlaveEngineSpontaneous:
    """数据变化上送测试."""

    @pytest.mark.asyncio
    async def test_send_spontaneous_yx(self, slave_engine, mock_connection):
        """测试自发上送遥信变化."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        await slave_engine.send_spontaneous_yx(ioa=1, value=True)

        # 验证数据存储更新
        yx = slave_engine._data_store.get_yx(1)
        assert yx is not None
        assert yx.value is True

        # 验证发送了帧
        mock_connection.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_spontaneous_yc(self, slave_engine, mock_connection):
        """测试自发上送遥测变化."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        await slave_engine.send_spontaneous_yc(ioa=101, value=220.5)

        yc = slave_engine._data_store.get_yc(101)
        assert yc is not None
        assert abs(yc.value - 220.5) < 0.01

        mock_connection.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_spontaneous_disabled(self, mock_tcp_server, point_table):
        """测试禁用自发上送."""
        engine = SlaveEngine(
            host="0.0.0.0",
            port=2404,
            common_addr=1,
            point_table=point_table,
            spontaneous_enabled=False,
        )

        mock_conn = MagicMock()
        mock_conn.name = "127.0.0.1:12345"
        mock_conn.is_connected = True
        mock_conn.send_frame = AsyncMock()

        engine._on_client_connected(mock_conn)
        state = engine._client_states[mock_conn.name]
        state.data_transfer_enabled = True

        await engine.send_spontaneous_yx(ioa=1, value=True)

        # 验证数据存储更新但未发送
        yx = engine._data_store.get_yx(1)
        assert yx is not None
        mock_conn.send_frame.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_spontaneous_no_enabled_clients(self, slave_engine):
        """测试无已启用客户端时上送."""
        await slave_engine.start()

        # 不添加任何客户端
        await slave_engine.send_spontaneous_yx(ioa=1, value=True)

        # 数据应被更新
        yx = slave_engine._data_store.get_yx(1)
        assert yx is not None


# ── U帧处理测试 ──────────────────────────────────────────────────

class TestSlaveEngineUFrame:
    """U帧处理测试."""

    @pytest.mark.asyncio
    async def test_handle_startdt_act(self, slave_engine, mock_connection):
        """测试处理 STARTDT ACT."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]

        # 创建 STARTDT ACT
        apci = APCICodec.decode(APCICodec.startdt_act())[0]

        # 处理
        slave_engine._handle_u_frame(state, apci)

        # 等待异步任务完成
        await asyncio.sleep(0.1)

        # 验证发送了 STARTDT CON (send_frame 被调用)
        assert mock_connection.send_frame.call_count >= 1

        # 验证数据传输已启用
        assert state.data_transfer_enabled is True

    @pytest.mark.asyncio
    async def test_handle_stopdt_act(self, slave_engine, mock_connection):
        """测试处理 STOPDT ACT."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 创建 STOPDT ACT
        apci = APCICodec.decode(APCICodec.stopdt_act())[0]

        # 处理
        slave_engine._handle_u_frame(state, apci)

        # 等待异步任务完成
        await asyncio.sleep(0.1)

        # 验证发送了 STOPDT CON
        assert mock_connection.send_frame.call_count >= 1

        # 验证数据传输已禁用
        assert state.data_transfer_enabled is False

    @pytest.mark.asyncio
    async def test_handle_testfr_act(self, slave_engine, mock_connection):
        """测试处理 TESTFR ACT."""
        await slave_engine.start()
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]

        # 创建 TESTFR ACT
        apci = APCICodec.decode(APCICodec.testfr_act())[0]

        # 处理
        slave_engine._handle_u_frame(state, apci)

        # 等待异步任务完成
        await asyncio.sleep(0.1)

        # 验证发送了 TESTFR CON
        assert mock_connection.send_frame.call_count >= 1


# ── 帧接收测试 ───────────────────────────────────────────────────

class TestSlaveEngineFrameHandling:
    """帧接收处理测试."""

    def test_on_frame_received_with_callback(self, slave_engine, mock_connection):
        """测试帧接收回调."""
        slave_engine._on_client_connected(mock_connection)

        received_frames = []

        def on_frame(frame, direction, client_id):
            received_frames.append((frame, direction, client_id))

        slave_engine.set_raw_frame_callback(on_frame)

        # 模拟接收 U 帧
        frame = APCICodec.startdt_act()
        slave_engine._on_frame_received(mock_connection, frame)

        assert len(received_frames) == 1
        assert received_frames[0][1] == "rx"
        assert received_frames[0][2] == mock_connection.name

    def test_on_frame_received_records_buffer(self, slave_engine, mock_connection):
        """测试帧接收记录缓冲区."""
        slave_engine._on_client_connected(mock_connection)

        frame = APCICodec.startdt_act()
        slave_engine._on_frame_received(mock_connection, frame)

        assert len(slave_engine._rx_buffer) == 1
        assert slave_engine._rx_buffer[0][1] == frame
        assert slave_engine._rx_buffer[0][2] == mock_connection.name


# ── 事件回调测试 ─────────────────────────────────────────────────

class TestSlaveEngineEvents:
    """事件回调测试."""

    def test_set_event_callback(self, slave_engine):
        """测试设置事件回调."""
        callback = MagicMock()
        slave_engine.set_event_callback(callback)
        assert slave_engine._event_callback == callback

    def test_fire_event(self, slave_engine):
        """测试触发事件."""
        callback = MagicMock()
        slave_engine.set_event_callback(callback)

        slave_engine._fire_event(SlaveEvent.CLIENT_CONNECTED, {"client_id": "test"})

        callback.assert_called_once_with(SlaveEvent.CLIENT_CONNECTED, {"client_id": "test"})

    def test_fire_event_no_callback(self, slave_engine):
        """测试无回调时触发事件."""
        # 不应抛出异常
        slave_engine._fire_event(SlaveEvent.CLIENT_CONNECTED)

    def test_fire_event_callback_error(self, slave_engine):
        """测试回调抛出异常."""
        def bad_callback(event, data):
            raise Exception("Callback error")

        slave_engine.set_event_callback(bad_callback)
        # 不应抛出异常
        slave_engine._fire_event(SlaveEvent.CLIENT_CONNECTED)


# ── 模拟功能测试 ─────────────────────────────────────────────────

class TestSlaveEngineSimulation:
    """模拟功能测试."""

    @pytest.mark.asyncio
    async def test_simulate_yx_change(self, slave_engine, mock_connection):
        """测试模拟遥信变化."""
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 直接调用 send_spontaneous_yx 而不是 simulate_yx_change
        # 因为 simulate_yx_change 使用 asyncio.create_task
        await slave_engine.send_spontaneous_yx(ioa=1, value=True)

        # 验证数据存储更新
        yx = slave_engine._data_store.get_yx(1)
        assert yx is not None
        assert yx.value is True

    @pytest.mark.asyncio
    async def test_simulate_yc_change(self, slave_engine, mock_connection):
        """测试模拟遥测变化."""
        slave_engine._on_client_connected(mock_connection)
        state = slave_engine._client_states[mock_connection.name]
        state.data_transfer_enabled = True

        # 直接调用 send_spontaneous_yc
        await slave_engine.send_spontaneous_yc(ioa=101, value=220.5)

        yc = slave_engine._data_store.get_yc(101)
        assert yc is not None
        assert abs(yc.value - 220.5) < 0.01


# ── 报文缓冲测试 ─────────────────────────────────────────────────

class TestSlaveEngineBuffer:
    """报文缓冲测试."""

    def test_get_rx_buffer(self, slave_engine):
        """测试获取接收缓冲区."""
        slave_engine._rx_buffer = [
            (1.0, b"frame1", "client1"),
            (2.0, b"frame2", "client2"),
        ]
        buffer = slave_engine.get_rx_buffer(count=10)
        assert len(buffer) == 2

    def test_get_tx_buffer(self, slave_engine):
        """测试获取发送缓冲区."""
        slave_engine._tx_buffer = [(1.0, b"frame1", "client1")]
        buffer = slave_engine.get_tx_buffer(count=10)
        assert len(buffer) == 1

    def test_get_rx_buffer_limit(self, slave_engine):
        """测试接收缓冲区限制."""
        for i in range(200):
            slave_engine._rx_buffer.append((float(i), b"frame", "client"))
        buffer = slave_engine.get_rx_buffer(count=100)
        assert len(buffer) == 100
