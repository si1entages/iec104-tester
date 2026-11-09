"""连接医生：主站侧分层自检（T94）.

把「连不上」的人工分层排查变成一次可自动执行的诊断，逐层给结论与证据：

  ① TCP connect     —— 端口通不通（拒绝/超时 → 人话：未监听 / 防火墙）；
  ② STARTDT ACT→CON —— 对端是不是 104 服务、是否确认启动；
  ③ 数据流观察      —— 自发帧？需要总召唤才回？自动解析收到的 ASDU 类型/IOA；
  ④ 结论与建议      —— 综合证据给人话结论，重点识别「对端不确认我方 I 帧」
                       （2026-11-10 真机联调：simulator4 的 N(R) 恒 0 → 按标准
                       t1 超时断链，属对端缺陷——诊断必须能把它点出来）。

本模块**不经 MasterEngine**：自建一条短连接，用 core.protocol 逐帧解码，
诊断过程不影响 UI 里的正式引擎连接。证据（S 帧计数、N(R) 推进、COT 异常）
随报告附存，供现场取证。
"""

from __future__ import annotations

import asyncio
import struct
import time
from dataclasses import dataclass, field

from ..protocol.apci import APCICodec, APDUType
from ..protocol.constants import U_STARTDT_ACT, U_STARTDT_CON
from ..protocol.types import COT
from .tcp_bridge import FrameSplitter

__all__ = ["DoctorStep", "DoctorReport", "run_doctor"]

# 保留 COT（46-47）与未知类型（42/43）——出现即对端实现可疑
_SUSPECT_COTS = {COT.UNKNOWN_CA.value, COT.UNKNOWN_IOA.value, 46, 47}


@dataclass
class DoctorStep:
    """单层检查结果（detail 为已面向用户的人话文本）."""

    key: str          # tcp / startdt / dataflow
    ok: bool
    detail: str
    evidence: dict = field(default_factory=dict)


@dataclass
class DoctorReport:
    ok: bool
    conclusion: str
    steps: list[DoctorStep]
    duration_ms: int

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "conclusion": self.conclusion,
            "steps": [
                {"key": s.key, "ok": s.ok, "detail": s.detail, "evidence": s.evidence}
                for s in self.steps
            ],
            "duration_ms": self.duration_ms,
        }


def _u_startdt_act() -> bytes:
    return bytes([0x68, 0x04, U_STARTDT_ACT, 0x00, 0x00, 0x00])


def _s_frame(vr: int) -> bytes:
    return b"\x68\x04\x01\x00" + struct.pack("<H", (vr & 0x7FFF) << 1)


def _i_gi(vs: int, vr: int, ca: int = 1, qoi: int = 20) -> bytes:
    asdu = bytes([100, 1, 6, 0]) + struct.pack("<H", ca) + b"\x00\x00\x00" + bytes([qoi])
    return APCICodec.encode_i(vs, vr, asdu)


def _vr_of(frame: bytes) -> int:
    return ((frame[5] << 8) | frame[4]) >> 1


async def _recv_frames(
    reader: asyncio.StreamReader, splitter: FrameSplitter, seconds: float
) -> list[bytes]:
    """在 seconds 内收帧（半包/脏字节由 FrameSplitter 处理）."""
    frames: list[bytes] = []

    async def _pump() -> None:
        while True:
            data = await reader.read(8192)
            if not data:
                return
            frames.extend(splitter.feed(data))

    task = asyncio.create_task(_pump())
    try:
        await asyncio.sleep(seconds)
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 — 探测协程的收尾
            pass
    frames.extend(splitter.feed(b""))  # 冲出缓存的半包/整帧
    return frames


