"""桥上网络条件注入器测试（T85）——帧级决策确定性验证（固定随机种子）."""

from __future__ import annotations

import random

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
