"""序列号管理器测试."""

import pytest
from core.protocol.sequence import SequenceManager


def test_sequence_manager():
    """测试序列号管理器."""
    print("=== Sequence Manager Tests ===")

    seq = SequenceManager(k=12, w=8)

    # 初始状态
    assert seq.send_seq == 0
    assert seq.recv_seq == 0
    assert seq.send_window_available == True
    assert seq.unconfirmed_count == 0

    # 发送
    for i in range(12):
        s = seq.get_send_seq()
        assert s == i

    # 窗口满
    assert seq.send_window_available == False
    try:
        seq.get_send_seq()
        assert False, "Should raise"
    except RuntimeError:
        pass

    # 确认
    seq.process_rx_s_frame(12)
    assert seq.send_window_available == True

    # 接收
    for i in range(8):
        result = seq.process_rx_i_frame(i)
        assert result == True

    print("  ✅ Sequence manager tests passed")