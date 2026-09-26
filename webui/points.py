"""点表服务：快照、批量、导入导出，并显式同步到引擎."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core.data.point_table import PointTable


class PointService:
    """PointTable 的应用层封装；变更后调用 sync_to_engine."""

    def __init__(self, table: PointTable | None = None):
        self.table = table or PointTable()
        self._count = 0

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
        def esc(v: Any) -> str:
            s = "" if v is None else str(v)
            if any(c in s for c in (',', '"', '\n', '\r')):
                return '"' + s.replace('"', '""') + '"'
            return s
        lines = ["type,ioa,name,group,enabled,value,quality"]
        for p in self.snapshot(engine):
            val = p.get("value", "")
            if isinstance(val, float):
                val = f"{val:.6g}"
            lines.append(",".join(esc(x) for x in (
                p["type"], p["ioa"], p.get("name", ""), p.get("group", ""),
                int(bool(p.get("enabled", True))), val, p.get("quality", ""),
            )))
        return "\n".join(lines) + "\n"