def _classify_conclusion(
    tcp_ok: bool, startdt_ok: bool, i_frames: int, peer_s: int, n_r_advanced: bool,
    sent_i: int, suspect_cots: int, types_seen: dict[int, int],
) -> str:
    if not tcp_ok:
        return "TCP 层不可达：先核对 IP/端口与防火墙。"
    if not startdt_ok:
        return "TCP 可达，但对端未在超时内确认 STARTDT——该地址上可能不是 IEC 104 服务，或对端实现异常。"
    if i_frames == 0:
        return (
            "链路与启动都正常，但对端在观察窗内没有发送任何数据：该装置可能只在收到总召唤后才上送，"
            "或需要主站侧配置周期召唤（gi_interval）。"
        )
    if sent_i > 0 and not n_r_advanced:
        return (
            f"链路通、数据在流动（观察 {i_frames} 个 I 帧）；但对端从不确认我方 I 帧"
            f"（N(R) 恒 0、{peer_s} 个 S 帧{f'、{suspect_cots} 个保留 COT' if suspect_cots else ''}）"
            "——我方每发一条命令都会按标准 t1 超时断链并自动重连。属对端实现缺陷：监测不受影响，"
            "命令确认类功能（遥控/设点/总召唤确认）不可用。"
        )
    extra = f"；收到对端类型 {sorted(types_seen)}" if types_seen else ""
    return f"四层自检全部通过：TCP → STARTDT → 数据流正常，对端按标准确认（N(R) 已推进）{extra}。"


