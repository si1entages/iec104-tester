"""桥上网络条件注入器测试（T85）——帧级决策确定性验证（固定随机种子）."""

from __future__ import annotations

import random

import pytest

from core.engine.condition_injector import ConditionInjector, DeliverAction
from core.protocol.apci import APCICodec
from core.simulation.conditions import NetworkCondition

I_FRAME = APCICodec.encode_i(tx_seq=0, rx_seq=0, asdu_data=b"")


def _process(inj: ConditionInjector, frame: bytes = I_FRAME,
             direction: str = "tx") -> list[DeliverAction]:
    return inj.process(frame, direction)


def test_clean_condition_is_plain_passthrough():
    inj = ConditionInjector(NetworkCondition())
    assert not inj.active
    out = _process(inj)
    assert len(out) == 1 and out[0].data == I_FRAME and out[0].delay_s == 0


def test_loss_drops_frame():
    random.seed(1)
    inj = ConditionInjector(NetworkCondition(loss_rate=1.0))
    assert inj.active and _process(inj) == []
    assert inj.stats.dropped == 1


def test_corrupt_flips_bits_and_stats():
    random.seed(2)
    inj = ConditionInjector(NetworkCondition(corrupt_rate=1.0, corrupt_bits=1))
    out = _process(inj)
    assert len(out) == 1 and out[0].data != I_FRAME
    assert inj.stats.corrupted == 1


def test_duplicate_emits_two_actions():
    random.seed(3)
    inj = ConditionInjector(NetworkCondition(duplicate_rate=1.0))
    out = _process(inj)
    assert len(out) == 2 and inj.stats.duplicated == 1


def test_delay_sets_positive_delay():
    random.seed(4)
    inj = ConditionInjector(NetworkCondition(delay_ms=100, delay_variance_ms=0))
    out = _process(inj)
    assert len(out) == 1 and out[0].delay_s > 0 and inj.stats.delayed == 1


def test_direction_filter_passes_untouched():
    inj = ConditionInjector(NetworkCondition(loss_rate=1.0, direction="rx"))
    assert len(_process(inj, direction="tx")) == 1  # 主站→子站不干扰
    assert _process(inj, direction="rx") == []       # 子站→主站全丢


def test_disconnect_blocks_for_duration():
    random.seed(5)
    inj = ConditionInjector(NetworkCondition(
        disconnect_rate=1.0, disconnect_duration_s=0.01))
    assert _process(inj) == []
    assert inj.is_disconnected() and inj.stats.disconnects == 1
    import time
    time.sleep(0.02)
    assert not inj.is_disconnected()
    # 恢复后关闭断线率，验证放行
    inj.update(NetworkCondition())
    assert len(_process(inj)) == 1


def test_inactive_condition_passthrough_and_update():
    inj = ConditionInjector(NetworkCondition(loss_rate=1.0, active=False))
    assert not inj.active and len(_process(inj)) == 1
    inj.update(NetworkCondition(loss_rate=1.0))
    assert inj.active and _process(inj) == []
    inj.update(None)
    assert not inj.active and len(_process(inj)) == 1


def test_reorder_batches_and_stats():
    random.seed(7)
    inj = ConditionInjector(NetworkCondition(
        reorder_rate=1.0, reorder_window=3))
    outs = [_process(inj) for _ in range(3)]
    assert inj.stats.reordered == 3
    # 乱序 = 附加延迟（后发先至），帧数守恒且每帧都带正延迟
    assert sum(len(o) for o in outs) == 3
    assert all(o[0].delay_s > 0 for o in outs)


@pytest.mark.asyncio
async def test_emit_actions_immediate_and_delayed():
    """emit_actions：立即动作写 writer，延迟动作由 loop 调度后写入."""
    import asyncio

    from core.engine.condition_injector import _delayed_write, emit_actions

    class FakeWriter:
        def __init__(self):
            self.buf = bytearray()
            self.is_closing = lambda: False

        def write(self, data):
            self.buf.extend(data)

        async def drain(self):
            pass

    w = FakeWriter()
    await emit_actions([DeliverAction(b"now"), DeliverAction(b"later", 0.01)], w)
    assert bytes(w.buf) == b"now"
    await asyncio.sleep(0.03)
    assert bytes(w.buf) == b"nowlater"

    # 关闭态延迟写被吞（不抛）
    closed = FakeWriter()
    closed.is_closing = lambda: True
    _delayed_write(closed, b"x")
    assert bytes(closed.buf) == b""


def test_disconnect_during_silence_drops_all():
    """断线期内所有帧被丢弃."""
    import time

    inj = ConditionInjector(NetworkCondition(
        disconnect_rate=1.0, disconnect_duration_s=0.05))
    assert _process(inj) == []
    assert _process(inj) == []
    assert inj.stats.disconnects == 1 and inj.stats.dropped >= 1  # 触发 + 静默期丢弃
    time.sleep(0.06)
