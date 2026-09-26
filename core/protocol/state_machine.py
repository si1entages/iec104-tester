"""连接状态机 — IEC 60870-5-104 连接生命周期管理.

状态转移图:

  ┌─────────┐   connect()    ┌────────────┐   STARTDT CON   ┌─────────┐
  │ STOPPED │ ──────────────→│ CONNECTING │ ────────────────→│ RUNNING │
  └─────────┘                └────────────┘                  └─────────┘
       ↑                          │                              │
       │    disconnect()          │ t0 timeout                   │
       │←─────────────────────────┘                              │
       │                                                         │
       │              disconnect() / STOPDT CON                  │
       └─────────────────────────────────────────────────────────┘

定时器:
  t0: 连接建立超时 (默认30s)
  t1: 发送/测试超时 (默认15s) — 发送I帧或U帧后等待确认
  t2: 无数据确认超时 (默认10s) — 收到I帧后多久发S帧
  t3: 空闲测试超时 (默认20s) — 空闲时发TESTFR
"""

from __future__ import annotations

import enum
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .constants import T0_DEFAULT, T1_DEFAULT, T2_DEFAULT, T3_DEFAULT
from .types import ConnState


class TimerType(enum.Enum):
    T0 = "t0"  # 连接建立超时
    T1 = "t1"  # 发送/测试超时
    T2 = "t2"  # 无数据确认超时
    T3 = "t3"  # 空闲测试超时


@dataclass
class TimerInfo:
    """定时器状态."""
    name: TimerType
    timeout: float          # 超时时间（秒）
    active: bool = False
    start_time: float = 0.0

    @property
    def elapsed(self) -> float:
        if not self.active:
            return 0.0
        return time.monotonic() - self.start_time

    @property
    def remaining(self) -> float:
        if not self.active:
            return 0.0
        return max(0.0, self.timeout - self.elapsed)

    @property
    def expired(self) -> bool:
        return self.active and self.elapsed >= self.timeout


