"""序列号管理器 — IEC 60870-5-104 流控核心.

实现:
- 发送序列号 (V(S)) 和接收序列号 (V(R)) 管理
- k-w 流控机制
- 窗口检测
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from .constants import K_DEFAULT, W_DEFAULT


class SequenceManager:
    """I帧序列号管理器.

    核心规则 (IEC 60870-5-104 Section 5.5):
    - 发送方: 每发一个I帧, V(S) += 1
    - 接收方: 每收一个I帧, V(R) += 1
    - S帧确认: 告知对方"我已收到序列号 < N 的所有I帧"
    - 流控: 当未确认I帧数 >= k 时，停止发送
    - 确认触发: 当收到w个未确认I帧时，发送S帧确认
    """

    def __init__(self, k: int = K_DEFAULT, w: int = W_DEFAULT):
        self._k = k              # 发送窗口大小
        self._w = w              # 接收确认阈值

        self._send_seq = 0       # V(S): 下一个要发送的I帧序列号
        self._recv_seq = 0       # V(R): 下一个期望接收的I帧序列号
        self._last_ack_rx = 0    # 最后被确认的接收序列号（对方S帧确认的值）
        self._i_frame_count = 0  # 自上次S帧确认后收到的I帧数量

        self._lock = threading.Lock()
        self._on_send_s_frame: Optional[Callable[[int], None]] = None

    # ── 属性 ──────────────────────────────────────────────────────

    @property
    def send_seq(self) -> int:
        with self._lock:
            return self._send_seq

    @property
    def recv_seq(self) -> int:
        with self._lock:
            return self._recv_seq

    @property
    def unconfirmed_count(self) -> int:
        """未确认的I帧数量."""
        with self._lock:
            return self._seq_diff(self._send_seq, self._last_ack_rx)

    @property
    def send_window_available(self) -> bool:
        """发送窗口是否还有空间."""
        with self._lock:
            return self._seq_diff(self._send_seq, self._last_ack_rx) < self._k

    @property
    def k(self) -> int:
        return self._k

    @property
    def w(self) -> int:
        return self._w

    # ── 发送操作 ──────────────────────────────────────────────────

    def get_send_seq(self) -> int:
        """获取当前发送序列号并递增.

        Returns:
            当前序列号（调用前的值）

        Raises:
            RuntimeError: 发送窗口已满
        """
        with self._lock:
            unconfirmed = self._seq_diff(self._send_seq, self._last_ack_rx)
            if unconfirmed >= self._k:
                raise RuntimeError(
                    f"Send window full: unconfirmed={unconfirmed}, k={self._k}"
                )
            seq = self._send_seq
            self._send_seq = (self._send_seq + 1) & 0x7FFF
            return seq

    # ── 接收操作 ──────────────────────────────────────────────────

    def get_recv_seq(self) -> int:
        """获取当前接收序列号."""
        with self._lock:
            return self._recv_seq

    def process_rx_i_frame(self, rx_seq: int) -> bool:
        """处理收到的I帧的发送序列号.

        Args:
            rx_seq: 收到的I帧的发送序列号（对方的V(S)）

        Returns:
            True 如果序列号正确（连续），False 如果失序
        """
        with self._lock:
            expected = self._recv_seq
            if rx_seq != expected:
                return False

            self._recv_seq = (self._recv_seq + 1) & 0x7FFF
            self._i_frame_count += 1

            # 检查是否需要发送S帧确认
            need_s_frame = self._i_frame_count >= self._w

            if need_s_frame:
                self._i_frame_count = 0

            # 触发回调
            if need_s_frame and self._on_send_s_frame:
                self._on_send_s_frame(self._recv_seq)

            return True

    def process_rx_s_frame(self, rx_seq: int) -> None:
        """处理收到的S帧确认.

        Args:
            rx_seq: S帧中的接收序列号（对方的V(R)，
                    表示已收到此序列号之前的所有I帧）
        """
        with self._lock:
            self._last_ack_rx = rx_seq & 0x7FFF

    def process_rx_u_frame_startdt_con(self) -> None:
        """收到STARTDT CON时重置序列号."""
        with self._lock:
            self._send_seq = 0
            self._recv_seq = 0
            self._last_ack_rx = 0
            self._i_frame_count = 0

    # ── 回调设置 ──────────────────────────────────────────────────

    def set_s_frame_callback(self, callback: Callable[[int], None]) -> None:
        """设置发送S帧的回调（当收到w个I帧时触发）."""
        self._on_send_s_frame = callback

    # ── 辅助 ──────────────────────────────────────────────────────

    @staticmethod
    def _seq_diff(a: int, b: int) -> int:
        """计算两个序列号的差值（模 2^15）."""
        return (a - b) & 0x7FFF

    def reset(self) -> None:
        """重置所有序列号."""
        with self._lock:
            self._send_seq = 0
            self._recv_seq = 0
            self._last_ack_rx = 0
            self._i_frame_count = 0

    def __str__(self) -> str:
        return (
            f"Seq[V(S)={self._send_seq}, V(R)={self._recv_seq}, "
            f"unack={self.unconfirmed_count}, k={self._k}, w={self._w}]"
        )
