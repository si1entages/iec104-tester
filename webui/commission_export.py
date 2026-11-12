"""对点 / 传动验收记录导出（WP2）.

三种格式共用同一份 ``CommissionSession.to_dict()`` 数据，保证「同一会话
导出三种格式，逐点证据条数一致」：

* ``xlsx`` —— 现场签字用的对点表（openpyxl，本仓已用于点表导出）；
* ``json`` —— 机器可读归档（含完整证据帧 hex）；
* ``html`` —— 自包含单文件报告，浏览器「打印 → 另存为 PDF」即可交付。

纯函数，不依赖引擎 / 事件循环，便于单测。
"""

from __future__ import annotations

import html
import io
import json
import time
from typing import Any

from openpyxl import Workbook

_XLSX_COLUMNS = [
    ("序号", 8), ("IOA", 10), ("名称", 24), ("类型", 8), ("组", 6),
    ("期望值", 14), ("实测值", 14), ("品质", 12), ("结论", 10),
    ("失败原因", 28), ("备注", 24), ("检查人", 14),
    ("下发时间", 22), ("回读时间", 22), ("下发帧(hex)", 46), ("回读帧(hex)", 46),
]

_VERDICT_ZH = {"pending": "待检", "pass": "通过", "fail": "不通过", "manual": "人工判定"}


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "ON" if v else "OFF"
    return str(v)


