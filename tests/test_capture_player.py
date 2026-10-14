"""`core/capture/player.py` 报文回放器单元测试.

覆盖加载（文件/帧列表）、过滤、速度钳制、异步回放（完成/pause 中断/取消）、
单步与跳转、迭代器、时间范围查询与统计。

**时序控制**：帧时间戳用相同值（delay=0）或对 ``asyncio.sleep`` 做可控替换，
不使用 time.sleep / 不依赖真实等待。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import core.capture.player as player_mod
from core.capture.filter import FrameFilter
from core.capture.format import DIRECTION_RX, DIRECTION_TX, CaptureFile, FileHeader, FrameEntry
from core.capture.player import PacketPlayer, PlaybackState

FRAME_U = b"\x68\x04\x07\x00\x00\x00"   # U 帧（I 帧控制域 bit0=0）
FRAME_I = APC = b"\x68\x0e\x00\x00\x00\x00" + b"\x00" * 8


def _frames(timestamps: list[float], directions: list[int] | None = None,
            data: bytes = FRAME_U) -> list[FrameEntry]:
    dirs = directions or [DIRECTION_RX] * len(timestamps)
    return [FrameEntry(timestamp=t, direction=d, frame_data=data)
            for t, d in zip(timestamps, dirs, strict=False)]


# ── 初始状态与属性 ───────────────────────────────────────────────

def test_initial_state():
    player = PacketPlayer()

    assert player.state is PlaybackState.STOPPED
    assert player.is_loaded is False
    assert player.total_frames == 0
    assert player.current_index == 0
    assert player.current_frame is None
    assert player.progress == 0.0
    assert player.duration == 0.0
    assert player.header is None


def test_load_frames_sets_header_and_progress():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0]))

    assert player.is_loaded is True
    assert player.total_frames == 3
    assert player.duration == pytest.approx(2.0)
    assert player.header is not None
    assert player.state is PlaybackState.STOPPED


def test_load_frames_with_explicit_header():
    player = PacketPlayer()
    header = FileHeader(description="显式头")
    player.load_frames(_frames([0.0]), header)
    assert player.header is header
    assert player.header.description == "显式头"


def test_load_from_file(tmp_path):
    """从磁盘加载（二进制）→ 帧数与 header 正确."""
    path = tmp_path / "session.i104"
    CaptureFile.save_binary(path, _frames([0.0, 0.5, 1.5]), description="回放会话",
                            created=1000.0)

    player = PacketPlayer()
    assert player.load(path) == 3

    assert player.is_loaded is True
    assert player.total_frames == 3
    assert player.header is not None
    assert player.header.description == "回放会话"


def test_progress_and_current_frame_advance():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0, 3.0]))

    assert player.current_frame.timestamp == 0.0
    player.step_forward()
    assert player.current_index == 1
    assert player.current_frame.timestamp == 1.0
    assert player.progress == pytest.approx(0.25)


# ── 过滤 ─────────────────────────────────────────────────────────

def test_set_filter_restricts_active_frames():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0], [DIRECTION_RX, DIRECTION_TX]))

    player.set_filter(FrameFilter(direction="tx"))
    assert player.total_frames == 1
    assert player.current_index == 0
    assert player.current_frame.direction_str == "TX"


def test_clear_filter_restores_all_frames():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0], [DIRECTION_RX, DIRECTION_TX]))

    player.set_filter(FrameFilter(direction="tx"))
    player.clear_filter()

    assert player.total_frames == 2
    assert player._filter is None


def test_set_filter_none_behaves_like_clear():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0]))

    player.set_filter(None)
    assert player.total_frames == 2


# ── 速度钳制 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    (1.0, 1.0), (2.0, 2.0), (0.5, 0.5),
    (0.0, 0.01), (-5.0, 0.01),      # 下界钳制
    (10**6, 1000.0),                # 上界钳制
])
def test_set_speed_clamps(given, expected):
    player = PacketPlayer()
    player.set_speed(given)
    assert player._speed == pytest.approx(expected)


# ── 异步回放 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_play_completes_and_invokes_callbacks():
    """时间戳相同 → delay=0，不产生真实等待；每帧回调 + 完成回调."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 0.0, 0.0]))

    seen: list[int] = []
    done: list[int] = []
    await player.play(on_frame=lambda fr, i: seen.append(i), on_complete=lambda: done.append(1))

    assert seen == [0, 1, 2]
    assert done == [1]
    assert player.state is PlaybackState.STOPPED


@pytest.mark.asyncio
async def test_play_is_noop_when_already_playing():
    """已处于 PLAYING 时重复 play 直接返回，不触碰帧."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 0.0]))
    player._state = PlaybackState.PLAYING

    called = []
    await player.play(on_frame=lambda fr, i: called.append(i))

    assert called == []
    assert player.state is PlaybackState.PLAYING
    assert player._current_index == 0


@pytest.mark.asyncio
async def test_play_with_no_frames_resets_to_stopped():
    player = PacketPlayer()
    await player.play()
    assert player.state is PlaybackState.STOPPED


@pytest.mark.asyncio
async def test_play_pause_breaks_loop_and_keeps_state():
    """回放中调用 pause → 循环中断，状态保留 PAUSED（可从当前索引继续）."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 0.0, 0.0, 0.0]))

    def on_frame(_frame, index):
        if index == 1:
            player.pause()

    await player.play(on_frame=on_frame)

    assert player.state is PlaybackState.PAUSED
    assert player.current_index == 1

    player.resume()
    assert player.state is PlaybackState.PLAYING