class ConnectionStateMachine:
    """IEC 60870-5-104 连接状态机.

    管理连接状态转移和4个协议定时器。
    """

    def __init__(
        self,
        t0: float = T0_DEFAULT,
        t1: float = T1_DEFAULT,
        t2: float = T2_DEFAULT,
        t3: float = T3_DEFAULT,
        on_state_change: Callable[[str, str], None] | None = None,
        on_timer_expired: Callable[[TimerType], None] | None = None,
        use_t0: bool = True,
    ):

        self._state = ConnState.STOPPED
        self._lock = threading.Lock()

        # t0 仅适用于发起 TCP 连接的一方（控制站/主站）: t0 是"连接建立超时",
        # 被控站（子站）被动接受连接，不使用 t0。子站传 use_t0=False。
        self._use_t0 = use_t0

        # 定时器
        self._timers = {
            TimerType.T0: TimerInfo(TimerType.T0, t0),
            TimerType.T1: TimerInfo(TimerType.T1, t1),
            TimerType.T2: TimerInfo(TimerType.T2, t2),
            TimerType.T3: TimerInfo(TimerType.T3, t3),
        }

        # 回调
        self._on_state_change = on_state_change
        self._on_timer_expired = on_timer_expired

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            return self._state.value

    @property
    def is_stopped(self) -> bool:
        with self._lock:
            return self._state == ConnState.STOPPED

    @property
    def is_connecting(self) -> bool:
        with self._lock:
            return self._state == ConnState.CONNECTING

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state == ConnState.RUNNING

    # ── 状态转移 ──────────────────────────────────────────────────

    def on_connected(self) -> None:
        """TCP 连接建立成功."""
        with self._lock:
            old = self._state.value
            if self._state == ConnState.STOPPED:
                self._state = ConnState.CONNECTING
                # t0 仅由发起连接的控制站启动；被控站 (use_t0=False) 不启动。
                if self._use_t0:
                    self._start_timer(TimerType.T0)
                self._notify_state_change(old, self._state.value)

    def on_startdt_con(self) -> None:
        """收到 STARTDT CON — 进入运行态."""
        with self._lock:
            old = self._state.value
            if self._state in (ConnState.CONNECTING, ConnState.RUNNING):
                self._state = ConnState.RUNNING
                self._stop_timer(TimerType.T0)
                self._stop_timer(TimerType.T1)
                self._start_timer(TimerType.T3)
                self._notify_state_change(old, self._state.value)

    def on_stopdt_con(self) -> None:
        """收到 STOPDT CON — 停止数据传输."""
        with self._lock:
            old = self._state.value
            # 只有在RUNNING或CONNECTING状态才处理STOPDT CON
            if self._state in (ConnState.RUNNING, ConnState.CONNECTING):
                self._state = ConnState.CONNECTING
                self._stop_timer(TimerType.T1)
                self._start_timer(TimerType.T3)
                self._notify_state_change(old, self._state.value)

    def on_disconnected(self) -> None:
        """TCP 连接断开."""
        with self._lock:
            old = self._state.value
            self._state = ConnState.STOPPED
            self._stop_all_timers()
            self._notify_state_change(old, self._state.value)

    def on_startdt_act_sent(self) -> None:
        """发送了 STARTDT ACT — 等待确认 (t1)."""
        self.on_u_frame_act_sent()

    def on_u_frame_act_sent(self) -> None:
        """发送了任意 U 帧 ACT (STARTDT/STOPDT/TESTFR) — 等待对应 CON.

        标准 (IEC 60870-5-104): 发送一个 I 格式报文**或 U 格式报文**后，
        必须在 t1 时间内得到接收方认可，否则认为 TCP 连接异常。因此
        STOPDT ACT 与 TESTFR ACT 同样需要启动 t1。
        """
        self._start_timer(TimerType.T1)

    def on_i_frame_sent(self) -> None:
        """发送了 I 帧 — 启动/重置 t1."""
        self._start_timer(TimerType.T1)

    def on_i_frame_received(self) -> None:
        """收到 I 帧 — 启动 t2（延迟确认）."""
        self._start_timer(TimerType.T2)

    def on_s_frame_sent(self) -> None:
        """发送了 S 帧 — 重置 t2."""
        self._stop_timer(TimerType.T2)

    def on_any_frame_sent(self) -> None:
        """发送了任意帧 — 重置 t3."""
        self._start_timer(TimerType.T3)

    def on_any_frame_received(self) -> None:
        """收到任意帧 — 重置 t3."""
        self._start_timer(TimerType.T3)

    def on_ack_received(self) -> None:
        """收到确认（S帧或带确认的U帧）— 重置 t1."""
        self._stop_timer(TimerType.T1)

    def on_testfr_act_received(self) -> None:
        """收到 TESTFR ACT — 重置 t3."""
        self._start_timer(TimerType.T3)

    # ── 定时器检查 ─────────────────────────────────────────────────

    def check_timers(self) -> TimerType | None:
        """检查所有定时器，返回第一个超时的定时器类型.

        Returns:
            超时的定时器类型，或 None
        """
        with self._lock:
            for ttype, timer in self._timers.items():
                if timer.expired:
                    timer.active = False
                    return ttype
        return None

    def get_timer_info(self) -> dict[str, TimerInfo]:
        """获取所有定时器信息."""
        with self._lock:
            return dict(self._timers)

    # ── 内部方法 ──────────────────────────────────────────────────

    def _start_timer(self, ttype: TimerType) -> None:
        """启动/重置定时器（调用前需持有锁，但这里单独处理）."""
        timer = self._timers[ttype]
        timer.active = True
        timer.start_time = time.monotonic()

    def _stop_timer(self, ttype: TimerType) -> None:
        timer = self._timers[ttype]
        timer.active = False

    def _stop_all_timers(self) -> None:
        for timer in self._timers.values():
            timer.active = False

    def _notify_state_change(self, old_state: str, new_state: str) -> None:
        if self._on_state_change and old_state != new_state:
            try:
                self._on_state_change(old_state, new_state)
            except Exception:
                pass

    def reset(self) -> None:
        """重置状态机."""
        with self._lock:
            self._state = ConnState.STOPPED
            self._stop_all_timers()
