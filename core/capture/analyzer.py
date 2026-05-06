"""报文分析器 — 统计与协议解析.

提供:
- 帧统计（按类型/方向/时间分布）
- ASDU 协议解析
- 异常检测（序列号跳变、超时、格式错误）
- 流量分析
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from .format import FrameEntry

logger = logging.getLogger("iec104.capture.analyzer")


@dataclass
class FrameStats:
    """帧统计信息."""
    total_frames: int = 0
    rx_frames: int = 0
    tx_frames: int = 0
    i_frames: int = 0
    s_frames: int = 0
    u_frames: int = 0
    unknown_frames: int = 0

    # ASDU 类型分布
    asdu_type_counts: dict = field(default_factory=dict)

    # COT 分布
    cot_counts: dict = field(default_factory=dict)

    # 时间分布（每秒帧数）
    time_distribution: dict = field(default_factory=dict)

    # 帧长度统计
    min_frame_length: int = 0
    max_frame_length: int = 0
    avg_frame_length: float = 0.0

    # 流量
    total_bytes: int = 0
    rx_bytes: int = 0
    tx_bytes: int = 0
    duration_s: float = 0.0
    avg_bps: float = 0.0  # bytes per second


@dataclass
class AnomalyInfo:
    """异常信息."""
    timestamp: float = 0.0
    frame_index: int = 0
    anomaly_type: str = ""  # seq_gap, timeout, format_error, unexpected
    severity: str = "warning"  # warning / error
    description: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """完整分析结果."""
    stats: FrameStats = field(default_factory=FrameStats)
    anomalies: list = field(default_factory=list)
    u_frame_details: list = field(default_factory=list)
    session_summary: str = ""


class CaptureAnalyzer:
    """报文分析器.

    用法:
        analyzer = CaptureAnalyzer()
        result = analyzer.analyze(frames)
        print(result.session_summary)
    """

    def analyze(self, frames: list[FrameEntry]) -> AnalysisResult:
        """分析帧列表."""
        result = AnalysisResult()

        if not frames:
            result.session_summary = "No frames to analyze"
            return result

        # 统计
        result.stats = self._compute_stats(frames)

        # 异常检测
        result.anomalies = self._detect_anomalies(frames)

        # U帧详情
        result.u_frame_details = self._extract_u_frames(frames)

        # 会话摘要
        result.session_summary = self._build_summary(result)

        return result

    # ── 统计计算 ──────────────────────────────────────────────────

    def _compute_stats(self, frames: list[FrameEntry]) -> FrameStats:
        stats = FrameStats()
        stats.total_frames = len(frames)

        type_counter = Counter()
        cot_counter = Counter()
        time_dist = defaultdict(int)
        lengths = []

        for f in frames:
            # 方向
            if f.direction == 0:
                stats.rx_frames += 1
                stats.rx_bytes += f.frame_length
            else:
                stats.tx_frames += 1
                stats.tx_bytes += f.frame_length

            stats.total_bytes += f.frame_length
            lengths.append(f.frame_length)

            # 帧类型
            ft = f.frame_type
            if ft == "I":
                stats.i_frames += 1
            elif ft == "S":
                stats.s_frames += 1
            elif ft == "U":
                stats.u_frames += 1
            else:
                stats.unknown_frames += 1

            # ASDU 解析
            if ft == "I" and f.frame_length >= 12:
                asdu_info = self._parse_asdu_header(f.frame_data)
                if asdu_info:
                    type_counter[asdu_info["type_id"]] += 1
                    cot_counter[asdu_info["cot"]] += 1

            # 时间分布（按秒）
            second = int(f.timestamp)
            time_dist[second] += 1

        # 长度统计
        if lengths:
            stats.min_frame_length = min(lengths)
            stats.max_frame_length = max(lengths)
            stats.avg_frame_length = sum(lengths) / len(lengths)

        # 时间
        if frames:
            stats.duration_s = frames[-1].timestamp - frames[0].timestamp
            if stats.duration_s > 0:
                stats.avg_bps = stats.total_bytes / stats.duration_s

        # ASDU 类型名称映射
        type_names = {
            1: "M_SP_NA_1", 2: "M_SP_TA_1", 3: "M_DP_NA_1", 4: "M_DP_TA_1",
            5: "M_ST_NA_1", 9: "M_ME_NA_1", 11: "M_ME_NB_1", 13: "M_ME_NC_1",
            15: "M_IT_NA_1", 20: "M_PS_NA_1", 21: "M_ME_ND_1",
            30: "M_SP_TB_1", 31: "M_DP_TB_1", 36: "M_ME_TF_1", 37: "M_IT_TB_1",
            45: "C_SC_NA_1", 46: "C_DC_NA_1", 47: "C_RC_NA_1",
            48: "C_SE_NA_1", 49: "C_SE_NB_1", 50: "C_SE_NC_1",
            100: "C_IC_NA_1", 101: "C_CI_NA_1", 103: "C_CS_NA_1",
            104: "C_TS_NA_1", 105: "C_RP_NA_1",
        }
        cot_names = {
            0: "NOT_USED", 1: "PERIODIC", 2: "BACK", 3: "SPONT", 4: "INIT",
            5: "REQ", 6: "ACT", 7: "ACTCON", 8: "DEACT", 9: "DEACTCON",
            10: "ACTTERM", 20: "INTROGEN",
        }

        stats.asdu_type_counts = {
            type_names.get(k, f"type_{k}"): v
            for k, v in type_counter.most_common()
        }
        stats.cot_counts = {
            cot_names.get(k, f"cot_{k}"): v
            for k, v in cot_counter.most_common()
        }
        stats.time_distribution = dict(sorted(time_dist.items()))

        return stats

    # ── 异常检测 ──────────────────────────────────────────────────

    def _detect_anomalies(self, frames: list[FrameEntry]) -> list[AnomalyInfo]:
        anomalies = []
        prev_rx_seq = -1
        prev_tx_seq = -1
        last_rx_time = 0.0

        for i, f in enumerate(frames):
            if f.frame_length < 6:
                anomalies.append(AnomalyInfo(
                    timestamp=f.timestamp,
                    frame_index=i,
                    anomaly_type="format_error",
                    severity="error",
                    description=f"Frame too short: {f.frame_length} bytes",
                ))
                continue

            cf = f.frame_data[2]

            # I帧序列号检查
            if (cf & 0x01) == 0:
                tx_seq = (f.frame_data[2] >> 1) | (f.frame_data[3] << 7)
                rx_seq = (f.frame_data[4] >> 1) | (f.frame_data[5] << 7)

                if f.direction == 0:  # RX
                    if prev_rx_seq >= 0 and tx_seq != prev_rx_seq + 1:
                        if tx_seq != 0 or prev_rx_seq != 32767:  # 正常翻转
                            anomalies.append(AnomalyInfo(
                                timestamp=f.timestamp,
                                frame_index=i,
                                anomaly_type="seq_gap",
                                severity="warning",
                                description=(
                                    f"RX I-frame sequence gap: "
                                    f"expected {prev_rx_seq + 1}, got {tx_seq}"
                                ),
                                details={"prev": prev_rx_seq, "actual": tx_seq},
                            ))
                    prev_rx_seq = tx_seq
                    last_rx_time = f.timestamp

                elif f.direction == 1:  # TX
                    if prev_tx_seq >= 0 and tx_seq != prev_tx_seq + 1:
                        if tx_seq != 0 or prev_tx_seq != 32767:
                            anomalies.append(AnomalyInfo(
                                timestamp=f.timestamp,
                                frame_index=i,
                                anomaly_type="seq_gap",
                                severity="warning",
                                description=(
                                    f"TX I-frame sequence gap: "
                                    f"expected {prev_tx_seq + 1}, got {tx_seq}"
                                ),
                                details={"prev": prev_tx_seq, "actual": tx_seq},
                            ))
                    prev_tx_seq = tx_seq

            # U帧检查
            elif (cf & 0x03) == 0x03:
                valid_u = {0x07, 0x0B, 0x13, 0x23, 0x43, 0x83}
                if cf not in valid_u:
                    anomalies.append(AnomalyInfo(
                        timestamp=f.timestamp,
                        frame_index=i,
                        anomaly_type="format_error",
                        severity="error",
                        description=f"Invalid U-frame function: 0x{cf:02X}",
                    ))

            # 帧间隔检查（超过30秒无帧）
            if f.direction == 0 and last_rx_time > 0:
                gap = f.timestamp - last_rx_time
                if gap > 30:
                    anomalies.append(AnomalyInfo(
                        timestamp=f.timestamp,
                        frame_index=i,
                        anomaly_type="timeout",
                        severity="warning",
                        description=f"Long silence: {gap:.1f}s since last RX frame",
                    ))

        return anomalies

    # ── U帧提取 ──────────────────────────────────────────────────

    def _extract_u_frames(self, frames: list[FrameEntry]) -> list[dict]:
        u_funcs = {
            0x07: "STARTDT ACT", 0x0B: "STARTDT CON",
            0x13: "STOPDT ACT", 0x23: "STOPDT CON",
            0x43: "TESTFR ACT", 0x83: "TESTFR CON",
        }
        result = []
        for i, f in enumerate(frames):
            if f.frame_type == "U" and f.frame_length >= 6:
                cf = f.frame_data[2]
                func_name = u_funcs.get(cf, f"UNKNOWN(0x{cf:02X})")
                result.append({
                    "index": i,
                    "timestamp": f.timestamp,
                    "direction": f.direction_str,
                    "function": func_name,
                    "raw_cf": cf,
                })
        return result

    # ── ASDU 解析 ─────────────────────────────────────────────────

    def _parse_asdu_header(self, frame_data: bytes) -> Optional[dict]:
        """解析 ASDU 头部信息."""
        try:
            if len(frame_data) < 12:
                return None
            asdu = frame_data[6:]
            type_id = asdu[0]
            vsq = asdu[1]
            cot = asdu[2] & 0x3F
            num = vsq & 0x7F
            common_addr = asdu[4] | (asdu[5] << 8)
            return {
                "type_id": type_id,
                "cot": cot,
                "num": num,
                "common_addr": common_addr,
            }
        except (IndexError, ValueError):
            return None

    # ── 摘要 ──────────────────────────────────────────────────────

    def _build_summary(self, result: AnalysisResult) -> str:
        s = result.stats
        lines = [
            f"📊 Capture Analysis",
            f"   Frames: {s.total_frames} (I={s.i_frames}, S={s.s_frames}, U={s.u_frames})",
            f"   Direction: RX={s.rx_frames}, TX={s.tx_frames}",
            f"   Bytes: {s.total_bytes:,} (RX={s.rx_bytes:,}, TX={s.tx_bytes:,})",
            f"   Duration: {s.duration_s:.2f}s, Avg: {s.avg_bps:.0f} B/s",
            f"   Frame size: min={s.min_frame_length}, max={s.max_frame_length}, avg={s.avg_frame_length:.0f}",
        ]

        if s.asdu_type_counts:
            lines.append(f"   ASDU types: {dict(list(s.asdu_type_counts.items())[:5])}")

        if result.anomalies:
            warnings = sum(1 for a in result.anomalies if a.severity == "warning")
            errors = sum(1 for a in result.anomalies if a.severity == "error")
            lines.append(f"   ⚠️ Anomalies: {warnings} warnings, {errors} errors")
        else:
            lines.append(f"   ✅ No anomalies detected")

        return "\n".join(lines)
