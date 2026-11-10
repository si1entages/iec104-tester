"""T95 Excel(xlsx) 点表导入 + 设计基准 vs 实测比对.

解析/回环/设计比对纯函数（不起网络）+ 端点接线（aiohttp 测试服务器）。
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from core.data.point_table import PointTable, YxPointDef
from webui.bridge import EngineBridge
from webui.points_xlsx import design_diff, export_xlsx_bytes, parse_xlsx_table

# ── 构造工具 ────────────────────────────────────────────────────────────


def _build_xlsx(rows: list[list[object]], header: list[str] | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header or ["类型", "ioa", "名称", "组", "启用", "子类型", "初始值",
                         "单位", "下限", "上限", "小数位"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEADER_EN = ["type", "ioa", "name", "group", "enabled", "subtype", "value",
             "sbo", "unit", "min_value", "max_value", "decimal_places"]


def _sample_rows() -> list[list[object]]:
    return [
        ["遥测", 1001, "母线电压", 1, "是", "短浮点", 0, "V", 0, 10, 2],
        ["YX", 2001, "开关位置", 1, "true", "double"],
        ["遥测", "bad", "坏行", 1, "", "", 0, "", 0, 10, 2],  # ioa 非整数 → 行级错误
        ["遥控", 3001, "遥控开关", 1, "", "single", "", 1],
        ["遥脉", 4001, "电度", 1],
        ["遥信", 5001, "缺subtype"],
    ]


# ── 解析（行级错误收集 / 中英列头 / 中文类型别名） ────────────────────────


def test_parse_xlsx_chinese_headers_and_type_aliases():
    tbl, errors, stats = parse_xlsx_table(_build_xlsx(_sample_rows()), PointTable())
    assert stats == {"YX": 2, "YC": 1, "YK": 1, "YM": 1, "STEP": 0}
    assert len(errors) == 1 and "第 4 行" in errors[0]  # ioa=bad 的坏行
    yc = tbl.get_all_yc()[0]
    assert yc.ioa == 1001 and yc.unit == "V" and yc.min_value == 0 and yc.max_value == 10
    assert yc.decimal_places == 2 and yc.data_type.value == "short_float"
    assert tbl.get_all_yx()[0].point_type.value == "double"
    assert tbl.get_all_yx()[1].point_type.value == "single"  # 缺 subtype 取默认
    assert tbl.get_all_yk()[0].select_before_execute is True
    assert tbl.get_all_ym()[0].initial_value == 0


def test_parse_xlsx_english_headers_and_bool_cells():
    rows = [
        ["YX", 1, "a", 1, True, "single"],
        ["YC", 2, "b", 1, False, "scaled", 3.5, "", "", -5, 5, 1],
    ]
    tbl, errors, stats = parse_xlsx_table(_build_xlsx(rows, HEADER_EN), PointTable())
    assert stats["YX"] == 1 and stats["YC"] == 1 and errors == []
    assert tbl.get_all_yx()[0].enabled is True
    assert tbl.get_all_yc()[0].enabled is False
    assert tbl.get_all_yc()[0].initial_value == 3.5
    assert tbl.get_all_yc()[0].min_value == -5 and tbl.get_all_yc()[0].max_value == 5


def test_parse_xlsx_fatal_errors():
    with pytest.raises(ValueError, match="无法解析 xlsx"):
        parse_xlsx_table(b"not an xlsx", PointTable())
    with pytest.raises(ValueError, match="缺少 type/ioa"):
        parse_xlsx_table(_build_xlsx([["YX", 1]], ["foo", "bar"]), PointTable())
    with pytest.raises(ValueError, match="未解析出有效点"):
        parse_xlsx_table(_build_xlsx([["XX", 1]], ["type", "ioa"]), PointTable())


def test_export_import_roundtrip():
    tbl = PointTable()
    tbl.generate_demo_points(yx_count=6, yc_count=4, yk_count=2, ym_count=2)
    tbl2, errors, stats = parse_xlsx_table(export_xlsx_bytes(tbl), PointTable())
    assert errors == []
    assert stats["YX"] == 6 and stats["YC"] == 4 and stats["YK"] == 2 and stats["YM"] == 2
    assert [p.ioa for p in tbl.get_all_yx()] == [p.ioa for p in tbl2.get_all_yx()]
    yc0, yc1 = tbl.get_all_yc()[0], tbl2.get_all_yc()[0]
    assert (yc0.min_value, yc0.max_value, yc0.unit) == (yc1.min_value, yc1.max_value, yc1.unit)


# ── 设计基准 vs 实测比对（缺 / 多 / 值域 / 类型不符 / 未观测不误报） ──────


class _FakeStore:
    """观测值域桩：IOA 1001 观测到 [1.0, 12.0]（越出设计 [0, 10]）."""

    def get_yc(self, ioa: int):
        if ioa != 1001:
            return None

        class D:
            min_val = 1.0
            max_val = 12.0

        return D()


class _FakeEngine:
    data_store = _FakeStore()


def _design_live():
    design = PointTable()
    design.generate_demo_points(yx_count=2, yc_count=2, yk_count=0, ym_count=0)
    live = design.clone()
    return design, live


def test_design_diff_self_is_empty():
    design, live = _design_live()
    r = design_diff(design, live, _FakeEngine())
    assert r["summary"] == {"missing": 0, "extra": 0, "mismatch": 0}
    assert r["truncated"] is False


def test_design_diff_missing_extra_range_mismatch():
    design, live = _design_live()
    # 设计声明值域 [0, 10]（demo YC 默认 ±99999 不构成越界场景）
    design.get_all_yc()[0].min_value = 0
    design.get_all_yc()[0].max_value = 10
    live.get_all_yc()[0].min_value = 0
    live.get_all_yc()[0].max_value = 10
    design.add_yx(YxPointDef(ioa=9001, name="设计有/未上线"))
    live.add_yx(YxPointDef(ioa=9501, name="自动学习"))
    engine = _FakeEngine()
    r = design_diff(design, live, engine)
    assert r["summary"] == {"missing": 1, "extra": 1, "mismatch": 1}
    assert r["missing"][0]["ioa"] == 9001
    assert r["extra"][0]["ioa"] == 9501
    m = r["mismatch"][0]
    assert m["ioa"] == live.get_all_yc()[0].ioa and "值域" in m["reason"]
    assert m["actual"]["max_obs"] == 12.0 and m["design"]["max_value"] == 10


def test_design_diff_type_mismatch_and_no_observation_no_false():
    design, live = _design_live()
    # 把 IOA 与设计 YC 相同的点从实测侧改成遥信 → 类型不符
    yc_ioa = live.get_all_yc()[0].ioa
    live._yc.clear()  # noqa: SLF001 — 测试构造捷径
    live.add_yx(YxPointDef(ioa=yc_ioa, name="变成遥信"))
    r = design_diff(design, live, None)  # engine=None：无观测数据
    assert r["summary"]["mismatch"] == 1 and "类型不符" in r["mismatch"][0]["reason"]
    # 完全一致 + 无观测 → 零差异（不误报值域）
    design2, live2 = _design_live()
    assert design_diff(design2, live2, None)["summary"]["mismatch"] == 0


def test_design_diff_truncation_cap():
    design, live = _design_live()
    for i in range(250):
        live.add_yx(YxPointDef(ioa=20000 + i, name=f"多{i}"))
    r = design_diff(design, live, None)
    assert r["summary"]["extra"] == 250
    assert len(r["extra"]) == 200 and r["truncated"] is True


# ── 端点接线 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xlsx_endpoints_and_design_flow():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    from aiohttp.test_utils import TestClient, TestServer

    from webui.server import create_app

    async with TestClient(TestServer(create_app(bridge))) as client:
        data = export_xlsx_bytes(bridge.points.table)
        # preview：无副作用
        r = await client.post("/api/points/xlsx/preview", data=data)
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is True and body["total"] > 0
        before = (await client.get("/api/points")).status
        assert before == 200
        # design-diff：未建基准
        r = await client.get("/api/points/design-diff")
        body = await r.json()
        assert body["ok"] is True and body["has_design"] is False
        # set 基准 → 改表（模拟自动学习）→ diff 出「多」
        r = await client.post("/api/points/design", json={"action": "set"})
        assert (await r.json())["has_design"] is True
        bridge.points.table.add_yx(YxPointDef(ioa=16385, name="真机学习点"))
        r = await client.get("/api/points/design-diff")
        body = await r.json()
        assert body["has_design"] is True and body["summary"]["extra"] == 1
        assert body["extra"][0]["ioa"] == 16385
        # import xlsx → 自动带设计基准
        r = await client.post("/api/points/xlsx/import", data=data)
        body = await r.json()
        assert body["ok"] is True and body["design"] is True and body["points"] > 0
        r = await client.get("/api/points/design-diff")
        body = await r.json()
        assert body["summary"] == {"missing": 0, "extra": 0, "mismatch": 0}
        # clear
        r = await client.post("/api/points/design", json={"action": "clear"})
        assert (await r.json())["has_design"] is False
        # 导出端点 + 非法 body
        r = await client.get("/api/points/xlsx")
        assert r.status == 200 and len(await r.read()) > 0
        r = await client.post("/api/points/xlsx/import", data=b"")
        assert r.status == 400
        r = await client.post("/api/points/xlsx/import", data=b"junk")
        body = await r.json()
        assert body["ok"] is False and "error" in body
        r = await client.post("/api/points/design", json={"action": "bad"})
        body = await r.json()
        assert body["ok"] is False
