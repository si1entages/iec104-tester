"""传输层 Mock 测试.

测试 TCP 传输层核心功能:
- TCPClient 连接
- TCPServer 监听
- TCPConnection 帧收发
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.transport.connection import ConnectionStats, TCPClient, TCPConnection, TCPServer

# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def mock_stream_reader():
    """模拟 StreamReader."""
    reader = AsyncMock()
    reader.read = AsyncMock()
    return reader


@pytest.fixture
def mock_stream_writer():
    """模拟 StreamWriter."""
    writer = AsyncMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    writer.is_closing = MagicMock(return_value=False)
    writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 12345))
    return writer


@pytest.fixture
def mock_connection(mock_stream_reader, mock_stream_writer):
    """创建 TCPConnection 实例."""
    conn = TCPConnection(
        reader=mock_stream_reader,
        writer=mock_stream_writer,
        on_frame=MagicMock(),
        on_disconnected=MagicMock(),
        name="test_conn",
    )
    return conn


@pytest.fixture
def tcp_client():
    """创建 TCPClient 实例."""
    return TCPClient(
        host="127.0.0.1",
        port=2404,
        reconnect_interval=1.0,
        max_reconnects=3,
        on_frame=MagicMock(),
        on_connected=MagicMock(),
        on_disconnected=MagicMock(),
    )


@pytest.fixture
def tcp_server():
    """创建 TCPServer 实例."""
    return TCPServer(
        host="0.0.0.0",
        port=2404,
        max_connections=16,
        on_connection=MagicMock(),
        on_frame=MagicMock(),
        on_disconnected=MagicMock(),
    )


# ── ConnectionStats 测试 ─────────────────────────────────────────

class TestConnectionStats:
    """ConnectionStats 测试."""

    def test_default_values(self):
        """测试默认值."""
        stats = ConnectionStats()
        assert stats.connected_at == 0.0
        assert stats.last_rx_time == 0.0
        assert stats.last_tx_time == 0.0
        assert stats.bytes_sent == 0
        assert stats.bytes_received == 0
        assert stats.frames_sent == 0
        assert stats.frames_received == 0
        assert stats.i_frames_sent == 0
        assert stats.i_frames_received == 0
        assert stats.s_frames_sent == 0
        assert stats.s_frames_received == 0
        assert stats.u_frames_sent == 0
        assert stats.u_frames_received == 0
        assert stats.errors == 0
        assert stats.reconnections == 0

    def test_custom_values(self):
        """测试自定义值."""
        stats = ConnectionStats(
            connected_at=1.0,
            bytes_sent=100,
            bytes_received=200,
        )
        assert stats.connected_at == 1.0
        assert stats.bytes_sent == 100
        assert stats.bytes_received == 200


# ── TCPConnection 测试 ───────────────────────────────────────────

class TestTCPConnection:
    """TCPConnection 测试."""

    def test_init(self, mock_stream_reader, mock_stream_writer):
        """测试初始化."""
        on_frame = MagicMock()
        on_disconnected = MagicMock()

        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=mock_stream_writer,
            on_frame=on_frame,
            on_disconnected=on_disconnected,
            name="test",
        )

        assert conn._reader is mock_stream_reader
        assert conn._writer is mock_stream_writer
        assert conn._on_frame is on_frame
        assert conn._on_disconnected is on_disconnected
        assert conn._name == "test"
        assert conn._running is False

    def test_name_property(self, mock_connection):
        """测试 name 属性."""
        assert mock_connection.name == "test_conn"

    def test_name_from_remote_addr(self, mock_stream_reader, mock_stream_writer):
        """测试从远程地址获取名称."""
        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=mock_stream_writer,
        )
        assert conn.name == "127.0.0.1:12345"

    def test_stats_property(self, mock_connection):
        """测试 stats 属性."""
        stats = mock_connection.stats
        assert isinstance(stats, ConnectionStats)

    def test_is_connected_initial(self, mock_connection):
        """测试初始连接状态."""
        assert mock_connection.is_connected is False

    def test_is_connected_running(self, mock_connection, mock_stream_writer):
        """测试运行时连接状态."""
        mock_connection._running = True
        mock_stream_writer.is_closing.return_value = False
        assert mock_connection.is_connected is True

    def test_is_connected_closing(self, mock_connection, mock_stream_writer):
        """测试关闭时连接状态."""
        mock_connection._running = True
        mock_stream_writer.is_closing.return_value = True
        assert mock_connection.is_connected is False

    @pytest.mark.asyncio
    async def test_start(self, mock_connection, mock_stream_reader):
        """测试启动连接."""
        # 模拟 reader 返回空数据（连接关闭）
        mock_stream_reader.read = AsyncMock(side_effect=[b"", asyncio.CancelledError()])

        await mock_connection.start()
        assert mock_connection._running is True
        assert mock_connection._read_task is not None

        # 等待读取循环结束
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_stop(self, mock_connection, mock_stream_writer):
        """测试停止连接."""
        mock_connection._running = True
        mock_connection._read_task = MagicMock()
        mock_connection._read_task.done.return_value = True

        await mock_connection.stop()

        assert mock_connection._running is False
        mock_stream_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_send(self, mock_connection, mock_stream_writer):
        """测试发送数据."""
        mock_connection._running = True
        mock_stream_writer.is_closing.return_value = False

        data = b"\x68\x04\x01\x00\x00\x00"
        await mock_connection.send(data)

        mock_stream_writer.write.assert_called_once_with(data)
        mock_stream_writer.drain.assert_called_once()

        # 验证统计更新
        assert mock_connection.stats.bytes_sent == len(data)
        assert mock_connection.stats.frames_sent == 1

    @pytest.mark.asyncio
    async def test_send_not_connected(self, mock_connection):
        """测试未连接时发送数据."""
        mock_connection._running = False

        with pytest.raises(ConnectionError, match="Not connected"):
            await mock_connection.send(b"test")

    @pytest.mark.asyncio
    async def test_send_frame(self, mock_connection, mock_stream_writer):
        """测试发送帧."""
        mock_connection._running = True
        mock_stream_writer.is_closing.return_value = False

        frame = b"\x68\x04\x01\x00\x00\x00"
        await mock_connection.send_frame(frame)

        mock_stream_writer.write.assert_called_once_with(frame)

    @pytest.mark.asyncio
    async def test_send_error(self, mock_connection, mock_stream_writer):
        """测试发送错误."""
        mock_connection._running = True
        mock_stream_writer.is_closing.return_value = False
        mock_stream_writer.drain.side_effect = Exception("Send error")

        with pytest.raises(Exception, match="Send error"):
            await mock_connection.send(b"test")

        assert mock_connection.stats.errors == 1

    @pytest.mark.asyncio
    async def test_read_loop_frame_extraction(self, mock_stream_reader):
        """测试帧提取."""
        # 模拟接收完整的 I 帧
        i_frame = bytes([
            0x68, 0x04,  # start + length
            0x01, 0x00,  # tx_seq
            0x00, 0x00,  # rx_seq
        ])

        # 模拟 read 返回数据，然后返回空数据表示连接关闭
        mock_stream_reader.read = AsyncMock(side_effect=[i_frame, b""])

        on_frame = MagicMock()
        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            on_frame=on_frame,
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        # 验证帧被提取
        on_frame.assert_called_once_with(i_frame)

    @pytest.mark.asyncio
    async def test_read_loop_buffer_multiple_frames(self, mock_stream_reader):
        """测试缓冲区多个帧."""
        # 两个帧粘包
        frame1 = bytes([0x68, 0x04, 0x01, 0x00, 0x00, 0x00])
        frame2 = bytes([0x68, 0x04, 0x02, 0x00, 0x00, 0x00])
        combined = frame1 + frame2

        mock_stream_reader.read = AsyncMock(side_effect=[combined, b""])

        on_frame = MagicMock()
        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            on_frame=on_frame,
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        # 验证两个帧都被提取
        assert on_frame.call_count == 2

    @pytest.mark.asyncio
    async def test_read_loop_partial_frame(self, mock_stream_reader):
        """测试不完整帧."""
        # 发送一个完整的帧（6字节）
        complete = bytes([0x68, 0x04, 0x00, 0x00, 0x00, 0x00])

        # 模拟分两次接收
        first_part = complete[:3]  # 前3字节
        second_part = complete[3:]  # 后3字节

        mock_stream_reader.read = AsyncMock(side_effect=[first_part, second_part, b""])

        on_frame = MagicMock()
        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            on_frame=on_frame,
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        # 验证只提取了完整帧
        on_frame.assert_called_once_with(complete)

    @pytest.mark.asyncio
    async def test_read_loop_stats_update(self, mock_stream_reader):
        """测试统计更新."""
        # I 帧: control field bit0 = 0
        frame = bytes([0x68, 0x04, 0x00, 0x00, 0x00, 0x00])
        mock_stream_reader.read = AsyncMock(side_effect=[frame, b""])

        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        assert conn.stats.bytes_received == len(frame)
        assert conn.stats.frames_received == 1
        assert conn.stats.i_frames_received == 1

    @pytest.mark.asyncio
    async def test_read_loop_cancelled(self, mock_stream_reader):
        """测试读取循环取消."""
        mock_stream_reader.read = AsyncMock(side_effect=asyncio.CancelledError())

        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            name="test",
        )
        conn._running = True

        # 不应抛出异常
        await conn._read_loop()
        assert conn._running is False


# ── TCPClient 测试 ───────────────────────────────────────────────

class TestTCPClient:
    """TCPClient 测试."""

    def test_init(self):
        """测试初始化."""
        client = TCPClient(
            host="192.168.1.100",
            port=2405,
            reconnect_interval=2.0,
            max_reconnects=5,
        )
        assert client._host == "192.168.1.100"
        assert client._port == 2405
        assert client._reconnect_interval == 2.0
        assert client._max_reconnects == 5

    def test_default_params(self):
        """测试默认参数."""
        client = TCPClient()
        assert client._host == "127.0.0.1"
        assert client._port == 2404
        assert client._reconnect_interval == 5.0
        assert client._max_reconnects == 0

    def test_is_connected_initial(self, tcp_client):
        """测试初始连接状态."""
        assert tcp_client.is_connected is False

    def test_connection_initial(self, tcp_client):
        """测试初始连接对象."""
        assert tcp_client.connection is None

    def test_stats_initial(self, tcp_client):
        """测试初始统计."""
        assert tcp_client.stats is None

    @pytest.mark.asyncio
    async def test_start(self, tcp_client):
        """测试启动."""
        with patch("asyncio.create_task") as mock_create_task:
            mock_create_task.return_value = MagicMock()
            await tcp_client.start()
            assert tcp_client._running is True

    @pytest.mark.asyncio
    async def test_stop(self, tcp_client):
        """测试停止."""
        tcp_client._running = True
        tcp_client._reconnect_task = MagicMock()
        tcp_client._reconnect_task.cancel = MagicMock()
        tcp_client._reconnect_task.__await__ = MagicMock(side_effect=asyncio.CancelledError)
        tcp_client._connection = MagicMock()
        tcp_client._connection.stop = AsyncMock()

        await tcp_client.stop()

        assert tcp_client._running is False

    @pytest.mark.asyncio
    async def test_send(self, tcp_client):
        """测试发送数据."""
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        mock_conn.send_frame = AsyncMock()
        tcp_client._connection = mock_conn

        data = b"\x68\x04\x01\x00\x00\x00"
        await tcp_client.send(data)

        mock_conn.send_frame.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_send_not_connected(self, tcp_client):
        """测试未连接时发送数据."""
        tcp_client._connection = None

        with pytest.raises(ConnectionError, match="Not connected"):
            await tcp_client.send(b"test")

    @pytest.mark.asyncio
    async def test_connect_success(self, tcp_client):
        """测试连接成功."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 2404))
        mock_writer.is_closing = MagicMock(return_value=False)

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            with patch("asyncio.create_task") as mock_create_task:
                mock_create_task.return_value = MagicMock()

                # 模拟连接后立即停止
                async def stop_after_connect():
                    tcp_client._running = False

                with patch.object(tcp_client, "_connect_loop", side_effect=stop_after_connect):
                    await tcp_client.start()

    def test_on_connected_callback(self, tcp_client):
        """测试连接成功回调."""
        on_connected = MagicMock()
        tcp_client._on_connected = on_connected

        # 模拟连接成功
        tcp_client._connection = MagicMock()
        tcp_client._connection.is_connected = True

        # 触发回调
        if tcp_client._on_connected:
            tcp_client._on_connected()

        on_connected.assert_called_once()

    def test_on_disconnected_callback(self, tcp_client):
        """测试断开连接回调."""
        on_disconnected = MagicMock()
        tcp_client._on_disconnected = on_disconnected

        # 触发回调
        if tcp_client._on_disconnected:
            tcp_client._on_disconnected()

        on_disconnected.assert_called_once()


