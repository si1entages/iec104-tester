"""Excel(xlsx) 点表导入导出 + 设计基准 vs 实测比对（T95，A2 采纳）.

解析为纯函数：行级错误收集（跳过坏行继续解析，不 fail-fast），
致命问题（非 xlsx / 缺 type/ioa 列 / 零有效行）抛 ``ValueError``。
导入语义与 CSV 一致（整表替换）；导入成功即把结果快照为**设计基准**，
供 :func:`design_diff` 与实测（自动学习后的点表 + data_store 观测值域）比对——
对应真机联调暴露的缺口：真机 IOA 16385+ 与演示表 1001 对不上，自动学习兜底但无法核对。

列头规范名与 CSV 导出一致（英文），解析兼容中文别名（类型/信息对象地址/名称/…），
类型与子类型亦接受中文（遥信/遥测/单点/双点/归一化/标度/短浮点）。
"""

from __future__ import annotations

import io
import math
from typing import Any

from openpyxl import Workbook, load_workbook

from core.data.point_table import (
    PointTable,
    StepPointDef,
    YcPointDef,
    YcType,
    YkPointDef,
    YmPointDef,
    YxPointDef,
    YxType,
)

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# 列定义：(规范列头, 别名…)。解析时按 strip+lower 归一后匹配任一名称。
_COLUMNS: tuple[tuple[str, ...], ...] = (
    ("type", "类型"),
    ("ioa", "信息对象地址"),
    ("name", "名称", "点名", "描述"),
    ("group", "组", "分组"),
    ("enabled", "启用", "有效"),
    ("subtype", "子类型"),
    ("value", "初始值", "初值"),
    ("sbo", "选择执行", "sbo"),
    ("unit", "单位"),
    ("min_value", "下限", "最小值"),
    ("max_value", "上限", "最大值"),
    ("decimal_places", "小数位"),
)

# 类型中文别名 → 规范值
_TYPE_ALIASES: dict[str, str] = {
    "遥信": "YX", "遥测": "YC", "遥控": "YK", "遥脉": "YM", "电度": "YM", "步位置": "STEP",
}
_SUBTYPE_ALIASES: dict[str, str] = {
    "单点": "single", "双点": "double",
    "归一化": "normalized", "标度": "scaled", "标度化": "scaled", "短浮点": "short_float",
}
_TRUTHY = ("true", "1", "yes", "是", "启用", "y", "on")
_FALSY = ("false", "0", "no", "否", "停用", "n", "off")


