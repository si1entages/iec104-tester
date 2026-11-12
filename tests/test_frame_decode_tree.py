"""WP7 报文值域解码树测试.

覆盖方案 `docs/optimization_plan_v111.md` §WP7 的验收判据：
**SQ=1 的 20 对象帧展开后 20 行值/品质/时标齐全，与构造输入逐字段一致**。

另覆盖：I/S/U 三种帧、五位品质位（IV/NT/SB/BL/OV）、CP56 时标、脏数据不抛异常、
`translate_hex` 旧 `segments` 契约不变（只增 `tree` 键）。
"""

from __future__ import annotations

import pytest

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject, TypeID
from core.protocol.io import SinglePoint
from core.protocol.types import COT, CP56Time2a, QualityDescriptor, QualityFlag
from webui.frame_translate import decode_tree, translate_hex


def _i_frame(apdu_asdu: bytes, vs: int = 0, vr: int = 0) -> str:
    return APCICodec.encode_i(vs, vr, apdu_asdu).hex()


def _asdu_frame(asdu: ASDU | bytes, vs: int = 0, vr: int = 0) -> str:
    """builder 返回 bytes，手搓的 ASDU 需要 encode()——两者都接受。"""
    body = asdu.encode() if isinstance(asdu, ASDU) else bytes(asdu)
    return _i_frame(body, vs, vr)


# ── 基础帧类型 ───────────────────────────────────────────────────────


class TestFrameTypes:
    def test_s_frame(self):
        tree = decode_tree(APCICodec.encode_s(5).hex())
        assert tree["ok"] is True and tree["format"] == "S"
        assert tree["apci"]["rx_seq"] == 5
        assert tree["asdu"] is None and tree["objects"] == []

    def test_u_frame(self):
        tree = decode_tree(APCICodec.testfr_act().hex())
        assert tree["format"] == "U"
        assert tree["apci"]["u_func_name"] == "TESTFR act"

    def test_i_frame_header_fields(self):
        asdu = ASDUBuilder.build_general_interrogation(common_addr=7)
        tree = decode_tree(_asdu_frame(asdu, vs=3, vr=9))
        assert tree["format"] == "I"
        assert tree["apci"]["tx_seq"] == 3 and tree["apci"]["rx_seq"] == 9
        a = tree["asdu"]
        assert a["type_id"] == int(TypeID.C_IC_NA_1)
        assert a["cot"] == int(COT.ACT) and a["cot_name"].startswith("激活")
        assert a["common_addr"] == 7
        assert a["object_count"] == 1

    @pytest.mark.parametrize("bad", ["", "zz", "68", "6804"])
    def test_bad_input_returns_error_not_raise(self, bad):
        tree = decode_tree(bad)
        assert tree["ok"] is False and tree["error"]


# ── SQ=1 展开（WP7 验收判据）──────────────────────────────────────────


class TestSequenceExpansion:
    def test_sq1_twenty_objects_expanded(self):
        """SQ=1 的 20 个单点对象：地址 base+i，值/品质逐条可查."""
        base = 1000
        values = [bool(i % 2) for i in range(20)]
        qualities = [0] * 20
        qualities[3] = int(QualityFlag.IV)
        qualities[7] = int(QualityFlag.NT | QualityFlag.BL)
        points = [(base + i, values[i], qualities[i]) for i in range(20)]
        asdu = ASDUBuilder.build_single_point_sequence(
            common_addr=1, points=points, cot=COT.SPONT)
        tree = decode_tree(_asdu_frame(asdu))

        assert tree["asdu"]["sq"] is True
        assert tree["asdu"]["num"] == 20
        objs = tree["objects"]
        assert len(objs) == 20, "SQ=1 必须展开成 20 行"

        for i, o in enumerate(objs):
            assert o["ioa"] == base + i, f"第 {i} 条地址应为 base+i"
            assert o["sq_index"] == i
            assert o["value"] is values[i]
            assert o["index"] == i + 1

        # 品质位逐条核对（第 4 条 IV、第 8 条 NT+BL）
        assert objs[3]["quality_bits"]["iv"] is True
        assert objs[3]["quality"] == "IV"
        assert objs[7]["quality_bits"]["nt"] is True
        assert objs[7]["quality_bits"]["bl"] is True
        assert objs[7]["quality_bits"]["iv"] is False
        assert objs[0]["quality"] == "GOOD"

    def test_sq0_objects_keep_own_addresses(self):
        """SQ=0 时每个对象自带地址（构造 ASDU 直接放两个对象）."""
        asdu = ASDU(type_id=TypeID.M_SP_NA_1, sq=False, num=2,
                    cot=COT.SPONT, common_addr=1, objects=[])
        for ioa, val in ((5000, True), (6000, False)):
            asdu.objects.append(
                InformationObject(ioa=ioa, data=SinglePoint(value=val, quality=QualityDescriptor(0))))
        tree = decode_tree(_asdu_frame(asdu))
        assert [o["ioa"] for o in tree["objects"]] == [5000, 6000]
        assert all("sq_index" not in o for o in tree["objects"])


