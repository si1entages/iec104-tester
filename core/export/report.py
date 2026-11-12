"""报告导出器（WP8）：xlsx / PDF / HTML 三种格式.

统一入口 :func:`export_report`，返回 ``(body: bytes, content_type, suffix)``。
三种格式共用同一份 :class:`~core.export.evidence.Evidence`，因此**逐点证据条数
必然一致**（有测试断言）。

PDF 依赖 **ReportLab 是可选依赖**（``pip install .[pdf]``）：未安装时
``export_report("pdf")`` 抛 :class:`PdfUnavailable`，由 HTTP 层返回可读的 400
而不是 500——**onefile 打包在未装 extra 时仍可正常启动**（HTML/xlsx 可用）。
"""

from __future__ import annotations

import io
import time

from .evidence import (
    AUDIT_HEADERS,
    POINT_HEADERS,
    Evidence,
    audit_row,
)

#: PDF 不可用（未安装可选依赖 reportlab）
PDF_EXTRA_HINT = "pip install iec104-tester[pdf]"


class PdfUnavailable(RuntimeError):
    """未安装 PDF 可选依赖；调用方应提示用户安装 extra 而非报 500."""


def export_report(ev: Evidence, fmt: str) -> tuple[bytes, str, str]:
    """按格式导出；返回 ``(body, content_type, suffix)``."""
    fmt = (fmt or "html").lower()
    if fmt == "xlsx":
        return export_xlsx(ev), _XLSX_CT, "xlsx"
    if fmt == "pdf":
        return export_pdf(ev), "application/pdf", "pdf"
    if fmt == "html":
        return export_html(ev), "text/html", "html"
    raise ValueError(f"不支持的格式：{fmt}（可选 html|xlsx|pdf）")


_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ── xlsx ─────────────────────────────────────────────────────────────