def _norm(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _norm_key(v: Any) -> str:
    return _norm(v).lower()


def _as_int(v: Any, field: str) -> int:
    if isinstance(v, bool):
        raise ValueError(f"{field} 须为整数，得到布尔值")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != int(v):
            raise ValueError(f"{field} 须为整数，得到 {v}")
        return int(v)
    s = _norm(v)
    if not s:
        raise ValueError(f"{field} 缺失")
    return int(s)  # ValueError 自然上抛（含原文）


def _as_float(v: Any, field: str) -> float:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = _norm(v)
    if not s:
        raise ValueError(f"{field} 缺失")
    return float(s)  # ValueError 自然上抛


def _as_bool(v: Any, field: str, default: bool) -> bool:
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    if isinstance(v, bool):
        return v
    s = _norm_key(v)
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    raise ValueError(f"{field} 须为 true/false，得到 {v!r}")


def _build_header_map(header_row: tuple[Any, ...]) -> dict[int, str]:
    """表头行 → {列下标: 规范键}；未知列忽略，type/ioa 缺失抛 ValueError."""
    lower_to_key: dict[str, str] = {}
    for names in _COLUMNS:
        for n in names:
            lower_to_key[n.lower()] = names[0]
    mapping: dict[int, str] = {}
    for idx, cell in enumerate(header_row):
        key = lower_to_key.get(_norm_key(cell))
        if key and key not in mapping.values():
            mapping[idx] = key
    if "type" not in mapping.values() or "ioa" not in mapping.values():
        raise ValueError(
            "xlsx 缺少 type/ioa 列（表头支持：type/类型, ioa/信息对象地址, name/名称, "
            "group/组, enabled/启用, subtype/子类型, value/初始值, sbo, unit/单位, "
            "min_value/下限, max_value/上限, decimal_places/小数位）")
    return mapping


def _row_def(key: str, row: dict[str, Any], subtype: str) -> Any:
    """按类型构造 PointDef（与 PointService.import_csv 语义一致）."""
    ioa = _as_int(row.get("ioa"), "ioa")
    name = _norm(row.get("name")) or f"{key}_{ioa}"
    g = row.get("group")
    group = _as_int(g, "group") if (isinstance(g, (int, float)) or _norm(g)) else 1
    enabled = _as_bool(row.get("enabled"), "enabled", True)
    if key == "YX":
        return YxPointDef(ioa=ioa, name=name, group=group, enabled=enabled,
                          point_type=YxType(subtype) if subtype else YxType.SINGLE)
    if key == "YC":
        min_v = _as_float(row["min_value"], "min_value") if _norm(row.get("min_value")) else -99999.0
        max_v = _as_float(row["max_value"], "max_value") if _norm(row.get("max_value")) else 99999.0
        return YcPointDef(
            ioa=ioa, name=name, group=group, enabled=enabled,
            data_type=YcType(subtype) if subtype in ("normalized", "scaled", "short_float")
            else YcType.SHORT_FLOAT,
            initial_value=_as_float(row["value"], "value") if _norm(row.get("value")) else 0.0,
            min_value=min_v, max_value=max_v,
            unit=_norm(row.get("unit")),
            decimal_places=_as_int(row.get("decimal_places") or 2, "decimal_places"),
        )
    if key == "YK":
        return YkPointDef(ioa=ioa, name=name, group=group, enabled=enabled,
                          command_type=subtype if subtype in ("single", "double") else "single",
                          select_before_execute=_as_bool(row.get("sbo"), "sbo", True))
    if key == "YM":
        return YmPointDef(ioa=ioa, name=name, group=group, enabled=enabled,
                          initial_value=_as_int(row.get("value") or 0, "value"))
    # STEP
    return StepPointDef(ioa=ioa, name=name, group=group, enabled=enabled,
                        initial_value=_as_int(row.get("value") or 0, "value"))


def parse_xlsx_table(data: bytes, base: PointTable) -> tuple[PointTable, list[str], dict[str, int]]:
    """解析 xlsx 字节 → (新点表, 行级错误列表, 各类型计数). 致命问题抛 ValueError."""
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f"无法解析 xlsx: {e}") from e
    ws = wb.active
    if ws is None:
        raise ValueError("xlsx 无工作表")
    rows_iter = ws.iter_rows(values_only=True)
    header = next(rows_iter, None)
    if header is None:
        raise ValueError("xlsx 空表（无表头行）")
    mapping = _build_header_map(header)

    new_table = PointTable()
    new_table.common_addr = base.common_addr
    new_table.station_name = base.station_name
    errors: list[str] = []
    stats = {"YX": 0, "YC": 0, "YK": 0, "YM": 0, "STEP": 0}
    for row_no, raw in enumerate(rows_iter, start=2):
        if raw is None or all(c is None or _norm(c) == "" for c in raw):
            continue  # 空行跳过
        row = {mapping[i]: raw[i] for i in mapping if i < len(raw)}
        try:
            tname = _norm_key(row.get("type"))
            key = tname.upper() if tname.upper() in ("YX", "YC", "YK", "YM", "STEP") \
                else _TYPE_ALIASES.get(tname, "")
            if not key:
                raise ValueError(f"type 须为 YX/YC/YK/YM/STEP，得到 {row.get('type')!r}")
            st = _norm_key(row.get("subtype"))
            subtype = _SUBTYPE_ALIASES.get(st, st)
            new_table_add = {
                "YX": new_table.add_yx, "YC": new_table.add_yc, "YK": new_table.add_yk,
                "YM": new_table.add_ym, "STEP": new_table.add_step,
            }[key]
            new_table_add(_row_def(key, row, subtype))
            stats[key] += 1
        except (ValueError, TypeError) as e:
            errors.append(f"第 {row_no} 行: {e}")
    if sum(stats.values()) == 0:
        raise ValueError("xlsx 未解析出有效点（type 须为 YX/YC/YK/YM/STEP）")
    return new_table, errors, stats


