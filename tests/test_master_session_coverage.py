"""`core/engine/master_session.py` 单元测试.

用轻量假引擎（不建真连接）覆盖：STARTDT/STOPDT、发送记账（回调/录制/历史库）、
TCP 事件、I/S/U 帧处理（含序号失步与冗余去重）、自动/周期总召、初始化后重总召、
t0~t3 超时处置与定时器循环。
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.engine.master_protocol import MasterEvent
from core.engine.master_session import MasterSession
from core.protocol.apci import APCICodec
from core.protocol.state_machine import TimerType


class _FakeEngine:
    """MasterSession 所需的最小引擎替身."""

    def __init__(self):
        self._client = types.SimpleNamespace(send=AsyncMock(), disconnect=AsyncMock())
        self._state_machine = MagicMock()
        self._state_machine.is_running = True
        self._seq = MagicMock()
        self._seq.process_rx_i_frame.return_value = True
        self._seq.send_window_available = True
        self._seq.get_recv_seq.return_value = 7
        self._tx_buffer: list = []
        self._rx_buffer: list = []
        self._raw_frame_callback = None
        self._recorder = None
        self._history_db = None
        self._protocol = MagicMock()
        self._redundancy = None
        self._auto_start = False
        self._auto_gi = False
        self._gi_interval = 0.0
        self._periodic_gi_task = None
        self._window_available = MagicMock()
        self.events: list = []
        self.spawned: list = []
        self.gi_calls = 0
        self.send_startdt = AsyncMock()

    def _fire_event(self, event, data=None):
        self.events.append((event, data))

    def _spawn(self, coro):
        # 同步断言用：记录并关闭 coroutine，避免 "never awaited" 警告
        self.spawned.append(coro)
        close = getattr(coro, "close", None)
        if close:
            close()
        return types.SimpleNamespace(name="spawned-task")

    async def general_interrogation(self):
        self.gi_calls += 1


def _session() -> tuple[MasterSession, _FakeEngine]:
    engine = _FakeEngine()
    return MasterSession(engine), engine


def _no_sleep(monkeypatch):
    """把 session 模块内的 asyncio 引用替换为带 sleep 的桩（不影响真 asyncio）."""
    calls = {"n": 0}

    async def fake_sleep(_seconds):
        calls["n"] += 1

    monkeypatch.setattr(
        "core.engine.master_session.asyncio",
        types.SimpleNamespace(
            sleep=fake_sleep,
            CancelledError=asyncio.CancelledError,
        ),
    )
    return calls


def _i_frame() -> bytes:
    return APCICodec.encode_i(0, 0, bytes([0x64, 0x01, 0x06, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x14]))


# ── 发送路径 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_startdt_and_stopdt():
    session, engine = _session()
    await session.send_startdt()
    engine._client.send.assert_awaited_once_with(APCICodec.startdt_act())
    engine._state_machine.on_startdt_act_sent.assert_called_once()

    await session.send_stopdt()
    engine._client.send.assert_awaited_with(APCICodec.stopdt_act())
    engine._state_machine.on_u_frame_act_sent.assert_called_once()


@pytest.mark.asyncio
async def test_send_frame_records_callback_recorder_history():
    session, engine = _session()
    seen = []
    engine._raw_frame_callback = lambda frame, direction: seen.append(direction)
    engine._recorder = MagicMock()
    engine._history_db = MagicMock()
    frame = APCICodec.startdt_act()

    await session.send_frame(frame)

    engine._client.send.assert_awaited_once_with(frame)
    assert seen == ["tx"]
    engine._recorder.record_frame.assert_called_once_with(frame, direction="tx")
    assert engine._tx_buffer and engine._tx_buffer[0][1] == frame
    engine._state_machine.on_any_frame_sent.assert_called_once()
    engine._history_db.record_frame.assert_called_once_with(
        "tx", frame, frame_type="U")


@pytest.mark.asyncio
async def test_send_frame_swallows_callback_error():
    session, engine = _session()

    def boom(frame, direction):
        raise RuntimeError("cb")

    engine._raw_frame_callback = boom
    await session.send_frame(APCICodec.startdt_act())   # 不抛出


# ── TCP 事件 ─────────────────────────────────────────────────────────────


def test_on_tcp_connected_and_disconnected():
    session, engine = _session()
    session.on_tcp_connected()
    engine._state_machine.on_connected.assert_called_once()
    assert (MasterEvent.CONNECTED, None) in engine.events
    assert engine.spawned == []          # auto_start=False 不自动 STARTDT

    engine._auto_start = True
    session.on_tcp_connected()
    assert len(engine.spawned) == 1      # 自动 STARTDT 协程已调度

    session.on_tcp_disconnected()
    engine._state_machine.on_disconnected.assert_called_once()
    assert (MasterEvent.DISCONNECTED, None) in engine.events


@pytest.mark.asyncio
async def test_auto_startdt_success_and_failure(monkeypatch):
    session, engine = _session()
    _no_sleep(monkeypatch)

    await session.auto_startdt()
    engine.send_startdt.assert_awaited_once()

    engine.send_startdt = AsyncMock(side_effect=RuntimeError("no link"))
    await session.auto_startdt()          # 失败只记日志


# ── 帧接收 ───────────────────────────────────────────────────────────────


def test_on_frame_received_u_frame_dispatch():
    session, engine = _session()
    seen = []
    engine._raw_frame_callback = lambda frame, direction: seen.append(direction)
    engine._recorder = MagicMock()
    engine._history_db = MagicMock()
    frame = APCICodec.testfr_con()

    session.on_frame_received(frame)

    assert seen == ["rx"]
    engine._recorder.record_frame.assert_called_once_with(frame, direction="rx")
    assert engine._rx_buffer and engine._rx_buffer[0][1] == frame
    engine._history_db.record_frame.assert_called_once_with(
        "rx", frame, frame_type="U")
    engine._state_machine.on_ack_received.assert_called_once()
    engine._state_machine.on_any_frame_received.assert_called_once()


def test_on_frame_received_malformed_is_logged():
    session, engine = _session()
    session.on_frame_received(b"\x00\x01\x02")   # 解码异常被吞掉
    engine._state_machine.on_any_frame_received.assert_not_called()


def test_handle_i_frame_normal_and_dispatch():
    session, engine = _session()
    frame = _i_frame()
    apci, _ = APCICodec.decode(frame)

    session.handle_i_frame(apci, frame)

    engine._seq.process_rx_i_frame.assert_called_once_with(0)
    engine._seq.process_rx_i_frame_ack.assert_called_once_with(0)
    engine._window_available.set.assert_called_once()
    engine._protocol.decode_and_dispatch.assert_called_once()
    engine._state_machine.on_i_frame_received.assert_called_once()


def test_handle_i_frame_sequence_mismatch_disconnects():
    session, engine = _session()
    engine._seq.process_rx_i_frame.return_value = False
    frame = _i_frame()
    apci, _ = APCICodec.decode(frame)

    session.handle_i_frame(apci, frame)

    assert len(engine.spawned) == 1      # disconnect() 被调度
    engine._protocol.decode_and_dispatch.assert_not_called()


def test_handle_i_frame_redundancy_dedup_skips_dispatch():
    session, engine = _session()
    engine._redundancy = MagicMock()
    engine._redundancy.is_duplicate_asdu.return_value = True
    frame = _i_frame()
    apci, _ = APCICodec.decode(frame)

    session.handle_i_frame(apci, frame)

    engine._protocol.decode_and_dispatch.assert_not_called()
    engine._state_machine.on_i_frame_received.assert_called_once()


def test_handle_s_frame():
    session, engine = _session()
    frame = APCICodec.encode_s(5)
    apci, _ = APCICodec.decode(frame)

    session.handle_s_frame(apci)

    engine._seq.process_rx_s_frame.assert_called_once_with(5)
    engine._window_available.set.assert_called_once()
    engine._state_machine.on_ack_received.assert_called_once()


def test_handle_u_frame_variants():
    session, engine = _session()

    # STARTDT CON + 自动总召 + 周期总召任务
    engine._auto_gi = True
    engine._gi_interval = 5.0
    startdt_con, _ = APCICodec.decode(APCICodec.startdt_con())
    session.handle_u_frame(startdt_con)
    engine._state_machine.on_startdt_con.assert_called_once()
    engine._seq.process_rx_u_frame_startdt_con.assert_called_once()
    assert (MasterEvent.STARTED, None) in engine.events
    assert len(engine.spawned) == 2
    assert engine._periodic_gi_task is not None

    # STOPDT CON
    stopdt_con, _ = APCICodec.decode(APCICodec.stopdt_con())
    session.handle_u_frame(stopdt_con)
    engine._state_machine.on_stopdt_con.assert_called_once()

    # TESTFR ACT → 回 CON
    testfr_act, _ = APCICodec.decode(APCICodec.testfr_act())
    before = len(engine.spawned)
    session.handle_u_frame(testfr_act)
    assert len(engine.spawned) == before + 1
    engine._state_machine.on_testfr_act_received.assert_called_once()

    # TESTFR CON → 确认
    testfr_con, _ = APCICodec.decode(APCICodec.testfr_con())
    session.handle_u_frame(testfr_con)
    engine._state_machine.on_ack_received.assert_called_once()


# ── 总召辅助 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_general_interrogation(monkeypatch):
    session, engine = _session()
    _no_sleep(monkeypatch)

    await session.auto_general_interrogation()
    assert engine.gi_calls == 1

    engine.general_interrogation = AsyncMock(side_effect=RuntimeError("x"))
    await session.auto_general_interrogation()   # 失败被吞掉


@pytest.mark.asyncio
async def test_periodic_gi_loop_calls_gi_when_running(monkeypatch):
    session, engine = _session()
    engine._gi_interval = 5.0

    async def fake_sleep(_seconds):
        engine._gi_interval = 0.0   # 一轮后退出

    monkeypatch.setattr(
        "core.engine.master_session.asyncio",
        types.SimpleNamespace(sleep=fake_sleep,
                              CancelledError=asyncio.CancelledError),
    )

    await session.periodic_gi_loop()

    assert engine.gi_calls == 1
    assert engine._periodic_gi_task is None


@pytest.mark.asyncio
async def test_periodic_gi_loop_skips_when_not_running(monkeypatch):
    session, engine = _session()
    engine._state_machine.is_running = False

    async def fake_sleep(_seconds):
        engine._gi_interval = 0.0

    monkeypatch.setattr(
        "core.engine.master_session.asyncio",
        types.SimpleNamespace(sleep=fake_sleep,
                              CancelledError=asyncio.CancelledError),
    )

    await session.periodic_gi_loop()
    assert engine.gi_calls == 0


@pytest.mark.asyncio
async def test_regi_after_init(monkeypatch):
    session, engine = _session()
    _no_sleep(monkeypatch)

    await session.regi_after_init()
    assert engine.gi_calls == 1

    engine._state_machine.is_running = False
    await session.regi_after_init()
    assert engine.gi_calls == 1

    engine._state_machine.is_running = True
    engine.general_interrogation = AsyncMock(side_effect=RuntimeError("x"))
    await session.regi_after_init()      # 失败被吞掉


# ── 定时器 ───────────────────────────────────────────────────────────────


def test_timer_expired_t0_t1_disconnect():
    session, engine = _session()
    session.on_timer_expired(TimerType.T0)
    session.on_timer_expired(TimerType.T1)
    assert len(engine.spawned) == 2
    assert (MasterEvent.TIMER_EXPIRED, {"timer": TimerType.T0}) in engine.events


def test_timer_expired_t2_sends_s_frame():
    session, engine = _session()
    session.on_timer_expired(TimerType.T2)
    assert len(engine.spawned) == 1
    engine._state_machine.on_s_frame_sent.assert_called_once()


def test_timer_expired_t3_sends_test_frame():
    session, engine = _session()
    session.on_timer_expired(TimerType.T3)
    assert len(engine.spawned) == 1
    engine._state_machine.on_u_frame_act_sent.assert_called_once()


@pytest.mark.asyncio
async def test_timer_loop_processes_timer_then_cancels(monkeypatch):
    session, engine = _session()
    _no_sleep(monkeypatch)

    engine._state_machine.check_timers = MagicMock(
        side_effect=[TimerType.T2, asyncio.CancelledError()])

    await session.timer_loop()
    engine._state_machine.check_timers.assert_called()
    engine._state_machine.on_s_frame_sent.assert_called_once()


@pytest.mark.asyncio
async def test_timer_loop_swallows_errors(monkeypatch):
    session, engine = _session()
    _no_sleep(monkeypatch)

    engine._state_machine.check_timers = MagicMock(
        side_effect=[RuntimeError("boom"), asyncio.CancelledError()])

    await session.timer_loop()   # 循环级异常被吞掉，下一次迭代退出


def test_on_state_change_logs():
    session, _ = _session()
    session.on_state_change("Stopped", "Running")   # 仅日志，不抛异常
