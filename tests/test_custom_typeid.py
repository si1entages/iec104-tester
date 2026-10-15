"""自定义（非标准）TypeID 编解码测试（T22）.

覆盖：往返正确、YAML/JSON 配置装载、标准类型不受影响、未注册类型仍走错误应答。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.engine.slave import SlaveEngine
from core.protocol.apci import APCICodec
from core.protocol.asdu import (
    ASDU,
    CUSTOM_TYPES,
    ASDUBuilder,
    CustomField,
    CustomObject,
    CustomTypeDef,
    InformationObject,
)
from core.protocol.types import COT, CP24Time2a, CP56Time2a, TypeID

# 本代码库已定义 71/108/109/128/129（分别对应 M_PS_TB_1/C_TS_NB_1/P_ME_ND_1/
# F_FR_NB_1/F_SR_NB_1），故测试使用**真正空闲**的 id。
CUSTOM_A = 130
CUSTOM_B = 131
CUSTOM_C = 140


@pytest.fixture(autouse=True)
def _clean_registry():
    CUSTOM_TYPES.clear()
    yield
    CUSTOM_TYPES.clear()


async def _drain(rounds: int = 8) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def _obj(ioa: int, data) -> InformationObject:
    return InformationObject(ioa=ioa, data=data)


def _build(type_id: int, ioa: int, values: dict) -> bytes:
    a = ASDU(type_id=type_id, sq=False, num=1, cot=COT.SPONT, common_addr=1)
    a.objects.append(_obj(ioa, CustomObject(type_id, values)))
    return a.encode()


def _apci_of(frame: bytes):
    apci, _ = APCICodec.decode(frame)
    return apci


# ── 往返 ─────────────────────────────────────────────────────────

class TestRoundtrip:
    def test_basic_roundtrip_and_reencode(self):
        CUSTOM_TYPES.register(CustomTypeDef(
            type_id=CUSTOM_A, name="VendorAlarm",
            fields=[CustomField("level", "u8"), CustomField("value", "i16"),
                    CustomField("qds", "qds")],
        ))
        raw = _build(CUSTOM_A, 5000, {"level": 3, "value": -1234, "qds": 0x80})
        decoded = ASDU.decode(raw)
        assert decoded.type_id == CUSTOM_A
        assert decoded.objects[0].ioa == 5000
        assert decoded.objects[0].data.values == {"level": 3, "value": -1234, "qds": 0x80}
        # 重新编码字节一致（往返稳定）
        assert decoded.encode() == raw

    def test_all_field_types(self):
        CUSTOM_TYPES.register(CustomTypeDef(
            type_id=CUSTOM_A, name="AllFields",
            fields=[
                CustomField("a_u8", "u8"), CustomField("a_i8", "i8"),
                CustomField("a_u16", "u16"), CustomField("a_i16", "i16"),
                CustomField("a_u32", "u32"), CustomField("a_i32", "i32"),
                CustomField("a_f32", "f32"), CustomField("a_f64", "f64"),
                CustomField("a_bool", "bool"), CustomField("a_bytes", "bytes", length=3),
                CustomField("a_ts", "cp56"), CustomField("a_short", "cp24"),
            ],
        ))
        ts = CP56Time2a(millisecond=12345, minute=30, hour=12, day=1, month=6, year=24)
        ts24 = CP24Time2a(millisecond=999, minute=15)
        values = {"a_u8": 200, "a_i8": -100, "a_u16": 60000, "a_i16": -30000,
                  "a_u32": 4000000000, "a_i32": -2000000000,
                  "a_f32": 1.5, "a_f64": 2.25, "a_bool": True,
                  "a_bytes": b"\x01\x02\x03", "a_ts": ts, "a_short": ts24}
        raw = _build(CUSTOM_A, 7, values)
        got = ASDU.decode(raw).objects[0].data.values
        assert got["a_u8"] == 200 and got["a_i8"] == -100
        assert got["a_u16"] == 60000 and got["a_i16"] == -30000
        assert got["a_u32"] == 4000000000 and got["a_i32"] == -2000000000
        assert abs(got["a_f32"] - 1.5) < 1e-6 and abs(got["a_f64"] - 2.25) < 1e-9
        assert got["a_bool"] is True
        assert got["a_bytes"] == b"\x01\x02\x03"
        assert got["a_ts"].minute == 30 and got["a_short"].minute == 15

    def test_multiple_objects(self):
        CUSTOM_TYPES.register(CustomTypeDef(
            type_id=CUSTOM_A, name="Multi", fields=[CustomField("v", "u8")]))
        a = ASDU(type_id=CUSTOM_A, sq=False, num=2, cot=COT.SPONT, common_addr=1)
        for ioa, v in ((10, 1), (11, 2)):
            a.objects.append(_obj(ioa, CustomObject(CUSTOM_A, {"v": v})))
        raw = a.encode()
        decoded = ASDU.decode(raw)
        assert [o.data.values["v"] for o in decoded.objects] == [1, 2]
        assert [o.ioa for o in decoded.objects] == [10, 11]


# ── 配置装载 ─────────────────────────────────────────────────────

class TestConfigLoad:
    def test_load_dict_list_and_mapping_forms(self):
        assert CUSTOM_TYPES.load_dict({"custom_types": [
            {"type_id": CUSTOM_A, "fields": [{"name": "v", "type": "u8"}]}]}) == 1
        assert CUSTOM_TYPES.ids() == [CUSTOM_A]
        CUSTOM_TYPES.clear()
        # 映射式：键即 type_id
        assert CUSTOM_TYPES.load_dict({CUSTOM_B: {"fields": ["x", "y"]}}) == 1
        assert CUSTOM_TYPES.ids() == [CUSTOM_B]
        assert [f.type for f in CUSTOM_TYPES.get(CUSTOM_B).fields] == ["u8", "u8"]

    def test_load_yaml_and_json(self, tmp_path):
        yml = tmp_path / "custom.yaml"
        yml.write_text(
            "custom_types:\n"
            f"  - type_id: {CUSTOM_A}\n"
            "    name: FromYaml\n"
            "    fields:\n"
            "      - {name: v, type: u16}\n",
            encoding="utf-8",
        )
        assert CUSTOM_TYPES.load_yaml(yml) == 1
        assert CUSTOM_TYPES.get(CUSTOM_A).name == "FromYaml"

        CUSTOM_TYPES.clear()
        js = tmp_path / "custom.json"
        js.write_text(json.dumps({str(CUSTOM_B): {"fields": [{"name": "v", "type": "i32"}]}}),
                      encoding="utf-8")
        assert CUSTOM_TYPES.load_json(js) == 1
        assert CUSTOM_TYPES.get(CUSTOM_B).fields[0].type == "i32"

    def test_unregister_and_clear(self):
        CUSTOM_TYPES.load_dict({"custom_types": [
            {"type_id": CUSTOM_A, "fields": ["v"]}]})
        assert CUSTOM_TYPES.unregister(CUSTOM_A) is True
        assert CUSTOM_TYPES.ids() == []
        assert CUSTOM_TYPES.unregister(CUSTOM_A) is False


# ── 校验与边界 ───────────────────────────────────────────────────

class TestValidation:
    def test_standard_type_id_rejected(self):
        # 9 = M_ME_NA_1，标准类型不得被自定义遮蔽
        with pytest.raises(ValueError):
            CUSTOM_TYPES.register(CustomTypeDef(type_id=int(TypeID.M_ME_NA_1),
                                                fields=[CustomField("v", "u8")]))

    def test_unknown_field_type_rejected(self):
        with pytest.raises(ValueError):
            CUSTOM_TYPES.register(CustomTypeDef(
                type_id=CUSTOM_A, fields=[CustomField("v", "u9")]))

    def test_bytes_field_requires_length(self):
        with pytest.raises(ValueError):
            CUSTOM_TYPES.register(CustomTypeDef(
                type_id=CUSTOM_A, fields=[CustomField("v", "bytes", length=0)]))

    def test_truncated_payload_raises(self):
        CUSTOM_TYPES.register(CustomTypeDef(
            type_id=CUSTOM_A, fields=[CustomField("a", "u32")]))
        # 信息体只给 2 字节，不足 4 字节
        raw = bytes([CUSTOM_A, 1, COT.SPONT, 0, 1, 0]) + b"\x0a\x00\x00" + b"\x01\x02"
        with pytest.raises(ValueError):
            ASDU.decode(raw)


# ── 未注册 / 标准类型 ────────────────────────────────────────────

class TestUnregisteredAndStandard:
    def test_unregistered_decode_raises_header_ok(self):
        raw = bytes([CUSTOM_C, 1, COT.SPONT, 0, 1, 0]) + b"\x00" * 6
        with pytest.raises(ValueError):
            ASDU.decode(raw)
        header = ASDU.decode_header(raw)
        assert header.type_id == CUSTOM_C and header.objects == []

    def test_standard_types_unaffected(self):
        # 注册自定义类型后，标准类型编解码不受影响
        CUSTOM_TYPES.register(CustomTypeDef(
            type_id=CUSTOM_A, fields=[CustomField("v", "u8")]))
        for raw in (
            ASDUBuilder.build_short_float(1, 1001, 220.5, 0),
            ASDUBuilder.build_single_point(1, 1, True, 0),
            ASDUBuilder.build_step_position(1, 4001, 5),
        ):
            assert ASDU.decode(raw) is not None
        assert ASDU.decode(ASDUBuilder.build_short_float(1, 1001, 1.0, 0)).type_id \
            == TypeID.M_ME_NC_1


# ── 引擎集成：未注册仍 COT=42；注册后可解码不再报错 ───────────────

def _make_slave():
    with patch("core.engine.slave.TCPServer"):
        engine = SlaveEngine(host="0.0.0.0", port=2404, common_addr=1)
    conn = MagicMock()
    conn.name = "c1"
    conn.is_connected = True
    conn.send_frame = AsyncMock()
    conn.stop = AsyncMock()
    engine._on_client_connected(conn)
    state = engine._client_states["c1"]
    state.data_transfer_enabled = True
    return engine, conn, state


class TestEngineIntegration:
    @pytest.mark.asyncio
    async def test_unregistered_type_still_cot42(self):
        engine, conn, state = _make_slave()
        asdu_data = bytes([CUSTOM_C, 0x01, COT.ACT, 0x00, 0x01, 0x00]) + b"\x00" * 6
        frame = APCICodec.encode_i(0, 0, asdu_data)
        engine._handle_i_frame(state, _apci_of(frame), frame)
        await _drain()

        sent = conn.send_frame.call_args[0][0]
        assert ASDU.decode_header(sent[6:]).cot == COT.UNKNOWN_TYPE

    @pytest.mark.asyncio
    async def test_registered_type_decoded_no_error_reply(self):
        CUSTOM_TYPES.register(CustomTypeDef(
            type_id=CUSTOM_C, fields=[CustomField("level", "u8")]))
        engine, conn, state = _make_slave()
        asdu_data = bytes([CUSTOM_C, 0x01, COT.SPONT, 0x00, 0x01, 0x00]) + b"\x0a\x00\x00" + b"\x03"
        frame = APCICodec.encode_i(0, 0, asdu_data)
        engine._handle_i_frame(state, _apci_of(frame), frame)
        await _drain()

        # 已注册 → 正常解码（无 COT=42 错误应答）
        conn.send_frame.assert_not_called()


# ── 配置接线：configs/*.yaml → AppConfig → CUSTOM_TYPES → 编解码 ──

class TestConfigWiring:
    """配置文件到注册表的端到端路径（app.py 启动流程）."""

    def test_example_config_registers_and_roundtrips(self):
        from core.config import load_config
        example = Path(__file__).parent.parent / "configs" / "custom_types_example.yaml"
        cfg = load_config(example)
        assert cfg.custom_types, "示例配置应含 custom_types"

        count = CUSTOM_TYPES.load_dict({"custom_types": cfg.custom_types})
        assert count == len(cfg.custom_types)
        assert CUSTOM_TYPES.ids() == [130, 131]

        # 130 = VendorAlarm: u8 + i16 + qds + cp56
        ts = CP56Time2a(millisecond=1000, minute=5, hour=8, day=2, month=3, year=25)
        raw = _build(130, 42, {"level": 2, "value": -7, "qds": 0x80, "ts": ts})
        got = ASDU.decode(raw)
        assert got.type_id == 130
        values = got.objects[0].data.values
        assert values["level"] == 2 and values["value"] == -7 and values["qds"] == 0x80
        assert values["ts"].minute == 5
        assert got.encode() == raw          # 往返字节稳定

        # 131 = VendorCounter: u32 + bool + bytes(4)
        raw2 = _build(131, 7, {"count": 4000000000, "flag": True,
                               "payload": b"\xde\xad\xbe\xef"})
        got2 = ASDU.decode(raw2).objects[0].data.values
        assert got2["count"] == 4000000000 and got2["flag"] is True
        assert got2["payload"] == b"\xde\xad\xbe\xef"

    def test_default_appconfig_has_no_custom_types(self):
        """默认配置不含自定义类型 → 未知 TypeID 行为与改动前一致."""
        from core.config import AppConfig
        assert AppConfig().custom_types == []
        assert CUSTOM_TYPES.ids() == []

    def test_yaml_mapping_form_normalized_to_list(self, tmp_path):
        from core.config import load_config
        p = tmp_path / "c.yaml"
        p.write_text(
            "custom_types:\n  140:\n    name: S\n    fields: [v]\n",
            encoding="utf-8",
        )
        cfg = load_config(p)
        assert cfg.custom_types == [{"name": "S", "fields": ["v"], "type_id": 140}]

        CUSTOM_TYPES.load_dict({"custom_types": cfg.custom_types})
        assert CUSTOM_TYPES.ids() == [140]

    def test_save_load_roundtrip(self, tmp_path):
        from core.config import AppConfig, load_config
        cfg = AppConfig()
        cfg.custom_types = [{"type_id": 150, "name": "X",
                             "fields": [{"name": "v", "type": "u16"}]}]
        out = tmp_path / "saved.yaml"
        cfg.save(out)

        assert load_config(out).custom_types == cfg.custom_types


class TestAllStandardTypesProtected:
    """72 种标准 TypeID 一个都不能被自定义遮蔽（回归锁）."""

    def test_every_standard_type_has_a_decoder(self):
        ASDU._ensure_decoders()
        standard = set(TypeID)
        assert len(standard) == 72
        assert standard <= set(ASDU._DECODERS)

    def test_no_standard_type_can_be_shadowed(self):
        for t in TypeID:
            with pytest.raises(ValueError):
                CUSTOM_TYPES.register(CustomTypeDef(
                    type_id=int(t), fields=[CustomField("v", "u8")]))
        assert CUSTOM_TYPES.ids() == []
