"""生成 IEC 104 互操作语料库（合成基线 + 回放回归输入）.

用法::

    python tests/fixtures/frames/generate_corpus.py

产物:
- ``*.i104``：主站视角的录制（TX=主站发出，RX=主站收到），可直接用
  ``capture_tool.py`` 打开/转换 pcap；
- ``manifest.json``：每帧解码后的 golden 快照 + 回放后应看到的点值。

⚠ 语料来源说明：本目录下的 ``*.i104`` 是**合成基线**（由协议构造器生成），
不是真机抓包。真机报文请放入 ``real/`` 子目录（同样支持 ``.i104``/``.json``），
回放测试会自动发现；放入前请按 README 做脱敏。合成基线用于锁定解码行为，
真机语料用于锁定现场兼容性，两者互补。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.capture.format import (  # noqa: E402
    DIRECTION_RX,
    DIRECTION_TX,
    CaptureFile,
    FrameEntry,
)
from core.protocol.apci import APCICodec  # noqa: E402
from core.protocol.asdu import ASDU, ASDUBuilder, InformationObject  # noqa: E402
from core.protocol.constants import (  # noqa: E402
    U_STARTDT_ACT,
    U_STARTDT_CON,
    U_TESTFR_ACT,
    U_TESTFR_CON,
)
from core.protocol.types import (  # noqa: E402
    COT,
    CP24Time2a,
    CP56Time2a,
    ParameterActivation,
    ParameterCommandNormalized,
    TypeID,
)

OUT_DIR = Path(__file__).resolve().parent
CREATED = 1767225600.0  # 2026-01-01 00:00:00 UTC，固定时间戳保证可复现

COMMON_ADDR = 1
CP24 = CP24Time2a(millisecond=5000, minute=4)
CP56 = CP56Time2a(millisecond=6500, minute=5, hour=6, day=2, month=1, year=26)


class Scenario:
    """按主站视角录制一个场景，并维护两侧序列号."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.frames: list[FrameEntry] = []
        self.master_checks: list[dict[str, Any]] = []
        self.master_i = 0   # 主站已发送 I 帧数（子站应确认的 rx_seq）
        self.slave_i = 0    # 子站已发送 I 帧数（主站期望的 tx_seq）
        self._t = 0.0

    def _next_ts(self) -> float:
        self._t = round(self._t + 0.01, 3)
        return self._t

    def _add(self, direction: int, data: bytes) -> None:
        self.frames.append(FrameEntry(
            timestamp=self._next_ts(), direction=direction, frame_data=data,
        ))

    def tx_u(self, func: int) -> None:
        self._add(DIRECTION_TX, APCICodec.encode_u(func))

    def rx_u(self, func: int) -> None:
        self._add(DIRECTION_RX, APCICodec.encode_u(func))

    def tx_i(self, asdu_data: bytes) -> None:
        frame = APCICodec.encode_i(self.master_i, self.slave_i, asdu_data)
        self.master_i += 1
        self._add(DIRECTION_TX, frame)

    def rx_i(self, asdu_data: bytes) -> None:
        frame = APCICodec.encode_i(self.slave_i, self.master_i, asdu_data)
        self.slave_i += 1
        self._add(DIRECTION_RX, frame)

    def rx_s(self) -> None:
        self._add(DIRECTION_RX, APCICodec.encode_s(self.master_i))

    def check(self, kind: str, ioa: int, value: Any) -> None:
        self.master_checks.append({"kind": kind, "ioa": ioa, "value": value})


def _parameter_ack(type_id: TypeID, ioa: int, value: float) -> bytes:
    """构造参数命令的 ACTCON（ASDUBuilder 只提供 ACT 方向，故手工组帧）."""
    asdu = ASDU(
        type_id=type_id, sq=False, num=1, cot=COT.ACTCON,
        common_addr=COMMON_ADDR,
    )
    if type_id == TypeID.P_AC_NA_1:
        data = ParameterActivation(ioa=ioa, qualifier=int(value))
    else:
        data = ParameterCommandNormalized(ioa=ioa, value=value)
    asdu.objects.append(InformationObject(ioa=ioa, data=data))
    return asdu.encode()


