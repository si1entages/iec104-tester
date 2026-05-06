"""点表管理 — 遥信/遥测/遥控/遥脉 点定义与管理.

点表是 SCADA 系统的核心数据结构，定义所有信息对象的地址、描述、初始值等。
"""

from __future__ import annotations

import enum
import csv
import threading
from dataclasses import dataclass, field
from typing import Any, Optional
from pathlib import Path

import yaml


class PointType(enum.Enum):
    """信息类型."""
    YX = "yx"   # 遥信 (单点/双点)
    YC = "yc"   # 遥测 (模拟量)
    YK = "yk"   # 遥控 (控制命令)
    YM = "ym"   # 遥脉 (电度/累计量)


class YxType(enum.Enum):
    """遥信类型."""
    SINGLE = "single"   # 单点
    DOUBLE = "double"   # 双点


class YcType(enum.Enum):
    """遥测类型."""
    NORMALIZED = "normalized"   # 归一化 (-1..+1)
    SCALED = "scaled"           # 标度化 (-32768..+32767)
    SHORT_FLOAT = "short_float" # 短浮点 (IEEE 754)


@dataclass
class PointDef:
    """点定义基类."""
    ioa: int                        # 信息对象地址
    name: str = ""                  # 描述/名称
    group: int = 1                  # 组号 (用于分组召唤, 1-16)
    enabled: bool = True            # 是否启用
    initial_quality: int = 0        # 初始品质
    tags: dict[str, str] = field(default_factory=dict)  # 自定义标签


@dataclass
class YxPointDef(PointDef):
    """遥信点定义."""
    point_type: YxType = YxType.SINGLE
    initial_value: bool = False
    inverted: bool = False          # 取反（常用于NC触点）


@dataclass
class YcPointDef(PointDef):
    """遥测点定义."""
    data_type: YcType = YcType.SHORT_FLOAT
    initial_value: float = 0.0
    min_value: float = -99999.0
    max_value: float = 99999.0
    dead_band: float = 0.0          # 死区（变化超过此值才上送）
    unit: str = ""                  # 单位
    scale: float = 1.0              # 比例系数
    offset: float = 0.0             # 偏移量
    decimal_places: int = 2         # 显示小数位数


@dataclass
class YkPointDef(PointDef):
    """遥控点定义."""
    command_type: str = "single"    # single/double
    select_before_execute: bool = True  # SBO (选择-执行)
    timeout_ms: int = 10000         # 选择超时


@dataclass
class YmPointDef(PointDef):
    """遥脉/电度点定义."""
    initial_value: int = 0
    counter_type: int = 0           # 0=不计数, 1=计数, 2=增量
    frozen: bool = False


