"""实时数据库 — 内存态高速数据存储.

设计目标:
- O(1) 按 IOA 查找
- 线程安全读写
- 变化事件回调
- 批量快照导出
- 支持10万+数据点
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..protocol.types import (
    QualityDescriptor, SinglePoint, DoublePoint,
    NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, CP56Time2a,
)


# ═══════════════════════════════════════════════════════════════════
#  实时数据点
# ═══════════════════════════════════════════════════════════════════

@dataclass
class YxData:
    """遥信实时数据."""
    ioa: int = 0
    value: bool = False
    double_state: int = 0       # 0=不确定, 1=分, 2=合, 3=中间
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    timestamp: float = 0.0      # 最后更新时间 (monotonic)
    change_count: int = 0       # 变化次数
    name: str = ""

    @property
    def state_str(self) -> str:
        if self.double_state:
            return {0: "不确定", 1: "分(OFF)", 2: "合(ON)", 3: "中间"}.get(
                self.double_state, "?"
            )
        return "合(ON)" if self.value else "分(OFF)"


@dataclass
class YcData:
    """遥测实时数据."""
    ioa: int = 0
    value: float = 0.0
    raw_value: float = 0.0      # 原始值（未做比例偏移处理）
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    timestamp: float = 0.0
    change_count: int = 0
    name: str = ""
    unit: str = ""
    min_val: float = float('inf')
    max_val: float = float('-inf')

    def update_min_max(self):
        if self.value < self.min_val:
            self.min_val = self.value
        if self.value > self.max_val:
            self.max_val = self.value


@dataclass
class YkData:
    """遥控状态."""
    ioa: int = 0
    last_command: str = ""      # 最后命令
    last_state: bool = False
    select_pending: bool = False
    timestamp: float = 0.0
    name: str = ""


@dataclass
class YmData:
    """遥脉/电度实时数据."""
    ioa: int = 0
    value: int = 0
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    timestamp: float = 0.0
    change_count: int = 0
    name: str = ""


@dataclass
class DataChangeEvent:
    """数据变化事件."""
    point_type: str     # "yx"/"yc"/"ym"
    ioa: int
    old_value: Any
    new_value: Any
    timestamp: float
    quality: QualityDescriptor


ChangeCallback = Callable[[DataChangeEvent], None]


# ═══════════════════════════════════════════════════════════════════
#  实时数据库
# ═══════════════════════════════════════════════════════════════════

class RealtimeDB:
    """实时数据库.

    线程安全，支持并发读写。
    使用 dict[int, *Data] 实现 O(1) 查找。
    """

    def __init__(self, event_buffer_size: int = 10000):
        self._yx: dict[int, YxData] = {}
        self._yc: dict[int, YcData] = {}
        self._yk: dict[int, YkData] = {}
        self._ym: dict[int, YmData] = {}
        self._lock = threading.RLock()

        # 变化事件
        self._subscribers: list[ChangeCallback] = []
        self._event_buffer: deque[DataChangeEvent] = deque(
            maxlen=event_buffer_size
        )

        # 统计
        self._total_updates = 0
        self._total_changes = 0

    # ── 初始化 ──────────────────────────────────────────────────

    def init_from_point_table(self, point_table) -> None:
        """从点表初始化实时数据库."""
        from .point_table import PointTable
        with self._lock:
            for p in point_table.get_all_yx():
                self._yx[p.ioa] = YxData(
                    ioa=p.ioa,
                    value=p.initial_value,
                    quality=QualityDescriptor(p.initial_quality),
                    timestamp=time.monotonic(),
                    name=p.name,
                )

            for p in point_table.get_all_yc():
                self._yc[p.ioa] = YcData(
                    ioa=p.ioa,
                    value=p.initial_value,
                    raw_value=p.initial_value,
                    quality=QualityDescriptor(p.initial_quality),
                    timestamp=time.monotonic(),
                    name=p.name,
                    unit=p.unit,
                )

            for p in point_table.get_all_yk():
                self._yk[p.ioa] = YkData(
                    ioa=p.ioa,
                    timestamp=time.monotonic(),
                    name=p.name,
                )

            for p in point_table.get_all_ym():
                self._ym[p.ioa] = YmData(
                    ioa=p.ioa,
                    value=p.initial_value,
                    quality=QualityDescriptor(p.initial_quality),
                    timestamp=time.monotonic(),
                    name=p.name,
                )

    # ── 遥信操作 ────────────────────────────────────────────────

    def update_yx(self, ioa: int, value: bool,
                  quality: QualityDescriptor = None,
                  double_state: int = 0) -> bool:
        """更新遥信值.

        Returns:
            True 如果值发生了变化
        """
        with self._lock:
            point = self._yx.get(ioa)
            if point is None:
                # 动态创建
                point = YxData(ioa=ioa)
                self._yx[ioa] = point

            old_value = point.value
            old_quality = point.quality
            changed = (value != old_value) or (
                quality is not None and quality != old_quality
            )

            point.value = value
            point.double_state = double_state
            if quality is not None:
                point.quality = quality
            point.timestamp = time.monotonic()

            if changed:
                point.change_count += 1
                self._total_changes += 1
                self._fire_event(DataChangeEvent(
                    point_type="yx", ioa=ioa,
                    old_value=old_value, new_value=value,
                    timestamp=point.timestamp,
                    quality=quality or point.quality,
                ))

            self._total_updates += 1
            return changed

    def get_yx(self, ioa: int) -> Optional[YxData]:
        with self._lock:
            return self._yx.get(ioa)

    def get_all_yx(self) -> dict[int, YxData]:
        with self._lock:
            return dict(self._yx)

    # ── 遥测操作 ────────────────────────────────────────────────

    def update_yc(self, ioa: int, value: float,
                  quality: QualityDescriptor = None,
                  scale: float = 1.0, offset: float = 0.0) -> bool:
        """更新遥测值."""
        with self._lock:
            point = self._yc.get(ioa)
            if point is None:
                point = YcData(ioa=ioa)
                self._yc[ioa] = point

            old_value = point.value
            raw_value = value
            scaled_value = value * scale + offset

            changed = abs(scaled_value - old_value) > 1e-6 or (
                quality is not None and quality != point.quality
            )

            point.raw_value = raw_value
            point.value = scaled_value
            if quality is not None:
                point.quality = quality
            point.timestamp = time.monotonic()
            point.update_min_max()

            if changed:
                point.change_count += 1
                self._total_changes += 1
                self._fire_event(DataChangeEvent(
                    point_type="yc", ioa=ioa,
                    old_value=old_value, new_value=scaled_value,
                    timestamp=point.timestamp,
                    quality=quality or point.quality,
                ))

            self._total_updates += 1
            return changed

    def get_yc(self, ioa: int) -> Optional[YcData]:
        with self._lock:
            return self._yc.get(ioa)

    def get_all_yc(self) -> dict[int, YcData]:
        with self._lock:
            return dict(self._yc)

    # ── 遥控操作 ────────────────────────────────────────────────

    def update_yk(self, ioa: int, command: str, state: bool = False) -> None:
        with self._lock:
            point = self._yk.get(ioa)
            if point is None:
                point = YkData(ioa=ioa)
                self._yk[ioa] = point

            point.last_command = command
            point.last_state = state
            point.timestamp = time.monotonic()
            if command == "select":
                point.select_pending = True
            elif command in ("execute", "cancel"):
                point.select_pending = False

    def get_yk(self, ioa: int) -> Optional[YkData]:
        with self._lock:
            return self._yk.get(ioa)

    def get_all_yk(self) -> dict[int, YkData]:
        with self._lock:
            return dict(self._yk)

    # ── 遥脉操作 ────────────────────────────────────────────────

    def update_ym(self, ioa: int, value: int,
                  quality: QualityDescriptor = None) -> bool:
        with self._lock:
            point = self._ym.get(ioa)
            if point is None:
                point = YmData(ioa=ioa)
                self._ym[ioa] = point

            old_value = point.value
            changed = value != old_value or (
                quality is not None and quality != point.quality
            )

            point.value = value
            if quality is not None:
                point.quality = quality
            point.timestamp = time.monotonic()

            if changed:
                point.change_count += 1
                self._total_changes += 1
                self._fire_event(DataChangeEvent(
                    point_type="ym", ioa=ioa,
                    old_value=old_value, new_value=value,
                    timestamp=point.timestamp,
                    quality=quality or point.quality,
                ))

            self._total_updates += 1
            return changed

    def get_ym(self, ioa: int) -> Optional[YmData]:
        with self._lock:
            return self._ym.get(ioa)

    def get_all_ym(self) -> dict[int, YmData]:
        with self._lock:
            return dict(self._ym)

    # ── 批量操作 ────────────────────────────────────────────────

    def get_snapshot(self) -> dict[str, dict]:
        """获取全量快照."""
        with self._lock:
            return {
                'yx': dict(self._yx),
                'yc': dict(self._yc),
                'yk': dict(self._yk),
                'ym': dict(self._ym),
                'stats': {
                    'total_updates': self._total_updates,
                    'total_changes': self._total_changes,
                    'yx_count': len(self._yx),
                    'yc_count': len(self._yc),
                    'yk_count': len(self._yk),
                    'ym_count': len(self._ym),
                },
            }

    # ── 事件订阅 ────────────────────────────────────────────────

    def subscribe(self, callback: ChangeCallback) -> None:
        """注册变化回调."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: ChangeCallback) -> None:
        """取消变化回调."""
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _fire_event(self, event: DataChangeEvent) -> None:
        """触发变化事件."""
        self._event_buffer.append(event)
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception:
                pass

    def get_recent_events(self, count: int = 100) -> list[DataChangeEvent]:
        """获取最近的变化事件."""
        with self._lock:
            events = list(self._event_buffer)
            return events[-count:] if len(events) > count else events

    # ── 统计 ────────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                'total_updates': self._total_updates,
                'total_changes': self._total_changes,
                'yx_count': len(self._yx),
                'yc_count': len(self._yc),
                'yk_count': len(self._yk),
                'ym_count': len(self._ym),
                'event_buffer_size': len(self._event_buffer),
            }

    def clear(self) -> None:
        """清空所有数据."""
        with self._lock:
            self._yx.clear()
            self._yc.clear()
            self._yk.clear()
            self._ym.clear()
            self._event_buffer.clear()
            self._total_updates = 0
            self._total_changes = 0
