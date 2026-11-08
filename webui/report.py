"""会话测试报告生成器（T75）——自包含 HTML（浏览器「打印 → 另存为 PDF」即可交付）.

纯函数、零第三方依赖：输入当前会话快照（status + 帧缓冲 + 事件缓冲），
输出一份内联 CSS 的单文件 HTML。帧证据表逐帧解码 APCI/ASDU 摘要
（解析失败的帧回退 raw，绝不抛出——报告是观察产物，不能因脏帧失败）。
"""

from __future__ import annotations

import html
import time
from collections import Counter
from typing import Any

from core.protocol.apci import APCICodec
from core.version import __version__

_MAX_NOTES = 2000
_MAX_EVENT_ROWS = 50


def _escape(v: Any) -> str:
    return html.escape(str(v), quote=True)


def _frame_summary(frame_hex: str) -> dict:
    """HEX → (帧型, 类型/COT 摘要)；解析失败回退占位."""
    try:
        data = bytes.fromhex(frame_hex)
        apci, _ = APCICodec.decode(data)
        kind = apci.frame_type.name
        if kind == "I" and len(data) > 6:
            try:
                from core.protocol.asdu import ASDU

                asdu = ASDU.decode(data[6:], ca_length=2)
                return {
                    "kind": kind,
                    "detail": f"{asdu.type_id.name} ca={asdu.common_addr} "
                              f"cot={asdu.cot}",
                }
            except Exception:  # noqa: BLE001 — 摘要尽力而为
                return {"kind": kind, "detail": "—"}
        if kind == "U":
            return {"kind": kind, "detail": f"func=0x{apci.u_func:02X}"}
        return {"kind": kind, "detail": f"rx={apci.rx_seq}"}
    except Exception:  # noqa: BLE001 — 脏帧回退
        return {"kind": "?", "detail": "raw"}


def _agg(frames: list[dict]) -> dict:
    """帧缓冲聚合：方向/帧型/ASDU 类型分布."""
    by_dir: Counter = Counter()
    by_kind: Counter = Counter()
    by_type: Counter = Counter()
    for f in frames:
        data = f.get("data") or {}
        by_dir[data.get("direction") or "?"] += 1
        info = _frame_summary(data.get("hex") or "")
        by_kind[info["kind"]] += 1
        if info["kind"] == "I":
            # 类型名取 detail 首段（C_IC_NA_1 ca=1 cot=6）
            by_type[info["detail"].split(" ")[0]] += 1
    return {
        "total": len(frames),
        "by_dir": dict(by_dir),
        "by_kind": dict(by_kind),
        "top_types": by_type.most_common(10),
    }


