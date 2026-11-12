"""WP1：ASDU 地址字段长度可配（1B CA / 2B IOA / 1B COT）.

验收判据：
* 默认配置（2/3/2）下编码逐字节与历史实现一致；
* 所有合法组合下 encode→decode 往返保真（含 SQ=1、时标、品质位）；
* 进程级 set_default / 任务级 use_default / 显式 override 三级优先级正确；
* 非法配置在启动阶段即报错，不留给帧解析阶段错位。
"""

from __future__ import annotations

import asyncio

import pytest

from core.protocol.address import (
    DEFAULT_ASDU_ADDRESS,
    AsduAddressConfig,
    get_default,
    set_default,
    use_default,
)
from core.protocol.asdu import APDU, ASDU, ASDUBuilder, InformationObject
from core.protocol.types import COT, CP56Time2a, SinglePoint, TypeID


@pytest.fixture(autouse=True)
def _restore_default():
    """每个用例后恢复进程默认，避免污染其余 1711 个用例。"""
    yield
    set_default(None)


def _gi_frame(cfg: AsduAddressConfig, *, common_addr: int = 1, ioa: int = 0) -> bytes:
    """按给定地址配置构造一帧总召唤 ASDU（显式配置，不受全局默认影响）。"""
    asdu = ASDU(
        type_id=TypeID.C_IC_NA_1,
        sq=False,
        num=1,
        cot=COT.ACT,
        common_addr=common_addr,
        address_config=cfg,
    )
    asdu.objects.append(InformationObject(ioa=ioa, data=bytes([20])))
    return asdu.encode()


# ── 默认行为零回归 ────────────────────────────────────────────────

def test_default_config_matches_historical_hardcoded_lengths():
    """默认 2/3/2；未配置时 ASDUBuilder 输出与历史逐字节一致。"""
    assert get_default() == AsduAddressConfig(2, 3, 2)
    assert AsduAddressConfig(2, 3, 2) == DEFAULT_ASDU_ADDRESS
    data = ASDUBuilder.build_general_interrogation(common_addr=0x0102, qoi=20)
    # TypeID, VSQ, COT(2), CA(2), IOA(3), QOI(1) = 10 字节
    assert len(data) == 10
    assert data[:6] == bytes([100, 1, 6, 0, 0x02, 0x01])
    assert data[6:9] == b"\x00\x00\x00"


def test_legacy_ca_length_override_keeps_old_semantics():
    """旧调用点 ASDU.decode(data, ca_length=1) 只覆盖 CA，IOA 仍按默认 3B。"""
    cfg = AsduAddressConfig(1, 3, 2)
    data = _gi_frame(cfg, common_addr=7)
    assert len(data) == 9  # 1+1+2+1+3+1
    decoded = ASDU.decode(data, ca_length=1)
    assert decoded.common_addr == 7
    assert decoded.objects[0].ioa == 0


# ── 全组合往返（黄金向量矩阵） ────────────────────────────────────

@pytest.mark.parametrize("ca_length", [1, 2])
@pytest.mark.parametrize("ioa_length", [1, 2, 3])
@pytest.mark.parametrize("cot_length", [1, 2])
@pytest.mark.parametrize("sq", [False, True])
def test_address_matrix_roundtrip(ca_length, ioa_length, cot_length, sq):
    """12 种长度组合 × SQ 开/关：CA / IOA / 值 / 品质 / 数量全部还原。"""
    cfg = AsduAddressConfig(ca_length, ioa_length, cot_length)
    ioa = min(0x010203, (1 << (8 * ioa_length)) - 1)
    asdu = ASDU(
        type_id=TypeID.M_SP_NA_1,
        sq=sq,
        num=2 if sq else 1,
        cot=COT.SPONT,
        common_addr=min(0x0102, (1 << (8 * ca_length)) - 1),
        address_config=cfg,
    )
    for i in range(2 if sq else 1):
        asdu.objects.append(InformationObject(
            ioa=ioa, data=SinglePoint(value=bool(i)),
        ))
    data = asdu.encode()

    # 头部 = TypeID(1)+VSQ(1)+COT+CA；SQ=0 每对象带 1 个 IOA + 1 字节数据，
    # SQ=1 仅首对象带 IOA、共 2 个数据字节。
    expected_len = 2 + cot_length + ca_length + (ioa_length + 2 if sq else ioa_length + 1)
    assert len(data) == expected_len

    decoded = ASDU.decode(data, address_config=cfg)
    assert decoded.common_addr == asdu.common_addr
    assert decoded.cot == COT.SPONT
    assert len(decoded.objects) == asdu.num
    assert decoded.objects[0].ioa == ioa
    if sq:
        assert decoded.objects[1].ioa == ioa + 1
    assert decoded.address_config == cfg