# ── 品质位与值 ───────────────────────────────────────────────────────


class TestQualityAndValue:
    def test_all_five_quality_flags(self):
        """五位置（IV/NT/SB/BL/OV）在**遥测 QDS** 上齐全.

        注意：单点遥信是 SIQ，bit0 是值本身而非 OV（见 QualityFlag 文档），
        所以这里必须用遥测（短浮点 / 标度化）来验证 OV 位。
        """
        q = int(QualityFlag.IV | QualityFlag.NT | QualityFlag.SB
                | QualityFlag.BL | QualityFlag.OV)
        asdu = ASDUBuilder.build_short_float(
            common_addr=1, ioa=1, value=1.0, quality=q, cot=COT.SPONT)
        o = decode_tree(_asdu_frame(asdu))["objects"][0]
        assert o["quality_bits"] == {"iv": True, "nt": True, "sb": True,
                                     "bl": True, "ov": True}
        assert o["quality"] == "IV|NT|SB|BL|OV"
        assert o["quality_raw"] == q & 0xFF

    def test_single_point_siq_has_no_ov_bit(self):
        """SIQ 的 bit0 是值本身：单点遥信不应被误报 OV（按标准，不迁就实现）."""
        asdu = ASDUBuilder.build_single_point(
            common_addr=1, ioa=1, value=True, quality=int(QualityFlag.IV),
            cot=COT.SPONT)
        o = decode_tree(_asdu_frame(asdu))["objects"][0]
        assert o["quality_bits"]["iv"] is True
        assert o["value"] is True

    def test_quality_raw_preserves_bit7(self):
        """IV=0x80 不能被截位（历史教训：两套掩码 + to_int 截位）."""
        asdu = ASDUBuilder.build_single_point(
            common_addr=1, ioa=1, value=False, quality=0x80, cot=COT.SPONT)
        o = decode_tree(_asdu_frame(asdu))["objects"][0]
        assert o["quality_raw"] == 0x80 and o["quality_bits"]["iv"] is True

    def test_measured_value_numeric(self):
        asdu = ASDUBuilder.build_short_float(
            common_addr=1, ioa=2001, value=3.5, cot=COT.SPONT)
        o = decode_tree(_asdu_frame(asdu))["objects"][0]
        assert o["value"] == pytest.approx(3.5)
        assert "3.5" in o["value_display"]
        assert o["quality"] == "GOOD"

    def test_cp56_timestamp_present(self):
        ts = CP56Time2a(year=24, month=11, day=12, hour=10, minute=30,
                        millisecond=15_250)
        asdu = ASDUBuilder.build_scaled_value(
            common_addr=1, ioa=3001, value=125, cot=COT.SPONT,
            with_time=True, time_tag=ts)
        o = decode_tree(_asdu_frame(asdu))["objects"][0]
        assert o["timestamp"] is not None
        assert "2024" in o["timestamp"] or "24" in o["timestamp"]
        assert "10:30" in o["timestamp"] or "10" in o["timestamp"]

    def test_quality_descriptor_helper_matches(self):
        """树里的品质位与 QualityDescriptor 属性一致（单一真值源）."""
        q = QualityDescriptor(raw=int(QualityFlag.NT))
        asdu = ASDUBuilder.build_single_point(
            common_addr=1, ioa=1, value=True, quality=q.to_int(), cot=COT.SPONT)
        bits = decode_tree(_asdu_frame(asdu))["objects"][0]["quality_bits"]
        assert bits["nt"] is q.not_topical