def build_session_report_html(
    role: str,
    status: dict,
    frames: list[dict],
    events: list[dict],
    *,
    title: str = "",
    notes: str = "",
    max_frames: int = 300,
    loadtest_summary: dict | None = None,
) -> str:
    """生成自包含 HTML 测试报告.

    Args:
        role: 会话角色（master/slave/bridge）.
        status: ``EngineBridge.status()`` 快照.
        frames: ``bus.recent("frame", N)`` 信封列表（新→旧或旧→新均可，按 ts 排序）.
        events: ``bus.recent("event", N)`` 信封列表.
        title: 报告标题（缺省「IEC 60870-5-104 测试报告」）.
        notes: 用户备注（纯文本，转义后输出）.
        max_frames: 帧证据表最大行数（防十万帧撑爆单文件）.
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = sorted(frames, key=lambda f: f.get("ts") or 0)
    agg = _agg(rows)
    evidence = rows[-max_frames:]
    ev_counter = Counter((e.get("data") or {}).get("type") or "?" for e in events)
    notes = (notes or "").strip()[:_MAX_NOTES]

    dir_str = "、".join(f"{k}×{v}" for k, v in sorted(agg["by_dir"].items()))
    kind_str = "、".join(f"{k}×{v}" for k, v in sorted(agg["by_kind"].items()))
    type_str = "、".join(f"{t}×{n}" for t, n in agg["top_types"]) or "—"
    ev_str = "、".join(f"{k}×{v}" for k, v in sorted(ev_counter.items())) or "—"

    def _row(f: dict) -> str:
        data = f.get("data") or {}
        ts = time.strftime("%H:%M:%S", time.localtime(f.get("ts") or 0))
        info = _frame_summary(data.get("hex") or "")
        hexv = data.get("hex") or ""
        shown = hexv[:64] + ("…" if len(hexv) > 64 else "")
        direction = "主站→子站" if data.get("direction") == "tx" else "子站→主站"
        return ("<tr>"
                f"<td>{_escape(ts)}</td>"
                f"<td>{_escape(direction)}</td>"
                f"<td>{_escape(info['kind'])}</td>"
                f"<td>{_escape(info['detail'])}</td>"
                f"<td class=n>{data.get('len', 0)}</td>"
                f"<td class=mono>{_escape(shown)}</td>"
                "</tr>")

    def _ev_row(e: dict) -> str:
        ts = time.strftime("%H:%M:%S", time.localtime(e.get("ts") or 0))
        data = e.get("data") or {}
        msg = data.get("data")
        msg_s = _escape(msg if isinstance(msg, str) else str(msg))[:120]
        return (f"<tr><td>{_escape(ts)}</td>"
                f"<td>{_escape(data.get('type') or '')}</td>"
                f"<td>{msg_s}</td></tr>")

    evidence_html = ("".join(_row(f) for f in evidence)
                     or "<tr><td colspan=6>缓冲内无帧</td></tr>")
    events_html = ("".join(_ev_row(e) for e in events[-_MAX_EVENT_ROWS:][::-1])
                   or "<tr><td colspan=3>缓冲内无事件</td></tr>")
    loadtest_html = ""
    if loadtest_summary:
        lt_rows = "".join(
            f"<tr><td>{_escape(k)}</td><td class=n>{_escape(v)}</td></tr>"
            for k, v in sorted(loadtest_summary.items())
            if not k.startswith("target_") and not k.startswith("duration_"))
        loadtest_html = (f"<h2>5. 压测汇总</h2>"
                         f'<table class=meta>{lt_rows}</table>'
                         "<p class=foot>压测口径：子站按目标速率自发事件，主站侧差分统计。</p>")
    notes_html = f"<p class=notes><b>备注：</b>{_escape(notes)}</p>" if notes else ""

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{_escape(title or "IEC 60870-5-104 测试报告")}</title>
<style>
  body {{ font-family: "IBM Plex Sans", "Microsoft YaHei", sans-serif;
         margin: 32px auto; max-width: 1100px; color: #161616; font-size: 14px; }}
  h1 {{ font-size: 20px; border-bottom: 2px solid #0f62fe; padding-bottom: 8px; }}
  h2 {{ font-size: 16px; margin-top: 28px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
  th, td {{ border: 1px solid #c6c6c6; padding: 4px 8px; text-align: left;
           font-size: 13px; word-break: break-all; }}
  th {{ background: #f4f4f4; }}
  td.n {{ text-align: right; }}
  td.mono, .mono {{ font-family: "IBM Plex Mono", Consolas, monospace; font-size: 12px; }}
  .meta td:first-child {{ width: 160px; background: #f4f4f4; font-weight: 600; }}
  .notes {{ background: #edf5ff; border-left: 3px solid #0f62fe; padding: 8px 12px; }}
  .foot {{ margin-top: 32px; font-size: 12px; color: #6f6f6f; }}
  @media print {{ body {{ margin: 8mm; }} h2 {{ page-break-after: avoid; }} }}
</style></head><body>
<h1>{_escape(title or "IEC 60870-5-104 测试报告")}</h1>
<p class=mono>生成时间 {now} ｜ 生成器 iec104-tester {__version__}</p>
{notes_html}
<h2>1. 会话信息</h2>
<table class=meta>
  <tr><td>角色</td><td>{_escape(role)}</td></tr>
  <tr><td>地址 / 端口 / 公共地址</td><td>{_escape(status.get("host") or "—")} : {_escape(status.get("port") or "—")} / {_escape(status.get("addr") or "—")}</td></tr>
  <tr><td>运行状态</td><td>{_escape("运行中" if status.get("running") else "未运行")}（started={_escape(status.get("started"))}）</td></tr>
  <tr><td>点表点数</td><td>{_escape(status.get("points", 0))}</td></tr>
  <tr><td>契约版本</td><td>{_escape(status.get("schemaVersion", "—"))}</td></tr>
</table>
<h2>2. 帧统计（缓冲窗口内）</h2>
<table class=meta>
  <tr><td>帧总数</td><td>{agg["total"]}</td></tr>
  <tr><td>方向分布</td><td>{_escape(dir_str)}</td></tr>
  <tr><td>帧型分布</td><td>{_escape(kind_str)}</td></tr>
  <tr><td>ASDU 类型 Top10</td><td>{_escape(type_str)}</td></tr>
  <tr><td>事件类型分布</td><td>{_escape(ev_str)}</td></tr>
</table>
<h2>3. 帧证据（最近 {min(max_frames, agg["total"])} 条 / 共 {agg["total"]} 条）</h2>
<table>
  <tr><th>时间</th><th>方向</th><th>帧型</th><th>类型 / COT</th><th>长度</th><th>报文 (HEX)</th></tr>
  {evidence_html}
</table>
<h2>4. 事件（最近 {_MAX_EVENT_ROWS} 条）</h2>
<table>
  <tr><th>时间</th><th>类型</th><th>内容</th></tr>
  {events_html}
</table>
{loadtest_html}
<p class=foot>由 iec104-tester 自动生成；本文件自包含（无外部引用），浏览器「打印 → 另存为 PDF」即可归档交付。</p>
</body></html>"""
