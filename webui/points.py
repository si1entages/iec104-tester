"""点表服务：快照、批量、导入导出，并显式同步到引擎."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core.data.point_table import (
    PointTable,
    YcPointDef,
    YkPointDef,
    YmPointDef,
    YxPointDef,
)


class PointService:
    """PointTable 的应用层封装；变更后调用 sync_to_engine."""

    def __init__(self, table: PointTable | None = None):
        self.table = table or PointTable()
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
                        "enabled": p.enabled, "value": "OFF"})
        for p in self.table.get_all_yc():
            out.append({"ioa": p.ioa, "type": "YC", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0.0})
        for p in self.table.get_all_yk():
            out.append({"ioa": p.ioa, "type": "YK", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": "—"})
        for p in self.table.get_all_ym():
            out.append({"ioa": p.ioa, "type": "YM", "name": p.name, "group": p.group,
                        "enabled": p.enabled, "value": 0})
        if engine is not None:
            store = getattr(engine, "data_store", None)
            if store is not None:
                for row in out:
                    if row["type"] == "YX":
                        d = store.get_yx(row["ioa"])
                        if d:
                            row["value"] = "ON" if d.value else "OFF"
                            row["quality"] = str(d.quality)
                    elif row["type"] == "YC":
                        d = store.get_yc(row["ioa"])
                        if d:
                            row["value"] = float(d.value)
                            row["quality"] = str(d.quality)
                    elif row["type"] == "YM":
                        d = store.get_ym(row["ioa"])
                        if d:
                            row["value"] = int(d.value)
                            row["quality"] = str(d.quality)
        return out

    def batch(self, ptype: str, ioas: list[int], action: str,
              group: int | None = None, engine: Any = None) -> dict:
        ptype = (ptype or "").upper()
        if ptype not in ("YX", "YC", "YK", "YM"):
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
                else:
                    continue
                count += 1
            except Exception as e:
                return {"ok": False,
                        "error": f"第 {count + 2} 行解析失败（ioa={row.get('ioa')}）: {e}"}

        if count == 0:
            return {"ok": False, "error": "CSV 未解析出有效点（type 须为 YX/YC/YK/YM）"}
        self.table = new_table
        self.refresh_count()
        if engine is not None:
            self.rebuild_store(engine)
        return {"ok": True, "points": self._count}
