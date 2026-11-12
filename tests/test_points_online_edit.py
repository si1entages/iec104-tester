"""WP10a 点表在线编辑测试.

核心验收点：**在线增改删点不重置设计基准**——``design`` 是导入时的设计快照，
现场改点若顺手重置基准，就再也看不出"现场改了什么"（设计 vs 实测比对失效）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.data.point_table import PointTable
from webui.bridge import EngineBridge
from webui.points import PointService
from webui.server import create_app

# ── 服务层 ───────────────────────────────────────────────────────────


class TestUpsert:
    def _svc(self) -> PointService:
        return PointService(PointTable())

    def test_create_then_update(self):
        svc = self._svc()
        r = svc.upsert("YK", {"ioa": 2001, "name": "合闸", "sbo": True})
        assert r["ok"] is True and r["created"] is True
        assert svc.table.get_yk(2001).name == "合闸"
        assert svc.table.get_yk(2001).select_before_execute is True

        r2 = svc.upsert("YK", {"ioa": 2001, "name": "改名"})
        assert r2["ok"] is True and r2["created"] is False
        assert svc.table.get_yk(2001).name == "改名"

    @pytest.mark.parametrize("ptype,fields,getter", [
        ("YX", {"ioa": 1, "name": "yx", "subtype": "double"}, "get_yx"),
        ("YC", {"ioa": 2, "name": "yc", "unit": "kV", "min_value": 0.0,
                "max_value": 100.0, "decimal_places": 1}, "get_yc"),
        ("YK", {"ioa": 3, "name": "yk", "command_type": "double", "timeout_ms": 5000}, "get_yk"),
        ("YM", {"ioa": 4, "name": "ym"}, "get_ym"),
        ("STEP", {"ioa": 5, "name": "st", "min_value": -10, "max_value": 10}, "get_step"),
    ])
    def test_all_types(self, ptype, fields, getter):
        svc = self._svc()
        assert svc.upsert(ptype, fields)["ok"] is True
        point = getattr(svc.table, getter)(fields["ioa"])
        assert point is not None and point.name == fields["name"]

    def test_field_updates_apply(self):
        svc = self._svc()
        svc.upsert("YC", {"ioa": 7, "name": "u", "unit": "A"})
        svc.upsert("YC", {"ioa": 7, "unit": "kV", "min_value": -5.0,
                          "max_value": 5.0, "decimal_places": 3})
        p = svc.table.get_yc(7)
        assert p.unit == "kV" and p.min_value == -5.0 and p.decimal_places == 3

    @pytest.mark.parametrize("ptype,fields,frag", [
        ("XX", {"ioa": 1}, "type 须为"),
        ("YX", {"ioa": -1}, "ioa 须为非负整数"),
        ("YX", {"ioa": True}, "ioa 须为非负整数"),
        ("YX", {}, "ioa 须为非负整数"),
        ("YX", {"ioa": 1, "subtype": "nonsense"}, "字段非法"),
        ("YC", {"ioa": 1, "min_value": "abc"}, "字段非法"),
    ])
    def test_invalid_rejected(self, ptype, fields, frag):
        svc = self._svc()
        out = svc.upsert(ptype, fields)
        assert out["ok"] is False and frag in out["error"]

    def test_count_refreshes(self):
        svc = self._svc()
        before = svc.count
        svc.upsert("YX", {"ioa": 100})
        assert svc.count == before + 1


class TestDelete:
    def test_delete_existing_and_missing(self):
        svc = TestUpsert()._svc()
        svc.upsert("YK", {"ioa": 2001})
        assert svc.delete_point("YK", 2001)["ok"] is True
        assert svc.table.get_yk(2001) is None
        assert svc.delete_point("YK", 2001)["ok"] is False

    def test_bad_type(self):
        svc = TestUpsert()._svc()
        assert "type 须为" in svc.delete_point("ZZ", 1)["error"]


# ── 设计基准不被重置（验收核心）───────────────────────────────────────


class TestDesignBaselinePreserved:
    def test_upsert_does_not_reset_design(self):
        svc = TestUpsert()._svc()
        svc.upsert("YX", {"ioa": 1, "name": "设计点"})
        svc.set_design("set")
        design_before = svc.design.clone()
        assert svc.design is not None

        svc.upsert("YX", {"ioa": 2, "name": "现场新增"})
        svc.upsert("YX", {"ioa": 1, "name": "现场改名"})

        # 基准仍是最初快照（仍是「设计点」，且不含 2 号点）
        assert svc.design is not None
        assert svc.design.get_yx(1).name == "设计点"
        assert svc.design.get_yx(2) is None
        assert design_before.get_yx(1).name == "设计点"

        # design-diff 能看出「多」出 2 号点——这正是基准没被重置的证据
        diff = svc.design_diff(None)
        assert diff["ok"] is True
        extra = [p["ioa"] for p in diff.get("extra", [])]
        assert 2 in extra

    def test_delete_does_not_reset_design(self):
        svc = TestUpsert()._svc()
        svc.upsert("YX", {"ioa": 5, "name": "A"})
        svc.set_design("set")
        svc.delete_point("YX", 5)
        assert svc.design is not None and svc.design.get_yx(5) is not None
        diff = svc.design_diff(None)
        assert 5 in [p["ioa"] for p in diff.get("missing", [])]

    def test_no_design_stays_none(self):
        svc = TestUpsert()._svc()
        svc.upsert("YX", {"ioa": 1})
        assert svc.design is None


# ── API ──────────────────────────────────────────────────────────────


class TestApi:
    async def _client(self, tmp_path: Path):
        from core.data.audit import AuditStore
        from webui.audit import AuditService

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None)
        store = AuditStore(tmp_path / "a.db")
        store.open()
        b.audit = AuditService(store)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_upsert_and_delete_roundtrip(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/points/upsert",
                             json={"type": "YK", "point": {"ioa": 2001, "name": "合闸"}})
            body = await r.json()
            assert r.status == 200 and body["ok"] is True and body["created"] is True

            body = await (await c.get("/api/points")).json()
            yk = [p for p in body["points"] if p["type"] == "YK" and p["ioa"] == 2001]
            assert len(yk) == 1 and yk[0]["name"] == "合闸"

            r = await c.delete("/api/points/delete?type=YK&ioa=2001")
            assert (await r.json())["ok"] is True
            body = await (await c.get("/api/points")).json()
            assert not [p for p in body["points"] if p["ioa"] == 2001]
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_invalid_requests(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/points/upsert", json={"type": "XX", "point": {"ioa": 1}})
            assert r.status == 400
            r = await c.post("/api/points/upsert", json={"type": "YX"})
            assert r.status == 400 and "point" in (await r.json())["error"]
            r = await c.delete("/api/points/delete?type=YX&ioa=abc")
            assert r.status == 400
            r = await c.delete("/api/points/delete?type=YX&ioa=999999")
            assert r.status == 404
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_design_diff_survives_online_edits(self, tmp_path: Path):
        """端到端：设基准 → 在线改点 → design-diff 仍能报出差异."""
        b, client = await self._client(tmp_path)
        async with client as c:
            await c.post("/api/points/upsert",
                         json={"type": "YX", "point": {"ioa": 10, "name": "设计"}})
            r = await c.post("/api/points/design", json={"action": "set"})
            assert (await r.json())["ok"] is True

            await c.post("/api/points/upsert",
                         json={"type": "YX", "point": {"ioa": 11, "name": "现场新增"}})
            diff = await (await c.get("/api/points/design-diff")).json()
            assert diff["ok"] is True
            assert 11 in [p["ioa"] for p in diff.get("extra", [])]
        await b.shutdown()


def test_upsert_keeps_object_identity():
    """更新走「就地改字段」，已持有的点对象引用仍然有效（不换对象）."""
    svc = PointService(PointTable())
    svc.upsert("YK", {"ioa": 1, "name": "A"})
    first = svc.table.get_yk(1)
    svc.upsert("YK", {"ioa": 1, "name": "B"})
    assert svc.table.get_yk(1) is first
    assert first.name == "B"


class TestBuildPointFields:
    """覆盖 _build_point 每类型的每个可选字段（含就地更新路径）。"""

    def test_yx_all_fields(self):
        svc = PointService(PointTable())
        svc.upsert("YX", {"ioa": 1, "subtype": "double", "inverted": True,
                          "group": 4, "enabled": False})
        p = svc.table.get_yx(1)
        assert p.point_type.value == "double" and p.inverted is True
        assert p.group == 4 and p.enabled is False

    def test_yc_all_fields(self):
        svc = PointService(PointTable())
        svc.upsert("YC", {"ioa": 2, "subtype": "scaled", "unit": "A",
                          "min_value": -1, "max_value": 9, "dead_band": 0.5,
                          "scale": 2, "offset": 1, "decimal_places": 3})
        p = svc.table.get_yc(2)
        assert p.data_type.value == "scaled" and p.unit == "A"
        assert p.min_value == -1 and p.max_value == 9
        assert p.dead_band == 0.5 and p.scale == 2 and p.offset == 1
        assert p.decimal_places == 3

    def test_yk_all_fields(self):
        svc = PointService(PointTable())
        svc.upsert("YK", {"ioa": 3, "command_type": "double", "sbo": False,
                          "timeout_ms": 1234})
        p = svc.table.get_yk(3)
        assert p.command_type == "double" and p.select_before_execute is False
        assert p.timeout_ms == 1234

    def test_ym_and_step_fields(self):
        svc = PointService(PointTable())
        svc.upsert("YM", {"ioa": 4, "group": 9, "enabled": False})
        p = svc.table.get_ym(4)
        assert p.group == 9 and p.enabled is False

        svc.upsert("STEP", {"ioa": 5, "min_value": -20, "max_value": 20,
                            "step_size": 2})
        st = svc.table.get_step(5)
        assert st.min_value == -20 and st.max_value == 20 and st.step_size == 2

    def test_in_place_update_keeps_reference(self):
        svc = PointService(PointTable())
        svc.upsert("YC", {"ioa": 6, "name": "A"})
        p = svc.table.get_yc(6)
        svc.upsert("YC", {"ioa": 6, "name": "B", "unit": "V"})
        assert svc.table.get_yc(6) is p and p.name == "B" and p.unit == "V"

    def test_bad_enum_value_returns_error(self):
        svc = PointService(PointTable())
        out = svc.upsert("YX", {"ioa": 1, "subtype": "no-such-type"})
        assert out["ok"] is False and "字段非法" in out["error"]


class TestMoreApiBranches:
    async def _client(self, tmp_path: Path):
        from core.data.audit import AuditStore
        from webui.audit import AuditService

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None)
        store = AuditStore(tmp_path / "a.db")
        store.open()
        b.audit = AuditService(store)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_upsert_invalid_json_and_body(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.post("/api/points/upsert", data="not json",
                             headers={"Content-Type": "application/json"})
            assert r.status == 400
            r = await c.post("/api/points/upsert", json=["list"])
            assert r.status == 400
            r = await c.post("/api/points/upsert",
                             json={"type": "YK", "point": {"ioa": -1}})
            assert r.status == 400
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_delete_bad_type(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.delete("/api/points/delete?type=ZZ&ioa=1")
            assert r.status == 404
        await b.shutdown()
