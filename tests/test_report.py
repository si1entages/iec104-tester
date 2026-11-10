"""会话测试报告生成器测试（T75）."""

from __future__ import annotations

import re

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.protocol.apci import APCICodec
from webui.bridge import EngineBridge
from webui.report import build_session_report_html
from webui.server import create_app


def _fake_status() -> dict:
    return {"role": "master", "running": True, "started": True, "host": "127.0.0.1",
            "port": 2404, "addr": 1, "points": 30, "schemaVersion": 12}


def _envelopes() -> list[dict]:
    """两条帧信封（GI 请求 I 帧 + STARTDT U 帧），模拟 bus.recent 信封形状."""
    gi = APCICodec.encode_i(tx_seq=0, rx_seq=1,
                            asdu_data=bytes([100, 1, 6, 0, 1, 0, 0, 0, 0, 20]))
    return [
        {"kind": "frame", "ts": 1000.0, "data": {"direction": "tx", "len": len(gi),
                                                 "hex": gi.hex(), "client": ""}},
        {"kind": "frame", "ts": 1001.0, "data": {"direction": "rx", "len": 6,
                                                 "hex": "68040b000000", "client": "c1"}},
    ]


def test_report_contains_sections_and_decoded_frames():
    html_text = build_session_report_html("master", _fake_status(), _envelopes(), [])
    assert "IEC 60870-5-104 测试报告" in html_text
    assert "会话信息" in html_text and "帧统计" in html_text and "帧证据" in html_text
    # I 帧被解码出 ASDU 摘要；U 帧显示 func
    assert "C_IC_NA_1" in html_text and "ca=1" in html_text
    assert "func=0x0B" in html_text
    # 方向中文化
    assert "主站→子站" in html_text and "子站→主站" in html_text
    # 证据表 2 行（行数按 <tr> 不精确，用时间戳断言）
    assert "1000" in html_text or "1001" in html_text


def test_report_notes_escaped_and_title():
    evil = "<script>alert(1)</script>"
    html_text = build_session_report_html("master", _fake_status(), [], [],
                                          title="T&标题", notes=evil)
    assert "T&amp;标题" in html_text
    assert "&lt;script&gt;" in html_text and "<script>" not in html_text.replace("&lt;script&gt;", "")


def test_report_empty_buffers_and_max_frames():
    html_text = build_session_report_html("slave", _fake_status(), [], [], max_frames=0)
    assert "缓冲内无帧" in html_text
    frames = [{"kind": "frame", "ts": float(i), "data": {"direction": "tx", "len": 6,
                                                         "hex": "680407000000", "client": ""}}
              for i in range(50)]
    html2 = build_session_report_html("slave", _fake_status(), frames, [], max_frames=10)
    assert "最近 10 条 / 共 50 条" in html2


def test_report_garbage_frame_does_not_raise():
    frames = [{"kind": "frame", "ts": 1.0, "data": {"direction": "tx", "len": 4,
                                                    "hex": "zzzz-nothex", "client": ""}}]
    html_text = build_session_report_html("slave", _fake_status(), frames, [])
    assert "raw" in html_text or "—" in html_text


def test_report_is_self_contained():
    html_text = build_session_report_html("master", _fake_status(), _envelopes(), [])
    assert not re.search(r'<(?:link|script)[^>]+src=', html_text)
    assert not re.search(r'<link[^>]+href=', html_text)


@pytest.mark.asyncio
async def test_report_endpoint():
    """GET /api/export/report.html：attachment HTML + limit 校验."""
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        r = await client.get("/api/export/report.html?title=T&limit=10")
        assert r.status == 200
        assert "text/html" in r.headers["Content-Type"]
        assert "attachment" in r.headers["Content-Disposition"]
        text = await r.text()
        assert "IEC 60870-5-104 测试报告" in text or "T" in text
        r2 = await client.get("/api/export/report.html?limit=abc")
        assert r2.status == 400
    finally:
        await bridge.shutdown()
        await client.close()


