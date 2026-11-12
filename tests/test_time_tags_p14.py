"""P1-4 时标口径测试：亚秒精度、世纪基准可配、显示与 epoch 一致.

只锁定「纯计算」行为，不冻结系统时钟（now() 用 monkeypatch 固定 time.time
与 time.localtime 的返回值）。时标的线上字节语义（本地时区）保持不变。
"""

from __future__ import annotations

import time
from datetime import datetime

from core.protocol.types import CP24Time2a, CP56Time2a


def test_cp24_now_keeps_subsecond(monkeypatch):
    """CP24 毫秒字段是「分内毫秒」：秒×1000 + 亚秒余数."""
    wall = 1730000123.456  # 固定值，避免依赖真实时钟
    monkeypatch.setattr(time, "time", lambda: wall)
    monkeypatch.setattr(time, "localtime", lambda _w: time.struct_time(
        (2026, 11, 12, 10, 30, 23, 0, 0, 0)))
    tag = CP24Time2a.now()
    assert tag.millisecond == 23 * 1000 + 456
    assert tag.minute == 30
    # 往返：毫秒字段在合法 0-59999 内且字节可还原
    assert CP24Time2a.from_bytes(tag.to_bytes()).millisecond == 23456


def test_cp56_now_keeps_subsecond(monkeypatch):
    wall = 1730000123.789
    monkeypatch.setattr(time, "time", lambda: wall)
    monkeypatch.setattr(time, "localtime", lambda _w: time.struct_time(
        (2026, 11, 12, 10, 30, 23, 0, 0, 0)))
    tag = CP56Time2a.now()
    assert tag.millisecond == 23 * 1000 + 789
    assert tag.year == 26
    assert CP56Time2a.from_bytes(tag.to_bytes()).millisecond == 23789


def test_century_base_default_is_2000():
    """默认 2000 与历史行为一致：year=0 → 2000 年."""
    tag = CP56Time2a(millisecond=1234, minute=5, hour=6, day=7, month=8, year=0)
    expected = datetime(2000, 8, 7, 6, 5, 1, 234000).timestamp()
    assert tag.to_epoch() == expected
    assert tag.to_datetime_str() == "2000-08-07 06:05:01.234"


def test_century_base_is_configurable(monkeypatch):
    """2099 年后可切世纪基准；epoch 与显示字符串同步跟随."""
    monkeypatch.setattr(CP56Time2a, "century_base", 2100)
    tag = CP56Time2a(millisecond=0, minute=0, hour=0, day=1, month=1, year=1)
    assert tag.to_epoch() == datetime(2101, 1, 1, 0, 0, 0).timestamp()
    assert tag.to_datetime_str() == "2101-01-01 00:00:00.000"


def test_to_epoch_matches_to_datetime_str():
    """两个出口用同一世纪基准，避免显示 2026、epoch 却按 1926 算."""
    tag = CP56Time2a(millisecond=4567, minute=30, hour=12, day=25, month=12, year=26)
    dt = datetime.fromtimestamp(tag.to_epoch())
    assert dt.year == 2026 and dt.month == 12 and dt.day == 25
    assert dt.hour == 12 and dt.minute == 30 and dt.second == 4
    assert tag.to_datetime_str().startswith("2026-12-25 12:30:04")
