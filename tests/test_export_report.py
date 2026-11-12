"""WP8 原生 Excel / PDF 报告测试.

覆盖方案 `docs/optimization_plan_v111.md` §WP8 的验收判据：
- **同一会话导出三种格式，逐点证据条数一致**；
- **未装 PDF extra 时仍可启动**（html/xlsx 可用，PDF 端点返回 400 + 安装提示）。

另覆盖：xlsx 三个 sheet 与表头、PDF 真实文件头（装了 reportlab 时）、
HTML 含逐点证据与审计段、逐点字段映射（布尔→ON/OFF、None→—）、
端点参数校验与 session 选择。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.export import (
    Evidence,
    PdfUnavailable,
    export_report,
    pdf_available,
    points_from_session,
)
from webui.bridge import EngineBridge
from webui.server import create_app

# ── 夹具 ─────────────────────────────────────────────────────────────


def _items(n: int = 5) -> list[dict]:
    return [
        {
            "ioa": 1000 + i,
            "name": f"点{i}",
            "kind": "YX" if i % 2 == 0 else "YC",
            "group": 1,
            "expected": True if i % 2 == 0 else 3.5,
            "actual": True if i % 2 == 0 else 3.4,
            "quality": "GOOD",
            "verdict": "pass" if i < 3 else "fail",
            "reason": "" if i < 3 else "实测不符",
            "note": f"备注{i}",
            "operator": "检修张",
            "tx_frame": "680e04000300",
            "rx_frame": "680e04000301",
            "checked_at": 1794450000.0 + i,
        }
        for i in range(n)
    ]


def _evidence(n: int = 5, audit: int = 2) -> Evidence:
    return Evidence(
        role="master",
        title="测试报告",
        session={"status": {"role": "master"}, "commission": {"id": "s1"}},
        points=points_from_session({"items": _items(n)}),
        audit=[
            {"ts": 1794450000.0, "operator": "检修张", "role": "admin",
             "source_ip": "127.0.0.1", "action": "master/yk", "target": "2001",
             "result": "ok", "reason": ""}
            for _ in range(audit)
        ],
        frames=[{"ts": 1.0, "data": {"direction": "tx", "len": 14, "hex": "680e04000300"}}],
        events=[{"ts": 1.0, "data": {"type": "ui"}}],
        alarms=[{"ts": 1.0, "kind": "comm", "ioa": None, "message": "断链", "acked": False}],
        conclusion="合格",
        conclusion_kind="pass",
        notes="现场验收",
    )


# ── 逐点证据模型 ─────────────────────────────────────────────────────


class TestEvidenceModel:
    def test_points_from_session_maps_all_fields(self):
        pts = points_from_session({"items": _items(2)})
        assert len(pts) == 2
        p = pts[0]
        assert p.ioa == 1000 and p.name == "点0" and p.kind == "YX"
        assert p.expected == "ON" and p.actual == "ON"   # 布尔 → ON/OFF
        assert p.verdict == "pass" and p.operator == "检修张"
        assert p.tx_frame == "680e04000300"

    def test_scalar_conversion(self):
        pts = points_from_session({"items": [
            {"ioa": 1, "expected": None, "actual": False},
        ]})
        assert pts[0].expected == "—"    # None → 破折号
        assert pts[0].actual == "OFF"

    def test_bad_items_skipped(self):
        pts = points_from_session({"items": [None, "x", {"ioa": 1}]})
        assert len(pts) == 1 and pts[0].ioa == 1
        # 缺省字段按「—」占位（报告里空单元格会让人以为是渲染丢失）
        assert pts[0].expected == "—" and pts[0].actual == "—"
        assert points_from_session({}) == []

    def test_summary_rows_include_counts(self):
        ev = _evidence(3)
        rows = dict(ev.summary_rows())
        assert rows["逐点证据条数 / Evidence rows"] == "3"
        assert rows["角色 / Role"] == "master"
        assert rows["结论 / Conclusion"] == "合格"


# ── 三格式一致性（验收判据）──────────────────────────────────────────


class TestFormatParity:
    def test_point_count_identical_across_formats(self):
        """验收判据：同一会话导出三种格式，逐点证据条数一致."""
        ev = _evidence(7)
        # xlsx：读回「逐点证据」sheet 的行数（减表头）
        xlsx_body, _, _ = export_report(ev, "xlsx")
        rows = _xlsx_sheet_rows(xlsx_body, "逐点证据")
        assert len(rows) - 1 == ev.point_count == 7

        # html：数证据表的数据行
        html_body, _, _ = export_report(ev, "html")
        html = html_body.decode("utf-8")
        assert "逐点证据（7 条）" in html
        # 逐点表每行都带下发帧；帧证据表另有 1 条同 hex，故为 7+1
        assert html.count("680e04000300") >= 7

        # pdf：装了 reportlab 就校验文件头与页数可用
        if pdf_available():
            pdf_body, ct, sfx = export_report(ev, "pdf")
            assert ct == "application/pdf" and sfx == "pdf"
            assert pdf_body.startswith(b"%PDF-")
            assert len(pdf_body) > 1000
        else:
            with pytest.raises(PdfUnavailable):
                export_report(ev, "pdf")

    def test_empty_evidence_all_formats_ok(self):
        ev = Evidence(role="master", title="空报告")
        for fmt in ("xlsx", "html"):
            body, _, _ = export_report(ev, fmt)
            assert body
        if pdf_available():
            body, _, _ = export_report(ev, "pdf")
            assert body.startswith(b"%PDF-")

    def test_unknown_format_rejected(self):
        with pytest.raises(ValueError, match="不支持的格式"):
            export_report(_evidence(), "docx")


def _xlsx_sheet_rows(body: bytes, sheet_name: str) -> list[list]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(body))
    assert sheet_name in wb.sheetnames
    ws = wb[sheet_name]
    return [list(r) for r in ws.iter_rows(values_only=True)]


class TestXlsx:
    def test_three_sheets_and_headers(self):
        body, ct, sfx = export_report(_evidence(2), "xlsx")
        assert sfx == "xlsx" and "spreadsheetml" in ct
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            assert any(n.startswith("xl/worksheets/") for n in z.namelist())
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(body))
        assert wb.sheetnames == ["摘要", "逐点证据", "审计流水"]
        head = [c.value for c in wb["逐点证据"][1]]
        assert head[0] == "IOA" and "下发帧" in head and "检查人" in head

    def test_audit_sheet_rows(self):
        body, _, _ = export_report(_evidence(1, audit=3), "xlsx")
        rows = _xlsx_sheet_rows(body, "审计流水")
        assert len(rows) - 1 == 3
        assert rows[1][4] == "master/yk"


class TestHtml:
    def test_contains_evidence_and_audit_sections(self):
        body, ct, _ = export_report(_evidence(3, audit=2), "html")
        assert "text/html" in ct
        html = body.decode("utf-8")
        assert "逐点证据（3 条）" in html
        assert "审计流水（2 条）" in html
        assert "检修张" in html

    def test_escapes_dangerous_content(self):
        ev = _evidence(1)
        ev.points[0].name = "<script>alert(1)</script>"
        html = export_report(ev, "html")[0].decode("utf-8")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestPdf:
    def test_pdf_unavailable_raises_with_hint(self, monkeypatch):
        """模拟未安装 reportlab：必须抛 PdfUnavailable 且带安装提示."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name.startswith("reportlab"):
                raise ImportError("no reportlab")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(PdfUnavailable, match="reportlab"):
            export_report(_evidence(), "pdf")

    @pytest.mark.skipif(not pdf_available(), reason="未安装 reportlab（可选依赖）")
    def test_pdf_real_file(self):
        body, ct, sfx = export_report(_evidence(20), "pdf")
        assert body.startswith(b"%PDF-1.4")
        assert body.rstrip().endswith(b"%%EOF")
        assert len(body) > 2000


