"""透明 TCP 桥（T73）——真实主站 ↔ 测试器 ↔ 真实子站.

定位：现场排障的**旁路观察器**。桥夹在既有主站与子站之间（子站地址不变，
主站改连桥监听口），对两侧都表现为普通 104 对端：

- **字节级透传**：转发先行，帧解析/解码是纯旁路——任何解析失败都**不得**
  影响转发（观察者永不在数据路径上制造故障）；
- **双向切帧**：两条链路各自独立按 APCI（0x68 + 长度）切帧，半包跨段缓存，
  脏字节重同步（丢 1 字节重找帧头，计数告警）；
- **方向约定**：``tx`` = 客户端(主站)→上游(子站)，即命令方向（下行）；
  ``rx`` = 上游→客户端，即监视方向（上行）。与引擎回调
  ``on_frame(data, direction, client_id)`` 同签名，可直接挂
  ``CaptureService.record_frame`` / WS 总线；
- **多客户端**：每个客户端连接独享一条上游连接（冗余主站/多主站各占一条）；
  上游断开随客户端断开，重连由主站按 t3/重连逻辑发起（v1 不做独立上游重试）。

典型用法（headless 现场排障）::

    python app.py --mode bridge --listen-port 2404 \\
        --upstream-host 192.168.1.9 --upstream-port 2404 --capture-file bridge.bin
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core.protocol.apci import APCICodec

logger = logging.getLogger("iec104.bridge")

START_BYTE = 0x68

# on_frame(data, direction, client_id) —— 与 EngineBridge._on_raw_frame 同签名
FrameCallback = Callable[[bytes, str, str], Awaitable[None]] | Callable[[bytes, str, str], None]


@dataclass
class BridgeConfig:
    """桥接配置：监听侧（面向真实主站）+ 上游侧（真实子站）.

    TLS（T84）：``listen_ssl`` 为服务端 context（桥对主站扮演"子站"），
    ``upstream_ssl`` 为客户端 context（桥对子站扮演"主站"，可校验真实
    子站证书）。两侧独立可配：明文↔TLS 混合桥接（一侧明文一侧加密）同样
    支持。TLS 终结在桥——帧内容对桥可见，合规监视/录制照常工作。
    """
    listen_host: str = "0.0.0.0"
    listen_port: int = 2404
    upstream_host: str = "127.0.0.1"
    upstream_port: int = 2404
    connect_timeout: float = 5.0     # 上游建连超时（秒）
    read_chunk: int = 4096
    idle_warning_s: float = 0.0      # >0 时链路静默超阈值打 info（0=关闭）
    listen_ssl: ssl.SSLContext | None = None    # 监听侧 TLS（None=明文）
    upstream_ssl: ssl.SSLContext | None = None  # 上游侧 TLS（None=明文）
    upstream_hostname: str = ""      # 上游证书主机名校验（空=不校验名）


@dataclass
class FrameSplitter:
    """APCI 帧切分器：feed() 喂原始字节，吐完整帧（透传零拷贝切片）.

    - 半包：以 ``0x68`` 开头但长度不足 → 缓存等后续；
    - 脏数据：非 0x68 开头或控制域非法 → 丢 1 字节重同步（``resyncs`` 计数），
      帧内乱入的脏字节同理——透传不受影响，只影响旁路观察的完整性。
    """

    buffer: bytearray = field(default_factory=bytearray)
    resyncs: int = 0

    def feed(self, data: bytes) -> list[bytes]:
        """喂一段字节，返回其中包含的完整帧（可能 0/1/N 个）."""
        self.buffer.extend(data)
        frames: list[bytes] = []
        while True:
            if len(self.buffer) < 2:
                break
            if self.buffer[0] != START_BYTE:
                # 脏字节：丢弃直到找到帧头（不整段清空，帧头可能在任意偏移）
                idx = self.buffer.find(bytes([START_BYTE]), 1)
                drop = idx if idx > 0 else len(self.buffer)
                del self.buffer[:drop]
                self.resyncs += drop
                continue
            length = self.buffer[1]
            if length < 4:
                # 长度域非法 → 视为脏字节重同步
                del self.buffer[:1]
                self.resyncs += 1
                continue
            total = 2 + length
            if len(self.buffer) < total:
                break  # 半包，等下一段
            frames.append(bytes(self.buffer[:total]))
            del self.buffer[:total]
        return frames


@dataclass
class BridgeStats:
    """桥接统计（只增计数，用于状态页/日志）."""
    clients_total: int = 0
    frames_dn: int = 0        # tx：主站→子站
    frames_up: int = 0        # rx：子站→主站
    bytes_dn: int = 0
    bytes_up: int = 0
    resyncs: int = 0
    upstream_errors: int = 0

    def as_dict(self) -> dict:
        return {
            "clients_total": self.clients_total,
            "frames_dn": self.frames_dn,
            "frames_up": self.frames_up,
            "bytes_dn": self.bytes_dn,
            "bytes_up": self.bytes_up,
            "resyncs": self.resyncs,
            "upstream_errors": self.upstream_errors,
        }


def describe_frame(frame: bytes) -> str:
    """单帧摘要（控制域 + ASDU 概要），解析失败回退到十六进制长度.

    只用于日志/控制台显示，**绝不在数据路径上**——异常一律吞掉。
    """
    try:
        apci, _ = APCICodec.decode(frame)
        base = f"{apci.frame_type.name}"
        if apci.frame_type.name == "I":
            base += f"(tx={apci.tx_seq},rx={apci.rx_seq})"
            # ASDU 概要：解析失败不影响（非 I 帧无 ASDU；类型未知时显示 hex 长度）
            try:
                from core.protocol.asdu import ASDU

                if len(frame) > 6:
                    asdu = ASDU.decode(frame[6:], ca_length=2)
                    base += f" {asdu.type_id.name} ca={asdu.common_addr} cot={asdu.cot}"
            except Exception:  # noqa: BLE001 — 旁路摘要，解析失败无所谓
                pass
        elif apci.frame_type.name == "U":
            base += f" func=0x{apci.u_func:02X}"
        else:
            base += f"(rx={apci.rx_seq})"
        return base
    except Exception:  # noqa: BLE001 — 旁路摘要
        return f"raw({len(frame)}B)"


class TcpBridge:
    """asyncio 透明桥：listen(主站) → upstream(子站)，双向透传 + 旁路观察."""

    def __init__(self, config: BridgeConfig, on_frame: FrameCallback | None = None):
        self.config = config
        self.on_frame = on_frame
        self.stats = BridgeStats()
        self._server: asyncio.Server | None = None
        self._client_tasks: set[asyncio.Task] = set()
        self._client_seq = 0
        self._stopping = False

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self) -> None:
        """启动监听（幂等保护：已启动时抛 RuntimeError）."""
        if self._server is not None:
            raise RuntimeError("TcpBridge already started")
        self._server = await asyncio.start_server(
            self._handle_client, self.config.listen_host, self.config.listen_port,
            ssl=self.config.listen_ssl)
        logger.info(
            "TcpBridge listening on %s:%d → upstream %s:%d",
            self.config.listen_host, self.listen_port,
            self.config.upstream_host, self.config.upstream_port,
        )

    async def stop(self) -> None:
        """停止监听并断开全部客户端（幂等）."""
        self._stopping = True
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001 — 停止路径尽力而为
                pass
            self._server = None
        for task in list(self._client_tasks):
            task.cancel()
        if self._client_tasks:
            await asyncio.gather(*self._client_tasks, return_exceptions=True)
        self._client_tasks.clear()
        logger.info("TcpBridge stopped (stats=%s)", self.stats.as_dict())

    @property
    def listen_port(self) -> int:
        """实际监听端口（listen_port=0 时由内核分配；未启动为配置值）。"""
        if self._server is not None and self._server.sockets:
            return int(self._server.sockets[0].getsockname()[1])
        return self.config.listen_port

    # ── 客户端处理 ────────────────────────────────────────────

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        self._client_seq += 1
        client_id = f"c{self._client_seq}"
        self.stats.clients_total += 1
        peer = writer.get_extra_info("peername")
        logger.info("[%s] client connected from %s", client_id, peer)

        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.config.upstream_host, self.config.upstream_port,
                    ssl=self.config.upstream_ssl,
                    server_hostname=self.config.upstream_hostname or None),
                timeout=self.config.connect_timeout,
            )
        except Exception as e:
            self.stats.upstream_errors += 1
            logger.warning(
                "[%s] upstream %s:%d connect failed: %s — closing client",
                client_id, self.config.upstream_host, self.config.upstream_port, e)
            writer.close()
            return

        dn_task = asyncio.create_task(
            self._pump(reader, writer, up_writer, "tx", client_id))
        up_task = asyncio.create_task(
            self._pump(up_reader, up_writer, writer, "rx", client_id))
        try:
            # 任一方向断开即结束（对端关闭/异常）；另一方向由 finally 收口
            done, _ = await asyncio.wait({dn_task, up_task},
                                         return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc is not None:
                    logger.info("[%s] link ended: %s", client_id, exc)
        finally:
            for t in (dn_task, up_task):
                t.cancel()
            await asyncio.gather(dn_task, up_task, return_exceptions=True)
            for w in (writer, up_writer):
                try:
                    w.close()
                except Exception:  # noqa: BLE001
                    pass
            logger.info("[%s] client disconnected", client_id)

    async def _pump(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                    peer_writer: asyncio.StreamWriter, direction: str,
                    client_id: str) -> None:
        """单方向泵：读 → 立即转发 → 旁路切帧/回调（转发永远优先于观察）."""
        splitter = FrameSplitter()
        while True:
            chunk = await reader.read(self.config.read_chunk)
            if not chunk:
                return  # 对端正常关闭
            peer_writer.write(chunk)
            try:
                await peer_writer.drain()
            except Exception as e:  # 对端写失败 → 结束本方向（连接即将收口）
                logger.info("[%s] %s relay write failed: %s", client_id, direction, e)
                return
            # ── 旁路观察（失败只丢观察，不影响已转发的数据）──
            if direction == "tx":
                self.stats.bytes_dn += len(chunk)
            else:
                self.stats.bytes_up += len(chunk)
            try:
                frames = splitter.feed(chunk)
            except Exception:  # noqa: BLE001 — 旁路兜底
                continue
            self.stats.resyncs += splitter.resyncs
            splitter.resyncs = 0
            for frame in frames:
                if direction == "tx":
                    self.stats.frames_dn += 1
                else:
                    self.stats.frames_up += 1
                if self.on_frame is not None:
                    try:
                        ret = self.on_frame(frame, direction, client_id)
                        if asyncio.iscoroutine(ret):
                            await ret
                    except Exception as e:  # noqa: BLE001 — 观察者异常不外溢
                        logger.warning("[%s] on_frame callback failed: %s", client_id, e)
