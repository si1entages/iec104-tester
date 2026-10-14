"""`core/capture/recorder.py` 报文录制器单元测试.

覆盖录制控制（开始/停止/暂停/恢复/重复开始）、方向统计、环形缓冲丢帧、
实时回调（含异常吞掉）、按计数/按时长自动刷盘、导出、统计与回调工厂。

**时序一律用显式 timestamp 或直接注入 ``_start_time``/``_last_flush_time`` 控制，
不使用 time.sleep，避免历史「靠真实等待碰巧通过」的假阳性。**
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.capture import format as capture_format
from core.capture.format import CaptureFile
from core.capture.recorder import PacketRecorder

FRAME = b"\x68\x0e\x00\x00\x00\x00\x01\x01\x03\x00\x01\x00\x64\x00\x00"


# ── 初始状态与属性 ───────────────────────────────────────────────

def test_initial_state():
    rec = PacketRecorder()

    assert rec.is_recording is False
    assert rec.is_paused is False
    assert rec.total_frames == 0
    assert rec.rx_frames == 0
    assert rec.tx_frames == 0
    assert rec.dropped_frames == 0
    assert rec.buffer_count == 0
    assert rec.elapsed == 0.0


def test_get_stats_snapshot():
    rec = PacketRecorder()
    stats = rec.get_stats()

    assert stats["recording"] is False
    assert stats["paused"] is False
    assert stats["total_frames"] == 0
    assert stats["file_path"] is None
    assert stats["elapsed_s"] == 0.0


def test_record_frame_before_start_is_ignored():
    rec = PacketRecorder()
    rec.record_frame(FRAME, direction="rx")

    assert rec.total_frames == 0
    assert rec.buffer_count == 0


# ── 录制控制 ─────────────────────────────────────────────────────

def test_start_memory_only_and_stop():
    """无路径 = 仅内存录制；stop 返回缓冲帧数."""
    rec = PacketRecorder()
    rec.start()  # memory-only
    assert rec.is_recording is True
    assert rec.get_stats()["file_path"] is None

    rec.record_frame(FRAME, direction="rx")
    rec.record_frame(FRAME, direction="tx")

    assert rec.stop() == 2
    assert rec.is_recording is False


def test_stop_when_not_recording_returns_zero():
    rec = PacketRecorder()
    assert rec.stop() == 0


def test_start_resets_counters_and_buffer():
    rec = PacketRecorder()
    rec.start()
    rec.record_frame(FRAME, direction="rx")
    assert rec.total_frames == 1

    rec.start()  # 重新开始 → 计数与缓冲清零
    assert rec.total_frames == 0
    assert rec.rx_frames == 0
    assert rec.tx_frames == 0
    assert rec.buffer_count == 0


def test_start_while_recording_stops_previous_session(tmp_path):
    """重复 start 会先 stop 上一会话（并把上一会话刷盘）."""
    path = tmp_path / "prev.i104"
    rec = PacketRecorder()
    rec.start(path, description="旧会话")
    rec.record_frame(FRAME, direction="rx")

    rec.start(tmp_path / "new.i104", description="新会话")

    assert path.exists()          # 旧会话已刷盘
    assert rec.total_frames == 0  # 新会话计数清零
    assert rec.is_recording is True


def test_pause_and_resume():
    rec = PacketRecorder()
    rec.start()
    rec.pause()
    assert rec.is_paused is True

    rec.record_frame(FRAME, direction="rx")
    assert rec.total_frames == 0  # 暂停期间不记录

    rec.resume()
    assert rec.is_paused is False
    rec.record_frame(FRAME, direction="rx")
    assert rec.total_frames == 1


# ── 方向统计与时间戳 ─────────────────────────────────────────────

def test_direction_counters_and_relative_timestamp():
    """显式 timestamp → 相对时间为 ts - _start_time，方向分别计数."""
    rec = PacketRecorder()
    rec.start()
    rec._start_time = 1000.0

    rec.record_frame(FRAME, direction="rx", timestamp=1002.5)
    rec.record_frame(FRAME, direction="tx", timestamp=1003.0)
    rec.record_frame(FRAME, direction="rx", metadata={"k": "v"}, timestamp=1004.0)

    assert (rec.rx_frames, rec.tx_frames, rec.total_frames) == (2, 1, 3)
    frames = list(rec._buffer)
    assert frames[0].timestamp == pytest.approx(2.5)
    assert frames[1].timestamp == pytest.approx(3.0)
    assert frames[2].metadata == {"k": "v"}


def test_elapsed_uses_injected_start_time():
    """elapsed 由 _start_time 推导（注入起点，不真实等待）."""
    rec = PacketRecorder()
    rec.start()
    rec._start_time = time.time() - 2.0

    assert rec.elapsed >= 2.0


def test_direction_defaults_to_rx():
    rec = PacketRecorder()
    rec.start()
    rec.record_frame(FRAME)  # 不传 direction
    assert rec.rx_frames == 1


# ── 环形缓冲丢帧 ─────────────────────────────────────────────────

def test_ring_buffer_drops_oldest_and_counts_dropped():
    rec = PacketRecorder(buffer_size=2)
    rec.start()
    for i in range(3):
        rec.record_frame(bytes([i]) + FRAME, direction="rx", timestamp=float(i))

    assert rec.buffer_count == 2
    assert rec.dropped_frames == 1
    assert rec.total_frames == 3  # 统计的是"收到"的帧数

    frames = list(rec._buffer)
    assert frames[0].frame_data[0] == 1  # 最旧的被淘汰
    assert frames[-1].frame_data[0] == 2


# ── 实时回调 ─────────────────────────────────────────────────────

def test_on_frame_callback_receives_entries():
    rec = PacketRecorder()
    rec.start()
    seen = []
    rec.set_on_frame(seen.append)

    rec.record_frame(FRAME, direction="tx", timestamp=5.0)

    assert len(seen) == 1
    assert seen[0].direction_str == "TX"
    assert seen[0].frame_data == FRAME


def test_on_frame_callback_exception_is_swallowed():
    """回调抛异常不得影响录制（录制器在线程/回调路径上必须稳健）."""
    rec = PacketRecorder()
    rec.start()

    def boom(_entry):
        raise RuntimeError("callback error")

    rec.set_on_frame(boom)
    rec.record_frame(FRAME, direction="rx")

    assert rec.total_frames == 1
    assert rec.buffer_count == 1


def test_make_frame_callback_records_fixed_direction():
    rec = PacketRecorder()
    rec.start()
    cb = rec.make_frame_callback("tx")

    cb(FRAME)
    cb(FRAME)

    assert rec.tx_frames == 2
    assert rec.rx_frames == 0


def test_make_engine_callback_master_and_slave():
    """master 回调透传方向；slave 回调额外写 client_id 元数据."""
    rec = PacketRecorder()
    rec.start()

    master_cb = rec.make_engine_callback("master")
    master_cb(FRAME, "rx")

    slave_cb = rec.make_engine_callback("slave")
    slave_cb(FRAME, "tx", "192.168.1.9:2404")

    frames = list(rec._buffer)
    assert frames[0].direction_str == "RX"
    assert frames[0].metadata == {}
    assert frames[1].direction_str == "TX"
    assert frames[1].metadata == {"client_id": "192.168.1.9:2404"}


# ── 自动刷盘 ─────────────────────────────────────────────────────

def test_auto_flush_by_frame_count(tmp_path):
    """达到 auto_flush_count 即刷盘（按计数触发，不依赖时间）."""
    path = tmp_path / "count.i104"
    rec = PacketRecorder(auto_flush_count=2)
    rec.start(path, description="计数刷盘")

    rec.record_frame(FRAME, direction="rx", timestamp=1.0)
    assert not path.exists()          # 未达阈值

    rec.record_frame(FRAME, direction="tx", timestamp=2.0)
    assert path.exists()              # 达阈值 → 已刷盘

    header, frames = CaptureFile.load_binary(path)
    assert len(frames) == 2
    assert header.description == "计数刷盘"


def test_auto_flush_by_elapsed_interval(tmp_path):
    """距上次刷盘超过 auto_flush_interval 即刷盘（注入 timestamp，不真实等待）."""
    path = tmp_path / "interval.i104"
    rec = PacketRecorder(auto_flush_interval=5.0, auto_flush_count=10**6)
    rec.start(path)
    rec._last_flush_time = 1000.0

    rec.record_frame(FRAME, direction="rx", timestamp=1000.1)
    assert not path.exists()          # 间隔未到

    rec.record_frame(FRAME, direction="rx", timestamp=1006.0)
    assert path.exists()              # 间隔已到 → 刷盘


def test_flush_with_empty_buffer_writes_nothing(tmp_path):
    path = tmp_path / "empty.i104"
    rec = PacketRecorder()
    rec.start(path)

    assert rec.stop() == 0
    assert not path.exists()


def test_flush_failure_is_logged_and_not_raised(tmp_path, monkeypatch):
    """刷盘失败（如磁盘错误）只记日志，不向录制调用方抛异常."""
    rec = PacketRecorder()
    rec.start(tmp_path / "fail.i104")
    rec.record_frame(FRAME, direction="rx")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(capture_format.CaptureFile, "save", staticmethod(boom))

    assert rec.stop() == 1  # 帧数照常返回


# ── 导出 ─────────────────────────────────────────────────────────

def test_export_binary_and_json_by_suffix(tmp_path):
    rec = PacketRecorder()
    rec.start()
    rec.record_frame(FRAME, direction="rx", timestamp=1.0)
    rec.record_frame(FRAME, direction="tx", timestamp=2.0)

    bin_path = tmp_path / "out.i104"
    assert rec.export(bin_path) == 2
    _, bin_frames = CaptureFile.load(bin_path)
    assert len(bin_frames) == 2

    json_path = tmp_path / "out.json"
    assert rec.export(json_path) == 2
    _, json_frames = CaptureFile.load(json_path)
    assert len(json_frames) == 2

    # 录制仍在进行（export 不停止录制）
    assert rec.is_recording is True


def test_export_without_format_dispatches_by_suffix(tmp_path):
    """format=None → 按扩展名分派（.json 写 JSON，其它写二进制）."""
    rec = PacketRecorder()
    rec.start()
    rec.record_frame(FRAME, direction="rx", timestamp=1.0)

    json_path = tmp_path / "auto.json"
    rec.export(json_path)
    assert json_path.read_text(encoding="utf-8").lstrip().startswith("{")

    bin_path = tmp_path / "auto.i104"
    rec.export(bin_path)
    assert bin_path.read_bytes()[:4] == b"I104"


def test_export_format_argument_is_currently_ignored(tmp_path):
    """**缺陷 D1（已上报 team-lead，未修源码）**：``export(path, format=...)`` 的
    ``format`` 形参被计算后从未使用——数据一律由 ``CaptureFile.save`` 按扩展名分派。

    本用例**钉住当前行为**：即使显式传 ``format="binary"``，``.json`` 路径仍写出 JSON。
    修复后（按显式 format 写文件）本用例需同步改为断言 ``b"I104"``。
    """
    rec = PacketRecorder()
    rec.start()
    rec.record_frame(FRAME, direction="rx", timestamp=1.0)

    path = tmp_path / "explicit.json"
    rec.export(path, format="binary")

    assert path.read_bytes()[:4] != b"I104"          # 当前：format 被忽略
    assert path.read_text(encoding="utf-8").lstrip().startswith("{")
