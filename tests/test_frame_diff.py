"""T96 离线报文对比：规格化签名多重集 diff（纯函数 + 端点）+ T95 覆盖补齐.

验收口径：同录制自 diff 为空（identical=True）；人为改动（改值/删帧/COT 变化/
类型变化）可检出；会话易变字段（N(S)/N(R)、时标、client_id、S 帧 rx_seq）不产生假差异。
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from openpyxl import Workbook

from core.capture import CaptureFile, FrameEntry
from core.data.point_table import PointTable, YxPointDef
from core.protocol.apci import APCICodec
from core.protocol.asdu import TypeID
from webui.bridge import EngineBridge
from webui.capture import CaptureService
from webui.frame_diff import diff_frames, frame_signature
from webui.points_xlsx import parse_xlsx_table
from webui.server import create_app

# ── 帧构造工具（不依赖引擎，纯字节） ────────────────────────────────────


def _asdu(type_id: int, cot: int, body: bytes, ca: int = 1) -> bytes:
    """最小 ASDU：type/vsq/cot/origin/ca(2) + body."""
    return bytes([type_id, 1, cot, 0, ca & 0xFF, ca >> 8]) + body


def _i(ns: int, nr: int, asdu: bytes) -> bytes:
    return APCICodec.encode_i(ns, nr, asdu)


def _s(nr: int) -> bytes:
    return APCICodec.encode_s(nr)


def _u(func: int) -> bytes:
    return APCICodec.encode_u(func)


# M_ME_NC_1（TypeID=13，短浮点）：信息体 = ioa(3) + float(4) + quality(1)


def _yc_asdu(ioa: int, value: int, cot: int = 3, ca: int = 1) -> bytes:
    body = (bytes([ioa & 0xFF, (ioa >> 8) & 0xFF, (ioa >> 16) & 0xFF])
            + struct.pack("<f", float(value)) + b"\x00")
    return _asdu(TypeID.M_ME_NC_1.value, cot, body, ca)


def _entry(data: bytes, direction: str = "RX") -> FrameEntry:
    return FrameEntry(frame_data=data,
                      direction=0 if direction == "RX" else 1)


def _segment() -> list[FrameEntry]:
    """一段标准会话：STARTDT → GI → 数据 → 确认."""
    return [
        _entry(_u(0x07), "TX"),                                  # STARTDT_ACT
        _entry(_u(0x0B), "RX"),                                  # STARTDT_CON
        _entry(_i(0, 0, _asdu(100, 6, b"\x00\x00\x00")), "TX"),  # C_IC_NA_1 激活 ioa+QOI
        _entry(_i(0, 1, _yc_asdu(1001, 345)), "RX"),
        _entry(_i(1, 1, _yc_asdu(1002, 678)), "RX"),
        _entry(_s(2), "TX"),
        _entry(_i(2, 3, _asdu(100, 10, b"\x00\x00\x00")), "RX"),  # GI 终止
    ]


# ── 纯函数：验收口径 ────────────────────────────────────────────────────


def test_self_diff_is_empty():
    seg = _segment()
    r = diff_frames(seg, seg)
    assert r["identical"] is True and r["entries"] == [] and r["diff_total"] == 0
    assert r["total_a"] == r["total_b"] == 7


def test_session_volatile_fields_ignored():
    """N(S)/N(R) 不同、S 帧 rx_seq 不同、client_id 不同 → 仍 identical."""
    a = _segment()
    b = [
        _entry(_u(0x07), "TX"),
        _entry(_u(0x0B), "RX"),
        _entry(_i(100, 50, _asdu(100, 6, b"\x00\x00\x00\x14")), "TX"),  # 序号完全不同
        _entry(_i(101, 51, _yc_asdu(1001, 345)), "RX"),
        _entry(_i(102, 51, _yc_asdu(1002, 678)), "RX"),
        _entry(_s(200), "TX"),                                    # rx_seq 不同
        _entry(_i(103, 52, _asdu(100, 10, b"\x00\x00\x00\x14")), "RX"),
    ]
    r = diff_frames(a, b)
    assert r["identical"] is True, r["entries"]


def test_value_change_detected():
    a = _segment()
    b = _segment()
    b[3] = _entry(_i(0, 1, _yc_asdu(1001, 999)), "RX")  # 值 345 → 999
    r = diff_frames(a, b)
    assert r["identical"] is False and r["diff_total"] == 2
    sigs = {e["signature"]: e for e in r["entries"]}
    assert any("ioa=1001" in s and "999" in s for s in sigs)
    assert sigs[[s for s in sigs if "345" in s][0]]["count_a"] == 1  # 旧值只在 A 段


def test_missing_and_extra_frames_detected():
    a = _segment()
    b = [f for f in _segment() if f.frame_data != _i(1, 1, _yc_asdu(1002, 678))]
    b.append(_entry(_u(0x11), "TX"))  # 多一个 TESTFR_ACT
    r = diff_frames(a, b)
    assert r["identical"] is False
    deltas = {e["delta"] for e in r["entries"]}
    assert -1 in deltas and 1 in deltas  # 缺 1 帧、多 1 帧


def test_cot_and_type_change_detected():
    a = [_entry(_i(0, 0, _yc_asdu(1001, 10, cot=3)))]
    b = [_entry(_i(0, 0, _yc_asdu(1001, 10, cot=6)))]
    assert diff_frames(a, b)["identical"] is False
    c = [_entry(_i(0, 0, _yc_asdu(1001, 10, cot=3, ca=2)))]  # CA 变化
    assert diff_frames(a, c)["identical"] is False
    d = [_entry(_i(0, 0, _asdu(TypeID.C_SC_NA_1.value, 6, bytes([1, 0x01, 0, 0]))))]  # 类型变了
    assert diff_frames(a, d)["identical"] is False


def test_direction_and_dirty_frame_fallback():
    a = [_entry(_yc_asdu(1001, 1), "RX")]
    b = [_entry(_yc_asdu(1001, 1), "TX")]
    assert diff_frames(a, b)["identical"] is False  # 方向属于签名
    dirty = bytes([0x68, 0xFF, 0x01]) + b"\xaa" * 20  # 解析失败
    assert "raw" in frame_signature(_entry(dirty))
    assert diff_frames([_entry(dirty)], [_entry(dirty)])["identical"] is True


def test_u_frames_and_time_tags():
    a = [_entry(_u(0x07)), _entry(_u(0x13))]
    b = [_entry(_u(0x07)), _entry(_u(0x13))]
    assert diff_frames(a, b)["identical"] is True
    assert diff_frames(a, [_entry(_u(0x07)), _entry(_u(0x23))])["identical"] is False


def test_truncation_and_counts():
    a = [_entry(_i(n, 0, _yc_asdu(1000 + n, n))) for n in range(260)]
    b = [_entry(_i(n, 0, _yc_asdu(1000 + n, n))) for n in range(5)]
    r = diff_frames(a, b)
    assert r["diff_total"] == 255  # 前 5 个 IOA 签名重叠，其余 255 个差异
    assert r["truncated"] is True and len(r["entries"]) == 200
    assert r["total_a"] == 260 and r["total_b"] == 5


# ── 录制文件 round-trip：写 .i104 → diff_files ──────────────────────────


def _write_capture(path: Path, frames: list[FrameEntry], desc: str = "t96") -> None:
    CaptureFile.save(path, frames, description=desc)


def test_capture_service_diff_files(tmp_path):
    svc = CaptureService(tmp_path, "master")
    _write_capture(tmp_path / "a.i104", _segment())
    _write_capture(tmp_path / "b.i104", _segment()[:5])  # 少 2 帧
    r = svc.diff_files("a.i104", "b.i104")
    assert r["ok"] is True and r["identical"] is False and r["diff_total"] == 2
    assert r["file_a"] == "a.i104" and r["total_b"] == 5
    # 自 diff
    r = svc.diff_files("a.i104", "a.i104")
    assert r["identical"] is True
    # 路径穿越 / 不存在
    assert svc.diff_files("../a.i104", "a.i104")["ok"] is False
    assert svc.diff_files("a.i104", "missing.i104")["ok"] is False
    # 非 i104 内容 → 加载失败
    (tmp_path / "junk.i104").write_bytes(b"garbage")
    r = svc.diff_files("a.i104", "junk.i104")
    assert r["ok"] is False and "load failed" in r["error"]


def test_json_capture_format_supported(tmp_path):
    svc = CaptureService(tmp_path, "slave")
    _write_capture(tmp_path / "a.i104", _segment())
    svc.export("a.i104", "json")
    assert (tmp_path / "a_json.json").is_file()
    r = svc.diff_files("a.i104", "a_json.json")
    assert r["ok"] is True and r["identical"] is True  # 跨格式同内容 → 空


# ── 端点 ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def capture_client(tmp_path):
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    bridge.captures = CaptureService(tmp_path, "master")
    client = TestClient(TestServer(create_app(bridge)))
    await client.start_server()
    yield client, tmp_path
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
async def test_capture_diff_endpoint(capture_client):
    client, tmp = capture_client
    _write_capture(tmp / "a.i104", _segment())
    _write_capture(tmp / "b.i104", _segment()[:5])
    r = await client.post("/api/capture/diff", json={"a": "a.i104", "b": "b.i104"})
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True and body["identical"] is False and body["diff_total"] == 2
    # 合同：entries 字段齐
    assert set(body["entries"][0].keys()) == {"signature", "count_a", "count_b", "delta"}
    # 文件不存在 → 400
    r = await client.post("/api/capture/diff", json={"a": "a.i104", "b": "nope.i104"})
    assert r.status == 400
    # 非法参数 → 400
    r = await client.post("/api/capture/diff", json={})
    assert r.status == 400
    r = await client.post("/api/capture/diff", json={"a": "a.i104", "b": "a.i104", "max_entries": "x"})
    assert r.status == 400
    # 非 JSON → 400
    r = await client.post("/api/capture/diff", data=b"junk")
    assert r.status == 400


# ── T95 覆盖补齐（points_xlsx 强制分支 + points.py 错误分支） ────────────


def _xlsx_with(rows: list[list[object]], header: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_coercion_error_branches():
    from webui.points_xlsx import _as_bool, _as_float, _as_int  # noqa: PLC0415 — 测试直测内部

    with pytest.raises(ValueError, match="布尔值"):
        _as_int(True, "ioa")
    with pytest.raises(ValueError, match="整数"):
        _as_int(3.5, "ioa")
    assert _as_int(3.0, "ioa") == 3  # 整值 float 接受
    with pytest.raises(ValueError, match="缺失"):
        _as_int(None, "ioa")
    with pytest.raises(ValueError, match="缺失"):
        _as_float("", "value")
    assert _as_float("1.5", "value") == 1.5  # 字符串浮点
    with pytest.raises(ValueError, match="true/false"):
        _as_bool("maybe", "enabled", True)
    assert _as_bool("否", "enabled", True) is False
    assert _as_bool(None, "enabled", True) is True

    header = ["type", "ioa", "name"]
    # 坏行与有效行并存：坏行进 errors，不阻断有效行（全坏行会被「未解析出有效点」兜底）
    tbl, errs, stats = parse_xlsx_table(
        _xlsx_with([["YX", True, "布尔"], ["YX", 3.5, "分数"], ["YX", None, "缺失"],
                    ["YX", 7, "好的"]], header), PointTable())
    assert stats["YX"] == 1 and len(errs) == 3
    assert "布尔值" in errs[0] and "整数" in errs[1] and "缺失" in errs[2]
    assert tbl.get_all_yx()[0].ioa == 7
    # 启用列非法字符串 → 行级错误；合法 "否" → False
    _, errs2, stats2 = parse_xlsx_table(
        _xlsx_with([["YX", 1, "x", "maybe"], ["YX", 2, "y", "否"]],
                   ["type", "ioa", "name", "enabled"]), PointTable())
    assert stats2["YX"] == 1 and len(errs2) == 1 and tbl.get_all_yx()[0].ioa == 7


def test_xlsx_empty_workbooks():
    wb = Workbook()
    buf = io.BytesIO()
    wb.save(buf)  # 无表头行
    with pytest.raises(ValueError, match="空表"):
        parse_xlsx_table(buf.getvalue(), PointTable())
    # （无工作表分支在 openpyxl 侧无法生成合法文件，属防御性代码，不测）
    # 全 None 行跳过
    tbl, errors, stats = parse_xlsx_table(
        _xlsx_with([[None] * 5, ["YX", 9, "x"]],
                   ["type", "ioa", "name", "enabled", "subtype"]), PointTable())
    assert stats["YX"] == 1 and errors == []


def test_points_service_error_branches():
    from webui.points import PointService  # noqa: PLC0415

    svc = PointService()
    assert svc.batch("XX", [1], "enable")["ok"] is False  # bad type
    assert svc.batch("YX", [1], "bad")["ok"] is False  # bad action
    assert svc.batch("YX", [1], "group")["ok"] is False  # group required
    assert svc.batch("YX", [], "enable")["ok"] is False  # empty ioas
    assert svc.import_csv(None)["ok"] is False  # 无法解析 → 解析失败分支
    # sync_to_engine：engine._point_table 赋值抛异常被吞
    class BadEngine:
        @property
        def _point_table(self):
            raise RuntimeError("no")

        @property
        def point_table(self):
            return object()
    svc.sync_to_engine(BadEngine())
    # rebuild_store：engine 无 data_store → 只同步
    svc.rebuild_store(object())
    # import_yaml + rebuild 抛异常 → ok False
    class ExplodeStore:
        def init_from_point_table(self, _t):
            raise RuntimeError("boom")
    class ExplodeEngine:
        data_store = ExplodeStore()
    assert svc.import_yaml("station_name: x\n", engine=ExplodeEngine())["ok"] is False
    # export_csv 转义：名称带逗号与引号
    svc2 = PointService()
    svc2.table.add_yx(YxPointDef(ioa=1, name='a,"b"'))  # noqa: PLC0415
    assert '"a,""b"""' in svc2.export_csv()
    # 设计基准：bad action / import xlsx with engine
    assert svc.set_design("nope")["ok"] is False