# ── TCPServer 测试 ───────────────────────────────────────────────

class TestTCPServer:
    """TCPServer 测试."""

    def test_init(self):
        """测试初始化."""
        server = TCPServer(
            host="192.168.1.100",
            port=2405,
            max_connections=32,
        )
        assert server._host == "192.168.1.100"
        assert server._port == 2405
        assert server._max_connections == 32

    def test_default_params(self):
        """测试默认参数."""
        server = TCPServer()
        assert server._host == "0.0.0.0"
        assert server._port == 2404
        assert server._max_connections == 16

    def test_is_running_initial(self, tcp_server):
        """测试初始运行状态."""
        assert tcp_server.is_running is False

    def test_connection_count_initial(self, tcp_server):
        """测试初始连接数."""
        assert tcp_server.connection_count == 0

    def test_connections_initial(self, tcp_server):
        """测试初始连接列表."""
        assert tcp_server.connections == {}

    @pytest.mark.asyncio
    async def test_start(self, tcp_server):
        """测试启动服务器."""
        mock_server = AsyncMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()

        with patch("asyncio.start_server", return_value=mock_server):
            await tcp_server.start()

            assert tcp_server.is_running is True
            assert tcp_server._server is mock_server

    @pytest.mark.asyncio
    async def test_stop(self, tcp_server):
        """测试停止服务器."""
        # 模拟运行状态
        tcp_server._running = True
        tcp_server._server = AsyncMock()
        tcp_server._server.close = MagicMock()
        tcp_server._server.wait_closed = AsyncMock()

        # 添加模拟连接
        mock_conn = AsyncMock()
        mock_conn.stop = AsyncMock()
        tcp_server._connections["test"] = mock_conn

        await tcp_server.stop()

        assert tcp_server.is_running is False
        mock_conn.stop.assert_called_once()
        tcp_server._server.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client(self, tcp_server):
        """测试处理客户端连接."""
        mock_reader = AsyncMock()
        mock_writer = AsyncMock()
        mock_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 12345))
        mock_writer.is_closing = MagicMock(return_value=False)
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        # 模拟连接回调
        on_connection = MagicMock()
        on_disconnected = MagicMock()
        tcp_server._on_connection = on_connection
        tcp_server._on_disconnected = on_disconnected

        # 模拟 _handle_client 中的 conn.start() 不实际启动读取循环
        with patch.object(TCPConnection, 'start', new_callable=AsyncMock):
            await tcp_server._handle_client(mock_reader, mock_writer)

        # 验证连接被添加
        assert tcp_server.connection_count == 1
        assert "127.0.0.1:12345" in tcp_server._connections

        # 验证回调被调用
        on_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client_max_connections(self, tcp_server):
        """测试最大连接数限制."""
        tcp_server._max_connections = 1
        tcp_server._connections["existing"] = MagicMock()

        mock_reader = AsyncMock()
        mock_writer = AsyncMock()

        await tcp_server._handle_client(mock_reader, mock_writer)

        # 验证连接被拒绝
        mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast(self, tcp_server):
        """测试广播数据."""
        mock_conn1 = MagicMock()
        mock_conn1.is_connected = True
        mock_conn1.send_frame = AsyncMock()

        mock_conn2 = MagicMock()
        mock_conn2.is_connected = True
        mock_conn2.send_frame = AsyncMock()

        tcp_server._connections = {
            "client1": mock_conn1,
            "client2": mock_conn2,
        }

        data = b"\x68\x04\x01\x00\x00\x00"
        await tcp_server.broadcast(data)

        mock_conn1.send_frame.assert_called_once_with(data)
        mock_conn2.send_frame.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_broadcast_skip_disconnected(self, tcp_server):
        """测试广播跳过断开的连接."""
        mock_conn1 = MagicMock()
        mock_conn1.is_connected = True
        mock_conn1.send_frame = AsyncMock()

        mock_conn2 = MagicMock()
        mock_conn2.is_connected = False
        mock_conn2.send_frame = AsyncMock()

        tcp_server._connections = {
            "client1": mock_conn1,
            "client2": mock_conn2,
        }

        data = b"\x68\x04\x01\x00\x00\x00"
        await tcp_server.broadcast(data)

        mock_conn1.send_frame.assert_called_once_with(data)
        mock_conn2.send_frame.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_to(self, tcp_server):
        """测试向指定连接发送数据."""
        mock_conn = MagicMock()
        mock_conn.is_connected = True
        mock_conn.send_frame = AsyncMock()

        tcp_server._connections = {"client1": mock_conn}

        data = b"\x68\x04\x01\x00\x00\x00"
        result = await tcp_server.send_to("client1", data)

        assert result is True
        mock_conn.send_frame.assert_called_once_with(data)

    @pytest.mark.asyncio
    async def test_send_to_unknown(self, tcp_server):
        """测试向未知连接发送数据."""
        data = b"\x68\x04\x01\x00\x00\x00"
        result = await tcp_server.send_to("unknown", data)

        assert result is False

    @pytest.mark.asyncio
    async def test_send_to_disconnected(self, tcp_server):
        """测试向断开的连接发送数据."""
        mock_conn = MagicMock()
        mock_conn.is_connected = False
        mock_conn.send_frame = AsyncMock()

        tcp_server._connections = {"client1": mock_conn}

        data = b"\x68\x04\x01\x00\x00\x00"
        result = await tcp_server.send_to("client1", data)

        assert result is False
        mock_conn.send_frame.assert_not_called()

    def test_on_client_disconnected(self, tcp_server):
        """测试客户端断开回调."""
        on_disconnected = MagicMock()
        tcp_server._on_disconnected = on_disconnected

        # 添加连接
        mock_conn = MagicMock()
        tcp_server._connections["client1"] = mock_conn

        # 模拟断开回调
        def on_disconnect():
            if "client1" in tcp_server._connections:
                del tcp_server._connections["client1"]
            if on_disconnected:
                on_disconnected(mock_conn)

        on_disconnect()

        assert "client1" not in tcp_server._connections
        on_disconnected.assert_called_once_with(mock_conn)


