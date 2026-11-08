"""SCD（IEC 61850-6 SCL + 80-1 映射）→ 104 点表导入测试."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from aiohttp.test_utils import TestClient, TestServer

from core.data.point_table import PointTable
from core.data.scd_import import TI_MAP, import_scd, parse_scl
from core.protocol.types import TypeID
from webui.bridge import EngineBridge
from webui.server import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "sample_104.scd"


def _fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _import(**kwargs) -> object:
    return import_scd(_fixture_text(), **kwargs)


def test_ti_map_is_subset_of_typeid() -> None:
    """映射表键必须是本仓 TypeID 枚举的子集（防两表漂移）."""
    valid = {t.value for t in TypeID}
    unknown = set(TI_MAP) - valid
    assert not unknown, f"TI_MAP 含 TypeID 未定义的 ti: {unknown}"


def test_parse_signals_and_station() -> None:
    signals, lntype_dos, dotype_cdc, station = parse_scl(_fixture_text())
    assert station == "DemoStation"
    # 精确映射 10（含 B2 的 casdu=99）+ 推断候选 4（Ind3/MW/Kwh/Op）
    assert len(signals) == 14
    assert sum(1 for s in signals if s.address is not None) == 10
    assert lntype_dos["LT_MMXU"]["TotW"] == "DT_MV"
    assert dotype_cdc["DT_MV"] == "MV"


def test_precise_mapping_categories() -> None:
    r = _import()
    pts = r.points
    by_ioa = {}
    for kind in ("yx", "yc", "yk", "ym", "step"):
        for p in pts[kind]:
            by_ioa[p["ioa"]] = (kind, p)

    # yx：精确 1（单点）/2（双点）+ 推断 3（SPC）
    assert by_ioa[1][0] == "yx" and by_ioa[1][1]["type"] == "single"
    assert by_ioa[2][0] == "yx" and by_ioa[2][1]["type"] == "double"
    assert by_ioa[3][0] == "yx"
    # yk：DPC 的 ctlVal（SDI 嵌套路径）→ 双命令
    kind, p = by_ioa[102]
    assert kind == "yk" and p["type"] == "double" and p["sbo"] is True
    # yc：ti=13 短浮点 / ti=36 带时标短浮点
    assert by_ioa[401][1]["type"] == "short_float"
    assert by_ioa[402][1]["type"] == "short_float"
    # ym / step
    assert by_ioa[501][0] == "ym"
    assert by_ioa[601][0] == "step"
    # 推断 yc/ym 落在各自基数分区
    assert by_ioa[4097][0] == "yc"
    assert by_ioa[12289][0] == "ym"


def test_names_prefer_desc() -> None:
    r = _import()
    pts = r.points
    names = {p["ioa"]: p["name"] for p in pts["yx"]}
    assert names[1] == "断路器位置"
    # 无 desc 的 DOI 回落 LN desc
    assert names[3] == "公共信号"
    # DOI 无 desc、LN 有 desc → LN desc
    ym_names = {p["ioa"]: p["name"] for p in pts["ym"]}
    assert ym_names[12289] == "电度"
    # DOI 与 LN 都无 desc → 完整信号路径
    mini = (
        '<SCL xmlns="http://www.iec.ch/61850/2003/SCL">'
        '<Substation name="S"/><IED name="C1"><AccessPoint name="AP"><Server>'
        '<LDevice inst="LD"><LN0 lnClass="LLN0" inst="" lnType="T0"/>'
        '<LN lnClass="GGIO" inst="1" lnType="T0"><DOI name="Ind1"/></LN>'
        "</LDevice></Server></AccessPoint></IED>"
        "<DataTypeTemplates><LNodeType id=\"T0\" lnClass=\"GGIO\">"
        '<DO name="Ind1" type="D0"/></LNodeType>'
        '<DOType id="D0" cdc="SPC"><DA name="stVal" bType="BOOLEAN" fc="ST"/></DOType>'
        "</DataTypeTemplates></SCL>"
    )
    r2 = import_scd(mini)
    assert r2.points["yx"][0]["name"] == "C1/LD/GGIO1.Ind1"


def test_da_path_keeps_sdi_chain() -> None:
    r = _import()
    ctl = next(s for s in r.signals if s.address and s.address.ioa == 102)
    assert ctl.da_path == "Oper.ctlVal"
    phsb = next(s for s in r.signals if s.address and s.address.ioa == 402)
    assert phsb.da_path == "cVal.mag.f"


def test_duplicate_ioa_conflict_warned() -> None:
    r = _import()
    assert any("IOA 冲突" in w and "TotW2" in w for w in r.warnings)
    # 冲突者被丢弃，先到者保留
    assert 401 in {p["ioa"] for p in r.points["yc"]}


def test_unsupported_ti_skipped_with_warning() -> None:
    r = _import()
    assert any("ti=33" in w for w in r.warnings)
    all_ioa = [p["ioa"] for k in ("yx", "yc", "yk", "ym", "step") for p in r.points[k]]
    assert 701 not in all_ioa


def test_multi_casdu_uses_majority_and_warns() -> None:
    r = _import()
    assert r.common_addr == 1
    assert any("casdu=99" in w for w in r.warnings)
    assert r.stats["dropped_other_casdu"] == 1
    # 显式指定公共地址时反向剔除：casdu=1 的精确点全部消失，
    # 只剩 casdu=99 的精确点与 CDC 推断点（推断不受 casdu 影响）
    r99 = _import(common_addr=99)
    assert r99.common_addr == 99
    assert any("casdu=1" in w for w in r99.warnings)
    assert r99.stats["dropped_other_casdu"] == 9
    assert len(r99.points["yk"]) == 0  # yk 全部来自精确映射（casdu=1）
    assert len(r99.points["ym"]) == 1  # 仅推断的 Kwh


def test_inferred_control_cdc_skipped() -> None:
    r = _import()
    assert any("CDC=ENC" in w for w in r.warnings)
    assert r.stats["dropped_other_casdu"] == 1


def test_ioa_bases_override() -> None:
    r = _import(ioa_bases={"yx": 500, "yc": 900, "ym": 1500})
    yx_ioa = [p["ioa"] for p in r.points["yx"] if p["ioa"] not in (1, 2)]
    assert yx_ioa == [500]
    assert 900 in {p["ioa"] for p in r.points["yc"]}


def test_roundtrip_through_point_table() -> None:
    """转换结果必须能被 PointTable.load_yaml 原样吸收（导入链路回归）."""
    r = _import()
    text = yaml.safe_dump(r.points, allow_unicode=True, sort_keys=True)
    table = PointTable()
    table.load_yaml_text(text) if hasattr(table, "load_yaml_text") else None
    # PointTable 的加载入口是 load_yaml(path)——经由 PointService.import_yaml 同款路径
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "points.yaml"
        path.write_text(text, encoding="utf-8")
        table.load_yaml(str(path))
    assert table.common_addr == 1
    assert table.station_name == "DemoStation"
    assert table.yx_count == 3
    assert table.yc_count == 3
    assert table.yk_count == 1
    assert table.ym_count == 2
    assert len(table.get_all_step()) == 1


def test_parse_error_raises() -> None:
    with pytest.raises(ValueError, match="XML 解析失败"):
        import_scd("<SCL><Unclosed>")


def test_empty_scl_yields_empty_table() -> None:
    r = import_scd('<?xml version="1.0"?><SCL xmlns="http://www.iec.ch/61850/2003/SCL"/>')
    assert r.signals == []
    assert r.common_addr == 1
    assert all(len(r.points[k]) == 0 for k in ("yx", "yc", "yk", "ym", "step"))


# ── Web 端点（/api/scd/preview）─────────────────────────────────────────


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
async def test_scd_preview_endpoint(slave_client):
    """预览端点返回可导入的 YAML 且**不修改当前点表**."""
    client, bridge = slave_client
    before = bridge.points.count
    r = await client.post("/api/scd/preview", data=_fixture_text())
    body = await r.json()
    assert r.status == 200
    assert body["ok"] is True, body
    assert body["station_name"] == "DemoStation"
    assert body["common_addr"] == 1
    assert body["stats"]["yx"] == 3 and body["stats"]["signals_total"] == 14
    assert any("IOA 冲突" in w for w in body["warnings"])
    data = yaml.safe_load(body["yaml"])
    assert data["station_name"] == "DemoStation" and data["common_addr"] == 1
    assert len(data["yx"]) == 3
    # 无副作用：点表未被修改
    assert bridge.points.count == before


@pytest.mark.asyncio
async def test_scd_preview_endpoint_common_addr_param(slave_client):
    """``?common_addr=`` 透传给转换器（多 casdu 场景可显式选择）."""
    client, _ = slave_client
    r = await client.post("/api/scd/preview?common_addr=99", data=_fixture_text())
    body = await r.json()
    assert r.status == 200 and body["ok"] is True
    assert body["common_addr"] == 99
    data = yaml.safe_load(body["yaml"])
    assert data["common_addr"] == 99


@pytest.mark.asyncio
async def test_scd_preview_endpoint_bad_input(slave_client):
    """XML 解析失败 → 400 + 错误信息；common_addr 非整数 → 400."""
    client, _ = slave_client
    r = await client.post("/api/scd/preview", data="<SCL><Unclosed>")
    assert r.status == 400
    body = await r.json()
    assert body["ok"] is False and "XML 解析失败" in body["error"]
    r2 = await client.post("/api/scd/preview?common_addr=abc", data=_fixture_text())
    assert r2.status == 400
