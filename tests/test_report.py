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
