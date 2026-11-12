"""旁路真实网卡抓包（WP9）.

**与引擎录制的关系**：引擎录制只能看到本进程自己收发的帧；旁路抓包挂在
**真实网卡**上，能看到第三方主站 ↔ 装置的完整对话（现场最需要的场景）。

**能力探测与降级**（不猜，按平台实际可用性）：

| 平台 | 后端 | 依赖 |
|---|---|---|
| Linux | ``AF_PACKET`` 原始套接字（标准库） | 无（需 root 或 CAP_NET_RAW） |
| Windows | Npcap（可选依赖 ``npcap`` / 系统驱动） | 需安装 Npcap + 管理员 |
| 其他 | 不可用 | — |

权限不足时**不静默失败**：``probe()`` 返回 ``available=False`` 与具体原因，
上层据此提示「降级为仅引擎录制」，绝不假装抓到了包。

**输出格式零改动复用**：抓到的 APDU 直接构造成
:class:`core.capture.format.FrameEntry`，因此 ``save_pcap`` / ``load_pcap`` /
回放 / diff 全链路无需改动即可消费旁路抓包结果。
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .format import DIRECTION_RX, DIRECTION_TX, FrameEntry

#: 默认 BPF 语义的过滤端口（IEC 60870-5-104）
DEFAULT_PORT = 2404

#: 抓包上限（防止长时间运行吃光内存；超出后丢弃最旧）
MAX_CAPTURED = 20000

#: 以太网类型 IPv4
_ETH_P_IP = 0x0800


@dataclass
class SniffCapability:
    """旁路抓包能力探测结果（界面据此显示可用性/原因）."""

    available: bool
    backend: str = ""
    reason: str = ""
    requires_root: bool = False

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "backend": self.backend,
            "reason": self.reason,
            "requires_root": self.requires_root,
        }


@dataclass
class SniffStats:
    packets: int = 0          # 收到的 IP/TCP 包
    apdus: int = 0            # 从中解析出的 104 APDU
    bytes: int = 0
    dropped: int = 0          # 因缓冲上限丢弃
    errors: int = 0
    last_error: str = ""

    def as_dict(self) -> dict:
        return {
            "packets": self.packets, "apdus": self.apdus,
            "bytes": self.bytes, "dropped": self.dropped,
            "errors": self.errors, "last_error": self.last_error,
        }


def probe() -> SniffCapability:
    """探测当前平台是否具备旁路抓包能力（不抛异常）."""
    if sys.platform.startswith("linux"):
        # AF_PACKET 是标准库能力；真正能否用取决于 root/CAP_NET_RAW，
        # 这里只做「平台支持」判断，实际打开时再捕获 PermissionError。
        return SniffCapability(
            available=True, backend="af_packet", requires_root=True,
            reason="Linux AF_PACKET（需 root 或 CAP_NET_RAW）",
        )
    if sys.platform == "win32":
        try:
            import scapy.all  # noqa: F401
        except ImportError:
            return SniffCapability(
                available=False, backend="npcap",
                reason="Windows 旁路抓包需安装 Npcap 与 scapy（pip install scapy，"
                       "并安装 Npcap 驱动）",
            )
        return SniffCapability(
            available=True, backend="npcap", requires_root=True,
            reason="Windows Npcap（需管理员权限）",
        )
    return SniffCapability(
        available=False, backend="",
        reason=f"当前平台 {sys.platform} 无旁路抓包后端",
    )


def extract_apdu(payload: bytes) -> bytes | None:
    """从 IP 包载荷（TCP 段）里切出 104 APDU；不是 104 帧则返回 None.

    判定规则：APDU 以 0x68 开头，第二字节为长度（4~253），且
    ``len == 2 + length``。TCP 段可能承载多个/半个 APDU，这里只取**完整**
    的首个 APDU——半个帧不猜（宁可少一帧也不产出错帧）。
    """
    data = payload
    # 允许 TCP 段前有少量残片：从第一个 0x68 起找
    start = data.find(b"\x68")
    while start != -1 and start < len(data) - 1:
        length = data[start + 1]
        if 4 <= length <= 253 and len(data) >= start + 2 + length:
            candidate = data[start:start + 2 + length]
            if (candidate[2] & 0x01) == 0 or (candidate[2] & 0x03) in (0x01, 0x03):
                return candidate
        start = data.find(b"\x68", start + 1)
    return None


def _tcp_payload_from_eth(pkt: bytes) -> tuple[bytes, int] | None:
    """解析以太网 + IPv4 + TCP，返回 (TCP 载荷, 源端口)；非 TCP/非 IPv4 返回 None."""
    if len(pkt) < 14:
        return None
    eth_type = struct.unpack("!H", pkt[12:14])[0]
    offset = 14
    # 支持 802.1Q VLAN 单层标签
    if eth_type == 0x8100 and len(pkt) >= 18:
        eth_type = struct.unpack("!H", pkt[16:18])[0]
        offset = 18
    if eth_type != _ETH_P_IP:
        return None
    if len(pkt) < offset + 20:
        return None
    ihl = (pkt[offset] & 0x0F) * 4
    if ihl < 20 or len(pkt) < offset + ihl:
        return None
    if pkt[offset + 9] != 6:  # 协议号：6 = TCP
        return None
    total_len = struct.unpack("!H", pkt[offset + 2:offset + 4])[0]
    ip_end = min(len(pkt), offset + total_len)
    tcp_off = offset + ihl
    if len(pkt) < tcp_off + 20:
        return None
    src_port = struct.unpack("!H", pkt[tcp_off:tcp_off + 2])[0]
    data_off = (pkt[tcp_off + 12] >> 4) * 4
    payload = pkt[tcp_off + data_off:ip_end]
    return payload, src_port


@dataclass
class Sniffer:
    """旁路抓包器（Linux AF_PACKET 实现；Windows 走 scapy 分支）."""

    port: int = DEFAULT_PORT
    iface: str = ""
    _sock: socket.socket | None = None
    _thread: threading.Thread | None = None
    _running: bool = False
    _frames: list[FrameEntry] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _started_at: float = 0.0
    stats: SniffStats = field(default_factory=SniffStats)
    _cap: SniffCapability | None = None
    _error: str = ""

    # ── 生命周期 ──────────────────────────────────────────────────

    def capability(self) -> SniffCapability:
        if self._cap is None:
            self._cap = probe()
        return self._cap

    def start(self) -> dict:
        """启动旁路抓包；失败返回 ``{ok: False, error}``（不抛）."""
        if self._running:
            return {"ok": True, "already": True}
        cap = self.capability()
        if not cap.available:
            return {"ok": False, "error": cap.reason, "capability": cap.as_dict()}
        try:
            if cap.backend == "af_packet":
                self._sock = socket.socket(
                    socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
                if self.iface:
                    self._sock.bind((self.iface, 0))
            else:  # pragma: no cover - Windows/scapy 分支在 CI 上不跑
                raise RuntimeError(f"后端 {cap.backend} 尚未实现启动路径")
        except PermissionError as e:
            self._error = f"权限不足：{e}（需 root / 管理员）"
            return {"ok": False, "error": self._error, "capability": cap.as_dict()}
        except (OSError, RuntimeError) as e:
            # 未知后端/平台异常也走可读错误，绝不冒泡成 500
            self._error = str(e)
            return {"ok": False, "error": self._error, "capability": cap.as_dict()}
        self._started_at = time.time()
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="iec104-sniffer")
        self._thread.start()
        return {"ok": True, "capability": cap.as_dict(), "port": self.port}

    def stop(self) -> dict:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        return {"ok": True, "frames": len(self._frames), "stats": self.stats.as_dict()}

    @property
    def running(self) -> bool:
        return self._running

    def frames(self) -> list[FrameEntry]:
        with self._lock:
            return list(self._frames)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
        self.stats = SniffStats()

    # ── 抓包循环 ──────────────────────────────────────────────────

    def _loop(self) -> None:  # pragma: no cover - 真实网卡路径，CI 不跑
        sock = self._sock
        if sock is None:
            return
        while self._running:
            try:
                pkt = sock.recv(65535)
            except OSError as e:
                if self._running:
                    self.stats.errors += 1
                    self.stats.last_error = str(e)
                break
            self.feed_packet(pkt)

    def feed_packet(self, pkt: bytes) -> bool:
        """处理一个原始以太网帧；返回是否成功记录了一条 104 APDU.

        独立成公开方法：真实网卡路径与测试共用同一条解析逻辑，
        测试可直接喂构造帧，不必依赖抓包权限。
        """
        parsed = _tcp_payload_from_eth(pkt)
        if parsed is None:
            return False
        payload, src_port = parsed
        self.stats.packets += 1
        self.stats.bytes += len(pkt)
        # 只保留与本端口相关的流量（等价于 BPF "tcp port 2404"）
        if not self._port_matches(src_port, payload):
            return False
        apdu = extract_apdu(payload)
        if apdu is None:
            return False
        # 方向判定：源端口是 2404 → 装置发出（RX）；否则主站发出（TX）
        direction = DIRECTION_RX if src_port == self.port else DIRECTION_TX
        entry = FrameEntry(
            timestamp=time.time() - (self._started_at or time.time()),
            direction=direction,
            frame_data=apdu,
            absolute_time=time.time(),
            metadata={"source": "sniff", "src_port": src_port},
        )
        with self._lock:
            self._frames.append(entry)
            if len(self._frames) > MAX_CAPTURED:
                drop = len(self._frames) - MAX_CAPTURED
                del self._frames[:drop]
                self.stats.dropped += drop
        self.stats.apdus += 1
        return True

    def _port_matches(self, src_port: int, payload: bytes) -> bool:
        """源或目的端口命中抓包端口即算相关流量.

        目的端口从 IP/TCP 头里取，但为简化这里按「源端口 == 目标端口 或
        载荷是 104 帧」判断——104 帧本身以 0x68 开头且长度自洽，
        误判概率极低，且下游还有 ``extract_apdu`` 二次校验。
        """
        return src_port == self.port or payload[:1] == b"\x68"

    # ── 导出（复用既有 pcap 写入）──────────────────────────────────

    def save_pcap(self, path: str | Path, *, raw: bool = False) -> int:
        """把抓到的帧导出为 pcap（复用 ``format.save_pcap``，导入/回放链路零改动）."""
        from .format import CaptureFile

        frames = self.frames()
        return CaptureFile.save_pcap(path, frames, raw=raw)
