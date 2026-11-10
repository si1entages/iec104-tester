"""离线报文对比（T96，D 采纳）：两段录制的规格化多重集 diff.

纯函数：输入两组 ``FrameEntry``，输出差异清单。对应现场标准动作——
装置升级前后各录一段，人工逐帧对比；这里自动给出「多/少/变」的帧。

规格化签名 = 方向 + 帧型 + ASDU 头（type/ca/cot/origin/PN/T）+ 信息体（IOA+值+品质）。
**必忽略会话易变字段**（两段录制必然不同，否则恒有假差异）：
- I 帧的 N(S)/N(R)（两段会话各自从 0 起算）；
- 录制时间戳 / absolute_time；
- metadata.client_id（桥侧连接序号）；
- S 帧的 rx_seq（确认序号随数据流量变化）→ S 帧只留「方向|S」；
- 信息体的 CP56Time2a 时标（解码后是独立字段，不进签名）。

脏帧（APCI/ASDU 解析失败）回退「方向|raw|长度|hex 前段」——同录制自 diff 仍为空。
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from core.capture import CaptureFile, FrameEntry
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU

_DIFF_CAP = 200


def _sig_i(data: bytes, direction: str) -> str:
    """I 帧签名：APCI 序号剥掉，ASDU 解码（失败回退 undecoded+长度）."""
    try:
        asdu = ASDU.decode(data[6:], ca_length=2)
    except Exception:  # noqa: BLE001 — 脏帧尽力而为
        return f"{direction}|I|undecoded|len={len(data)}"
    parts = [
        f"{asdu.type_id.name}",
        f"ca={asdu.common_addr}",
        f"cot={asdu.cot}",
    ]
    if asdu.pn:
        parts.append("PN")
    if asdu.test:
        parts.append("T")
    for obj in asdu.objects:
        parts.append(f"ioa={obj.ioa}={obj.data!r}")
    return f"{direction}|I|" + " ".join(parts)


def frame_signature(frame: FrameEntry) -> str:
    """单帧 → 规格化签名（忽略会话易变字段）."""
    direction = frame.direction_str
    try:
        apci, _ = APCICodec.decode(frame.frame_data)
    except Exception:  # noqa: BLE001 — 脏帧回退原始（自洽，不抛）
        raw = frame.frame_data[:16].hex().upper()
        return f"{direction}|raw|len={len(frame.frame_data)}|{raw}"
    kind = apci.frame_type.name
    if kind == "I":
        if len(frame.frame_data) <= 6:
            return f"{direction}|I|empty_asdu"
        return _sig_i(frame.frame_data, direction)
    if kind == "U":
        return f"{direction}|U|func=0x{apci.u_func:02X}"
    # S 帧：确认行为本身有意义，rx_seq 会话相关 → 只留帧型
    return f"{direction}|S"


def diff_frames(frames_a: list[FrameEntry], frames_b: list[FrameEntry],
                *, max_entries: int = _DIFF_CAP) -> dict:
    """两段帧列表的多重集 diff：count_a ≠ count_b 的签名即差异条目.

    同录制自 diff 恒为空（identical=True）；改值/删帧/COT 变化都会产生
    count_a ≠ count_b 的签名条目。对顺序不敏感（重传/TESTFR 时机差异不算变化）。
    """
    ca: Counter[str] = Counter()
    cb: Counter[str] = Counter()
    for f in frames_a:
        ca[frame_signature(f)] += 1
    for f in frames_b:
        cb[frame_signature(f)] += 1
    entries = []
    for sig in sorted(set(ca) | set(cb)):
        na, nb = ca.get(sig, 0), cb.get(sig, 0)
        if na != nb:
            entries.append({"signature": sig, "count_a": na, "count_b": nb,
                            "delta": nb - na})
    # 展示序：差异绝对值大的在前，同值按签名（稳定、可复现）
    entries.sort(key=lambda e: (-abs(e["delta"]), e["signature"]))
    return {
        "identical": not entries,
        "total_a": sum(ca.values()),
        "total_b": sum(cb.values()),
        "unique_a": len(ca),
        "unique_b": len(cb),
        "diff_total": len(entries),
        "entries": entries[:max(1, int(max_entries))],
        "truncated": len(entries) > max(1, int(max_entries)),
    }


def diff_capture_files(path_a: Any, path_b: Any, *, max_entries: int = _DIFF_CAP) -> dict:
    """加载两段录制文件并 diff（路径安全由调用方 CaptureService 保证）."""
    try:
        _, fa = CaptureFile.load(path_a)
        _, fb = CaptureFile.load(path_b)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"load failed: {e}"}
    out = diff_frames(fa, fb, max_entries=max_entries)
    out["ok"] = True
    return out


def signature_summary(sig: str) -> str:
    """签名 → 单行可读摘要（UI 表格用）：去长度噪声、截断超长签名."""
    return sig if len(sig) <= 160 else sig[:157] + "…"


def now_ts() -> float:
    """隔离用时间戳（供报告段使用，保持纯函数无全局态）."""
    return time.time()
