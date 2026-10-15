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
from pathlib import Path

from ..protocol.constants import START_BYTE

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


# ═══════════════════════════════════════════════════════════════════
#  TLS / IEC 62351 传输层加密
# ═══════════════════════════════════════════════════════════════════
#
# 覆盖边界（**请勿宣传为"支持 IEC 62351"**）:
#   已实现 —— TLS 1.2+ 传输层加密、服务端/客户端证书与私钥、受信 CA、
#             客户端可选校验、双向认证（mTLS）。
#   未实现 —— IEC 62351 的应用层认证（62351-4/-6）、会话密钥协商、
#             安全关联与访问控制、证书吊销（CRL/OCSP）、重放防护等。
# 详见 docs/tls.md §覆盖边界。


class TlsConfigError(ValueError):
    """TLS 配置错误（文件缺失、参数矛盾等）."""


def _require_file(path: str, what: str) -> str:
    """校验文件存在，返回其字符串路径."""
    if not path:
        raise TlsConfigError(f"{what} 未配置")
    if not Path(path).is_file():
        raise TlsConfigError(f"{what} 不存在: {path!r}")
    return str(path)


def build_server_context(
    *, certfile: str, keyfile: str = "", cafile: str = "",
    verify_client: bool = False,
) -> ssl.SSLContext:
    """构造服务端（子站）``SSLContext``.

    Args:
        certfile: 服务端证书（PEM）。
        keyfile: 私钥（PEM）；为空时假定私钥与证书同文件。
        cafile: 受信 CA（PEM）；``verify_client=True`` 时必填。
        verify_client: 是否要求并校验客户端证书（双向认证 / mTLS）。

    Returns:
        配置好的 ``SSLContext``（最低 TLS 1.2）。

    Raises:
        TlsConfigError: 证书/密钥/CA 缺失或路径不存在。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(
        certfile=_require_file(certfile, "certfile"),
        keyfile=keyfile or None,
    )
    if verify_client:
        ctx.load_verify_locations(cafile=_require_file(cafile, "cafile"))
        ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def build_client_context(
    *, cafile: str = "", certfile: str = "", keyfile: str = "",
    verify: bool = True,
) -> ssl.SSLContext:
    """构造客户端（主站）``SSLContext``.

    Args:
        cafile: 受信 CA；``verify=True`` 且为空时退回系统信任库。
        certfile: 客户端证书（双向认证时提供）。
        keyfile: 客户端私钥。
        verify: 是否校验服务端证书；``False`` 时同时关闭主机名校验
            （**仅供自签证书联调，生产禁用**）。

    Returns:
        配置好的 ``SSLContext``（最低 TLS 1.2）。

    Raises:
        TlsConfigError: 提供的证书/密钥/CA 路径不存在。
    """
    if verify:
        ctx = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=_require_file(cafile, "cafile") if cafile else None,
        )
    else:
        # 注意顺序：必须先关 check_hostname 再置 CERT_NONE，否则 ValueError
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    if certfile:
        ctx.load_cert_chain(
            certfile=_require_file(certfile, "certfile"),
            keyfile=keyfile or None,
        )
    return ctx


def build_context_from_config(tls_cfg, role: str) -> ssl.SSLContext:
    """按 ``core.config.TlsConfig`` 与角色构造 ``SSLContext``."""
    if role == "slave":
        return build_server_context(
            certfile=tls_cfg.certfile,
            keyfile=tls_cfg.keyfile,
            cafile=tls_cfg.cafile,
            verify_client=tls_cfg.verify_client,
        )
    return build_client_context(
        cafile=tls_cfg.cafile,
        certfile=tls_cfg.certfile,
        keyfile=tls_cfg.keyfile,
        verify=tls_cfg.verify,
    )


def configure_engine_tls(engine, role: str, tls_cfg) -> bool:
    """把 TLS 注入引擎内部的传输对象；返回是否已启用.

    ⚠ 已知接缝：``MasterEngine`` / ``SlaveEngine`` 在构造时**自行**创建
    ``TCPClient`` / ``TCPServer``，且其源码不在 T20 可改范围，故这里按私有
    属性（``_client`` / ``_server``）注入上下文。若将来把 ``ssl`` 参数贯穿到
    引擎构造函数，本函数可整体删除。**必须在引擎 ``start()`` 之前调用。**

    Args:
        engine: ``MasterEngine`` 或 ``SlaveEngine`` 实例。
        role: "master" / "slave"。
        tls_cfg: ``core.config.TlsConfig``。

    Returns:
        True 表示已注入；``tls_cfg.enabled`` 为 False 时返回 False（不注入）。

    Raises:
        TlsConfigError: 上下文构造失败，或引擎未暴露预期的传输对象。
    """
    if not getattr(tls_cfg, "enabled", False):
        return False

    ctx = build_context_from_config(tls_cfg, role)
    if role == "slave":
        transport = getattr(engine, "_server", None)
        if transport is None or not hasattr(transport, "set_ssl_context"):
            raise TlsConfigError("SlaveEngine 未暴露可注入 TLS 的 TCPServer")
        transport.set_ssl_context(ctx)
        logger.info("TLS enabled on slave (server side)")
    else:
        transport = getattr(engine, "_client", None)
        if transport is None or not hasattr(transport, "set_ssl_context"):
            raise TlsConfigError("MasterEngine 未暴露可注入 TLS 的 TCPClient")
        transport.set_ssl_context(ctx, getattr(tls_cfg, "server_hostname", "") or None)
        logger.info("TLS enabled on master (client side)")
    return True