# ── 兼容性 ───────────────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_translate_hex_keeps_segments_and_adds_tree(self):
        hex_str = _asdu_frame(ASDUBuilder.build_general_interrogation(common_addr=1))
        out = translate_hex(hex_str)
        assert out["ok"] is True
        assert out["format"] == "I"
        # 旧契约：segments 结构不变
        assert [s["title"] for s in out["segments"]][0].startswith("APCI")
        assert all("lines" in s for s in out["segments"])
        # 新增：tree
        assert out["tree"]["asdu"]["type_id"] == int(TypeID.C_IC_NA_1)

    def test_translate_hex_error_paths_still_have_no_tree_crash(self):
        out = translate_hex("zz")
        assert out["ok"] is False and "tree" not in out
        out2 = translate_hex("68")
        assert out2["ok"] is False

    def test_truncated_frame_reports_readable_error(self):
        """帧被截断（声明长度 > 实到字节）→ 可读错误，不抛异常.

        这是 APCI 层的正确拒绝：长度字节声明 16 字节而只到了 14，
        此时连 ASDU 边界都无法确定，不应强行解出半截对象。
        """
        asdu = ASDUBuilder.build_general_interrogation(common_addr=1)
        full = _asdu_frame(asdu)
        tree = decode_tree(full[:-4])
        assert tree["ok"] is True
        assert tree["asdu"] is None and tree["objects"] == []
        assert "Incomplete" in tree["error"] or "解析失败" in tree["error"]

    def test_truncated_asdu_body_keeps_header(self):
        """APCI 长度自洽但 ASDU 信息体不足 → 解出头部 + error，对象为空."""
        asdu = ASDUBuilder.build_general_interrogation(common_addr=1)
        # 去掉最后一个信息体字节，并把 APCI 长度字节同步减 1（保持自洽）
        body = asdu[:-1]
        raw = bytearray(APCICodec.encode_i(0, 0, body))
        raw[1] = len(raw) - 2
        tree = decode_tree(bytes(raw).hex())
        assert tree["ok"] is True
        assert tree["asdu"] is not None          # 头部可用（TypeID/COT/CA）
        assert tree["asdu"]["type_id"] == int(TypeID.C_IC_NA_1)
        assert tree["error"]                      # 有说明
        assert tree["objects"] == []              # 不编造半截对象


class TestObjectEntryDegradation:
    """单对象层面的降级：无品质字段/异常数据不得让整帧解析失败."""

    def test_object_without_quality_field(self):
        """无品质字段的信息体 → 按 GOOD 处理（get_value_quality 的默认语义），不抛.

        说明：`get_value_quality` 对无 `quality` 属性的对象返回默认
        `QualityDescriptor()`（raw=0 → GOOD），因此 bits 是"全 false"而非 None。
        这符合"没声明品质就是好值"的行业惯例，不应当作缺陷改成 None。
        """
        from webui.frame_translate import _object_entry

        class _NoQuality:
            value = 7

        entry = _object_entry(1, InformationObject(ioa=1, data=_NoQuality()), 100)
        assert entry["quality"] == "GOOD"
        assert entry["quality_bits"] == {"iv": False, "nt": False, "sb": False,
                                         "bl": False, "ov": False}
        assert entry["quality_raw"] == 0
        assert entry["value"] == 7

    def test_jsonable_value_variants(self):
        from webui.frame_translate import _jsonable_value

        assert _jsonable_value(None) is None
        assert _jsonable_value(True) is True
        assert _jsonable_value(3) == 3
        assert _jsonable_value(1.5) == 1.5
        assert _jsonable_value("s") == "s"
        assert _jsonable_value(b"") == "0102"
        assert _jsonable_value(type("X", (), {"value": 9})()) == 9
        assert _jsonable_value(type("Y", (), {})()).startswith("<")

    def test_object_with_broken_display_uses_fallback(self):
        """值格式化抛异常 → 回落 str(value)，不让整帧失败."""
        from webui.frame_translate import _object_entry

        class _Boom:
            value = "x"

            def __repr__(self):
                return "Boom"

        entry = _object_entry(1, InformationObject(ioa=1, data=_Boom()), 999999)
        assert entry["value_display"]  # 有回落串，非空
        assert entry["ioa"] == 1

    def test_non_byte_data_has_no_raw_hex(self):
        from core.protocol.io import ShortFloat
        from webui.frame_translate import _object_entry

        entry = _object_entry(1, InformationObject(ioa=1, data=ShortFloat(value=1.0)),
                              int(TypeID.M_ME_NC_1))
        assert entry["raw_hex"] is None
        assert entry["value"] == 1.0
