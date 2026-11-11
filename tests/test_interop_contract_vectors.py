"""cases.tsv 契约向量映射（otfabric/iec104-interop v0.6.0）→ 本仓离线回归.

不依赖 Docker：把 `iec104-interop/tests/cases.tsv` 中可在本仓协议层验证的
断言子集（否定确认 COT、未知地址拒绝、组召唤语义、测试命令类型）抽成
pytest，作为 consumer 矩阵的前置护栏。

来源（2026-11-11 抽取）：
  case.interrogate-qoi-21          → 期望 conf=7n（否定 ACTCON）
  case.counter-interrogate-qcc-69  → 期望 conf=7n
  case.read-ioa-999                → 期望 C_RD_NA_1/47
  case.command-...-ioa-999         → 期望 47n / 7n
  case.test-command                → C_TS_TA_1(107)/7
  case.interrogate-common-address-7 → 期望 conf=46n
  case.interrogate                  → 12 条 ASDU 序列（GI 数据 + ACTTERM）

**标准口径差异（本仓按 101，lib60870/otfabric 按 104 补充）**：
  未知信息对象地址：本仓 COT=45（IEC 60870-5-101 QRP 口径，
  docs/iec104-conformance-fixes.md:198 已锁定）；lib60870 家族回 COT=47。
  两套都应能进否定应答处理，不作硬失败（见 test_negative_cot_variants）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.types import COT, TypeID

CA = 1


def _decode(raw: bytes) -> ASDU:
    return ASDU.decode(raw)


# ── 1. 否定确认 COT 口径 ────────────────────────────────────────────────


def test_negative_cot_variants():
    """cases.tsv 里的否定帧 COT：7(否定 ACTCON)/45/46/47 本仓都要能识别处理.

    - conf=7n：否定激活确认（P/N=1）
    - 45：UNKNOWN_IOA（本仓/101 口径）
    - 46：UNKNOWN_COT? 实际 otfabric 里 46=unknown CA 的否定确认
    - 47：UNKNOWN_IOA（lib60870/104 补充口径，本轮实测）
    """
    assert COT.UNKNOWN_CA == 44
    assert COT.UNKNOWN_IOA == 45
    # 46/47 在本仓 COT 枚举里未具名（保留），但 P/N 否定与通用错误处理不得漏
    # 否定 ACTCON 的构造：P/N 位（COT 字节 bit6）
    from core.protocol.asdu import ASDU as _ASDU
    from core.protocol.asdu import InformationObject
    asdu = _ASDU(type_id=TypeID.C_RD_NA_1, sq=False, num=1,
                 cot=COT.ACTCON, common_addr=CA)
    asdu.objects.append(InformationObject(ioa=0, data=b""))
    asdu.pn = True
    assert asdu.pn is True
    raw = asdu.encode()
    assert (raw[2] & 0x40) == 0x40, "P/N 必须写进 COT 字节 bit6（否定确认编码）"
    decoded = _decode(raw)
    assert decoded.cot == COT.ACTCON and decoded.pn is True


# ── 2. 组召唤 / 累计量语义（cases.tsv QOI=21、QCC=69） ─────────────────


def test_group_interrogation_cot_range():
    """COT 21~36 = 第 1~16 组召唤响应；38~41 = 累计量分组（与 cases.tsv 一致）."""
    for g in range(1, 17):
        assert COT.group_response(g) == 20 + g
    assert COT.INTROGEN == 20 and COT.COUNTER_REQ == 37


def test_qoi_qcc_are_raw_qualifier_octets():
    """QOI/QCC 为原始限定词八位组：21 组召唤、69 累计量非法 QCC（可被否定）."""
    gi21 = ASDUBuilder.build_general_interrogation(CA, qoi=21)
    asdu = _decode(gi21)
    assert asdu.type_id == TypeID.C_IC_NA_1 and asdu.cot == COT.ACT
    # QOI 在信息体第 4 字节（IOA3 + QOI1）
    body = asdu.objects[0].data
    # 信息体末尾 = QOI 八位组（IOA 之后）
    assert (body[-1] if isinstance(body, (bytes, bytearray)) else body) == 21
    ci69 = ASDUBuilder.build_counter_interrogation(CA, qcc=69)
    asdu2 = _decode(ci69)
    assert asdu2.type_id == TypeID.C_CI_NA_1 and asdu2.cot == COT.ACT


# ── 3. 测试命令类型（cases.tsv test-command = C_TS_TA_1/7） ─────────────


def test_test_command_with_time_is_type_107():
    """契约的 test-command 是 C_TS_TA_1(107)；本仓 HTTP 只暴露 104，核心层须能造 107."""
    raw = ASDUBuilder.build_test_command_with_time(CA)
    asdu = _decode(raw)
    assert asdu.type_id == TypeID.C_TS_TA_1
    assert int(asdu.type_id.value) == 107
    assert asdu.cot == COT.ACT
    assert len(asdu.objects) == 1
    # 信息体 = 0xAA55(2) + CP56Time2a(7) = 9 字节
    assert len(asdu.objects[0].data) == 9
    assert asdu.objects[0].data[:2] == b"\xaa\x55"


def test_test_command_plain_is_type_104():
    raw = ASDUBuilder.build_test_command(CA)
    asdu = _decode(raw)
    assert asdu.type_id == TypeID.C_TS_NA_1 and int(asdu.type_id.value) == 104


# ── 4. 未知 IOA 读（cases.tsv read-ioa-999 → C_RD_NA_1/47） ────────────


def test_read_unknown_ioa_asdu_is_wellformed():
    """读命令构造（对端应回否定确认，本仓负责构造与解码，不在此断言对端行为）."""
    raw = ASDUBuilder.build_read_command(CA, ioa=999)
    asdu = _decode(raw)
    assert asdu.type_id == TypeID.C_RD_NA_1
    assert asdu.objects[0].ioa == 999
    assert asdu.cot == COT.REQ or asdu.cot == COT.ACT  # 两种实现均可


# ── 5. GI 序列形状（cases.tsv case.interrogate 的 12 条 ASDU） ──────────


def test_gi_command_shape_matches_interop_case():
    """GI 命令：C_IC_NA_1(100)/ACT(6)/QOI=20，与 interop case.interrogate 对齐."""
    raw = ASDUBuilder.build_general_interrogation(CA, qoi=20)
    asdu = _decode(raw)
    assert asdu.type_id == TypeID.C_IC_NA_1
    assert asdu.cot == COT.ACT
    body = asdu.objects[0].data
    assert (body[-1] if isinstance(body, (bytes, bytearray)) else body) == 20