async def run_doctor(
    host: str,
    port: int,
    common_addr: int = 1,
    *,
    observe_seconds: float = 3.0,
    connect_timeout: float = 5.0,
    startdt_timeout: float = 5.0,
) -> DoctorReport:
    """执行分层自检，返回逐层结果与总结论（不经 MasterEngine，短连接自检）."""
    t0 = time.monotonic()
    steps: list[DoctorStep] = []
    splitter = FrameSplitter()

    # ── ① TCP ────────────────────────────────────────────────────
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=connect_timeout
        )
        steps.append(DoctorStep("tcp", True, f"TCP 可达：{host}:{port} 连接建立。",
                                {"host": host, "port": port}))
    except ConnectionRefusedError:
        steps.append(DoctorStep("tcp", False, "TCP 连接被拒绝：目标端口没有服务在监听。",
                                {"host": host, "port": port}))
    except TimeoutError:
        steps.append(DoctorStep("tcp", False, "TCP 连接超时：网络不通或被防火墙拦截。",
                                {"host": host, "port": port, "timeout_s": connect_timeout}))
    except OSError as exc:
        steps.append(DoctorStep("tcp", False, f"TCP 连接失败：{exc}",
                                {"host": host, "port": port}))
    if writer is None:
        return DoctorReport(False, _classify_conclusion(False, False, 0, 0, False, 0, 0, {}),
                            steps, int((time.monotonic() - t0) * 1000))

    # ── ② STARTDT ACT → CON ──────────────────────────────────────
    startdt_ok = False
    try:
        writer.write(_u_startdt_act())
        await writer.drain()
        deadline = time.monotonic() + startdt_timeout
        while time.monotonic() < deadline and not startdt_ok:
            rest = min(0.25, deadline - time.monotonic())
            if rest <= 0:
                break
            for frame in await _recv_frames(reader, splitter, rest):
                try:
                    apci, _ = APCICodec.decode(frame)
                except ValueError:
                    continue
                if apci.frame_type == APDUType.U and frame[2] == U_STARTDT_CON:
                    startdt_ok = True
                    break
            if startdt_ok:
                break
    except (OSError, ConnectionError) as exc:
        steps.append(DoctorStep("startdt", False, f"发送 STARTDT 失败：{exc}", {}))
    if startdt_ok:
        steps.append(DoctorStep("startdt", True, "对端已确认 STARTDT（是可用的 IEC 104 服务端）。",
                                {"timeout_s": startdt_timeout}))
    else:
        steps.append(DoctorStep(
            "startdt", False,
            "对端未在超时内确认 STARTDT：该端口上可能不是 IEC 104 服务，或对端不响应启动激活。",
            {"timeout_s": startdt_timeout}))
    if not startdt_ok:
        writer.close()
        return DoctorReport(False, _classify_conclusion(True, False, 0, 0, False, 0, 0, {}),
                            steps, int((time.monotonic() - t0) * 1000))

    # ── ③ 数据流观察（先看自发流；没有则发一次总召唤再观察） ──────
    i_frames = 0
    peer_s = 0
    suspect_cots = 0
    n_r_advanced = False
    sent_i = 0
    types_seen: dict[int, int] = {}
    ioa_samples: list[int] = []
    vs = 0
    vr = 0
    unacked = 0
    used_gi = False

    def _observe(frames: list[bytes]) -> None:
        nonlocal i_frames, peer_s, suspect_cots, n_r_advanced, vr, unacked
        for frame in frames:
            try:
                apci, _ = APCICodec.decode(frame)
            except ValueError:
                continue
            if apci.frame_type == APDUType.S:
                peer_s += 1
                continue
            if apci.frame_type != APDUType.I:
                continue
            i_frames += 1
            n_r = _vr_of(frame)
            if n_r != 0:
                n_r_advanced = True
            # S 帧确认计数：对端 I 帧 N(R) 覆盖我方发送则视为确认（vs=0 → N(R)≥1）
            if n_r > 0:
                unacked = 0
            try:
                asdu = frame[6:6 + apci.asdu_length]
                if len(asdu) < 6:
                    continue
                tid = asdu[0]
                cot = asdu[2] & 0x3F
                types_seen[tid] = types_seen.get(tid, 0) + 1
                if cot in _SUSPECT_COTS:
                    suspect_cots += 1
                if cot in (3, 20, 21) and tid in (1, 2, 13, 30):
                    off = 6
                    if not (asdu[1] & 0x80) and off + 3 <= len(asdu):
                        ioa_samples.append(
                            asdu[off] | (asdu[off + 1] << 8) | (asdu[off + 2] << 16))
            except (ValueError, struct.error):
                continue

    # 先观察自发流
    _observe(await _recv_frames(reader, splitter, observe_seconds))
    if i_frames == 0:
        # 没有自发流：发一次总召唤（很多装置只在 GI 后上送）
        used_gi = True
        sent_i = 1
        writer.write(_i_gi(vs, vr, common_addr))
        await writer.drain()
        _observe(await _recv_frames(reader, splitter, observe_seconds))
    if not used_gi:
        # 有自发流也要补一次总召唤：专门取证「对端是否确认我方 I 帧」——
        # N(R) 推进/S 帧是对端确认行为的唯一证据（T92 真机联调的核心结论）
        used_gi = True
        sent_i += 1
        writer.write(_i_gi(vs, vr, common_addr))
        await writer.drain()
        _observe(await _recv_frames(reader, splitter, observe_seconds))
    if unacked >= 8:
        writer.write(_s_frame(vr))
        await writer.drain()
        unacked = 0

    dataflow_ok = i_frames > 0
    detail = (
        f"观察到 {i_frames} 个 I 帧（类型 {sorted(types_seen)}）"
        + (f"，IOA 样例 {sorted(set(ioa_samples))[:6]}" if ioa_samples else "")
        + ("（数据来自总召唤响应）" if used_gi else "（自发流）") + "。"
    )
    steps.append(DoctorStep("dataflow", dataflow_ok, detail, {
        "i_frames": i_frames,
        "peer_s_frames": peer_s,
        "peer_n_r_advanced": n_r_advanced,
        "we_sent_i_frames": sent_i,
        "suspect_cots": suspect_cots,
        "types": {str(k): v for k, v in sorted(types_seen.items())},
        "ioa_samples": sorted(set(ioa_samples))[:8],
        "used_gi": used_gi,
        "observe_seconds": observe_seconds,
    }))

    try:
        writer.close()
    except OSError:
        pass

    conclusion = _classify_conclusion(
        True, startdt_ok, i_frames, peer_s, n_r_advanced, sent_i, suspect_cots, types_seen)
    ok = dataflow_ok
    return DoctorReport(ok, conclusion, steps, int((time.monotonic() - t0) * 1000))