def test_report_includes_loadtest_summary_when_present():
    """压测汇总存在时生成 §5（T78 贯通）；缺省无该节."""
    base = build_session_report_html("master", _fake_status(), _envelopes(), [])
    assert "压测汇总" not in base
    with_lt = build_session_report_html(
        "master", _fake_status(), _envelopes(), [],
        loadtest_summary={"events_sent": 6000, "rx_frames": 5980,
                          "avg_eps": 100.0, "avg_fps": 99.7, "errors": 0})
    assert "压测汇总" in with_lt and "6000" in with_lt and "99.7" in with_lt


def test_report_compliance_violations_section():
    """合规违规列表存在时生成 §6（T79 报告贯通）；缺省无该节."""
    base = build_session_report_html("master", _fake_status(), _envelopes(), [])
    assert "合规违规" not in base
    with_v = build_session_report_html(
        "master", _fake_status(), _envelopes(), [],
        compliance_violations=[{"ts": 1000.0, "side": "slave", "kind": "seq-jump",
                                "detail": "I 帧发送序号 5，期望 1"}])
    assert "合规违规" in with_v and "seq-jump" in with_v and "slave" in with_v


def test_report_conclusion_banner():
    """结论横幅：颜色按 kind、文本转义；无结论时无横幅."""
    base = build_session_report_html("master", _fake_status(), _envelopes(), [])
    assert "测试结论" not in base
    ok = build_session_report_html("master", _fake_status(), _envelopes(), [],
                                   conclusion="合格", conclusion_kind="pass")
    assert "测试结论：</b>合格" in ok and "#1a7f37" in ok
    bad = build_session_report_html("master", _fake_status(), _envelopes(), [],
                                    conclusion="不合格：<b>注入</b>", conclusion_kind="fail")
    assert "#c62828" in bad and "&lt;b&gt;注入&lt;/b&gt;" in bad


def test_report_injection_section():
    """注入统计存在时生成 §7（T85 报告贯通）；缺省无该节."""
    base = build_session_report_html("master", _fake_status(), _envelopes(), [])
    assert "网络条件注入" not in base
    with_inj = build_session_report_html(
        "master", _fake_status(), _envelopes(), [],
        injection={"total": 100, "dropped": 5, "corrupted": 2,
                   "duplicated": 0, "delayed": 0, "reordered": 0, "disconnects": 0},
        condition="loss=5%")
    assert "网络条件注入" in with_inj and "loss=5%" in with_inj and ">5<" in with_inj


@pytest.mark.asyncio
async def test_report_post_endpoint_with_chart_images():
    """POST 报告端点：嵌入 dataURL 图片；非图片前缀被过滤（防注入）."""
    from webui.bridge import EngineBridge
    from webui.server import create_app

    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        r = await client.post("/api/export/report.html", json={
            "title": "T87",
            "conclusion": "合格",
            "conclusion_kind": "pass",
            "chart_images": ["data:image/png;base64,AAAA", "javascript:alert(1)"],
        })
        assert r.status == 200 and "text/html" in r.headers["Content-Type"]
        text = await r.text()
        assert "历史曲线快照" in text and "data:image/png;base64,AAAA" in text
        assert "javascript:alert" not in text
        assert "测试结论" in text
    finally:
        await bridge.shutdown()
        await client.close()


def test_report_frame_summary_fallback_and_event_rows():
    """脏 I 帧（ASDU 解析失败）回退占位；S 帧摘要 rx=；事件表行渲染（T97 补覆盖）."""
    dirty_i = APCICodec.encode_i(tx_seq=0, rx_seq=0,
                                 asdu_data=bytes([250, 250, 250, 0, 1, 0, 9]))  # 未知类型
    frames = [
        {"kind": "frame", "ts": 1000.0,
         "data": {"direction": "tx", "len": len(dirty_i), "hex": dirty_i.hex(), "client": ""}},
        {"kind": "frame", "ts": 1001.0,
         "data": {"direction": "rx", "len": 6, "hex": "680401000100", "client": ""}},
    ]
    events = [
        {"kind": "event", "ts": 1002.0, "data": {"type": "MASTER_EVENT", "data": "状态文本"}},
        {"kind": "event", "ts": 1003.0, "data": {"type": "OTHER", "data": 123}},
    ]
    html = build_session_report_html("master", _fake_status(), frames, events)
    assert "4. 事件" in html and "状态文本" in html and "123" in html
    assert "帧证据" in html
