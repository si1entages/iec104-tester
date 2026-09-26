"""点表导入测试（CSV 回环 + Web 端点）."""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from core.data.point_table import (
    PointTable,
    YcPointDef,
    YxPointDef,
    YxType,
)
from webui.bridge import EngineBridge
from webui.points import PointService
from webui.server import create_app


def _sample_table() -> PointTable:
    pt = PointTable()
    pt.common_addr = 7
    pt.station_name = "IMP"
    pt.add_yx(YxPointDef(ioa=1, name="YX1", group=1, point_type=YxType.SINGLE))
    pt.add_yx(YxPointDef(ioa=2002, name="YX2002", group=2, point_type=YxType.DOUBLE))
    pt.add_yc(YcPointDef(ioa=4001, name="YC4001", group=1))
    return pt


def test_csv_round_trip():
    """导出 → 导入 → 导出，内容必须一致（回环兼容）."""
    svc = PointService(_sample_table())
    csv_text = svc.export_csv()

    svc2 = PointService(PointTable())
    r = svc2.import_csv(csv_text)
    assert r["ok"] is True, r
    assert r["points"] == svc.count

    assert svc2.export_csv().splitlines()[0] == csv_text.splitlines()[0]
    assert svc2.export_csv().splitlines()[1:] == csv_text.splitlines()[1:]


def test_csv_import_preserves_subtype_and_sbo():
    """CSV 中的 subtype/sbo 必须还原到点定义（双点遥信、SBO 遥控）."""
    csv_text = (
        "type,ioa,name,group,enabled,value,quality,subtype,sbo\n"
        "YX,1,YX1,1,true,,,single,\n"
        "YX,2002,YX2002,1,true,,,double,\n"
        "YK,3001,YK3001,1,true,,,single,1\n"
        "YC,4001,YC4001,1,true,,,short_float,\n"
        "YM,5001,YM5001,1,true,10,,,\n"
    )
    svc = PointService(PointTable())
    r = svc.import_csv(csv_text)
    assert r["ok"] is True and r["points"] == 5

    t = svc.table
    yx = {p.ioa: p for p in t.get_all_yx()}
    assert yx[1].point_type == YxType.SINGLE
    assert yx[2002].point_type == YxType.DOUBLE
    yk = {p.ioa: p for p in t.get_all_yk()}
    assert yk[3001].command_type == "single"
    assert yk[3001].select_before_execute is True
    ym = {p.ioa: p for p in t.get_all_ym()}
    assert ym[5001].initial_value == 10


def test_csv_import_errors():
    svc = PointService(PointTable())
    assert svc.import_csv("")["ok"] is False
    assert svc.import_csv("ioa,name\n1,a\n")["ok"] is False          # 缺 type 列
    bad = "type,ioa,name\nYX,abc,损坏\n"
    r = svc.import_csv(bad)
    assert r["ok"] is False and "解析失败" in r["error"]
    empty = "type,ioa,name\nXX,1,未知类型\n"
    r2 = svc.import_csv(empty)
    assert r2["ok"] is False and "有效点" in r2["error"]


@pytest_asyncio.fixture
async def slave_client():
    bridge = EngineBridge("slave")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
async def test_import_endpoint_auto_sniff(slave_client):
    """`/api/points/import` 不带 format 时按内容自动嗅探 CSV."""
    client, bridge = slave_client
    csv_text = (
        "type,ioa,name,group,enabled,value,quality,subtype,sbo\n"
        "YX,11,YX11,1,true,,,single,\n"
        "YX,12,YX12,1,true,,,double,\n"
    )
    r = await client.post("/api/points/import", data=csv_text)
    body = await r.json()
    assert body["ok"] is True, body
    assert body["points"] == 2
    yx = {p.ioa: p for p in bridge.points.table.get_all_yx()}
    assert yx[12].point_type == YxType.DOUBLE


@pytest.mark.asyncio
async def test_import_endpoint_json(slave_client):
    """JSON（键结构与 YAML 一致）也可导入."""
    client, bridge = slave_client
    payload = ('{"common_addr": 1, "station_name": "J", '
               '"yx": [{"ioa": 21, "name": "A", "group": 1}]}')
    r = await client.post("/api/points/import?format=json", data=payload)
    body = await r.json()
    assert body["ok"] is True, body
    yx = {p.ioa: p.name for p in bridge.points.table.get_all_yx()}
    assert yx.get(21) == "A"