@pytest.mark.asyncio
async def test_play_frame_callback_error_is_logged_not_fatal():
    """帧回调抛异常仅记日志，其余帧继续回放."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 0.0, 0.0]))

    seen = []

    def bad_callback(_frame, index):
        seen.append(index)
        raise RuntimeError("callback boom")

    await player.play(on_frame=bad_callback)
    assert seen == [0, 1, 2]


@pytest.mark.asyncio
async def test_play_complete_callback_error_is_swallowed():
    player = PacketPlayer()
    player.load_frames(_frames([0.0]))

    def boom():
        raise RuntimeError("complete boom")

    await player.play(on_complete=boom)
    assert player.state is PlaybackState.STOPPED


@pytest.mark.asyncio
async def test_play_uses_previously_set_callbacks():
    """未显式传回调时沿用 set 过的回调（play 参数为 None）."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0]))
    seen = []
    player._on_frame = lambda fr, i: seen.append(i)

    await player.play()
    assert seen == [0]


@pytest.mark.asyncio
async def test_play_clamps_long_delay(monkeypatch):
    """帧间隔很大时等待被钳制到 10s 上限（用可控 sleep 替换，不真实等待）."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 100.0]))
    player.set_speed(1.0)

    real_sleep = asyncio.sleep
    delays: list[float] = []

    async def fake_sleep(delay):
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(player_mod.asyncio, "sleep", fake_sleep)

    await player.play()

    assert delays == [10.0]      # (100-0)/1.0 → 钳制到 10.0
    assert player.state is PlaybackState.STOPPED


@pytest.mark.asyncio
async def test_stop_cancels_running_playback(monkeypatch):
    """stop() 取消正在挂起的回放任务，CancelledError 被内部吞掉."""
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 100.0]))
    player.set_speed(1.0)

    real_sleep = asyncio.sleep
    entered = asyncio.Event()

    async def fake_sleep(_delay):
        entered.set()
        await real_sleep(3600)   # 真实挂起，等待被 stop() 取消

    monkeypatch.setattr(player_mod.asyncio, "sleep", fake_sleep)

    task = asyncio.create_task(player.play())
    await entered.wait()

    player.stop()
    await asyncio.wait_for(task, timeout=1.0)   # 取消被吞，任务正常结束

    assert player.state is PlaybackState.STOPPED
    assert player._play_task is None


def test_stop_without_playback_and_double_stop_are_safe():
    player = PacketPlayer()
    player.stop()
    player.stop()
    assert player.state is PlaybackState.STOPPED


def test_pause_and_resume_are_state_guarded():
    """非 PLAYING 时 pause 无效；非 PAUSED 时 resume 无效."""
    player = PacketPlayer()
    player.pause()
    assert player.state is PlaybackState.STOPPED

    player.resume()
    assert player.state is PlaybackState.STOPPED


# ── 单步 / 跳转 ──────────────────────────────────────────────────

def test_step_forward_stops_at_last_frame():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0]))

    assert player.step_forward() is not None
    assert player.current_index == 1
    assert player.step_forward() is None      # 已在末帧
    assert player.current_index == 1


def test_step_backward_stops_at_first_frame():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0]))
    player.seek(1)

    assert player.step_backward() is not None
    assert player.current_index == 0
    assert player.step_backward() is None
    assert player.current_index == 0


def test_seek_valid_and_out_of_range():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0]))

    assert player.seek(2).timestamp == pytest.approx(2.0)
    assert player.current_index == 2

    assert player.seek(99) is None
    assert player.current_index == 2      # 越界不改变位置


def test_seek_time_finds_first_frame_at_or_after():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0, 3.0]))

    assert player.seek_time(1.5).timestamp == pytest.approx(2.0)
    assert player.current_index == 2


def test_seek_time_beyond_end_goes_to_last_frame():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0]))

    assert player.seek_time(99.0).timestamp == pytest.approx(2.0)
    assert player.current_index == 2


def test_seek_time_on_empty_player_returns_none():
    player = PacketPlayer()
    assert player.seek_time(1.0) is None


# ── 迭代器与时间范围 ─────────────────────────────────────────────

def test_iter_frames_full_and_sliced():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0, 3.0]))

    assert len(list(player.iter_frames())) == 4
    assert [f.timestamp for f in player.iter_frames(start=1, end=3)] == [1.0, 2.0]


def test_iter_frames_with_temporary_filter():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0], [DIRECTION_RX, DIRECTION_TX, DIRECTION_TX]))

    tx_only = list(player.iter_frames(frame_filter=FrameFilter(direction="tx")))
    assert len(tx_only) == 2
    assert all(f.direction_str == "TX" for f in tx_only)


def test_get_frames_in_range_is_inclusive():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0, 3.0]))

    got = player.get_frames_in_range(1.0, 2.0)
    assert [f.timestamp for f in got] == [1.0, 2.0]


# ── 统计 ─────────────────────────────────────────────────────────

def test_get_stats_reflects_frames_and_filter():
    player = PacketPlayer()
    player.load_frames(_frames([0.0, 1.0, 2.0], [DIRECTION_RX, DIRECTION_TX, DIRECTION_RX]))

    stats = player.get_stats()
    assert stats["loaded"] is True
    assert stats["state"] == "stopped"
    assert stats["total_frames"] == 3
    assert stats["original_frames"] == 3
    assert stats["filtered"] is False
    assert stats["rx_frames"] == 2
    assert stats["tx_frames"] == 1
    assert stats["duration_s"] == pytest.approx(2.0)
    assert stats["speed"] == pytest.approx(1.0)
    assert stats["frame_types"] == {"U": 3}

    player.set_filter(FrameFilter(direction="tx"))
    filtered = player.get_stats()
    assert filtered["total_frames"] == 1
    assert filtered["filtered"] is True
    assert filtered["tx_frames"] == 1
    assert filtered["rx_frames"] == 0
