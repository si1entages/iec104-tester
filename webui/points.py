"""点表服务：快照、批量、导入导出，并显式同步到引擎."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core.data.point_table import (
    PointTable,
    StepPointDef,
    YcPointDef,
    YkPointDef,
    YmPointDef,
    YxPointDef,
)

#: 类型 → PointTable 的 add_* 方法（PointTable 无通用 add()）
_ADDERS = {
    "YX": lambda t, p: t.add_yx(p),
    "YC": lambda t, p: t.add_yc(p),
    "YK": lambda t, p: t.add_yk(p),
    "YM": lambda t, p: t.add_ym(p),
    "STEP": lambda t, p: t.add_step(p),
}


def _interlock_summary(point: Any) -> list[dict]:
    """点表快照里的闭锁摘要（WP4b）：前端据此显示「联锁」标记与条件提示.

    只读投影，不含运行时实测值——实测值随 /api/points 的 YX 行给出。
    """
    conds = getattr(point, "interlock", ()) or ()
    return [
        {"ioa": c.ioa, "value": bool(c.value), "label": getattr(c, "label", "")}
        for c in conds
    ]


class PointService:
    """PointTable 的应用层封装；变更后调用 sync_to_engine.

    ``design`` 为设计基准快照（T95）：导入 xlsx 时自动建立，也可手动
    set/clear；``design_diff`` 用它与实测（含自动学习的点 + 观测值域）比对。
    """

    def __init__(self, table: PointTable | None = None):
        self.table = table or PointTable()
        self.design: PointTable | None = None
        self._count = 0
        self.refresh_count()

    @property
    def count(self) -> int:
        return self._count

    def ensure_demo(self, yx: int, yc: int, yk: int, ym: int,
                    common_addr: int = 1, name: str = "WebDemo") -> None:
        if self.table.yx_count == 0:
            self.table.generate_demo_points(yx_count=yx, yc_count=yc, yk_count=yk, ym_count=ym)
            self.table.common_addr = common_addr
            self.table.station_name = name
        self.refresh_count()

    def refresh_count(self) -> int:
        self._count = (
            len(self.table.get_all_yx())
            + len(self.table.get_all_yc())
            + len(self.table.get_all_yk())
            + len(self.table.get_all_ym())
            + len(self.table.get_all_step())
        )
        return self._count

    def sync_to_engine(self, engine: Any) -> None:
        """显式同步点表引用到引擎；不重置实时库（避免冲掉运行值）.

        仅在导入新点表后需要重建实时库时调用 rebuild_store。
        """
        eng_pt = getattr(engine, "point_table", None)
        if eng_pt is not None and eng_pt is not self.table:
            try:
                engine._point_table = self.table  # noqa: SLF001 — 引擎未提供 setter
            except Exception:
                pass

    def rebuild_store(self, engine: Any) -> None:
        """导入新定义后重建实时库（会丢弃当前值，仅用于 import）."""
        store = getattr(engine, "data_store", None)
        if store is not None and hasattr(store, "init_from_point_table"):
            store.init_from_point_table(self.table)
        self.sync_to_engine(engine)

    def snapshot(self, engine: Any = None) -> list[dict]:
        out: list[dict] = []
        for p in self.table.get_all_yx():
            out.append({"ioa": p.ioa, "type": "YX", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": "OFF",
                        "subtype": p.point_type.value, "ts": 0})
        for p in self.table.get_all_yc():
            out.append({"ioa": p.ioa, "type": "YC", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0.0,
                        "subtype": p.data_type.value,
                        # 设计规范 §5.3：界面按声明的小数位与单位显示遥测值
                        "unit": p.unit, "decimal_places": p.decimal_places, "ts": 0,
                        "min_value": p.min_value, "max_value": p.max_value,
                        "interlock": _interlock_summary(p)})
        for p in self.table.get_all_yk():
            out.append({"ioa": p.ioa, "type": "YK", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": "—",
                        "subtype": str(p.command_type),
                        "sbo": bool(p.select_before_execute), "ts": 0,
                        "interlock": _interlock_summary(p)})
        for p in self.table.get_all_ym():
            out.append({"ioa": p.ioa, "type": "YM", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0, "ts": 0})
        for p in self.table.get_all_step():
            out.append({"ioa": p.ioa, "type": "STEP", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0, "ts": 0,
                        "interlock": _interlock_summary(p)})
        if engine is not None:
            store = getattr(engine, "data_store", None)
            if store is not None:
                for row in out:
                    if row["type"] == "YX":
                        d = store.get_yx(row["ioa"])
                        if d:
                            row["value"] = "ON" if d.value else "OFF"
                            row["quality"] = str(d.quality)
                            row["ts"] = int(d.last_update_time * 1000)
                    elif row["type"] == "YC":
                        d = store.get_yc(row["ioa"])
                        if d:
                            row["value"] = float(d.value)
                            row["quality"] = str(d.quality)
                            row["ts"] = int(d.last_update_time * 1000)
                    elif row["type"] == "YM":
                        d = store.get_ym(row["ioa"])
                        if d:
                            row["value"] = int(d.value)
                            row["quality"] = str(d.quality)
                            row["ts"] = int(d.last_update_time * 1000)
                    elif row["type"] == "STEP":
                        d = store.get_step(row["ioa"])
                        if d:
                            row["value"] = int(d.value)
                            row["quality"] = str(d.quality)
                            row["ts"] = int(d.last_update_time * 1000)
        return out

    def batch(self, ptype: str, ioas: list[int], action: str,
              group: int | None = None, engine: Any = None) -> dict:
        ptype = (ptype or "").upper()
        if ptype not in ("YX", "YC", "YK", "YM", "STEP"):
            return {"ok": False, "error": "bad type"}
        action = (action or "").lower()
        if action not in ("enable", "disable", "group"):
            return {"ok": False, "error": "bad action"}
        if action == "group" and group is None:
            return {"ok": False, "error": "group required"}
        want = {int(x) for x in (ioas or [])}
        if not want:
            return {"ok": False, "error": "empty ioas"}
        getters = {
            "YX": self.table.get_all_yx,
            "YC": self.table.get_all_yc,
            "YK": self.table.get_all_yk,
            "YM": self.table.get_all_ym,
            "STEP": self.table.get_all_step,
        }
        changed = 0
        for p in getters[ptype]():
            if p.ioa not in want:
                continue
            if action == "enable":
                p.enabled = True
            elif action == "disable":
                p.enabled = False
            else:
                p.group = int(group)
            changed += 1
        if engine is not None:
            self.sync_to_engine(engine)
        return {"ok": True, "changed": changed}

    # ── 在线编辑（WP10a）──────────────────────────────────────────

    def upsert(self, ptype: str, fields: dict, engine: Any = None) -> dict:
        """新增或更新一个点定义（按 IOA 匹配）；返回 ``{ok, created, point}``.

        **不重置设计基准**：``design`` 是「导入时的设计快照」，在线改点属于
        现场调整，若顺手重置基准就再也看不出"现场改了什么"。要更新基准请显式
        调 ``set_design("set")``（界面上的「重设基准」按钮）。
        """
        ptype = (ptype or "").upper()
        if ptype not in ("YX", "YC", "YK", "YM", "STEP"):
            return {"ok": False, "error": "type 须为 YX|YC|YK|YM|STEP"}
        ioa = fields.get("ioa")
        if not isinstance(ioa, int) or isinstance(ioa, bool) or ioa < 0:
            return {"ok": False, "error": "ioa 须为非负整数"}
        try:
            point, created = self._build_point(ptype, fields)
        except (ValueError, TypeError, KeyError) as e:
            return {"ok": False, "error": f"字段非法：{e}"}
        _ADDERS[ptype](self.table, point)
        self.refresh_count()
        self.sync_to_engine(engine)
        return {
            "ok": True, "created": created,
            "point": {"ioa": point.ioa, "type": ptype, "name": point.name,
                      "group": point.group, "enabled": point.enabled},
        }

    def _build_point(self, ptype: str, f: dict):
        """按类型构造点定义；已存在则复用对象就地改字段（保持引用稳定）."""
        from core.data.point_table import (
            StepPointDef,
            YcPointDef,
            YcType,
            YkPointDef,
            YmPointDef,
            YxPointDef,
            YxType,
        )

        ioa = int(f["ioa"])
        name = str(f.get("name", ""))
        group = int(f.get("group", 1))
        enabled = bool(f.get("enabled", True))

        if ptype == "YX":
            existing = self.table.get_yx(ioa)
            pt = existing or YxPointDef(ioa=ioa)
            pt.name, pt.group, pt.enabled = name, group, enabled
            if "subtype" in f:
                pt.point_type = YxType(str(f["subtype"]))
            if "inverted" in f:
                pt.inverted = bool(f["inverted"])
        elif ptype == "YC":
            existing = self.table.get_yc(ioa)
            pt = existing or YcPointDef(ioa=ioa)
            pt.name, pt.group, pt.enabled = name, group, enabled
            if "subtype" in f:
                pt.data_type = YcType(str(f["subtype"]))
            for key in ("min_value", "max_value", "dead_band", "scale", "offset"):
                if key in f:
                    setattr(pt, key, float(f[key]))
            for key in ("unit",):
                if key in f:
                    setattr(pt, key, str(f[key]))
            for key in ("decimal_places",):
                if key in f:
                    setattr(pt, key, int(f[key]))
        elif ptype == "YK":
            existing = self.table.get_yk(ioa)
            pt = existing or YkPointDef(ioa=ioa)
            pt.name, pt.group, pt.enabled = name, group, enabled
            if "command_type" in f:
                pt.command_type = str(f["command_type"])
            if "sbo" in f:
                pt.select_before_execute = bool(f["sbo"])
            if "timeout_ms" in f:
                pt.timeout_ms = int(f["timeout_ms"])
        elif ptype == "YM":
            existing = self.table.get_ym(ioa)
            pt = existing or YmPointDef(ioa=ioa)
            pt.name, pt.group, pt.enabled = name, group, enabled
        else:  # STEP
            existing = self.table.get_step(ioa)
            pt = existing or StepPointDef(ioa=ioa)
            pt.name, pt.group, pt.enabled = name, group, enabled
            for key in ("min_value", "max_value", "step_size"):
                if key in f:
                    setattr(pt, key, int(f[key]))
        return pt, existing is None

    def delete_point(self, ptype: str, ioa: int, engine: Any = None) -> dict:
        """删除一个点定义；**不重置设计基准**（同 ``upsert``）."""
        from core.data.point_table import PointType

        ptype = (ptype or "").upper()
        try:
            pt_enum = PointType(ptype.lower())
        except ValueError:
            return {"ok": False, "error": "type 须为 YX|YC|YK|YM|STEP"}
        removed = self.table.remove_point(pt_enum, int(ioa))
        if removed:
            self.refresh_count()
            self.sync_to_engine(engine)
        return {"ok": removed, "deleted": removed}

    def export_yaml(self) -> str:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "points.yaml"
            self.table.save_yaml(str(path))
            return path.read_text(encoding="utf-8")

    def import_yaml(self, text: str, engine: Any = None) -> dict:
        try:
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "points.yaml"
                path.write_text(text, encoding="utf-8")
                self.table.load_yaml(str(path))
            self.refresh_count()
            if engine is not None:
                self.rebuild_store(engine)
            return {"ok": True, "points": self._count}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def export_csv(self, engine: Any = None) -> str:
        """导出 CSV（列: type,ioa,name,group,enabled,value,quality,subtype,sbo）.

        ``subtype`` 为类型细分（遥信 single/double、遥测 short_float/normalized/scaled、
        遥控 single/double）；``sbo`` 仅遥控有效（是否需要选择-执行）。
        导入 :meth:`import_csv` 与本格式回环兼容，且兼容缺列的旧文件。
        """

        def esc(v: Any) -> str:
            s = "" if v is None else str(v)
            if any(c in s for c in (',', '"', '\n', '\r')):
                return '"' + s.replace('"', '""') + '"'
            return s

        subtype = {
            "YX": {p.ioa: p.point_type.value for p in self.table.get_all_yx()},
            "YC": {p.ioa: p.data_type.value for p in self.table.get_all_yc()},
            # 遥控命令类型是字符串（"single"/"double"），不是枚举
            "YK": {p.ioa: str(p.command_type) for p in self.table.get_all_yk()},
            "YM": {},
        }
        sbo = {p.ioa: int(bool(p.select_before_execute)) for p in self.table.get_all_yk()}

        lines = ["type,ioa,name,group,enabled,value,quality,subtype,sbo"]
        for p in self.snapshot(engine):
            val = p.get("value", "")
            if isinstance(val, float):
                val = f"{val:.6g}"
            ioa = p["ioa"]
            t = p["type"]
            lines.append(",".join(esc(x) for x in (
                t, ioa, p.get("name", ""), p.get("group", ""),
                int(bool(p.get("enabled", True))), val, p.get("quality", ""),
                subtype.get(t, {}).get(ioa, ""), sbo.get(ioa, "") if t == "YK" else "",
            )))
        return "\n".join(lines) + "\n"

    def import_csv(self, text: str, engine: Any = None) -> dict:
        """从 CSV 文本导入点表（整表替换）.

        列: ``type,ioa,name,group,enabled[,value[,quality[,subtype[,sbo]]]]``
        与 :meth:`export_csv` 回环兼容；缺失列取缺省值。
        """
        import csv
        import io

        try:
            rows = list(csv.DictReader(io.StringIO(text)))
        except Exception as e:
            return {"ok": False, "error": f"CSV 解析失败: {e}"}
        if not rows:
            return {"ok": False, "error": "CSV 无数据行"}
        if "type" not in rows[0] or "ioa" not in rows[0]:
            return {"ok": False, "error": "CSV 缺少 type/ioa 列"}

        new_table = PointTable()
        new_table.common_addr = self.table.common_addr
        new_table.station_name = self.table.station_name
        count = 0
        for row in rows:
            try:
                ptype = (row.get("type") or "").strip().upper()
                ioa = int(row.get("ioa") or 0)
                name = (row.get("name") or f"{ptype}_{ioa}").strip()
                group = int(row.get("group") or 1)
                enabled = (row.get("enabled") or "true").strip().lower() in ("true", "1", "yes")
                subtype = (row.get("subtype") or "").strip()
                if ptype == "YX":
                    from core.data.point_table import YxType

                    new_table.add_yx(YxPointDef(
                        ioa=ioa, name=name, group=group, enabled=enabled,
                        point_type=YxType(subtype) if subtype else YxType.SINGLE,
                    ))
                elif ptype == "YC":
                    from core.data.point_table import YcType

                    new_table.add_yc(YcPointDef(
                        ioa=ioa, name=name, group=group, enabled=enabled,
                        data_type=YcType(subtype) if subtype else YcType.SHORT_FLOAT,
                        initial_value=float(row.get("value") or 0),
                    ))
                elif ptype == "YK":
                    new_table.add_yk(YkPointDef(
                        ioa=ioa, name=name, group=group, enabled=enabled,
                        command_type=subtype if subtype in ("single", "double") else "single",
                        select_before_execute=(row.get("sbo") or "0").strip()
                        in ("1", "true", "True"),
                    ))
                elif ptype == "YM":
                    new_table.add_ym(YmPointDef(ioa=ioa, name=name, group=group,
                                                enabled=enabled,
                                                initial_value=int(row.get("value") or 0)))
                elif ptype == "STEP":
                    new_table.add_step(StepPointDef(
                        ioa=ioa, name=name, group=group, enabled=enabled,
                        initial_value=int(row.get("value") or 0),
                    ))
                else:
                    continue
                count += 1
            except Exception as e:
                return {"ok": False,
                        "error": f"第 {count + 2} 行解析失败（ioa={row.get('ioa')}）: {e}"}

        if count == 0:
            return {"ok": False, "error": "CSV 未解析出有效点（type 须为 YX/YC/YK/YM/STEP）"}
        self.table = new_table
        self.refresh_count()
        if engine is not None:
            self.rebuild_store(engine)
        return {"ok": True, "points": self._count}

    # ── T95：Excel(xlsx) 导入导出 + 设计基准 vs 实测比对 ────────────────

    def export_xlsx_bytes(self) -> bytes:
        from webui.points_xlsx import export_xlsx_bytes

        return export_xlsx_bytes(self.table)

    def preview_xlsx_bytes(self, data: bytes) -> dict:
        """解析 xlsx（无副作用）：返回各类型计数、行级错误与前 100 行摘要."""
        from webui.points_xlsx import parse_xlsx_table

        try:
            new_table, errors, stats = parse_xlsx_table(data, self.table)
        except ValueError as e:
            return {"ok": False, "error": str(e), "stats": {}, "errors": [],
                    "rows": [], "total": 0}
        rows = [{"ioa": p.ioa, "name": p.name}
                for p in (new_table.get_all_yx() + new_table.get_all_yc()
                          + new_table.get_all_yk() + new_table.get_all_ym()
                          + new_table.get_all_step())[:100]]
        total = sum(stats.values())
        return {"ok": True, "stats": {k: v for k, v in stats.items() if v},
                "errors": errors, "rows": rows, "total": total}

    def import_xlsx_bytes(self, data: bytes, engine: Any = None) -> dict:
        """导入 xlsx（整表替换）并把导入结果快照为设计基准."""
        from webui.points_xlsx import parse_xlsx_table

        try:
            new_table, errors, stats = parse_xlsx_table(data, self.table)
        except ValueError as e:
            return {"ok": False, "error": str(e), "points": 0, "errors": [],
                    "stats": {}, "design": False}
        self.table = new_table
        self.design = new_table.clone()
        self.refresh_count()
        if engine is not None:
            self.rebuild_store(engine)
        return {"ok": True, "points": self._count, "errors": errors,
                "stats": {k: v for k, v in stats.items() if v}, "design": True}

    def set_design(self, action: str) -> dict:
        """设计基准管理：set=把当前点表快照为基准，clear=清除."""
        if action == "set":
            self.design = self.table.clone()
            return {"ok": True, "has_design": True, "points": self._count}
        if action == "clear":
            self.design = None
            return {"ok": True, "has_design": False, "points": self._count}
        return {"ok": False, "error": "action 须为 set/clear", "has_design": self.design is not None}

    def design_diff(self, engine: Any = None) -> dict:
        """设计基准 vs 实测差异清单（缺/多/值域）；未建立基准返回 has_design=False."""
        from webui.points_xlsx import design_diff

        if self.design is None:
            return {"ok": True, "has_design": False,
                    "summary": {"missing": 0, "extra": 0, "mismatch": 0},
                    "missing": [], "extra": [], "mismatch": [], "truncated": False}
        out = design_diff(self.design, self.table, engine)
        out["has_design"] = True
        return out
