"""`core/simulation/conditions.py` 网络异常条件与预设单元测试."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.simulation.conditions import AnomalyType, ConditionPreset, NetworkCondition


def test_default_condition_is_clean_and_active():
    c = NetworkCondition()

    assert c.active is True
    assert c.direction == "both"
    assert c.has_any() is False
    assert c.describe() == "(none)"


@pytest.mark.parametrize("kwargs", [
    {"delay_ms": 10},
    {"loss_rate": 0.1},
    {"duplicate_rate": 0.1},
    {"corrupt_rate": 0.1},
    {"reorder_rate": 0.1},
    {"disconnect_rate": 0.1},
    {"bandwidth_bps": 1024},
])
def test_has_any_detects_each_condition(kwargs):
    assert NetworkCondition(**kwargs).has_any() is True


def test_describe_lists_all_conditions():
    c = NetworkCondition(
        delay_ms=30, delay_variance_ms=10, loss_rate=0.05, duplicate_rate=0.02,
        corrupt_rate=0.01, corrupt_bits=2, reorder_rate=0.03,
        disconnect_rate=0.04, disconnect_duration_s=5, bandwidth_bps=2048,
    )
    desc = c.describe()

    assert "delay=30ms±10ms" in desc
    assert "loss=5%" in desc
    assert "dup=2%" in desc
    assert "corrupt=1%(2bit)" in desc
    assert "reorder=3%" in desc
    assert "disconnect=4%/5s" in desc
    assert "bw=2048B/s" in desc


def test_anomaly_type_values_are_stable():
    """枚举值是与外部配置/文档约定的字符串，不应轻易变更."""
    assert AnomalyType.DELAY.value == "delay"
    assert AnomalyType.LOSS.value == "loss"
    assert AnomalyType.CORRUPT.value == "corrupt"
    assert AnomalyType.DISCONNECT.value == "disconnect"
    assert len(list(AnomalyType)) == 8


# ── 预设 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("preset,checks", [
    (ConditionPreset.clean, {}),
    (ConditionPreset.poor_wifi, {"delay_ms": 30, "loss_rate": 0.05, "reorder_rate": 0.02}),
    (ConditionPreset.congested, {"delay_ms": 100, "loss_rate": 0.1, "duplicate_rate": 0.02}),
    (ConditionPreset.satellite, {"delay_ms": 500, "loss_rate": 0.02}),
    (ConditionPreset.unreliable, {"loss_rate": 0.3, "corrupt_rate": 0.05}),
    (ConditionPreset.intermittent, {"disconnect_rate": 0.05, "disconnect_duration_s": 5.0}),
    (ConditionPreset.slow_link, {"bandwidth_bps": 1024, "delay_ms": 50}),
    (ConditionPreset.stress_test, {"loss_rate": 0.1, "disconnect_rate": 0.01}),
])
def test_presets_return_expected_conditions(preset, checks):
    c = preset()
    assert isinstance(c, NetworkCondition)
    for key, value in checks.items():
        assert getattr(c, key) == pytest.approx(value)


def test_clean_preset_has_no_anomaly():
    assert ConditionPreset.clean().has_any() is False


def test_stress_preset_has_anomaly_and_describes():
    c = ConditionPreset.stress_test()
    assert c.has_any() is True
    assert "loss=" in c.describe()


@pytest.mark.parametrize("name,attr", [
    ("clean", "loss_rate"),
    ("poor_wifi", "delay_ms"),
    ("congested", "duplicate_rate"),
    ("satellite", "delay_ms"),
    ("unreliable", "corrupt_rate"),
    ("intermittent", "disconnect_rate"),
    ("slow_link", "bandwidth_bps"),
    ("stress", "reorder_rate"),
])
def test_from_name_resolves_all_presets(name, attr):
    c = ConditionPreset.from_name(name)
    assert isinstance(c, NetworkCondition)
    assert hasattr(c, attr)


def test_from_name_unknown_raises_with_available_list():
    with pytest.raises(ValueError, match="Unknown preset: bogus"):
        ConditionPreset.from_name("bogus")
