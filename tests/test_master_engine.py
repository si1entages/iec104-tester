"""主站引擎 Mock 测试.

测试 MasterEngine 的核心功能:
- 初始化
- 连接管理 (STARTDT/STOPDT)
- 总召唤命令
- 时钟同步命令
- 遥控命令
- ASDU 处理
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from core.engine.master import MasterEngine, MasterEvent
from core.protocol.apci import APCICodec, APCI
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject
from core.protocol.types import (
    TypeID, COT, QualityDescriptor,
    SinglePoint, DoublePoint, ShortFloat, CP56Time2a,
    SingleCommand, DoubleCommand,
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mock_tcp_client():
    """模拟 TCPClient."""
    with patch("core.engine.master.TCPClient") as MockClient:
        client = MockClient.return_value
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.send = AsyncMock()
        client.stats = MagicMock()
        yield client


@pytest.fixture
def master_engine(mock_tcp_client):
    """创建 MasterEngine 实例."""
    engine = MasterEngine(
        host="127.0.0.1",
        port=2404,
        common_addr=1,
        auto_start=False,
        auto_gi=False,
        reconnect=False,
    )
    return engine


@pytest.fixture
def running_engine(master_engine):
    """创建已启动的 MasterEngine."""
    from core.protocol.types import ConnState
    # 模拟状态机处于运行状态
    master_engine._state_machine._state = ConnState.RUNNING
    return master_engine


# ── 初始化测试 ───────────────────────────────────────────────────

class TestMasterEngineInit:
    """MasterEngine 初始化测试."""

    def test_default_params(self, master_engine):
        """测试默认参数."""
        assert master_engine._host == "127.0.0.1"
        assert master_engine._port == 2404
        assert master_engine._common_addr == 1
        assert master_engine._auto_start is False
        assert master_engine._auto_gi is False

    def test_custom_params(self, mock_tcp_client):
        """测试自定义参数."""
        engine = MasterEngine(
            host="192.168.1.100",
            port=2405,
            common_addr=2,
            k=20,
            w=10,
            auto_start=True,
            auto_gi=True,
        )
        assert engine._host == "192.168.1.100"
        assert engine._port == 2405
        assert engine._common_addr == 2
        assert engine._auto_start is True
        assert engine._auto_gi is True

    def test_initial_state(self, master_engine):
        """测试初始状态."""
        assert master_engine._event_callback is None
        assert master_engine._raw_frame_callback is None
        assert master_engine._recorder is None
        assert master_engine._timer_task is None
        assert master_engine._rx_buffer == []
        assert master_engine._tx_buffer == []

    def test_properties(self, master_engine):
        """测试属性访问."""
        assert master_engine.data_store is not None
        assert master_engine.sequence_manager is not None
        assert master_engine.scheduler is not None


# ── 生命周期测试 ─────────────────────────────────────────────────

class TestMasterEngineLifecycle:
    """MasterEngine 生命周期测试."""

    @pytest.mark.asyncio
    async def test_start(self, master_engine, mock_tcp_client):
        """测试启动."""
        await master_engine.start()
        mock_tcp_client.start.assert_called_once()
        assert master_engine._timer_task is not None

    @pytest.mark.asyncio
    async def test_stop(self, master_engine, mock_tcp_client):
        """测试停止."""
        await master_engine.start()
        await master_engine.stop()
        mock_tcp_client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, master_engine, mock_tcp_client):
        """测试完整生命周期."""
        await master_engine.start()
        assert master_engine._timer_task is not None

        await master_engine.stop()
        mock_tcp_client.stop.assert_called_once()


# ── 连接管理测试 ─────────────────────────────────────────────────

class TestMasterEngineConnection:
    """连接管理测试 (STARTDT/STOPDT)."""

    @pytest.mark.asyncio
    async def test_send_startdt(self, running_engine, mock_tcp_client):
        """测试发送 STARTDT ACT."""
        await running_engine.send_startdt()
        mock_tcp_client.send.assert_called_once()

        # 验证发送的是 U 帧
        call_args = mock_tcp_client.send.call_args[0][0]
        assert len(call_args) == 6
        assert call_args[0] == 0x68  # START_BYTE
        assert call_args[2] == 0x07  # STARTDT ACT

    @pytest.mark.asyncio
    async def test_send_stopdt(self, running_engine, mock_tcp_client):
        """测试发送 STOPDT ACT."""
        await running_engine.send_stopdt()
        mock_tcp_client.send.assert_called_once()

        call_args = mock_tcp_client.send.call_args[0][0]
        assert len(call_args) == 6
        assert call_args[0] == 0x68
        assert call_args[2] == 0x13  # STOPDT ACT

    @pytest.mark.asyncio
    async def test_on_tcp_connected_auto_start(self, mock_tcp_client):
        """测试 TCP 连接后自动发送 STARTDT."""
        engine = MasterEngine(
            host="127.0.0.1",
            port=2404,
            auto_start=True,
            reconnect=False,
        )
        # 模拟状态机
        engine._state_machine = MagicMock()

        # 触发连接回调
        engine._on_tcp_connected()

        # 验证状态机被调用
        engine._state_machine.on_connected.assert_called_once()

        # 等待自动 STARTDT 任务完成
        await asyncio.sleep(0.3)

    def test_on_tcp_disconnected(self, master_engine):
        """测试 TCP 断开回调."""
        master_engine._state_machine = MagicMock()
        event_data = {}

        def on_event(event, data):
            event_data.update(data)

        master_engine.set_event_callback(on_event)
        master_engine._on_tcp_disconnected()

        master_engine._state_machine.on_disconnected.assert_called_once()


# ── 总召唤测试 ───────────────────────────────────────────────────

class TestMasterEngineInterrogation:
    """总召唤命令测试."""

    @pytest.mark.asyncio
    async def test_general_interrogation(self, running_engine, mock_tcp_client):
        """测试发送总召唤命令."""
        await running_engine.general_interrogation(qoi=20)
        mock_tcp_client.send.assert_called_once()

        # 验证发送的是 I 帧
        call_args = mock_tcp_client.send.call_args[0][0]
        assert len(call_args) >= 6
        assert call_args[0] == 0x68
        assert (call_args[2] & 0x01) == 0  # I 帧标志

    @pytest.mark.asyncio
    async def test_general_interrogation_not_running(self, master_engine):
        """测试未启动时发送总召唤应抛出异常."""
        with pytest.raises(RuntimeError, match="Not in running state"):
            await master_engine.general_interrogation()

    @pytest.mark.asyncio
    async def test_general_interrogation_group(self, running_engine, mock_tcp_client):
        """测试组召唤."""
        await running_engine.general_interrogation(qoi=1)  # 第1组
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_general_interrogation_fires_event(self, running_engine, mock_tcp_client):
        """测试总召唤触发事件."""
        event_data = {}

        def on_event(event, data):
            event_data.update(data)

        running_engine.set_event_callback(on_event)
        await running_engine.general_interrogation(qoi=20)

        assert event_data.get("qoi") == 20


# ── 时钟同步测试 ─────────────────────────────────────────────────

class TestMasterEngineClockSync:
    """时钟同步命令测试."""

    @pytest.mark.asyncio
    async def test_clock_sync(self, running_engine, mock_tcp_client):
        """测试发送时钟同步命令."""
        await running_engine.clock_sync()
        mock_tcp_client.send.assert_called_once()

        call_args = mock_tcp_client.send.call_args[0][0]
        assert len(call_args) >= 6
        assert call_args[0] == 0x68

    @pytest.mark.asyncio
    async def test_clock_sync_not_running(self, master_engine):
        """测试未启动时发送时钟同步应抛出异常."""
        with pytest.raises(RuntimeError, match="Not in running state"):
            await master_engine.clock_sync()

    @pytest.mark.asyncio
    async def test_clock_sync_with_time_tag(self, running_engine, mock_tcp_client):
        """测试带时标的时钟同步."""
        time_tag = CP56Time2a.now()
        await running_engine.clock_sync(time_tag=time_tag)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_clock_sync_records_time(self, running_engine, mock_tcp_client):
        """测试时钟同步记录发送时间."""
        assert running_engine._last_clock_sync_sent_time is None
        await running_engine.clock_sync()
        assert running_engine._last_clock_sync_sent_time is not None


# ── 遥控命令测试 ─────────────────────────────────────────────────

class TestMasterEngineCommands:
    """遥控命令测试."""

    @pytest.mark.asyncio
    async def test_single_command_execute(self, running_engine, mock_tcp_client):
        """测试单命令执行."""
        await running_engine.single_command(ioa=100, state=True, select=False)
        mock_tcp_client.send.assert_called_once()

        call_args = mock_tcp_client.send.call_args[0][0]
        assert len(call_args) >= 6
        assert call_args[0] == 0x68

    @pytest.mark.asyncio
    async def test_single_command_select(self, running_engine, mock_tcp_client):
        """测试单命令选择."""
        await running_engine.single_command(ioa=100, state=True, select=True)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_single_command_not_running(self, master_engine):
        """测试未启动时发送单命令应抛出异常."""
        with pytest.raises(RuntimeError, match="Not in running state"):
            await master_engine.single_command(ioa=100, state=True)

    @pytest.mark.asyncio
    async def test_double_command(self, running_engine, mock_tcp_client):
        """测试双命令."""
        await running_engine.double_command(ioa=200, state=2, select=False)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_command_select(self, running_engine, mock_tcp_client):
        """测试双命令选择."""
        await running_engine.double_command(ioa=200, state=2, select=True)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_setpoint_normalized(self, running_engine, mock_tcp_client):
        """测试归一化设点命令."""
        await running_engine.setpoint_normalized(ioa=300, value=0.75)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_setpoint_shortfloat(self, running_engine, mock_tcp_client):
        """测试短浮点设点命令."""
        await running_engine.setpoint_shortfloat(ioa=300, value=220.5)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_regulating_step_command(self, running_engine, mock_tcp_client):
        """测试升降命令."""
        await running_engine.regulating_step_command(ioa=400, state=2)
        mock_tcp_client.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_command(self, running_engine, mock_tcp_client):
        """测试读命令."""
        await running_engine.read_command(ioa=100)
        mock_tcp_client.send.assert_called_once()


# ── ASDU 处理测试 ────────────────────────────────────────────────

class TestMasterEngineASDU:
    """ASDU 处理测试."""

    def test_process_single_point(self, master_engine):
        """测试处理单点遥信."""
        # 创建 ASDU
        asdu = ASDU(
            type_id=TypeID.M_SP_NA_1,
            sq=False,
            num=1,
            cot=COT.SPONT,
            common_addr=1,
        )
        sp = SinglePoint(value=True, quality=QualityDescriptor())
        asdu.objects.append(InformationObject(ioa=100, data=sp))

        # 处理
        master_engine._process_asdu(asdu)

        # 验证数据存储更新
        yx = master_engine._data_store.get_yx(100)
        assert yx is not None
        assert yx.value is True

    def test_process_double_point(self, master_engine):
        """测试处理双点遥信."""
        asdu = ASDU(
            type_id=TypeID.M_DP_NA_1,
            sq=False,
            num=1,
            cot=COT.SPONT,
            common_addr=1,
        )
        dp = DoublePoint(value=2, quality=QualityDescriptor())
        asdu.objects.append(InformationObject(ioa=200, data=dp))

        master_engine._process_asdu(asdu)

        yx = master_engine._data_store.get_yx(200)
        assert yx is not None

    def test_process_short_float(self, master_engine):
        """测试处理短浮点遥测."""
        asdu = ASDU(
            type_id=TypeID.M_ME_NC_1,
            sq=False,
            num=1,
            cot=COT.SPONT,
            common_addr=1,
        )
        sf = ShortFloat(value=220.5, quality=QualityDescriptor())
        asdu.objects.append(InformationObject(ioa=300, data=sf))

        master_engine._process_asdu(asdu)

        yc = master_engine._data_store.get_yc(300)
        assert yc is not None
        assert abs(yc.value - 220.5) < 0.01

    def test_process_command_ack(self, master_engine):
        """测试处理命令确认."""
        asdu = ASDU(
            type_id=TypeID.C_SC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACTCON,
            common_addr=1,
        )
        cmd = SingleCommand(ioa=100, state=True, select=False, qu=0)
        asdu.objects.append(InformationObject(ioa=100, data=cmd))

        master_engine._process_asdu(asdu)

        yk = master_engine._data_store.get_yk(100)
        assert yk is not None

    def test_process_clock_sync_ack(self, master_engine):
        """测试处理时钟同步确认."""
        # 先记录发送时间
        import time
        master_engine._last_clock_sync_sent_time = time.monotonic()

        asdu = ASDU(
            type_id=TypeID.C_CS_NA_1,
            sq=False,
            num=1,
            cot=COT.ACTCON,
            common_addr=1,
        )
        time_tag = CP56Time2a.now()
        asdu.objects.append(InformationObject(ioa=0, data=time_tag))

        master_engine._process_asdu(asdu)

        # 验证发送时间被清除
        assert master_engine._last_clock_sync_sent_time is None

    def test_process_gi_actcon(self, master_engine):
        """测试处理总召唤确认."""
        asdu = ASDU(
            type_id=TypeID.C_IC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACTCON,
            common_addr=1,
        )

        # 不应抛出异常
        master_engine._process_asdu(asdu)

    def test_process_common_addr_mismatch(self, master_engine):
        """测试公共地址不匹配."""
        asdu = ASDU(
            type_id=TypeID.M_SP_NA_1,
            sq=False,
            num=1,
            cot=COT.SPONT,
            common_addr=2,  # 不匹配
        )
        sp = SinglePoint(value=True, quality=QualityDescriptor())
        asdu.objects.append(InformationObject(ioa=100, data=sp))

        master_engine._process_asdu(asdu)

        # 数据不应被更新
        yx = master_engine._data_store.get_yx(100)
        assert yx is None

    def test_process_broadcast_addr(self, master_engine):
        """测试广播地址 (255)."""
        asdu = ASDU(
            type_id=TypeID.M_SP_NA_1,
            sq=False,
            num=1,
            cot=COT.SPONT,
            common_addr=255,  # 广播地址
        )
        sp = SinglePoint(value=True, quality=QualityDescriptor())
        asdu.objects.append(InformationObject(ioa=100, data=sp))

        # 广播地址不应被拒绝
        master_engine._process_asdu(asdu)


# ── 帧接收测试 ───────────────────────────────────────────────────

class TestMasterEngineFrameHandling:
    """帧接收处理测试."""

    def test_on_frame_received_u_frame(self, master_engine):
        """测试接收 U 帧."""
        master_engine._state_machine = MagicMock()

        # STARTDT CON
        frame = APCICodec.startdt_con()
        master_engine._on_frame_received(frame)

        master_engine._state_machine.on_any_frame_received.assert_called_once()

    def test_on_frame_received_s_frame(self, master_engine):
        """测试接收 S 帧."""
        master_engine._state_machine = MagicMock()

        frame = APCICodec.encode_s(0)
        master_engine._on_frame_received(frame)

        master_engine._state_machine.on_any_frame_received.assert_called_once()

    def test_on_frame_received_with_callback(self, master_engine):
        """测试帧接收回调."""
        received_frames = []

        def on_frame(frame, direction):
            received_frames.append((frame, direction))

        master_engine.set_raw_frame_callback(on_frame)

        frame = APCICodec.startdt_con()
        master_engine._state_machine = MagicMock()
        master_engine._on_frame_received(frame)

        assert len(received_frames) == 1
        assert received_frames[0][1] == "rx"

    def test_on_frame_received_records_buffer(self, master_engine):
        """测试帧接收记录缓冲区."""
        master_engine._state_machine = MagicMock()

        frame = APCICodec.startdt_con()
        master_engine._on_frame_received(frame)

        assert len(master_engine._rx_buffer) == 1
        assert master_engine._rx_buffer[0][1] == frame


# ── 事件回调测试 ─────────────────────────────────────────────────

class TestMasterEngineEvents:
    """事件回调测试."""

    def test_set_event_callback(self, master_engine):
        """测试设置事件回调."""
        callback = MagicMock()
        master_engine.set_event_callback(callback)
        assert master_engine._event_callback == callback

    def test_fire_event(self, master_engine):
        """测试触发事件."""
        callback = MagicMock()
        master_engine.set_event_callback(callback)

        master_engine._fire_event(MasterEvent.CONNECTED, {"test": True})

        callback.assert_called_once_with(MasterEvent.CONNECTED, {"test": True})

    def test_fire_event_no_callback(self, master_engine):
        """测试无回调时触发事件."""
        # 不应抛出异常
        master_engine._fire_event(MasterEvent.CONNECTED)

    def test_fire_event_callback_error(self, master_engine):
        """测试回调抛出异常."""
        def bad_callback(event, data):
            raise Exception("Callback error")

        master_engine.set_event_callback(bad_callback)
        # 不应抛出异常
        master_engine._fire_event(MasterEvent.CONNECTED)


# ── 定时器测试 ───────────────────────────────────────────────────

class TestMasterEngineTimers:
    """定时器测试."""

    def test_on_timer_expired_t3(self, master_engine, mock_tcp_client):
        """测试 T3 超时发送测试帧."""
        master_engine._on_timer_expired(MagicMock(value="T3"))
        # T3 超时应发送 TESTFR ACT

    def test_on_state_change(self, master_engine):
        """测试状态变化回调."""
        # 不应抛出异常
        master_engine._on_state_change("CONNECTED", "RUNNING")


# ── 报文缓冲测试 ─────────────────────────────────────────────────

class TestMasterEngineBuffer:
    """报文缓冲测试."""

    def test_get_rx_buffer(self, master_engine):
        """测试获取接收缓冲区."""
        master_engine._rx_buffer = [(1.0, b"frame1"), (2.0, b"frame2")]
        buffer = master_engine.get_rx_buffer(count=10)
        assert len(buffer) == 2

    def test_get_tx_buffer(self, master_engine):
        """测试获取发送缓冲区."""
        master_engine._tx_buffer = [(1.0, b"frame1")]
        buffer = master_engine.get_tx_buffer(count=10)
        assert len(buffer) == 1

    def test_get_rx_buffer_limit(self, master_engine):
        """测试接收缓冲区限制."""
        for i in range(200):
            master_engine._rx_buffer.append((float(i), b"frame"))
        buffer = master_engine.get_rx_buffer(count=100)
        assert len(buffer) == 100