def export_xlsx(ev: Evidence) -> bytes:
    """xlsx：摘要 / 逐点证据 / 审计流水 三个 sheet（无证据时也给空表头）."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    head_font = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="DDE4EA")

    def _sheet(ws, headers: list[str], rows: list[list[str]]) -> None:
        ws.append(headers)
        for cell in ws[1]:
            cell.font = head_font
            cell.fill = head_fill
        for row in rows:
            ws.append(row)
        ws.freeze_panes = "A2"

    ws1 = wb.active
    ws1.title = "摘要"
    _sheet(ws1, ["项", "值"], [[k, v] for k, v in ev.summary_rows()])
    ws1.column_dimensions["A"].width = 32
    ws1.column_dimensions["B"].width = 60

    ws2 = wb.create_sheet("逐点证据")
    _sheet(ws2, POINT_HEADERS, [p.to_row() for p in ev.points])
    for col, width in zip("ABCDEFGHIJKLMN",
                          [8, 22, 8, 6, 14, 14, 12, 10, 30, 20, 12, 40, 40, 20], strict=True):
        ws2.column_dimensions[col].width = width

    ws3 = wb.create_sheet("审计流水")
    _sheet(ws3, AUDIT_HEADERS, [audit_row(r) for r in ev.audit])
    for col, width in zip("ABCDEFGH", [20, 14, 10, 16, 24, 12, 8, 40], strict=True):
        ws3.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────


def _pdf_available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def export_pdf(ev: Evidence) -> bytes:
    """PDF：摘要 + 逐点证据表（横向 A4，逐点列多）+ 审计摘要.

    未安装 reportlab 时抛 :class:`PdfUnavailable`（不静默产出空文件）。
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as e:  # pragma: no cover - 取决于可选依赖
        raise PdfUnavailable(
            f"PDF 导出需要可选依赖 reportlab（{PDF_EXTRA_HINT}）"
        ) from e

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
        title=ev.title or "IEC 60870-5-104 测试报告",
    )
    styles = getSampleStyleSheet()
    flow: list = [
        Paragraph(ev.title or "IEC 60870-5-104 测试报告", styles["Title"]),
        Spacer(1, 6),
    ]

    summary = Table(
        [[k, v] for k, v in ev.summary_rows()],
        colWidths=[70 * mm, 180 * mm],
    )
    summary.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    flow.append(summary)

    flow.append(Spacer(1, 10))
    flow.append(Paragraph(
        f"逐点证据（{ev.point_count} 条）", styles["Heading2"]))
    if ev.points:
        rows = [POINT_HEADERS] + [p.to_row() for p in ev.points]
        table = Table(rows, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE4EA")),
            ("FONTSIZE", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        flow.append(table)
    else:
        flow.append(Paragraph("（无逐点证据）", styles["Normal"]))

    if ev.audit:
        flow.append(Spacer(1, 10))
        flow.append(Paragraph(f"审计流水（{len(ev.audit)} 条）", styles["Heading2"]))
        rows = [AUDIT_HEADERS] + [audit_row(r) for r in ev.audit]
        t2 = Table(rows, repeatRows=1)
        t2.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE4EA")),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        flow.append(t2)

    doc.build(flow)
    return buf.getvalue()


# ── HTML ─────────────────────────────────────────────────────────────


def export_html(ev: Evidence) -> bytes:
    """HTML：优先复用 ``webui/report.py`` 的自包含渲染（含样式/可打印）.

    传入同一份 frames/events/结论，并额外附逐点证据与审计段；
    这样「打印成 PDF」与原生 PDF 导出看到的是同一批数据。
    """
    try:
        from webui.report import build_session_report_html
    except Exception:  # pragma: no cover - webui 不可用时退回极简渲染
        return _fallback_html(ev).encode("utf-8")

    html = build_session_report_html(
        ev.role or "master",
        ev.session.get("status") or {},
        ev.frames, ev.events,
        title=ev.title,
        notes=ev.notes,
        max_frames=300,
        conclusion=ev.conclusion,
        conclusion_kind=ev.conclusion_kind,
        chart_images=ev.chart_images,
        alarms=ev.alarms or None,
    )
    extra = _evidence_sections_html(ev)
    if extra:
        html = html.replace("</body>", extra + "</body>") if "</body>" in html else html + extra
    return html.encode("utf-8")


def _evidence_sections_html(ev: Evidence) -> str:
    """逐点证据 + 审计摘要段（纯内联样式，与主报告同风格）."""
    from html import escape

    if not ev.points and not ev.audit:
        return ""
    parts = ['<div style="page-break-before:always"></div>']
    if ev.points:
        parts.append(f"<h2>逐点证据（{ev.point_count} 条）</h2><table>")
        parts.append("<tr>" + "".join(f"<th>{escape(h)}</th>" for h in POINT_HEADERS) + "</tr>")
        for p in ev.points:
            cells = "".join(f"<td>{escape(c)}</td>" for c in p.to_row())
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    if ev.audit:
        parts.append(f"<h2>审计流水（{len(ev.audit)} 条）</h2><table>")
        parts.append("<tr>" + "".join(f"<th>{escape(h)}</th>" for h in AUDIT_HEADERS) + "</tr>")
        for r in ev.audit:
            cells = "".join(f"<td>{escape(c)}</td>" for c in audit_row(r))
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    return "".join(parts)


def _fallback_html(ev: Evidence) -> str:
    from html import escape

    rows = "".join(
        f"<tr>{''.join(f'<td>{escape(c)}</td>' for c in p.to_row())}</tr>"
        for p in ev.points
    )
    return (
        "<!doctype html><meta charset=utf-8>"
        f"<title>{escape(ev.title or 'IEC 60870-5-104 测试报告')}</title>"
        f"<h1>{escape(ev.title or 'IEC 60870-5-104 测试报告')}</h1>"
        f"<p>生成时间 {time.strftime('%Y-%m-%d %H:%M:%S')}</p>"
        f"<h2>逐点证据（{ev.point_count} 条）</h2>"
        "<table border=1 cellspacing=0 cellpadding=3><tr>"
        + "".join(f"<th>{escape(h)}</th>" for h in POINT_HEADERS)
        + f"</tr>{rows}</table>"
    )


def pdf_available() -> bool:
    """PDF 能力探测（供 ``/api/export/report?format=pdf`` 与界面提示用）."""
    return _pdf_available()