def test_short_ioa_rejects_overflowing_address():
    """2B IOA 配置下写入 3B 地址会被静默截断——显式校验防止现场误配。"""
    cfg = AsduAddressConfig(2, 2, 2)
    asdu = ASDU(
        type_id=TypeID.M_SP_NA_1, sq=False, num=1, cot=COT.SPONT,
        common_addr=1, address_config=cfg,
    )
    asdu.objects.append(InformationObject(ioa=0x010203, data=SinglePoint(value=True)))
    with pytest.raises(ValueError, match="IOA"):
        asdu.encode()


def test_cot_length_1_drops_origin_addr_byte():
    """COT=1B 时不写源发地址，解码 origin_addr 恒为 0，其他字段不串位。"""
    cfg = AsduAddressConfig(2, 3, 1)
    asdu = ASDU(
        type_id=TypeID.M_SP_NA_1, sq=False, num=1, cot=COT.SPONT,
        origin_addr=9, common_addr=0x0102, address_config=cfg,
    )
    asdu.objects.append(InformationObject(ioa=0x030201, data=SinglePoint(value=True)))
    data = asdu.encode()
    assert len(data) == 9  # 1+1+1+2+3+1
    assert data[2] == int(COT.SPONT) & 0x3F
    assert data[3:5] == b"\x02\x01"
    decoded = ASDU.decode(data, address_config=cfg)
    assert decoded.origin_addr == 0
    assert decoded.common_addr == 0x0102
    assert decoded.objects[0].ioa == 0x030201


def test_timed_object_roundtrip_with_nonstandard_lengths():
    """带 CP56 时标的遥信在 1B CA / 2B IOA 下仍完整还原。"""
    cfg = AsduAddressConfig(1, 2, 2)
    tag = CP56Time2a.now()
    asdu = ASDU(
        type_id=TypeID.M_SP_TB_1, sq=False, num=1, cot=COT.SPONT,
        common_addr=7, address_config=cfg,
    )
    asdu.objects.append(InformationObject(
        ioa=0x0102, data=SinglePoint(value=True), time_tag=tag,
    ))
    decoded = ASDU.decode(asdu.encode(), address_config=cfg)
    assert decoded.objects[0].ioa == 0x0102
    assert decoded.objects[0].time_tag is not None
    assert decoded.objects[0].time_tag.to_bytes() == tag.to_bytes()


# ── 三级优先级 ────────────────────────────────────────────────────

def test_set_default_changes_both_encode_and_decode():
    """进程级默认对 builder 与引擎解码同时生效（单一真值源）。"""
    set_default(AsduAddressConfig(1, 2, 2))
    data = ASDUBuilder.build_general_interrogation(common_addr=7, qoi=20)
    assert len(data) == 8  # 1+1+2+1+2+1
    decoded = ASDU.decode(data)
    assert decoded.common_addr == 7
    assert decoded.objects[0].ioa == 0
    assert decoded.address_config == AsduAddressConfig(1, 2, 2)


def test_use_default_is_task_scoped_and_restores():
    """use_default 只影响当前任务，退出后还原；多站/桥两侧不串味。"""
    set_default(AsduAddressConfig(2, 3, 2))

    async def two_tasks():
        async def short():
            with use_default(AsduAddressConfig(1, 2, 2)):
                await asyncio.sleep(0)
                return ASDUBuilder.build_general_interrogation(1)

        async def standard():
            await asyncio.sleep(0)
            return ASDUBuilder.build_general_interrogation(1)

        return await asyncio.gather(short(), standard())

    short_frame, std_frame = asyncio.run(two_tasks())
    assert len(short_frame) == 8
    assert len(std_frame) == 10
    assert get_default() == AsduAddressConfig(2, 3, 2)


def test_use_default_none_falls_back_to_process_default():
    """use_default(None) = 不覆盖，不能把进程级 set_default 屏蔽成 2/3/2。

    透明桥两侧未单独配置时会走这条路；若语义错成「恢复标准默认」，
    非标装置配置会在桥上被静默丢弃。
    """
    set_default(AsduAddressConfig(1, 2, 2))
    with use_default(None) as effective:
        assert effective == AsduAddressConfig(1, 2, 2)
        assert len(ASDUBuilder.build_general_interrogation(1)) == 8
    assert get_default() == AsduAddressConfig(1, 2, 2)


