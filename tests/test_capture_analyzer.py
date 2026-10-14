"""`core/capture/analyzer.py` 报文分析器单元测试.

覆盖统计计算（方向/帧型/ASDU 类型与 COT 名称映射/时间分布/长度/流量）、
异常检测（短帧、RX/TX 序列号跳变与 15 位翻转、非法 U 功能码、长时间静默）、
U 帧提取与 ASDU 头部解析、会话摘要文本。全部用真实编码帧，无网络依赖。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.capture.analyzer import AnalysisResult, CaptureAnalyzer, FrameStats
from core.capture.format import DIRECTION_RX, DIRECTION_TX, FrameEntry
from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDUBuilder
from core.protocol.types import COT

# ── 帧构造 helper ────────────────────────────────────────────────

def _i_entry(tx_seq: int = 0, ts: float = 0.0, direction: int = DIRECTION_RX,
             ioa: int = 100, cot: int = COT.SPONT):
    asdu = ASDUBuilder.build_single_point(1, ioa, True, cot=cot)
    return FrameEntry(timestamp=ts, direction=direction,
                      frame_data=APCICodec.encode_i(tx_seq, 0, asdu))


def _u_entry(cf: int = 0x07, ts: float = 0.0, direction: int = DIRECTION_TX):
    return FrameEntry(timestamp=ts, direction=direction,
                      frame_data=bytes([0x68, 0x04, cf, 0x00, 0x00, 0x00]))


def _s_entry(rx_seq: int = 0, ts: float = 0.0, direction: int = DIRECTION_TX):
    return FrameEntry(timestamp=ts, direction=direction,
                      frame_data=APCICodec.encode_s(rx_seq))


def _raw_i_frame(asdu_bytes: bytes, tx_seq: int = 0, ts: float = 0.0,
                 direction: int = DIRECTION_RX) -> FrameEntry:
    return FrameEntry(timestamp=ts, direction=direction,
                      frame_data=APCICodec.encode_i(tx_seq, 0, asdu_bytes))


# ── analyze 入口 ─────────────────────────────────────────────────

def test_analyze_empty_frame_list():
    result = CaptureAnalyzer().analyze([])

    assert isinstance(result, AnalysisResult)
    assert result.session_summary == "No frames to analyze"
    assert result.anomalies == []
    assert result.stats.total_frames == 0


def test_analyze_returns_all_sections():
    frames = [_i_entry(0, 0.0), _u_entry(0x07, 0.5), _s_entry(1, 1.0)]
    result = CaptureAnalyzer().analyze(frames)

    assert result.stats.total_frames == 3
    assert result.stats.i_frames == 1
    assert result.stats.u_frames == 1
    assert result.stats.s_frames == 1
    assert len(result.u_frame_details) == 1
    assert "Capture Analysis" in result.session_summary


# ── 统计 ─────────────────────────────────────────────────────────

def test_stats_direction_bytes_and_lengths():
    frames = [
        _i_entry(0, 0.0),                                    # RX, I 帧
        _i_entry(1, 1.0, direction=DIRECTION_TX),            # TX, I 帧
        _s_entry(2, 2.0, direction=DIRECTION_TX),            # TX, S 帧（6 字节）
    ]
    stats = CaptureAnalyzer()._compute_stats(frames)

    assert stats.total_frames == 3
    assert stats.rx_frames == 1
    assert stats.tx_frames == 2
    assert stats.rx_bytes == len(frames[0].frame_data)
    assert stats.tx_bytes == len(frames[1].frame_data) + 6
    assert stats.total_bytes == len(frames[0].frame_data) + len(frames[1].frame_data) + 6

    lengths = [len(f.frame_data) for f in frames]
    assert stats.min_frame_length == min(lengths)
    assert stats.max_frame_length == max(lengths)
    assert stats.avg_frame_length == pytest.approx(sum(lengths) / 3)


def test_stats_unknown_frame_type_for_short_frame():
    """帧长 < 6 时 frame_type 为 '?' → 计入 unknown_frames."""
    short = FrameEntry(timestamp=0.0, direction=DIRECTION_RX, frame_data=b"\x68\x04")
    stats = CaptureAnalyzer()._compute_stats([short, _u_entry(0x07, 1.0)])

    assert stats.unknown_frames == 1
    assert stats.u_frames == 1
    assert stats.min_frame_length == 2
    assert stats.max_frame_length == 6


def test_stats_time_distribution_and_flow_rate():
    frames = [_i_entry(0, 0.5), _i_entry(1, 1.5), _i_entry(2, 1.9)]
    stats = CaptureAnalyzer()._compute_stats(frames)

    assert stats.time_distribution == {0: 1, 1: 2}
    assert stats.duration_s == pytest.approx(1.4)
    assert stats.avg_bps == pytest.approx(stats.total_bytes / 1.4)


def test_stats_zero_duration_keeps_avg_bps_zero():
    """所有帧时间戳相同 → duration=0，不产生除零."""
    stats = CaptureAnalyzer()._compute_stats([_i_entry(0, 5.0), _i_entry(1, 5.0)])

    assert stats.duration_s == 0.0
    assert stats.avg_bps == 0.0


def test_stats_asdu_type_names_known_and_unknown():
    known = _i_entry(0, 0.0)                                   # M_SP_NA_1 (type 1)
    unknown_type = _raw_i_frame(bytes([55, 0x01, COT.SPONT, 0, 1, 0, 0, 0, 0, 0]), 1, 1.0)
    stats = CaptureAnalyzer()._compute_stats([known, unknown_type])

    assert stats.asdu_type_counts == {"M_SP_NA_1": 1, "type_55": 1}


def test_stats_cot_names_known_unknown_and_group():
    spont = _i_entry(0, 0.0, cot=COT.SPONT)                       # SPONT (3)
    group1 = _i_entry(1, 1.0, cot=COT.group_response(1))          # INTROGEN_GROUP_1 (21)
    unknown_cot = _raw_i_frame(bytes([1, 0x01, 60, 0, 1, 0, 0, 0, 0, 0]), 2, 2.0)
    counter_group = _i_entry(3, 3.0, cot=38)   # 累计量分组响应 COT 38 → COUNTER_GROUP_1
    stats = CaptureAnalyzer()._compute_stats([spont, group1, unknown_cot, counter_group])

    assert stats.cot_counts["SPONT"] == 1
    assert stats.cot_counts["INTROGEN_GROUP_1"] == 1
    assert stats.cot_counts["cot_60"] == 1
    assert stats.cot_counts["COUNTER_GROUP_1"] == 1


def test_stats_skips_asdu_parse_for_non_i_or_short_frames():
    """非 I 帧与 <12 字节帧不参与 ASDU 统计."""
    short_i = FrameEntry(timestamp=0.0, direction=DIRECTION_RX,
                         frame_data=b"\x68\x04\x00\x00\x00\x00")  # 6 字节 I 帧
    stats = CaptureAnalyzer()._compute_stats([short_i, _u_entry(0x07, 1.0), _s_entry(0, 2.0)])

    assert stats.asdu_type_counts == {}
    assert stats.cot_counts == {}


# ── 异常检测 ─────────────────────────────────────────────────────

def test_detect_short_frame_as_format_error():
    short = FrameEntry(timestamp=1.0, direction=DIRECTION_RX, frame_data=b"\x68\x04")
    anomalies = CaptureAnalyzer()._detect_anomalies([short])

    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.anomaly_type == "format_error"
    assert a.severity == "error"
    assert a.frame_index == 0
    assert "Frame too short: 2 bytes" in a.description


def test_detect_rx_sequence_gap():
    frames = [_i_entry(0, 0.0), _i_entry(1, 0.1), _i_entry(5, 0.2)]

    anomalies = CaptureAnalyzer()._detect_anomalies(frames)

    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "seq_gap"
    assert anomalies[0].severity == "warning"
    assert anomalies[0].frame_index == 2
    assert anomalies[0].details == {"prev": 1, "actual": 5}


def test_detect_tx_sequence_gap():
    frames = [
        _i_entry(0, 0.0, direction=DIRECTION_TX),
        _i_entry(3, 0.1, direction=DIRECTION_TX),
    ]
    anomalies = CaptureAnalyzer()._detect_anomalies(frames)

    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "seq_gap"
    assert "TX I-frame sequence gap" in anomalies[0].description


def test_no_gap_on_15bit_sequence_wraparound():
    """RX 序列号 32767 → 0 属正常 15 位翻转，不应报 seq_gap."""
    frames = [_i_entry(32767, 0.0), _i_entry(0, 0.1)]
    assert CaptureAnalyzer()._detect_anomalies(frames) == []


def test_no_gap_on_tx_sequence_wraparound():
    frames = [
        _i_entry(32767, 0.0, direction=DIRECTION_TX),
        _i_entry(0, 0.1, direction=DIRECTION_TX),
    ]
    assert CaptureAnalyzer()._detect_anomalies(frames) == []


def test_rx_and_tx_sequences_are_tracked_separately():
    """RX/TX 各自独立计数：交错发送不应互相误判."""
    frames = [
        _i_entry(0, 0.0, direction=DIRECTION_RX),
        _i_entry(0, 0.1, direction=DIRECTION_TX),
        _i_entry(1, 0.2, direction=DIRECTION_RX),
        _i_entry(1, 0.3, direction=DIRECTION_TX),
    ]
    assert CaptureAnalyzer()._detect_anomalies(frames) == []


def test_detect_invalid_u_frame_function():
    bad_u = _u_entry(0x0F, 0.0)     # bit0=1, bits1-2=11 但功能码非法
    anomalies = CaptureAnalyzer()._detect_anomalies([bad_u])

    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "format_error"
    assert "Invalid U-frame function: 0x0F" in anomalies[0].description


@pytest.mark.parametrize("cf", [0x07, 0x0B, 0x13, 0x23, 0x43, 0x83])
def test_valid_u_frames_not_flagged(cf):
    assert CaptureAnalyzer()._detect_anomalies([_u_entry(cf, 0.0)]) == []


def test_detect_long_silence_as_timeout():
    """间隔 >30s 报 timeout：检测在「RX I 帧 → 后续 RX 非 I 帧」时生效.

    （原因见 ``test_long_silence_between_two_rx_i_frames_is_not_detected``：
    RX I 帧会先把 ``last_rx_time`` 更新为自身时间戳，故紧随其后的 I 帧算得 gap=0。）
    """
    frames = [_i_entry(0, 10.0), _u_entry(0x07, 50.0, direction=DIRECTION_RX)]
    anomalies = CaptureAnalyzer()._detect_anomalies(frames)

    assert [a.anomaly_type for a in anomalies] == ["timeout"]
    assert anomalies[0].severity == "warning"
    assert "Long silence" in anomalies[0].description


def test_long_silence_between_two_rx_i_frames_is_not_detected():
    """**缺陷 D2（已上报 team-lead，未改源码）**：静默检测在把 ``last_rx_time``
    更新为当前 I 帧时间戳**之后**才比较，因此连续两个 RX I 帧之间无论间隔多久，
    算出的 ``gap`` 恒为 0，永远检测不到"长时间静默"。

    本用例钉住当前行为；修复（先比较、后更新，或改为记录"上一次 RX 帧时间"）后
    应改为断言 ``["timeout"]``。
    """
    frames = [_i_entry(0, 10.0), _i_entry(1, 50.0)]   # 间隔 40s
    assert CaptureAnalyzer()._detect_anomalies(frames) == []


def test_no_silence_anomaly_when_first_rx_frame_is_at_zero():
    """首帧时间戳为 0 时 last_rx_time 仍为 0 → 静默检测不触发（现有实现语义）."""
    frames = [_i_entry(0, 0.0), _u_entry(0x07, 40.0, direction=DIRECTION_RX)]
    assert [a.anomaly_type for a in CaptureAnalyzer()._detect_anomalies(frames)] == []


def test_short_silence_not_flagged():
    frames = [_i_entry(0, 10.0), _u_entry(0x07, 20.0, direction=DIRECTION_RX)]
    assert CaptureAnalyzer()._detect_anomalies(frames) == []


def test_silence_check_only_applies_to_rx_frames():
    """静默检测只对 RX 帧生效（TX 帧不刷新也不触发）."""
    frames = [
        _i_entry(0, 10.0, direction=DIRECTION_RX),
        _u_entry(0x07, 100.0, direction=DIRECTION_TX),   # TX 不触发静默告警
    ]
    assert CaptureAnalyzer()._detect_anomalies(frames) == []


# ── U 帧提取 ─────────────────────────────────────────────────────

def test_extract_u_frames_known_and_unknown_function():
    frames = [_i_entry(0, 0.0), _u_entry(0x07, 0.5), _u_entry(0x0F, 1.0)]
    details = CaptureAnalyzer()._extract_u_frames(frames)

    assert len(details) == 2
    assert details[0]["function"] == "STARTDT ACT"
    assert details[0]["direction"] == "TX"
    assert details[0]["raw_cf"] == 0x07
    assert details[1]["function"] == "UNKNOWN(0x0F)"
    assert details[1]["index"] == 2


def test_extract_u_frames_all_known_functions():
    cfs = {0x07: "STARTDT ACT", 0x0B: "STARTDT CON", 0x13: "STOPDT ACT",
           0x23: "STOPDT CON", 0x43: "TESTFR ACT", 0x83: "TESTFR CON"}
    frames = [_u_entry(cf, float(i)) for i, cf in enumerate(cfs)]
    details = CaptureAnalyzer()._extract_u_frames(frames)

    assert [d["function"] for d in details] == list(cfs.values())


def test_extract_u_frames_ignores_short_frames():
    short = FrameEntry(timestamp=0.0, direction=DIRECTION_RX, frame_data=b"\x68\x04")
    assert CaptureAnalyzer()._extract_u_frames([short]) == []


# ── ASDU 头部解析 ────────────────────────────────────────────────

def test_parse_asdu_header_fields():
    entry = _i_entry(0, 0.0, ioa=100, cot=COT.SPONT)
    info = CaptureAnalyzer()._parse_asdu_header(entry.frame_data)

    assert info is not None
    assert info["type_id"] == 1          # M_SP_NA_1
    assert info["cot"] == COT.SPONT
    assert info["num"] == 1
    assert info["common_addr"] == 1


def test_parse_asdu_header_rejects_short_frame():
    assert CaptureAnalyzer()._parse_asdu_header(b"\x68\x04\x00\x00\x00\x00") is None


# ── 摘要 ─────────────────────────────────────────────────────────

def test_build_summary_without_anomalies():
    result = AnalysisResult(stats=FrameStats(total_frames=2, i_frames=2, rx_frames=2,
                                             total_bytes=200, rx_bytes=200,
                                             duration_s=1.0, avg_bps=200.0,
                                             min_frame_length=10, max_frame_length=10,
                                             avg_frame_length=10.0))
    summary = CaptureAnalyzer()._build_summary(result)

    assert "Frames: 2 (I=2, S=0, U=0)" in summary
    assert "RX=2, TX=0" in summary
    assert "✅ No anomalies detected" in summary
    assert "ASDU types" not in summary   # 无 ASDU 统计时不输出该行


def test_build_summary_with_anomalies_and_asdu_types():
    from core.capture.analyzer import AnomalyInfo

    result = AnalysisResult(
        stats=FrameStats(total_frames=3, asdu_type_counts={"M_SP_NA_1": 2}),
        anomalies=[
            AnomalyInfo(severity="warning"),
            AnomalyInfo(severity="error"),
        ],
    )
    summary = CaptureAnalyzer()._build_summary(result)

    assert "ASDU types: {'M_SP_NA_1': 2}" in summary
    assert "Anomalies: 1 warnings, 1 errors" in summary


def test_analyze_end_to_end_summary_contents():
    frames = [_i_entry(0, 0.0), _i_entry(1, 0.0)]
    summary = CaptureAnalyzer().analyze(frames).session_summary

    assert "Frames: 2 (I=2, S=0, U=0)" in summary
    assert "ASDU types" in summary