def scenario_gi_basic() -> Scenario:
    s = Scenario(
        "gi_basic",
        "STARTDT → 总召唤 → 单点/双点/归一化/标度化/短浮点/累计量 → 总召结束",
    )
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.tx_i(ASDUBuilder.build_general_interrogation(COMMON_ADDR, qoi=20))
    s.rx_i(ASDUBuilder.build_general_interrogation_ack(COMMON_ADDR, qoi=20))
    s.rx_i(ASDUBuilder.build_single_point_sequence(
        COMMON_ADDR, [(100, True, 0), (101, False, 0), (102, True, 0)], cot=COT.INTROGEN,
    ))
    s.rx_i(ASDUBuilder.build_double_point(COMMON_ADDR, 110, 1, cot=COT.INTROGEN))
    s.rx_i(ASDUBuilder.build_double_point(COMMON_ADDR, 111, 2, cot=COT.INTROGEN))
    s.rx_i(ASDUBuilder.build_normalized_value(COMMON_ADDR, 200, 0.5, cot=COT.INTROGEN))
    s.rx_i(ASDUBuilder.build_normalized_value(COMMON_ADDR, 201, -0.25, cot=COT.INTROGEN))
    s.rx_i(ASDUBuilder.build_scaled_value(COMMON_ADDR, 210, 1234, cot=COT.INTROGEN))
    s.rx_i(ASDUBuilder.build_short_float(COMMON_ADDR, 220, 3.5, cot=COT.INTROGEN))
    s.rx_i(ASDUBuilder.build_counter_value(COMMON_ADDR, 300, 42, cot=COT.INTROGEN))
    s.rx_s()
    s.rx_i(ASDUBuilder.build_general_interrogation_end(COMMON_ADDR, qoi=20))
    for kind, ioa, value in (
        ("yx", 100, True), ("yx", 101, False), ("yx", 102, True),
        ("yx", 110, False), ("yx", 111, True),
        ("yc", 200, 0.5), ("yc", 201, -0.25),
        ("yc", 210, 1234.0), ("yc", 220, 3.5),
        ("ym", 300, 42),
    ):
        s.check(kind, ioa, value)
    return s


def scenario_soe_burst() -> Scenario:
    s = Scenario("soe_burst", "SOE 突发：带 CP56 时标的遥信/遥测连续变位")
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.rx_i(ASDUBuilder.build_single_point(COMMON_ADDR, 400, True, cot=COT.SPONT,
                                          with_time=True))
    s.rx_i(ASDUBuilder.build_double_point(COMMON_ADDR, 401, 2, cot=COT.SPONT,
                                          with_time=True))
    s.rx_i(ASDUBuilder.build_short_float(COMMON_ADDR, 402, 12.5, cot=COT.SPONT,
                                        with_time=True))
    s.rx_i(ASDUBuilder.build_single_point(COMMON_ADDR, 400, False, cot=COT.SPONT,
                                          with_time=True))
    s.rx_i(ASDUBuilder.build_short_float(COMMON_ADDR, 402, 13.5, cot=COT.SPONT,
                                        with_time=True))
    s.check("yx", 400, False)
    s.check("yx", 401, True)
    s.check("yc", 402, 13.5)
    return s


def scenario_cp24_variants() -> Scenario:
    s = Scenario("cp24_variants", "CP24/CP56 时标变体：累计量/归一化/标度化/短浮点/步位置")
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.rx_i(ASDUBuilder.build_counter_cp24(COMMON_ADDR, 500, 100, time_tag=CP24))
    s.rx_i(ASDUBuilder.build_normalized_cp24(COMMON_ADDR, 501, 0.25, time_tag=CP24))
    s.rx_i(ASDUBuilder.build_scaled_cp24(COMMON_ADDR, 502, -12, time_tag=CP24))
    s.rx_i(ASDUBuilder.build_short_float_cp24(COMMON_ADDR, 503, 1.25, time_tag=CP24))
    s.rx_i(ASDUBuilder.build_counter_value(COMMON_ADDR, 504, 200, with_time=True))
    s.rx_i(ASDUBuilder.build_step_position(COMMON_ADDR, 505, 3, with_time=True))
    s.check("ym", 500, 100)
    s.check("yc", 501, 0.25)
    s.check("yc", 502, -12.0)
    s.check("yc", 503, 1.25)
    s.check("ym", 504, 200)
    return s


def scenario_silent_device() -> Scenario:
    s = Scenario("silent_device", "只发 EI、不主动上送数据的静默装置（需周期总召）")
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.rx_i(ASDUBuilder.build_initialization_end(COMMON_ADDR))
    s.tx_u(U_TESTFR_ACT)
    s.rx_u(U_TESTFR_CON)
    return s


def scenario_sbo_command() -> Scenario:
    s = Scenario("sbo_command", "SBO 选择-执行-终止 + 同 IOA 遥信变位")
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.tx_i(ASDUBuilder.build_single_command(COMMON_ADDR, 600, True, select=True))
    s.rx_i(ASDUBuilder.build_single_command(COMMON_ADDR, 600, True, select=True,
                                            cot=COT.ACTCON))
    s.tx_i(ASDUBuilder.build_single_command(COMMON_ADDR, 600, True, select=False))
    s.rx_i(ASDUBuilder.build_single_command(COMMON_ADDR, 600, True, select=False,
                                            cot=COT.ACTCON))
    s.rx_i(ASDUBuilder.build_single_command(COMMON_ADDR, 600, True, select=False,
                                            cot=COT.ACTTERM))
    s.rx_i(ASDUBuilder.build_single_point(COMMON_ADDR, 600, True, cot=COT.SPONT,
                                          with_time=True))
    s.check("yx", 600, True)
    return s