class PointTable:
    """点表管理器.

    支持:
    - 按IOA查找
    - 按类型分组
    - YAML/CSV 导入导出
    - 线程安全操作
    """

    def __init__(self):
        self._yx: dict[int, YxPointDef] = {}
        self._yc: dict[int, YcPointDef] = {}
        self._yk: dict[int, YkPointDef] = {}
        self._ym: dict[int, YmPointDef] = {}
        self._lock = threading.RLock()
        self._station_name: str = ""
        self._common_addr: int = 1

    @property
    def station_name(self) -> str:
        return self._station_name

    @station_name.setter
    def station_name(self, name: str):
        self._station_name = name

    @property
    def common_addr(self) -> int:
        return self._common_addr

    @common_addr.setter
    def common_addr(self, addr: int):
        self._common_addr = addr

    # ── 点操作 ──────────────────────────────────────────────────

    def add_yx(self, point: YxPointDef) -> None:
        with self._lock:
            self._yx[point.ioa] = point

    def add_yc(self, point: YcPointDef) -> None:
        with self._lock:
            self._yc[point.ioa] = point

    def add_yk(self, point: YkPointDef) -> None:
        with self._lock:
            self._yk[point.ioa] = point

    def add_ym(self, point: YmPointDef) -> None:
        with self._lock:
            self._ym[point.ioa] = point

    def get_yx(self, ioa: int) -> Optional[YxPointDef]:
        with self._lock:
            return self._yx.get(ioa)

    def get_yc(self, ioa: int) -> Optional[YcPointDef]:
        with self._lock:
            return self._yc.get(ioa)

    def get_yk(self, ioa: int) -> Optional[YkPointDef]:
        with self._lock:
            return self._yk.get(ioa)

    def get_ym(self, ioa: int) -> Optional[YmPointDef]:
        with self._lock:
            return self._ym.get(ioa)

    def remove_point(self, point_type: PointType, ioa: int) -> bool:
        with self._lock:
            store = self._get_store(point_type)
            if ioa in store:
                del store[ioa]
                return True
            return False

    def get_all_yx(self) -> list[YxPointDef]:
        with self._lock:
            return sorted(self._yx.values(), key=lambda p: p.ioa)

    def get_all_yc(self) -> list[YcPointDef]:
        with self._lock:
            return sorted(self._yc.values(), key=lambda p: p.ioa)

    def get_all_yk(self) -> list[YkPointDef]:
        with self._lock:
            return sorted(self._yk.values(), key=lambda p: p.ioa)

    def get_all_ym(self) -> list[YmPointDef]:
        with self._lock:
            return sorted(self._ym.values(), key=lambda p: p.ioa)

    def get_yx_by_group(self, group: int) -> list[YxPointDef]:
        with self._lock:
            return sorted(
                [p for p in self._yx.values() if p.group == group],
                key=lambda p: p.ioa
            )

    def get_yc_by_group(self, group: int) -> list[YcPointDef]:
        with self._lock:
            return sorted(
                [p for p in self._yc.values() if p.group == group],
                key=lambda p: p.ioa
            )

    @property
    def yx_count(self) -> int:
        with self._lock:
            return len(self._yx)

    @property
    def yc_count(self) -> int:
        with self._lock:
            return len(self._yc)

    @property
    def yk_count(self) -> int:
        with self._lock:
            return len(self._yk)

    @property
    def ym_count(self) -> int:
        with self._lock:
            return len(self._ym)

    def _get_store(self, point_type: PointType) -> dict:
        return {
            PointType.YX: self._yx,
            PointType.YC: self._yc,
            PointType.YK: self._yk,
            PointType.YM: self._ym,
        }[point_type]

    # ── YAML 导入导出 ────────────────────────────────────────────

    def load_yaml(self, path: str | Path) -> None:
        """从 YAML 文件加载点表."""
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data:
            return

        self._station_name = data.get('station_name', '')
        self._common_addr = data.get('common_addr', 1)

        with self._lock:
            self._yx.clear()
            self._yc.clear()
            self._yk.clear()
            self._ym.clear()

            for p in data.get('yx', []):
                point = YxPointDef(
                    ioa=p['ioa'],
                    name=p.get('name', ''),
                    group=p.get('group', 1),
                    enabled=p.get('enabled', True),
                    point_type=YxType(p.get('type', 'single')),
                    initial_value=p.get('initial_value', False),
                    inverted=p.get('inverted', False),
                )
                self._yx[point.ioa] = point

            for p in data.get('yc', []):
                point = YcPointDef(
                    ioa=p['ioa'],
                    name=p.get('name', ''),
                    group=p.get('group', 1),
                    enabled=p.get('enabled', True),
                    data_type=YcType(p.get('type', 'short_float')),
                    initial_value=p.get('initial_value', 0.0),
                    min_value=p.get('min_value', -99999.0),
                    max_value=p.get('max_value', 99999.0),
                    dead_band=p.get('dead_band', 0.0),
                    unit=p.get('unit', ''),
                    scale=p.get('scale', 1.0),
                    offset=p.get('offset', 0.0),
                    decimal_places=p.get('decimal_places', 2),
                )
                self._yc[point.ioa] = point

            for p in data.get('yk', []):
                point = YkPointDef(
                    ioa=p['ioa'],
                    name=p.get('name', ''),
                    group=p.get('group', 1),
                    enabled=p.get('enabled', True),
                    command_type=p.get('type', 'single'),
                    select_before_execute=p.get('sbo', True),
                    timeout_ms=p.get('timeout_ms', 10000),
                )
                self._yk[point.ioa] = point

            for p in data.get('ym', []):
                point = YmPointDef(
                    ioa=p['ioa'],
                    name=p.get('name', ''),
                    group=p.get('group', 1),
                    enabled=p.get('enabled', True),
                    initial_value=p.get('initial_value', 0),
                )
                self._ym[point.ioa] = point

    def save_yaml(self, path: str | Path) -> None:
        """导出点表到 YAML 文件."""
        with self._lock:
            data = {
                'station_name': self._station_name,
                'common_addr': self._common_addr,
                'yx': [
                    {
                        'ioa': p.ioa,
                        'name': p.name,
                        'group': p.group,
                        'enabled': p.enabled,
                        'type': p.point_type.value,
                        'initial_value': p.initial_value,
                        'inverted': p.inverted,
                    }
                    for p in sorted(self._yx.values(), key=lambda x: x.ioa)
                ],
                'yc': [
                    {
                        'ioa': p.ioa,
                        'name': p.name,
                        'group': p.group,
                        'enabled': p.enabled,
                        'type': p.data_type.value,
                        'initial_value': p.initial_value,
                        'min_value': p.min_value,
                        'max_value': p.max_value,
                        'dead_band': p.dead_band,
                        'unit': p.unit,
                        'scale': p.scale,
                        'offset': p.offset,
                        'decimal_places': p.decimal_places,
                    }
                    for p in sorted(self._yc.values(), key=lambda x: x.ioa)
                ],
                'yk': [
                    {
                        'ioa': p.ioa,
                        'name': p.name,
                        'group': p.group,
                        'enabled': p.enabled,
                        'type': p.command_type,
                        'sbo': p.select_before_execute,
                        'timeout_ms': p.timeout_ms,
                    }
                    for p in sorted(self._yk.values(), key=lambda x: x.ioa)
                ],
                'ym': [
                    {
                        'ioa': p.ioa,
                        'name': p.name,
                        'group': p.group,
                        'enabled': p.enabled,
                        'initial_value': p.initial_value,
                    }
                    for p in sorted(self._ym.values(), key=lambda x: x.ioa)
                ],
            }

        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # ── CSV 导入 ──────────────────────────────────────────────────

    def load_csv(self, path: str | Path, point_type: PointType) -> None:
        """从 CSV 文件加载指定类型的点表.

        CSV 格式: ioa, name, group, enabled, [type-specific fields...]
        """
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                ioa = int(row['ioa'])
                name = row.get('name', '')
                group = int(row.get('group', 1))
                enabled = row.get('enabled', 'true').lower() in ('true', '1', 'yes')

                if point_type == PointType.YX:
                    self.add_yx(YxPointDef(
                        ioa=ioa, name=name, group=group, enabled=enabled,
                        point_type=YxType(row.get('type', 'single')),
                        initial_value=row.get('initial_value', 'false').lower() == 'true',
                    ))
                elif point_type == PointType.YC:
                    self.add_yc(YcPointDef(
                        ioa=ioa, name=name, group=group, enabled=enabled,
                        data_type=YcType(row.get('type', 'short_float')),
                        initial_value=float(row.get('initial_value', 0)),
                        unit=row.get('unit', ''),
                    ))

    # ── 批量生成 ──────────────────────────────────────────────────

    def generate_demo_points(
        self,
        yx_count: int = 100,
        yc_count: int = 50,
        yk_count: int = 20,
        ym_count: int = 10,
    ) -> None:
        """生成演示用点表."""
        with self._lock:
            self._yx.clear()
            self._yc.clear()
            self._yk.clear()
            self._ym.clear()

            for i in range(yx_count):
                group = (i // 16) + 1  # 每16个一组
                self._yx[i + 1] = YxPointDef(
                    ioa=i + 1,
                    name=f"YX_{i + 1:04d}",
                    group=min(group, 16),
                    point_type=YxType.SINGLE,
                    initial_value=False,
                )

            for i in range(yc_count):
                group = (i // 8) + 1
                self._yc[i + 1001] = YcPointDef(
                    ioa=i + 1001,
                    name=f"YC_{i + 1:04d}",
                    group=min(group, 16),
                    data_type=YcType.SHORT_FLOAT,
                    initial_value=0.0,
                    unit="kW" if i % 3 == 0 else ("kV" if i % 3 == 1 else "A"),
                )

            for i in range(yk_count):
                self._yk[i + 2001] = YkPointDef(
                    ioa=i + 2001,
                    name=f"YK_{i + 1:04d}",
                    command_type="single",
                )

            for i in range(ym_count):
                self._ym[i + 3001] = YmPointDef(
                    ioa=i + 3001,
                    name=f"YM_{i + 1:04d}",
                    initial_value=0,
                )