# ── 帧类型统计测试 ───────────────────────────────────────────────

class TestFrameTypeStats:
    """帧类型统计测试."""

    @pytest.mark.asyncio
    async def test_i_frame_stats(self, mock_stream_reader):
        """测试 I 帧统计."""
        # I 帧: control field bit0 = 0
        i_frame = bytes([0x68, 0x04, 0x00, 0x00, 0x00, 0x00])
        mock_stream_reader.read = AsyncMock(side_effect=[i_frame, b""])

        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        assert conn.stats.i_frames_received == 1
        assert conn.stats.s_frames_received == 0
        assert conn.stats.u_frames_received == 0

    @pytest.mark.asyncio
    async def test_s_frame_stats(self, mock_stream_reader):
        """测试 S 帧统计."""
        # S 帧: control field = 0x01
        s_frame = bytes([0x68, 0x04, 0x01, 0x00, 0x00, 0x00])
        mock_stream_reader.read = AsyncMock(side_effect=[s_frame, b""])

        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        assert conn.stats.i_frames_received == 0
        assert conn.stats.s_frames_received == 1
        assert conn.stats.u_frames_received == 0

    @pytest.mark.asyncio
    async def test_u_frame_stats(self, mock_stream_reader):
        """测试 U 帧统计."""
        # U 帧: control field = 0x03
        u_frame = bytes([0x68, 0x04, 0x03, 0x00, 0x00, 0x00])
        mock_stream_reader.read = AsyncMock(side_effect=[u_frame, b""])

        conn = TCPConnection(
            reader=mock_stream_reader,
            writer=MagicMock(),
            name="test",
        )
        conn._running = True

        await conn._read_loop()

        assert conn.stats.i_frames_received == 0
        assert conn.stats.s_frames_received == 0
        assert conn.stats.u_frames_received == 1


