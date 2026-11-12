"""TCP 异步传输层 — 基于 asyncio 的 IEC 104 通信.

提供:
- TCP Server (子站)
- TCP Client (主站)
- 连接管理
- 报文收发
- TLS 传输层加密（IEC 62351 的传输层部分，见 §TLS）

⚠ TLS 覆盖边界（诚实声明，详见 ``docs/tls.md``）:
本模块**只实现 TLS 传输层加密**（SSLContext + 证书/密钥配置）。IEC 62351
的其他部分（应用层认证、会话密钥协商、安全关联等）**未实现**。
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..protocol.constants import START_BYTE

# TLS 实现在 ``core/transport/tls_context.py``（T21 行数收口时移出）；
# 此处再导出保持既有 ``from core.transport.connection import TlsConfigError,
# build_*_context, configure_engine_tls`` 兼容。
from .tls_context import (  # noqa: F401  — 向后兼容再导出
    TlsConfigError,
    build_client_context,
    build_context_from_config,
    build_server_context,
    configure_engine_tls,
)

logger = logging.getLogger("iec104.transport")


@dataclass
class ConnectionStats:
    """连接统计."""
    connected_at: float = 0.0
    last_rx_time: float = 0.0
    last_tx_time: float = 0.0
    bytes_sent: int = 0
    bytes_received: int = 0
    frames_sent: int = 0
    frames_received: int = 0
    i_frames_sent: int = 0
    i_frames_received: int = 0
    s_frames_sent: int = 0
    s_frames_received: int = 0
    u_frames_sent: int = 0
    u_frames_received: int = 0
    errors: int = 0
    reconnections: int = 0
    # WP6 链路可观测：最近一次连接失败原因与时刻（现场排障第一问）
    last_error: str = ""
    last_error_at: float = 0.0
    last_connected_at: float = 0.0


class TCPConnection:
    """单个 TCP 连接封装.

    处理:
    - 字节流帧分割（找0x68起始符）
    - 完整APDU帧提取
    - 异步读写
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        on_frame: Callable[[bytes], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
        name: str = "",
    ):
        self._reader = reader
        self._writer = writer
        self._on_frame = on_frame
        self._on_disconnected = on_disconnected
        self._name = name

        self._running = False
        self._read_task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._stats = ConnectionStats()
        self._stats.connected_at = time.monotonic()

        peer = writer.get_extra_info('peername')
        self._remote_addr = f"{peer[0]}:{peer[1]}" if peer else "unknown"

    @property
    def name(self) -> str:
        return self._name or self._remote_addr

    @property
    def stats(self) -> ConnectionStats:
        return self._stats

    @property
    def is_connected(self) -> bool:
        return self._running and not self._writer.is_closing()

    async def start(self) -> None:
        """启动异步读取循环."""
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info(f"[{self._name}] Connection started: {self._remote_addr}")

    def close(self) -> None:
        """请求关闭底层连接（幂等、非阻塞）.

        读循环退出（对端断开/EOF/取消）与显式 ``stop()`` 都必须走到这里，
        否则 socket 会一直处于打开状态：Python 3.13+ 的 ``Server.wait_closed()``
        会等待所有连接真正关闭，未关闭的连接会让 ``TCPServer.stop()`` 阻塞到超时，
        同时泄漏文件描述符。
        """
        writer = self._writer
        try:
            if not writer.is_closing():
                writer.close()
        except Exception as e:  # noqa: BLE001 — 关闭阶段不允许抛出
            logger.debug(f"[{self._name}] close() failed: {e}")

    async def stop(self) -> None:
        """停止连接."""
        self._running = False
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await asyncio.wait_for(self._read_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        self.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), timeout=1.0)
        except Exception:
            pass

        logger.info(f"[{self._name}] Connection closed: {self._remote_addr}")

    async def send(self, data: bytes) -> None:
        """发送原始字节数据."""
        if not self.is_connected:
            raise ConnectionError("Not connected")

        async with self._send_lock:
            try:
                self._writer.write(data)
                await self._writer.drain()
                self._stats.bytes_sent += len(data)
                self._stats.frames_sent += 1
                self._stats.last_tx_time = time.monotonic()
            except Exception as e:
                logger.error(f"[{self._name}] Send error: {e}")
                self._stats.errors += 1
                raise

    async def send_frame(self, apdu_bytes: bytes) -> None:
        """发送 APDU 帧."""
        await self.send(apdu_bytes)

    async def _read_loop(self) -> None:
        """异步读取循环 — 帧分割与提取."""
        buffer = bytearray()

        try:
            while self._running:
                try:
                    data = await asyncio.wait_for(
                        self._reader.read(4096),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

                if not data:
                    logger.info(f"[{self._name}] Connection closed by peer")
                    break

                buffer.extend(data)
                self._stats.bytes_received += len(data)
                self._stats.last_rx_time = time.monotonic()

                # 帧分割: 寻找完整的 APDU
                while len(buffer) >= 2:
                    # 找起始字节
                    if buffer[0] != START_BYTE:
                        # 丢弃直到找到 0x68
                        try:
                            idx = buffer.index(START_BYTE)
                            buffer = buffer[idx:]
                        except ValueError:
                            buffer.clear()
                            break

                    if len(buffer) < 2:
                        break

                    length = buffer[1]
                    total_len = 2 + length  # start + length + payload

                    if len(buffer) < total_len:
                        break  # 数据不完整，等待更多

                    # 提取完整帧
                    frame = bytes(buffer[:total_len])
                    buffer = buffer[total_len:]

                    self._stats.frames_received += 1

                    # 分类统计
                    if len(frame) >= 6:
                        cf = frame[2]
                        if (cf & 0x01) == 0:
                            self._stats.i_frames_received += 1
                        elif (cf & 0x03) == 0x01:
                            self._stats.s_frames_received += 1
                        elif (cf & 0x03) == 0x03:
                            self._stats.u_frames_received += 1

                    # 回调
                    if self._on_frame:
                        try:
                            self._on_frame(frame)
                        except Exception as e:
                            logger.error(f"[{self._name}] Frame callback error: {e}")
                            self._stats.errors += 1

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[{self._name}] Read loop error: {e}")
            self._stats.errors += 1
        finally:
            self._running = False
            # 无论何种退出路径都必须关闭 transport（否则 FD 泄漏 + 服务端停止阻塞）
            self.close()
            if self._on_disconnected:
                self._on_disconnected()


class TCPServer:
    """IEC 104 TCP 服务端 (子站用).

    监听端口，接受多个客户端连接。
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 2404,
        max_connections: int = 16,
        on_connection: Callable[[TCPConnection], None] | None = None,
        on_frame: Callable[[TCPConnection, bytes], None] | None = None,
        on_disconnected: Callable[[TCPConnection], None] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ):
        self._host = host
        self._port = port
        self._max_connections = max_connections
        self._on_connection = on_connection
        self._on_frame = on_frame
        self._on_disconnected = on_disconnected
        self._ssl_context = ssl_context

        self._server: asyncio.Server | None = None
        self._connections: dict[str, TCPConnection] = {}
        self._running = False

    def set_ssl_context(self, ssl_context: ssl.SSLContext | None) -> None:
        """注入 TLS 上下文（须在 ``start()`` 之前调用；None 表示明文）."""
        self._ssl_context = ssl_context

    @property
    def tls_enabled(self) -> bool:
        return self._ssl_context is not None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    @property
    def connections(self) -> dict[str, TCPConnection]:
        return dict(self._connections)

    async def start(self) -> None:
        """启动服务端（``set_ssl_context`` 注入时启用 TLS）."""
        if self._running:
            return

        kwargs: dict = {}
        if self._ssl_context is not None:
            kwargs["ssl"] = self._ssl_context

        self._server = await asyncio.start_server(
            self._handle_client,
            self._host,
            self._port,
            **kwargs,
        )
        self._running = True
        logger.info(
            f"Server started on {self._host}:{self._port}"
            f"{' (TLS)' if self._ssl_context is not None else ''}"
        )

    async def stop(self) -> None:
        """停止服务端."""
        self._running = False

        # 关闭所有连接
        for conn in list(self._connections.values()):
            try:
                await asyncio.wait_for(conn.stop(), timeout=2.0)
            except Exception as e:
                logger.warning(f"Connection stop error: {e}")
        self._connections.clear()

        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            except Exception as e:
                logger.warning(f"Server wait_closed timeout: {e}")

        logger.info("Server stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """处理新的客户端连接."""
        if len(self._connections) >= self._max_connections:
            logger.warning("Max connections reached, rejecting")
            writer.close()
            return

        peer = writer.get_extra_info('peername')
        conn_id = f"{peer[0]}:{peer[1]}"

        def on_frame(frame: bytes):
            if self._on_frame:
                self._on_frame(conn, frame)

        def on_disconnect():
            if conn_id in self._connections:
                del self._connections[conn_id]
            if self._on_disconnected:
                self._on_disconnected(conn)

        conn = TCPConnection(
            reader=reader,
            writer=writer,
            on_frame=on_frame,
            on_disconnected=on_disconnect,
            name=conn_id,
        )

        self._connections[conn_id] = conn

        if self._on_connection:
            self._on_connection(conn)

        await conn.start()

    async def broadcast(self, data: bytes) -> None:
        """向所有连接广播数据."""
        for conn in list(self._connections.values()):
            if conn.is_connected:
                try:
                    await conn.send_frame(data)
                except Exception as e:
                    logger.error(f"Broadcast error to {conn.name}: {e}")

    async def send_to(self, conn_id: str, data: bytes) -> bool:
        """向指定连接发送数据."""
        conn = self._connections.get(conn_id)
        if conn and conn.is_connected:
            await conn.send_frame(data)
            return True
        return False


class TCPClient:
    """IEC 104 TCP 客户端 (主站用).

    连接到服务端，支持断线重连。
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2404,
        reconnect_interval: float = 5.0,
        max_reconnects: int = 0,    # 0=无限
        on_frame: Callable[[bytes], None] | None = None,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        server_hostname: str | None = None,
    ):
        self._host = host
        self._port = port
        self._reconnect_interval = reconnect_interval
        self._max_reconnects = max_reconnects
        self._on_frame = on_frame
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._ssl_context = ssl_context
        # TLS 主机名校验用名；None 时 asyncio 回落到 host。
        # 按 IP 连接而证书只签了域名时，在此显式给出证书中的域名。
        self._server_hostname = server_hostname or None

        self._connection: TCPConnection | None = None
        self._running = False
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_count = 0
        # WP6：最近一次连接失败原因/时刻（即使从未建连也有记录，供 /api/status 展示）
        self._last_error = ""
        self._last_error_at = 0.0
        self._ever_connected = False

    def set_ssl_context(self, ssl_context: ssl.SSLContext | None,
                        server_hostname: str | None = None) -> None:
        """注入 TLS 上下文（须在 ``start()`` 之前调用；None 表示明文）."""
        self._ssl_context = ssl_context
        self._server_hostname = server_hostname or None

    @property
    def tls_enabled(self) -> bool:
        return self._ssl_context is not None

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and self._connection.is_connected

    @property
    def connection(self) -> TCPConnection | None:
        return self._connection

    @property
    def stats(self) -> ConnectionStats | None:
        return self._connection.stats if self._connection else None

    def link_stats(self) -> dict:
        """链路只读快照（WP6）：目标、连接态、重连计数与最近失败原因.

        与 ``stats`` 不同，本方法在**未建立连接**时依然可用——正是"连不上"
        的时候最需要看到原因。
        """
        conn = self._connection
        return {
            "target": f"{self._host}:{self._port}",
            "connected": bool(conn is not None and conn.is_connected),
            "tls": self._ssl_context is not None,
            "reconnect_count": self._reconnect_count,
            "max_reconnects": self._max_reconnects,
            "reconnect_interval": self._reconnect_interval,
            "reconnect_in_seconds": (
                None if self._reconnect_count <= 0 else self._reconnect_interval
            ),
            "ever_connected": self._ever_connected,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
        }

    async def start(self) -> None:
        """启动客户端连接."""
        if self._running:
            return
        self._running = True
        self._reconnect_task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        """停止客户端."""
        self._running = False

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._connection:
            await self._connection.stop()
            self._connection = None

    async def disconnect(self) -> None:
        """主动关闭当前 TCP 连接以触发重建（保留重连循环）.

        用于序列号失序等需要重建 TCP 连接的场景：仅关闭底层连接，
        ``_connect_loop`` 会检测到断开 → 调用 ``on_disconnected`` 回调
        （使上层状态机离开 Running 并触发 DISCONNECTED 事件）→ 按配置重连。

        与 ``stop()`` 的区别：``stop()`` 会停止整个客户端（取消重连循环），
        本方法仅重建当前连接。
        """
        if self._connection:
            await self._connection.stop()

    async def send(self, data: bytes) -> None:
        """发送数据."""
        if self._connection and self._connection.is_connected:
            await self._connection.send_frame(data)
        else:
            raise ConnectionError("Not connected")

    async def _connect_loop(self) -> None:
        """连接/重连循环."""
        while self._running:
            established = False
            try:
                kwargs: dict = {}
                if self._ssl_context is not None:
                    kwargs["ssl"] = self._ssl_context
                    if self._server_hostname:
                        kwargs["server_hostname"] = self._server_hostname

                reader, writer = await asyncio.open_connection(
                    self._host, self._port, **kwargs
                )

                def on_frame(frame: bytes):
                    if self._on_frame:
                        self._on_frame(frame)

                def on_disconnect():
                    logger.info("Disconnected from server")

                self._connection = TCPConnection(
                    reader=reader,
                    writer=writer,
                    on_frame=on_frame,
                    on_disconnected=on_disconnect,
                    name="client",
                )

                await self._connection.start()
                self._reconnect_count = 0
                self._ever_connected = True
                self._last_error = ""
                self._connection.stats.last_connected_at = time.time()
                established = True

                if self._on_connected:
                    self._on_connected()

                logger.info(
                    f"Connected to {self._host}:{self._port}"
                    f"{' (TLS)' if self._ssl_context is not None else ''}"
                )

                # 等待连接断开（stop() 取消本任务时同样在此抛 CancelledError）
                while self._running and self._connection.is_connected:
                    await asyncio.sleep(0.5)

            except asyncio.CancelledError:
                # stop() 或主动关闭取消了本循环：连接已断，仍须通知上层，
                # 否则上层状态机会残留 Running（序列号失序修复的前提）。
                if established and self._on_disconnected:
                    self._on_disconnected()
                break
            except Exception as e:
                # WP6：保留失败原因文本（类型 + 消息），供链路面板显示"为什么重连"
                self._last_error = f"{type(e).__name__}: {e}"
                self._last_error_at = time.time()
                if self._connection is not None:
                    self._connection.stats.last_error = self._last_error
                    self._connection.stats.last_error_at = self._last_error_at
                logger.error(f"Connection failed: {e}")

            # 正常断开路径：通知上层（取消路径已在 except 中通知并 break）
            if established and self._on_disconnected:
                self._on_disconnected()

            if not self._running:
                break

            # 重连
            self._reconnect_count += 1
            if (self._max_reconnects > 0 and
                    self._reconnect_count >= self._max_reconnects):
                logger.warning("Max reconnection attempts reached")
                break

            if self._connection:
                self._connection.stats.reconnections += 1

            logger.info(
                f"Reconnecting in {self._reconnect_interval}s "
                f"(attempt {self._reconnect_count})..."
            )
            await asyncio.sleep(self._reconnect_interval)