def test_explicit_override_wins_over_default():
    """离线工具按帧显式指定时，优先于进程默认。"""
    set_default(AsduAddressConfig(1, 2, 2))
    cfg = AsduAddressConfig(2, 3, 2)
    frame = _gi_frame(cfg, common_addr=0x0102)
    assert len(frame) == 10
    decoded = ASDU.decode(frame, address_config=cfg)
    assert decoded.common_addr == 0x0102


def test_apdu_decode_propagates_address_config():
    """APDU.decode 透传完整配置，I 帧 ASDU 不错位。"""
    cfg = AsduAddressConfig(1, 2, 2)
    asdu = ASDU(
        type_id=TypeID.M_SP_NA_1, sq=False, num=1, cot=COT.SPONT,
        common_addr=7, address_config=cfg,
    )
    asdu.objects.append(InformationObject(ioa=0x0102, data=SinglePoint(value=True)))
    apdu = APDU()
    apdu.asdu = asdu
    decoded = APDU.decode(apdu.encode(), address_config=cfg)
    assert decoded.asdu.common_addr == 7
    assert decoded.asdu.objects[0].ioa == 0x0102


def test_decode_header_uses_config():
    """仅头部解析同样按配置取 CA，未知类型标识也能正确定位。"""
    cfg = AsduAddressConfig(1, 2, 2)
    raw = bytes([200, 1, 6, 0, 7, 0x02, 0x01])  # 未知 TypeID=200
    header = ASDU.decode_header(raw, address_config=cfg)
    assert header.type_id == 200
    assert header.common_addr == 7


# ── 配置合法性 ────────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs", [
    {"ca_length": 0}, {"ca_length": 3},
    {"ioa_length": 0}, {"ioa_length": 4},
    {"cot_length": 0}, {"cot_length": 3},
])
def test_invalid_config_rejected_at_construction(kwargs):
    """非法长度在配置构造阶段抛错，不留给帧解析阶段静默错位。"""
    with pytest.raises(ValueError):
        AsduAddressConfig(**kwargs)


# ── AppConfig YAML 接线 ───────────────────────────────────────────

def test_app_config_asdu_address_yaml_roundtrip(tmp_path):
    """asdu_address 节 save→load 往返保真；CLI 覆盖也走同一对象。"""
    from core.config import AppConfig, load_config

    cfg = AppConfig()
    cfg.asdu_address = AsduAddressConfig(1, 2, 2)
    path = tmp_path / "nonstandard.yaml"
    cfg.save(path)

    text = path.read_text(encoding="utf-8")
    assert "asdu_address:" in text
    assert "ca_length: 1" in text

    loaded = load_config(path)
    assert loaded.asdu_address == AsduAddressConfig(1, 2, 2)


def test_app_config_without_asdu_address_uses_standard_default(tmp_path):
    """旧配置文件缺 asdu_address 节 → 2/3/2，字节行为零变化（向后兼容）。"""
    from core.config import AppConfig, load_config

    cfg = AppConfig()
    path = tmp_path / "legacy.yaml"
    cfg.save(path)
    text = path.read_text(encoding="utf-8")
    # 模拟历史文件：删掉本版新增的节
    lines = [ln for ln in text.splitlines() if not ln.startswith("asdu_address:")
             and not ln.startswith("  ca_length:") and not ln.startswith("  ioa_length:")
             and not ln.startswith("  cot_length:")]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert load_config(path).asdu_address == DEFAULT_ASDU_ADDRESS
    assert load_config(tmp_path / "missing.yaml").asdu_address == DEFAULT_ASDU_ADDRESS


def test_load_config_rejects_invalid_asdu_address(tmp_path):
    """YAML 里写 ioa_length: 4 必须启动即报错，不能等到帧解析才错位。"""
    from core.config import load_config

    path = tmp_path / "bad.yaml"
    path.write_text("asdu_address:\n  ioa_length: 4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ioa_length"):
        load_config(path)


def test_status_exposes_asdu_address():
    """/api/status 新增 asdu_address 键，旧前端忽略即可（只增不改）。"""
    from webui.bridge import EngineBridge

    cfg = __import__("core.config", fromlist=["AppConfig"]).AppConfig()
    cfg.asdu_address = AsduAddressConfig(1, 2, 1)
    bridge = EngineBridge(role="master", app_config=cfg)
    st = bridge.status()
    assert st["asdu_address"] == {
        "ca_length": 1, "ioa_length": 2, "cot_length": 1,
    }