def test_sig_details_pn_test_and_empty_asdu():
    # COT 字节带 P/N(0x40) 与 T(0x80) 位 → 签名含 PN/T
    asdu_pn = bytes([13, 1, 0x40 | 3, 0, 1, 0]) + b"\x00" * 8
    asdu_t = bytes([13, 1, 0x80 | 3, 0, 1, 0]) + b"\x00" * 8
    sig_pn = frame_signature(_entry(_i(0, 0, asdu_pn)))
    sig_t = frame_signature(_entry(_i(0, 0, asdu_t)))
    assert "PN" in sig_pn and "T" not in sig_pn
    assert "T" in sig_t and "PN" not in sig_t
    # 空 ASDU 的 I 帧（仅 APCI）
    assert "empty_asdu" in frame_signature(_entry(_i(0, 0, b"")))
    # 脏 ASDU 回退 undecoded
    assert "undecoded" in frame_signature(_entry(_i(0, 0, bytes([0xff] * 6))))
    # signature_summary 截断 + now_ts 纯函数
    long_sig = "x" * 200
    from webui.frame_diff import now_ts, signature_summary  # noqa: PLC0415
    assert signature_summary(long_sig).endswith("…") and len(signature_summary(long_sig)) == 158
    assert signature_summary("short") == "short"
    assert now_ts() > 0