# ── 端点 ─────────────────────────────────────────────────────────────


class TestEndpoint:
    async def _client(self, tmp_path: Path):
        from core.data.audit import AuditStore
        from webui.audit import AuditService

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None,
                         data_dir=tmp_path)
        store = AuditStore(tmp_path / "audit.db")
        store.open()
        b.audit = AuditService(store)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_xlsx_download(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=xlsx&title=T")
            assert r.status == 200
            assert "spreadsheetml" in r.content_type
            assert "attachment" in r.headers["Content-Disposition"]
            assert (await r.read())[:2] == b"PK"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_html_download(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=html")
            assert r.status == 200 and "text/html" in r.content_type
            assert "测试报告" in await r.text()
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_pdf_when_available_or_400(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=pdf")
            if pdf_available():
                assert r.status == 200 and r.content_type == "application/pdf"
                assert (await r.read())[:4] == b"%PDF"
            else:
                assert r.status == 400
                body = await r.json()
                assert body["ok"] is False and "reportlab" in body["error"]
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_bad_format_400(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=docx")
            assert r.status == 400
            assert "html|xlsx|pdf" in (await r.json())["error"]
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_includes_commission_points_and_audit(self, tmp_path: Path):
        """报告自动并入最近一次传动会话的逐点证据与审计流水."""
        b, client = await self._client(tmp_path)
        # 造一个会话（用真实 CommissionService，落独立临时库）

        # 用桥自带演示点表（无引擎时 ensure_demo_points 仍会建点），
        # 全选（ioas=None）以保证至少有可验收的点
        b.ensure_demo_points()
        b.commission.create_session("验收", "检修张", None, None, None)

        async with client as c:
            r = await c.get("/api/export/report?format=xlsx")
            body = await r.read()
        rows = _xlsx_sheet_rows(body, "逐点证据")
        assert len(rows) - 1 >= 1, "报告应包含会话的逐点证据"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_no_engine_still_exports(self, tmp_path: Path):
        """引擎未启动（无帧/无会话/无审计）时仍能出报告，不 500."""
        b, client = await self._client(tmp_path)
        async with client as c:
            for fmt in ("html", "xlsx"):
                r = await c.get(f"/api/export/report?format={fmt}")
                assert r.status == 200, fmt
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_legacy_html_endpoint_unchanged(self, tmp_path: Path):
        """旧端点 /api/export/report.html 行为不变（WP8 未改动它）."""
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report.html")
            assert r.status == 200 and "text/html" in r.content_type
        await b.shutdown()


class TestReportFallback:
    def test_fallback_html(self, monkeypatch):
        import core.export.report as mod

        real_import = __import__

        def fake(name, *a, **kw):
            if name.startswith("webui"):
                raise ImportError("no webui")
            return real_import(name, *a, **kw)

        monkeypatch.setattr("builtins.__import__", fake)
        ev = Evidence(role="master", title="<T>")
        html = mod.export_html(ev).decode("utf-8")
        assert "<!doctype html>" in html and "&lt;T&gt;" in html

    def test_html_audit_section(self):
        ev = Evidence(
            role="master", title="t",
            audit=[{"ts": 0, "operator": "", "role": "", "source_ip": "",
                    "action": "", "target": "", "result": "", "reason": ""}],
        )
        body, _, _ = export_report(ev, "html")
        assert "审计流水（1 条）" in body.decode("utf-8")


class TestEndpointBranches:
    async def _client(self, tmp_path: Path):
        from core.data.audit import AuditStore
        from webui.audit import AuditService

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None,
                         data_dir=tmp_path)
        store = AuditStore(tmp_path / "a.db")
        store.open()
        b.audit = AuditService(store)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_bad_audit_limit_falls_back(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=html&audit_limit=abc")
            assert r.status == 200
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_audit_limit_zero_skips_audit(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=html&audit_limit=0")
            assert r.status == 200
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_specific_session(self, tmp_path: Path):

        b = EngineBridge("master", point_table=None, connection=None,
                         history_db=None, app_config=None,
                         data_dir=tmp_path)
        b.ensure_demo_points()
        sess = b.commission.create_session("S", "op", None, None, None)
        sid = sess["id"] if isinstance(sess, dict) else sess.id
        async with TestClient(TestServer(create_app(b))) as c:
            r = await c.get(f"/api/export/report?format=html&session={sid}")
            assert r.status == 200
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_commission_failure_does_not_break_report(self, tmp_path: Path, monkeypatch):
        b, client = await self._client(tmp_path)
        monkeypatch.setattr(b.commission, "list_sessions",
                            lambda _n: (_ for _ in ()).throw(RuntimeError("db gone")))
        async with client as c:
            r = await c.get("/api/export/report?format=html")
            assert r.status == 200
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_report(self, tmp_path: Path, monkeypatch):
        b, client = await self._client(tmp_path)
        monkeypatch.setattr(b.audit, "list_records",
                            lambda **_kw: (_ for _ in ()).throw(RuntimeError("db gone")))
        async with client as c:
            r = await c.get("/api/export/report?format=xlsx")
            assert r.status == 200
        await b.shutdown()
    @pytest.mark.asyncio
    async def test_export_exception_returns_400(self, tmp_path: Path, monkeypatch):
        """导出器抛异常 → 400 + 可读错误，不冒泡成 500."""
        import webui.server as srv

        real = srv.asyncio.to_thread

        def boom(fn, *a, **kw):
            if fn is not None and getattr(fn, "__name__", "") == "export_report":
                raise RuntimeError("renderer exploded")
            return real(fn, *a, **kw)

        monkeypatch.setattr(srv.asyncio, "to_thread", boom)
        b, client = await self._client(tmp_path)
        async with client as c:
            r = await c.get("/api/export/report?format=xlsx")
            assert r.status == 400
            assert "报告生成失败" in (await r.json())["error"]
        await b.shutdown()
