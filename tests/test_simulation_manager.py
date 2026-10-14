"""`core/simulation/manager.py` 模拟管理器单元测试.

覆盖预设/自定义条件的应用与同步、安装（包装引擎收发回调）与卸载（恢复原始
回调）、统计与摘要文本、便捷方法（丢包/延迟/损坏/手动断线）。

用轻量假引擎替代真实 MasterEngine/SlaveEngine，不建连接、不启事件循环。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.simulation.conditions import NetworkCondition
from core.simulation.manager import SimulationManager


class _FakeEngine:
    """最小引擎替身：只提供模拟层需要的最小接口."""

    def __init__(self, raw_cb=None, with_client=True):
        self._raw_cb = raw_cb
        self._send_frame = AsyncMock()
        self._on_frame_received = lambda frame: None
        if with_client:
            self._client = SimpleNamespace(_on_frame=None)

    def get_raw_frame_callback(self):
        return self._raw_cb

    def set_raw_frame_callback(self, callback):
        self._raw_cb = callback


# ── 初始状态 ─────────────────────────────────────────────────────

def test_initial_state_is_inactive():
    sim = SimulationManager()

    assert sim.is_active is False
    assert isinstance(sim.condition, NetworkCondition)
    assert sim.proxy is None
    assert sim.stats() == {}
    assert sim.stats_summary() == "Simulation not active"


# ── 条件配置 ─────────────────────────────────────────────────────

def test_apply_preset_updates_condition():
    sim = SimulationManager()
    sim.apply_preset("congested")

    assert sim.condition.delay_ms == pytest.approx(100)
    assert sim.condition.loss_rate == pytest.approx(0.1)


def test_apply_preset_propagates_to_installed_proxy():
    """已安装时应用预设需同步给 proxy（否则注入条件不生效）."""
    sim = SimulationManager()
    engine = _FakeEngine()
    sim.install(engine)
    proxy = sim.proxy
    assert proxy is not None

    sim.apply_preset("satellite")

    assert proxy._condition is sim.condition
    assert proxy._condition.delay_ms == pytest.approx(500)


def test_apply_condition_sets_known_keys_and_warns_on_unknown():
    sim = SimulationManager()
    sim.apply_condition(loss_rate=0.3, delay_ms=25, not_a_field=1)

    assert sim.condition.loss_rate == pytest.approx(0.3)
    assert sim.condition.delay_ms == pytest.approx(25)
    assert not hasattr(sim.condition, "not_a_field")


def test_apply_condition_propagates_to_installed_proxy():
    sim = SimulationManager()
    sim.install(_FakeEngine())
    proxy = sim.proxy

    sim.apply_condition(loss_rate=0.42)

    assert proxy._condition is sim.condition
    assert proxy._condition.loss_rate == pytest.approx(0.42)


def test_set_active_toggles_injection():
    sim = SimulationManager()
    sim.install(_FakeEngine())
    assert sim.is_active is True

    sim.set_active(False)
    assert sim.is_active is False
    assert sim.proxy._condition.active is False

    sim.set_active(True)
    assert sim.is_active is True


# ── 安装 / 卸载 ──────────────────────────────────────────────────

def test_install_wraps_engine_callbacks():
    def original_raw(frame, direction):
        return None

    engine = _FakeEngine(raw_cb=original_raw)

    sim = SimulationManager()
    sim.install(engine)

    assert sim.is_active is True
    assert sim.proxy is not None
    # 收到帧回调被替换为代理包装版本（不再是原回调对象）
    assert engine.get_raw_frame_callback() is not original_raw
    # 代理保存了原始回调引用，供卸载时恢复
    assert sim.proxy._original_rx is original_raw
    # TCP 客户端的回调引用被同步更新
    assert engine._client._on_frame is engine._on_frame_received


def test_install_without_raw_callback_leaves_it_unset():
    engine = _FakeEngine(raw_cb=None)

    sim = SimulationManager()
    sim.install(engine)

    assert engine.get_raw_frame_callback() is None
    assert sim.is_active is True


def test_install_twice_replaces_previous_proxy():
    engine = _FakeEngine(raw_cb=lambda frame, direction: None)

    sim = SimulationManager()
    sim.install(engine)
    first_proxy = sim.proxy
    sim.install(engine)

    assert sim.proxy is not first_proxy
    assert sim.is_active is True


def test_remove_when_not_installed_is_noop():
    sim = SimulationManager()
    sim.remove()
    assert sim.is_active is False


def test_remove_restores_original_callback():
    def original_raw(frame, direction):
        return None

    engine = _FakeEngine(raw_cb=original_raw)

    sim = SimulationManager()
    sim.install(engine)
    assert engine.get_raw_frame_callback() is not original_raw

    sim.remove()

    assert engine.get_raw_frame_callback() is original_raw
    assert sim.proxy is None
    assert sim.is_active is False


def test_remove_without_engine_is_noop():
    """_installed=True 但 _engine 为空（异常状态）时安全返回."""
    sim = SimulationManager()
    sim._installed = True
    sim._engine = None

    sim.remove()
    assert sim._installed is True      # 未做任何修改


# ── 统计与摘要 ───────────────────────────────────────────────────

def test_stats_and_reset_after_install():
    sim = SimulationManager()
    sim.install(_FakeEngine())
    sim.proxy._stats["rx_total"] = 5

    assert sim.stats()["rx_total"] == 5

    sim.reset_stats()
    assert sim.stats()["rx_total"] == 0


def test_stats_summary_base_lines():
    sim = SimulationManager()
    sim.install(_FakeEngine())
    summary = sim.stats_summary()

    assert "Network Simulation" in summary
    assert "Active: True" in summary
    assert "RX: 0 total, 0 dropped, 0 corrupted" in summary
    assert "Disconnects" not in summary       # 0 时不输出
    assert "Duplicated" not in summary        # 0 时不输出


def test_stats_summary_includes_optional_lines():
    sim = SimulationManager()
    sim.install(_FakeEngine())
    sim.proxy._stats.update({"disconnects": 2, "rx_duplicated": 1, "tx_duplicated": 3})

    summary = sim.stats_summary()

    assert "Disconnects: 2" in summary
    assert "Duplicated: RX=1, TX=3" in summary


# ── 便捷方法 ─────────────────────────────────────────────────────

def test_set_loss_delay_corrupt_shortcuts():
    sim = SimulationManager()

    sim.set_loss(0.25)
    assert sim.condition.loss_rate == pytest.approx(0.25)

    sim.set_delay(80, variance=15)
    assert sim.condition.delay_ms == pytest.approx(80)
    assert sim.condition.delay_variance_ms == pytest.approx(15)

    sim.set_corrupt(0.1, bits=3)
    assert sim.condition.corrupt_rate == pytest.approx(0.1)
    assert sim.condition.corrupt_bits == 3


def test_disconnect_without_proxy_is_noop():
    sim = SimulationManager()
    sim.disconnect(5.0)          # 未安装 → 不抛异常
    assert sim.proxy is None


def test_manual_disconnect_sets_deadline_and_counts():
    sim = SimulationManager()
    sim.install(_FakeEngine())

    sim.disconnect(3.0)

    assert sim.proxy._disconnected_until > 0
    assert sim.stats()["disconnects"] == 1