def scenario_param_file() -> Scenario:
    s = Scenario("param_file", "参数装载/激活确认 + 文件传输握手（目录/节/段/最后节）")
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.tx_i(ASDUBuilder.build_parameter_normalized(COMMON_ADDR, 700, 0.5))
    s.rx_i(_parameter_ack(TypeID.P_ME_NA_1, 700, 0.5))
    s.tx_i(ASDUBuilder.build_parameter_activation(COMMON_ADDR, 700, qualifier=1))
    s.rx_i(_parameter_ack(TypeID.P_AC_NA_1, 700, 0.0))
    s.rx_i(ASDUBuilder.build_file_ready(COMMON_ADDR, 0, file_name=1,
                                        file_length=4))
    s.tx_i(ASDUBuilder.build_file_ready_ack(COMMON_ADDR, 0, file_name=1,
                                            file_length=4))
    s.rx_i(ASDUBuilder.build_section_ready(COMMON_ADDR, 0, file_name=1,
                                           section_name=0, section_length=4))
    s.tx_i(ASDUBuilder.build_ack_file_section(COMMON_ADDR, 0, file_name=1,
                                              section_name=0, qualifier=0))
    s.rx_i(ASDUBuilder.build_file_segment(COMMON_ADDR, 0, file_name=1,
                                          section_name=0, data=b"ABCD"))
    s.rx_i(ASDUBuilder.build_last_section(COMMON_ADDR, 0, file_name=1,
                                          section_name=0, lsq=1))
    return s


def scenario_malformed() -> Scenario:
    s = Scenario("malformed", "畸形帧鲁棒性：截断/未知类型/长度不符后仍能恢复")
    s.tx_u(U_STARTDT_ACT)
    s.rx_u(U_STARTDT_CON)
    s.rx_i(ASDUBuilder.build_single_point(COMMON_ADDR, 800, True))
    # 1) 帧头声称 20 字节，实际只有 6 字节（截断）
    s._add(DIRECTION_RX, b"\x68\x14\x00\x00\x00\x00")
    # 2) APCI 合法、ASDU 类型未知（0xFF）—— 应解码失败但不影响后续帧
    s.rx_i(bytes([0xFF, 1, 0, 6, 0, COMMON_ADDR]))
    # 3) ASDU 只有 1 字节类型标识（长度不足）
    s._add(DIRECTION_RX, APCICodec.encode_i(s.slave_i, s.master_i, b"\x01"))
    s.slave_i += 1
    s.rx_i(ASDUBuilder.build_single_point(COMMON_ADDR, 801, True))
    s.check("yx", 800, True)
    s.check("yx", 801, True)
    return s


SCENARIOS = [
    scenario_gi_basic,
    scenario_soe_burst,
    scenario_cp24_variants,
    scenario_silent_device,
    scenario_sbo_command,
    scenario_param_file,
    scenario_malformed,
]


def _scalar(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)


def object_summary(obj: Any) -> dict[str, Any]:
    data = obj.data
    payload: dict[str, Any] = {}
    if is_dataclass(data):
        raw = asdict(data)
        for key in ("value", "state", "qualifier", "qoi", "qcc",
                    "file_name", "section_name", "select"):
            if key in raw:
                payload[key] = _scalar(raw[key])
    return {"ioa": obj.ioa, **payload}


def frame_summary(entry: FrameEntry) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "direction": entry.direction_str,
        "frame_type": entry.frame_type,
    }
    try:
        apci, _ = APCICodec.decode(entry.frame_data)
    except Exception as exc:  # 畸形帧语料：记录失败类型，回放测试据此断言不崩溃
        summary["decode_error"] = type(exc).__name__
        return summary
    summary.update({"tx_seq": apci.tx_seq, "rx_seq": apci.rx_seq})
    if apci.is_i_frame:
        try:
            asdu = ASDU.decode(entry.frame_data[6:6 + apci.asdu_length])
        except Exception as exc:
            summary["asdu_decode_error"] = type(exc).__name__
            return summary
        summary.update({
            "type_id": int(asdu.type_id),
            "type_name": asdu.type_id.name,
            "cot": int(asdu.cot),
            "common_addr": asdu.common_addr,
            "sq": asdu.sq,
            "num": asdu.num,
            "objects": [object_summary(o) for o in asdu.objects],
        })
    elif apci.is_u_frame:
        summary["u_func"] = apci.u_func
    return summary


def generate() -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": 1,
        "description": (
            "IEC 104 互操作语料库（合成基线）。TX=主站发出，RX=主站收到。"
            "manifest 为解码后的 golden 快照 + 回放应看到的点值。"
        ),
        "generated_by": "tests/fixtures/frames/generate_corpus.py",
        "created": CREATED,
        "scenarios": [],
    }
    for factory in SCENARIOS:
        scenario = factory()
        path = OUT_DIR / f"{scenario.name}.i104"
        CaptureFile.save_binary(
            path, scenario.frames, description=scenario.description, created=CREATED,
        )
        manifest["scenarios"].append({
            "file": path.name,
            "name": scenario.name,
            "description": scenario.description,
            "frames": [frame_summary(f) for f in scenario.frames],
            "master_checks": scenario.master_checks,
        })
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


if __name__ == "__main__":
    data = generate()
    print(f"generated {len(data['scenarios'])} scenarios in {OUT_DIR}")