def export_xlsx_bytes(table: PointTable) -> bytes:
    """导出点表为 xlsx 字节（列头与解析端回环兼容）.

    列序（对应 _COLUMNS 规范名）：type, ioa, name, group, enabled, subtype,
    value(初始值), sbo, unit, min_value, max_value, decimal_places。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "points"
    ws.append([names[0] for names in _COLUMNS])
    for p in table.get_all_yx():
        ws.append(["YX", p.ioa, p.name, p.group, p.enabled, p.point_type.value])
    for p in table.get_all_yc():
        ws.append(["YC", p.ioa, p.name, p.group, p.enabled, p.data_type.value,
                   p.initial_value, "", p.unit, p.min_value, p.max_value, p.decimal_places])
    for p in table.get_all_yk():
        ws.append(["YK", p.ioa, p.name, p.group, p.enabled, str(p.command_type),
                   "", int(bool(p.select_before_execute))])
    for p in table.get_all_ym():
        ws.append(["YM", p.ioa, p.name, p.group, p.enabled, "", p.initial_value])
    for p in table.get_all_step():
        ws.append(["STEP", p.ioa, p.name, p.group, p.enabled, "", p.initial_value])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

_EPS = 1e-6
_DIFF_CAP = 200


def _type_of(p: Any) -> str:
    if isinstance(p, YxPointDef):
        return "YX"
    if isinstance(p, YcPointDef):
        return "YC"
    if isinstance(p, YkPointDef):
        return "YK"
    if isinstance(p, YmPointDef):
        return "YM"
    return "STEP"


def design_diff(design: PointTable, live: PointTable, engine: Any = None) -> dict:
    """设计基准 vs 实测比对：缺（设计有/实测无）、多（实测有/设计无）、值域/类型不符.

    值域取 ``engine.data_store`` 的 YC 观测极值（min_val/max_val，仅已观测点参与），
    与设计声明的 ``min_value``/``max_value`` 比较——不要混用设计声明值当「实测」。
    """
    design_pts: dict[int, list[Any]] = {}
    for p in design.get_all_yx() + design.get_all_yc() + design.get_all_yk() \
            + design.get_all_ym() + design.get_all_step():
        design_pts.setdefault(p.ioa, []).append(p)
    live_pts: dict[int, list[Any]] = {}
    for p in live.get_all_yx() + live.get_all_yc() + live.get_all_yk() \
            + live.get_all_ym() + live.get_all_step():
        live_pts.setdefault(p.ioa, []).append(p)

    store = getattr(engine, "data_store", None) if engine is not None else None

    missing: list[dict] = []
    extra: list[dict] = []
    mismatch: list[dict] = []
    missing_total = extra_total = mismatch_total = 0
    for ioa, dpts in design_pts.items():
        lpts = live_pts.get(ioa)
        if not lpts:
            for p in dpts:
                missing_total += 1
                if len(missing) < _DIFF_CAP:
                    missing.append({"ioa": ioa, "type": _type_of(p), "name": p.name})
            continue
        d_types = {_type_of(p) for p in dpts}
        l_types = {_type_of(p) for p in lpts}
        if d_types != l_types:
            mismatch_total += 1
            if len(mismatch) < _DIFF_CAP:
                mismatch.append({
                    "ioa": ioa,
                    "design": {"type": "/".join(sorted(d_types))},
                    "actual": {"type": "/".join(sorted(l_types))},
                    "reason": f"类型不符（设计 {'/'.join(sorted(d_types))} → 实测 {'/'.join(sorted(l_types))}）",
                })
            continue
        # 同类型：YC 比对观测值域 vs 设计声明域
        for lp in lpts:
            if _type_of(lp) != "YC":
                continue
            dp = next(p for p in dpts if _type_of(p) == "YC")
            obs_min = obs_max = None
            if store is not None:
                d = store.get_yc(ioa)
                if d is not None and math.isfinite(d.min_val) and math.isfinite(d.max_val):
                    obs_min, obs_max = float(d.min_val), float(d.max_val)
            if obs_min is None:
                continue  # 尚未观测到数据，无从比对
            if obs_min < dp.min_value - _EPS or obs_max > dp.max_value + _EPS:
                mismatch_total += 1
                if len(mismatch) < _DIFF_CAP:
                    mismatch.append({
                        "ioa": ioa,
                        "design": {"type": "YC", "min_value": dp.min_value,
                                   "max_value": dp.max_value},
                        "actual": {"type": "YC", "min_obs": obs_min, "max_obs": obs_max},
                        "reason": (f"实测值域越界（设计 [{dp.min_value:g}, {dp.max_value:g}]，"
                                   f"实测 [{obs_min:g}, {obs_max:g}]）"),
                    })
    for ioa, lpts in live_pts.items():
        if ioa in design_pts:
            continue
        for p in lpts:
            extra_total += 1
            if len(extra) < _DIFF_CAP:
                extra.append({"ioa": ioa, "type": _type_of(p), "name": p.name})

    return {
        "ok": True,
        "summary": {"missing": missing_total, "extra": extra_total,
                    "mismatch": mismatch_total},
        "missing": missing,
        "extra": extra,
        "mismatch": mismatch,
        "truncated": missing_total > len(missing) or extra_total > len(extra)
        or mismatch_total > len(mismatch),
    }
