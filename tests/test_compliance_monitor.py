"""合规监视器测试（T79）——合成帧序列确定性验证（不起真机）."""

from __future__ import annotations

from core.engine.compliance_monitor import ComplianceMonitor
from core.protocol.apci import APCICodec
from core.protocol.constants import (
    U_STARTDT_ACT,
    U_STARTDT_CON,
    U_STOPDT_ACT,
    U_TESTFR_ACT,
    U_TESTFR_CON,
)


def _u(func: int) -> bytes:
    return APCICodec.encode_u(func)


def _i(tx: int, rx: int, asdu: bytes = b"") -> bytes:
    return APCICodec.encode_i(tx, rx, asdu)


def _kinds(m: ComplianceMonitor) -> set[str]:
    return set(m.violation_counts.keys())


def test_clean_handshake_and_data_no_violations():
    m = ComplianceMonitor()
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _i(0, 0), 0.2)     # 主站 I seq0
    m.observe("rx", _i(0, 1), 0.3)     # 子站 I seq0 + 确认主站 seq0
    m.observe("tx", _i(1, 1), 0.4)     # 主站 I seq1 + 确认子站 seq0
    m.poll(0.5)
    assert m.violation_counts == {}, m.violations
    assert m.as_dict()["frames_seen"] == 5


def test_seq_jump_and_dup():
    m = ComplianceMonitor()
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _i(0, 0), 0.2)
    m.observe("tx", _i(5, 0), 0.3)     # 跳变（期望 1）
    m.observe("tx", _i(5, 0), 0.4)     # 重复
    assert "seq-jump" in _kinds(m)
    assert "seq-dup" in _kinds(m)


def test_ack_ahead_flags_slave():
    """子站确认序号超前主站实际发送 → ack-ahead 违规归属子站."""
    m = ComplianceMonitor()
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _i(0, 0), 0.2)     # 主站仅发送到 seq0
    m.observe("rx", _i(0, 3), 0.3)     # 子站却确认到 seq2
    assert "ack-ahead" in _kinds(m)
    v = [x for x in m.violations if x.kind == "ack-ahead"][-1]
    assert v.side == "slave"


def test_i_frame_before_startdt():
    m = ComplianceMonitor()
    m.observe("tx", _i(0, 0), 0.0)     # 未 STARTDT 即传数据
    assert "no-startdt" in _kinds(m)


def test_startdt_duplicate():
    m = ComplianceMonitor()
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _u(U_STARTDT_ACT), 0.2)  # 未 STOPDT 再启动
    assert "startdt-dup" in _kinds(m)


def test_t1_timeout_then_ack_clears():
    m = ComplianceMonitor(t1=15.0)
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _i(0, 0), 1.0)
    m.poll(17.0)                        # t1=15 已过，无确认
    assert "t1" in _kinds(m)
    # 确认到达 → 解除；不再重复报
    m.observe("rx", APCICodec.encode_s(rx_seq=1), 18.0)
    m.poll(40.0)
    assert sum(1 for v in m.violations if v.kind == "t1") == 1


def test_t2_missing_ack():
    m = ComplianceMonitor(t2=10.0)
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    # 主站发 I（子站收到），子站长时间不确认
    m.observe("tx", _i(0, 0), 1.0)
    m.poll(12.0)                        # t2=10 已过
    assert "t2" in _kinds(m)
    # 子站随后确认（S 帧归属子站发送方向 = rx）
    m.observe("rx", APCICodec.encode_s(rx_seq=1), 12.5)
    m.poll(30.0)
    assert sum(1 for v in m.violations if v.kind == "t2") == 1


def test_t3_silence():
    m = ComplianceMonitor(t3=20.0)
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.poll(25.0)                        # 静默 > t3
    assert "t3" in _kinds(m)
    m.observe("tx", _i(0, 0), 26.0)     # 恢复流量
    m.poll(40.0)                        # 26→40 仅 14s 静默，不构成第二次 t3
    assert sum(1 for v in m.violations if v.kind == "t3") == 1


def test_k_exceed():
    m = ComplianceMonitor(k=5)
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    for seq in range(6):                # 发 6 帧无确认，k=5
        m.observe("tx", _i(seq, 0), 1.0 + seq * 0.01)
    assert "k-exceed" in _kinds(m)


def test_testfr_duplicate_and_con_clears():
    m = ComplianceMonitor()
    m.observe("tx", _u(U_TESTFR_ACT), 0.0)
    m.observe("tx", _u(U_TESTFR_ACT), 0.1)   # 未 CON 重复
    assert "testfr-dup" in _kinds(m)
    m.observe("rx", _u(U_TESTFR_CON), 0.2)   # CON 解除 pending
    m.observe("tx", _u(U_TESTFR_ACT), 0.3)
    assert sum(1 for v in m.violations if v.kind == "testfr-dup") == 1


def test_seq_mod_wrap_not_flagged():
    m = ComplianceMonitor()
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _i(32767, 0), 0.2)
    m.observe("tx", _i(0, 0), 0.3)      # 32767 → 0（mod 32768）正常
    assert "seq-jump" not in _kinds(m)


def test_stopdt_reallows_startdt():
    m = ComplianceMonitor()
    m.observe("tx", _u(U_STARTDT_ACT), 0.0)
    m.observe("rx", _u(U_STARTDT_CON), 0.1)
    m.observe("tx", _u(U_STOPDT_ACT), 0.2)
    m.observe("tx", _u(U_STARTDT_ACT), 0.3)  # STOPDT 后再启动不算重复
    assert "startdt-dup" not in _kinds(m)