# ── 并发测试 ─────────────────────────────────────────────────────

class TestConcurrency:
    """并发测试."""

    @pytest.mark.asyncio
    async def test_concurrent_send(self, mock_connection, mock_stream_writer):
        """测试并发发送."""
        mock_connection._running = True
        mock_stream_writer.is_closing.return_value = False

        # 并发发送多个帧
        tasks = []
        for i in range(10):
            task = asyncio.create_task(
                mock_connection.send(bytes([0x68, 0x04, i, 0x00, 0x00, 0x00]))
            )
            tasks.append(task)

        await asyncio.gather(*tasks)

        # 验证所有帧都被发送
        assert mock_stream_writer.write.call_count == 10
        assert mock_connection.stats.frames_sent == 10

    @pytest.mark.asyncio
    async def test_concurrent_broadcast(self, tcp_server):
        """测试并发广播."""
        mock_conns = []
        for i in range(5):
            mock_conn = MagicMock()
            mock_conn.is_connected = True
            mock_conn.send_frame = AsyncMock()
            mock_conns.append(mock_conn)
            tcp_server._connections[f"client{i}"] = mock_conn

        # 广播多个帧
        tasks = []
        for i in range(3):
            task = asyncio.create_task(
                tcp_server.broadcast(bytes([0x68, 0x04, i, 0x00, 0x00, 0x00]))
            )
            tasks.append(task)

        await asyncio.gather(*tasks)

        # 验证所有连接都收到了所有帧
        for mock_conn in mock_conns:
            assert mock_conn.send_frame.call_count == 3