def export_xlsx(session: dict) -> bytes:
    """生成对点表 xlsx（逐点一行 + 会话信息表头 + 汇总行）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "对点验收记录"

    ws.append(["对点 / 传动验收记录"])
    ws.append(["会话", session.get("name", "")])
    ws.append(["会话 ID", session.get("id", "")])
    ws.append(["检查人", session.get("operator", "")])
    ws.append(["创建时间", _fmt_ts(session.get("created_at", 0))])
    ws.append(["开始时间", _fmt_ts(session.get("started_at", 0))])
    ws.append(["结束时间", _fmt_ts(session.get("finished_at", 0))])
    s = session.get("summary", {})
    ws.append(["汇总", f"共 {s.get('total', 0)} 点："
                       f"通过 {s.get('pass', 0)} / 不通过 {s.get('fail', 0)} / "
                       f"人工 {s.get('manual', 0)} / 待检 {s.get('pending', 0)}"])
    ws.append([])

    header = len(ws["A"]) + 1
    ws.append([c[0] for c in _XLSX_COLUMNS])
    for idx, (_name, width) in enumerate(_XLSX_COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=header, column=idx).column_letter].width = width

    for n, it in enumerate(session.get("items", []), start=1):
        ws.append([
            n, it.get("ioa"), it.get("name", ""), it.get("kind", ""),
            it.get("group", ""), _fmt(it.get("expected")), _fmt(it.get("actual")),
            it.get("quality", ""), _VERDICT_ZH.get(it.get("verdict"), it.get("verdict", "")),
            it.get("reason", ""), it.get("note", ""), it.get("operator", ""),
            _fmt_ts(it.get("tx_time", 0)), _fmt_ts(it.get("rx_time", 0)),
            it.get("tx_frame", ""), it.get("rx_frame", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_json(session: dict) -> str:
    return json.dumps(session, ensure_ascii=False, indent=2)


def export_html(session: dict) -> str:
    """自包含 HTML 报告（浏览器打印即 PDF）。"""
    e = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    s = session.get("summary", {})
    rows = []
    for n, it in enumerate(session.get("items", []), start=1):
        verdict = it.get("verdict", "")
        cls = {"pass": "ok", "fail": "bad", "manual": "warn"}.get(verdict, "")
        rows.append(
            "<tr>"
            f"<td>{n}</td><td>{e(it.get('ioa'))}</td><td>{e(it.get('name'))}</td>"
            f"<td>{e(it.get('kind'))}</td><td>{e(_fmt(it.get('expected')))}</td>"
            f"<td>{e(_fmt(it.get('actual')))}</td><td>{e(it.get('quality'))}</td>"
            f"<td class='{cls}'>{e(_VERDICT_ZH.get(verdict, verdict))}</td>"
            f"<td>{e(it.get('reason'))}</td><td>{e(it.get('note'))}</td>"
            f"<td>{e(it.get('operator'))}</td>"
            f"<td>{e(_fmt_ts(it.get('tx_time', 0)))}</td>"
            f"<td>{e(_fmt_ts(it.get('rx_time', 0)))}</td>"
            f"<td class='mono'>{e(it.get('tx_frame',''))[:120]}</td>"
            f"<td class='mono'>{e(it.get('rx_frame',''))[:120]}</td>"
            "</tr>"
        )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>对点 / 传动验收记录 — {e(session.get('name',''))}</title>
<style>
@page {{ size: A4 landscape; margin: 12mm; }}
body {{ font-family: "Microsoft YaHei", "Segoe UI", sans-serif; color: #161616; margin: 0; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }}
.meta {{ color: #525252; font-size: 12px; line-height: 1.7; margin-bottom: 12px; }}
.summary {{ background: #f4f4f4; border-left: 4px solid #0f62fe; padding: 8px 12px;
  font-size: 13px; margin-bottom: 14px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
th, td {{ border: 1px solid #c6c6c6; padding: 4px 6px; text-align: left;
  vertical-align: top; word-break: break-all; }}
th {{ background: #e0e0e0; white-space: nowrap; }}
td.ok {{ color: #0e6027; font-weight: 600; }}
td.bad {{ color: #a2191f; font-weight: 600; }}
td.warn {{ color: #8e6a00; font-weight: 600; }}
.mono {{ font-family: Consolas, monospace; font-size: 9px; color: #525252;
  max-width: 150px; }}
.foot {{ margin-top: 16px; font-size: 11px; color: #6f6f6f; }}
</style></head><body>
<h1>对点 / 传动验收记录</h1>
<div class="meta">
会话：{e(session.get('name',''))}　ID：{e(session.get('id',''))}<br>
检查人：{e(session.get('operator',''))}
创建：{e(_fmt_ts(session.get('created_at',0)))}
开始：{e(_fmt_ts(session.get('started_at',0)))}
结束：{e(_fmt_ts(session.get('finished_at',0)))}
状态：{e(session.get('status',''))}
</div>
<div class="summary">共 <b>{s.get('total',0)}</b> 点　通过 <b>{s.get('pass',0)}</b>
不通过 <b>{s.get('fail',0)}</b>　人工判定 <b>{s.get('manual',0)}</b>
待检 <b>{s.get('pending',0)}</b></div>
<table><thead><tr>
<th>#</th><th>IOA</th><th>名称</th><th>类型</th><th>期望</th><th>实测</th><th>品质</th>
<th>结论</th><th>失败原因</th><th>备注</th><th>检查人</th><th>下发时间</th>
<th>回读时间</th><th>下发帧 hex</th><th>回读帧 hex</th>
</tr></thead><tbody>{''.join(rows) or '<tr><td colspan="15">无记录</td></tr>'}</tbody></table>
<div class="foot">由 iec104-tester 自动生成；本文件自包含，浏览器「打印 → 另存为 PDF」即可归档交付。
逐点证据帧为原始 HEX（此处截断显示 120 字符，完整帧见 xlsx / json 导出）。</div>
</body></html>"""


def export(session: dict, fmt: str) -> tuple[bytes, str, str]:
    """按格式导出，返回 ``(body, content_type, filename_suffix)``。"""
    f = (fmt or "xlsx").lower()
    if f == "xlsx":
        return export_xlsx(session), \
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    if f == "json":
        return export_json(session).encode("utf-8"), "application/json", "json"
    if f == "html":
        return export_html(session).encode("utf-8"), "text/html", "html"
    raise ValueError(f"unsupported format: {fmt}")
