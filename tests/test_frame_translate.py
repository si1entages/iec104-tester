"""报文逐段翻译（webui/frame_translate.py + GET /api/frames/decode）单测.

第二批体验改造 ④：悬停翻译的后端能力与端点行为。
"""

from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDUBuilder
from core.protocol.types import COT
from webui.bridge import EngineBridge
from webui.frame_translate import translate_hex
from webui.server import create_app


def _gi_act_frame(ns: int = 2, nr: int = 1) -> bytes:
    """I 帧 + C_IC_NA_1(100) 总召唤激活（QOI=20, CA=1, IOA=0）."""
    asdu = ASDUBuilder.build_general_interrogation(1, qoi=20, cot=COT.ACT)
    return APCICodec.encode_i(ns, nr, asdu)


def test_i_frame_segments():
    r = translate_hex(_gi_act_frame().hex())
    assert r["ok"] is True
    assert r["format"] == "I"
    titles = [s["title"] for s in r["segments"]]
    assert any("APCI" in t for t in titles)
    assert any("C_IC_NA_1" in t for t in titles)
    apci = r["segments"][0]["lines"]
    assert any("I 帧" in ln and "VS=2" in ln and "VR=1" in ln for ln in apci)
    asdu_seg = r["segments"][1]["lines"]
    assert any("C_IC_NA_1(100)" in ln and "COT=6" in ln and "激活" in ln for ln in asdu_seg)
    assert any("公共地址 1" in ln for ln in asdu_seg)
    assert any("QOI=20" in ln and "站召唤" in ln for ln in asdu_seg)


def test_u_frame_segments():
    r = translate_hex(APCICodec.startdt_act().hex())
    assert r["ok"] is True
    assert r["format"] == "U"
    assert any("STARTDT act" in ln for s in r["segments"] for ln in s["lines"])


def test_s_frame_segments():
    r = translate_hex(APCICodec.encode_s(8).hex())
    assert r["ok"] is True
    assert r["format"] == "S"
    assert any("S 帧" in ln and "VR=8" in ln for s in r["segments"] for ln in s["lines"])


def test_yc_frame_with_timestamp():
    """M_ME_TF_1 短浮点带时标：信息体行含值与时标."""
    asdu = ASDUBuilder.build_short_float(1, 101, 25.5, 0, cot=COT.SPONT, with_time=True)
    frame = APCICodec.encode_i(0, 1, asdu)
    r = translate_hex(frame.hex())
    io_lines = [ln for s in r["segments"] for ln in s["lines"] if ln.startswith("信息体")]
    assert io_lines, io_lines
    assert any("IOA 101" in ln and "25.5000" in ln and "时标" in ln for ln in io_lines)


def test_invalid_inputs():
    assert translate_hex("zz")["ok"] is False
    assert translate_hex("6804")["ok"] is False
    assert translate_hex("")["ok"] is False


def test_truncated_asdu_does_not_raise():
    """ASDU 体不完整（长度字段撒谎）也不应抛异常，只记备注段."""
    frame = bytearray(_gi_act_frame())
    frame[1] = 200  # 声称 ASDU 巨长
    r = translate_hex(bytes(frame).hex())
    assert r["ok"] is True


@pytest.mark.asyncio
async def test_frames_decode_endpoint():
    bridge = EngineBridge("master")
    try:
        client = TestClient(TestServer(create_app(bridge)))
        await client.start_server()
        try:
            # 正常帧
            r = await client.get("/api/frames/decode", params={"hex": _gi_act_frame().hex()})
            assert r.status == 200
            body = await r.json()
            assert body["ok"] is True
            assert body["format"] == "I"
            # 契约 §2.9 锁定为扁平结构：前端曾误读 r.translation 导致恒报「翻译失败」。
            # WP7 起额外带 tree（结构化树），故断言「必含三键 + 无 translation 包裹」。
            assert {"ok", "format", "segments"} <= set(body)
            assert "translation" not in body
            assert body.get("tree") is not None

            # 非法 hex → ok=false（HTTP 200，业务错误走 ok 字段）
            r = await client.get("/api/frames/decode", params={"hex": "zz"})
            assert r.status == 200
            assert (await r.json())["ok"] is False

            # 缺 hex → 400
            r = await client.get("/api/frames/decode")
            assert r.status == 400

            # 超长 → 400
            r = await client.get("/api/frames/decode", params={"hex": "68" * 3000})
            assert r.status == 400
        finally:
            await client.close()
    finally:
        import asyncio

        try:
            await asyncio.wait_for(bridge.shutdown(), timeout=2)
        except Exception:
            pass
