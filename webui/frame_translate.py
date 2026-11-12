"""报文逐段翻译（第二批体验改造 ④）。

把一帧 HEX 拆成带注释的分段，供报文查看器悬停展示：

- APCI：起始/长度/控制域 → I/U/S 帧类型与序号
- ASDU：TypeID 含义 / VSQ(SQ、个数) / COT 含义 / 源发地址 / 公共地址
- 信息体：逐个 IOA + 值 + 品质 + 时标（复用 ``core/protocol/io.py`` 的解析与显示格式化）

只做**只读解析**，任何一段解析失败都不抛出——失败段记入备注行，
保证悬停翻译对脏数据/半帧同样可用。
"""

from __future__ import annotations

from typing import Any

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU
from core.protocol.io import format_value_display, get_value_quality, get_value_timestamp
from core.protocol.types import COT, CP56Time2a, TypeID

#: U 帧功能码 → 名称（与 core/protocol/constants.py 的取值一致）
U_FUNC_NAMES: dict[int, str] = {
    0x07: "STARTDT act",
    0x0B: "STARTDT con",
    0x13: "STOPDT act",
    0x23: "STOPDT con",
    0x43: "TESTFR act",
    0x83: "TESTFR con",
}

#: COT 中文名（常用项；缺省回落枚举名/区间名）
COT_ZH: dict[int, str] = {
    0: "未用", 1: "周期", 2: "背景扫描", 3: "突发", 4: "初始化", 5: "被请求",
    6: "激活", 7: "激活确认", 8: "停止激活", 9: "停止激活确认", 10: "激活终止",
    11: "远方命令返送", 12: "当地命令返送", 13: "文件传输",
    20: "响应站召唤", 37: "响应累计量总召唤",
}


def _cot_name(cot: int, pn: bool, test: bool) -> str:
    base = COT_ZH.get(cot)
    if base is None:
        try:
            base = COT(cot).name
        except ValueError:
            if 20 <= cot <= 36:
                base = f"响应第 {cot - 20} 组召唤"
            elif 38 <= cot <= 41:
                base = f"响应第 {cot - 37} 组累计量召唤"
            else:
                base = f"COT {cot}"
    flags = []
    if test:
        flags.append("测试位 T=1")
    if pn:
        flags.append("否定确认 P/N=1")
    return base + (f"（{'，'.join(flags)}）" if flags else "")


def _type_name(type_id: int) -> str:
    try:
        return f"{TypeID(type_id).name}({type_id})"
    except ValueError:
        return f"未知类型 TypeID {type_id}"


def _display_value(type_id: int, value: Any) -> str:
    """信息体显示值；对以原始字节存放的系统命令（QOI/时标）给出可读翻译。"""
    if isinstance(value, (bytes, bytearray)):
        if type_id == int(TypeID.C_IC_NA_1) and len(value) == 1:
            qoi = value[0]
            name = "站召唤" if qoi == 20 else f"第 {qoi - 20} 组召唤" if 21 <= qoi <= 36 else ""
            return f"QOI={qoi}" + (f"（{name}）" if name else "")
        if type_id == int(TypeID.C_CS_NA_1) and len(value) == 7:
            try:
                return f"时间={CP56Time2a.from_bytes(bytes(value), 0).to_datetime_str()}"
            except Exception:
                pass
        return bytes(value).hex().upper()
    return format_value_display(TypeID(type_id), value)


def _hex_bytes(hex_str: str) -> bytes | None:
    try:
        return bytes.fromhex(hex_str.strip())
    except ValueError:
        return None


def _translate_apci(data: bytes) -> tuple[list[str], str, bytes]:
    """解析 APCI 段；返回 (行列表, 帧类型 "I"/"S"/"U"/"?", 剩余 ASDU 字节)."""
    lines: list[str] = []
    try:
        apci, _consumed = APCICodec.decode(data)
    except ValueError as e:
        lines.append(f"APCI 解析失败：{e}")
        return lines, "?", b""

    lines.append(f"起始 0x68 | APDU 长度 {data[1] + 2} 字节（ASDU {apci.asdu_length}）")
    if apci.frame_type.name == "I":
        fmt = "I"
        lines.append(f"I 帧 | 发送序号 VS={apci.tx_seq} 接收序号 VR={apci.rx_seq}")
    elif apci.frame_type.name == "S":
        fmt = "S"
        lines.append(f"S 帧（确认）| 接收序号 VR={apci.rx_seq}")
    else:
        fmt = "U"
        name = U_FUNC_NAMES.get(apci.u_func, f"0x{apci.u_func:02X}")
        lines.append(f"U 帧（控制）| 功能 {name}")
    # APCI 固定 6 字节（0x68 + 长度 + 4 控制域）；APCICodec.decode 的 consumed
    # 返回的是整帧长度，这里自行切出 ASDU 体
    asdu_body = data[6 : 2 + data[1]]
    return lines, fmt, asdu_body


def _translate_asdu(asdu: ASDU) -> list[str]:
    lines = [
        f"{_type_name(int(asdu.type_id))} | VSQ={asdu.num} SQ={'1 连续' if asdu.sq else '0 非连续'}"
        f" | COT={asdu.cot} {_cot_name(asdu.cot, asdu.pn, asdu.test)}",
        f"源发地址 {asdu.origin_addr} | 公共地址 {asdu.common_addr} | 信息体 {len(asdu.objects)} 个",
    ]
    for i, obj in enumerate(asdu.objects, start=1):
        try:
            display = _display_value(int(asdu.type_id), obj.data)
        except Exception:
            display = str(getattr(obj.data, "value", obj.data))
        row = f"信息体 {i}: IOA {obj.ioa} | {display}"
        quality = get_value_quality(obj.data)
        if not quality.is_good:
            row += f" | 品质 {quality}"
        ts = get_value_timestamp(obj.data) or obj.time_tag
        if ts is not None:
            try:
                row += f" | 时标 {ts.to_datetime_str()}"
            except Exception:
                pass
        lines.append(row)
    return lines


def _quality_bits(quality: Any) -> dict:
    """五位品质位 → 布尔字典（WP7；按 IEC 60870-5-101 位定义）."""
    return {
        "iv": bool(getattr(quality, "invalid", False)),
        "nt": bool(getattr(quality, "not_topical", False)),
        "sb": bool(getattr(quality, "substituted", False)),
        "bl": bool(getattr(quality, "blocked", False)),
        "ov": bool(getattr(quality, "overflow", False)),
    }


def _object_entry(index: int, obj: Any, type_id: int) -> dict:
    """单个信息对象 → 结构化条目（值/品质/时标/原始字节）.

    ``raw_hex`` 是该信息对象的线上字节（含 IOA 之后的全部内容），
    便于现场把可疑对象直接拿去和装置手册对照。
    """
    data = getattr(obj, "data", None)
    entry: dict[str, Any] = {"index": index, "ioa": int(getattr(obj, "ioa", 0))}
    try:
        entry["value_display"] = _display_value(type_id, data)
    except Exception:  # noqa: BLE001 — 单个对象解析失败不影响整帧
        entry["value_display"] = str(getattr(data, "value", data))
    try:
        entry["value"] = _jsonable_value(data)
    except Exception:  # noqa: BLE001
        entry["value"] = None
    try:
        quality = get_value_quality(data)
        entry["quality"] = str(quality)
        entry["quality_bits"] = _quality_bits(quality)
        entry["quality_raw"] = int(getattr(quality, "raw", 0))
    except Exception:  # noqa: BLE001 — 无品质字段的类型（系统命令等）
        entry["quality"] = ""
        entry["quality_bits"] = None
        entry["quality_raw"] = None
    ts = None
    try:
        ts = get_value_timestamp(data) or getattr(obj, "time_tag", None)
    except Exception:  # noqa: BLE001
        ts = None
    if ts is not None:
        try:
            entry["timestamp"] = ts.to_datetime_str()
        except Exception:  # noqa: BLE001
            entry["timestamp"] = None
    else:
        entry["timestamp"] = None
    try:
        raw = bytes(data) if isinstance(data, (bytes, bytearray)) else None
        entry["raw_hex"] = raw.hex().upper() if raw is not None else None
    except Exception:  # noqa: BLE001
        entry["raw_hex"] = None
    return entry


def _jsonable_value(data: Any) -> Any:
    """把信息体的值收敛成 JSON 可表示的形态（bool/int/float/str/None）."""
    if data is None:
        return None
    if isinstance(data, (bool, int, float, str)):
        return data
    if isinstance(data, (bytes, bytearray)):
        return bytes(data).hex().upper()
    inner = getattr(data, "value", None)
    if isinstance(inner, (bool, int, float, str)):
        return inner
    if inner is not None:
        return str(inner)
    return str(data)


def decode_tree(hex_str: str) -> dict[str, Any]:
    """结构化解码树（WP7）：``{ok, format, apci, asdu, objects, error?}``.

    与 :func:`translate_hex` 的分段文本互补——文本给人看，树给前端渲染可展开子表。
    **SQ=1 时** ASDU 只携带首地址，后续对象地址为 ``base + i``；这里显式展开
    并标 ``sq_index``，避免界面显示成"20 个对象同地址"。
    """
    raw = _hex_bytes(hex_str)
    if raw is None:
        return {"ok": False, "error": "非法 HEX 串"}
    if len(raw) < 6:
        return {"ok": False, "error": f"帧过短：{len(raw)} 字节（至少 6）"}

    out: dict[str, Any] = {"ok": True, "format": "?", "apci": None, "asdu": None,
                           "objects": []}
    try:
        apci, _ = APCICodec.decode(raw)
    except ValueError as e:
        out["error"] = f"APCI 解析失败：{e}"
        return out
    out["format"] = apci.frame_type.name
    out["apci"] = {
        "length": data_len(raw),
        "asdu_length": apci.asdu_length,
        "frame_type": apci.frame_type.name,
        "tx_seq": getattr(apci, "tx_seq", None),
        "rx_seq": getattr(apci, "rx_seq", None),
        "u_func": getattr(apci, "u_func", None),
        "u_func_name": U_FUNC_NAMES.get(getattr(apci, "u_func", -1)),
    }
    if out["format"] != "I" or len(raw) <= 6:
        return out

    body = raw[6: 2 + raw[1]]
    try:
        asdu = ASDU.decode(body)
    except Exception:  # noqa: BLE001 — 退回只解头部，至少给出 TypeID/COT
        try:
            asdu = ASDU.decode_header(body)
            out["error"] = "ASDU 信息体解析失败（仅解出头部）"
        except Exception as e:  # noqa: BLE001
            out["error"] = f"ASDU 解析失败：{e}"
            return out

    type_id = int(asdu.type_id)
    out["asdu"] = {
        "type_id": type_id,
        "type_name": _type_name(type_id),
        "sq": bool(asdu.sq),
        "num": int(asdu.num),
        "cot": int(asdu.cot),
        "cot_name": _cot_name(asdu.cot, asdu.pn, asdu.test),
        "pn": bool(asdu.pn),
        "test": bool(asdu.test),
        "origin_addr": int(asdu.origin_addr),
        "common_addr": int(asdu.common_addr),
        "object_count": len(asdu.objects),
    }
    for i, obj in enumerate(asdu.objects):
        entry = _object_entry(i + 1, obj, type_id)
        if asdu.sq:
            entry["sq_index"] = i
        out["objects"].append(entry)
    return out


def data_len(raw: bytes) -> int:
    """APDU 总长度（首字节 0x68 + 长度字节 + 2）."""
    return raw[1] + 2


def translate_hex(hex_str: str) -> dict[str, Any]:
    """翻译一帧 HEX 为分段文本。返回 ``{ok, error?, format?, segments?}``.

    segments: [{title, lines: [str]}]，任何失败段只记备注不抛出。
    """
    raw = _hex_bytes(hex_str)
    if raw is None:
        return {"ok": False, "error": "非法 HEX 串"}
    if len(raw) < 6:
        return {"ok": False, "error": f"帧过短：{len(raw)} 字节（至少 6）"}

    segments: list[dict[str, Any]] = []
    # WP7：同一份 HEX 顺带产出结构化树（纯新增键；失败时为 None，不影响分段文本）
    try:
        tree = decode_tree(hex_str)
    except Exception:  # noqa: BLE001
        tree = None
    apci_lines, fmt, asdu_body = _translate_apci(raw)
    segments.append({"title": "APCI（传输控制头）", "lines": apci_lines})

    if fmt == "I" and asdu_body:
        try:
            asdu = ASDU.decode(asdu_body)
        except Exception:
            try:
                asdu = ASDU.decode_header(asdu_body)
            except Exception as e:
                segments.append({"title": "ASDU", "lines": [f"ASDU 解析失败：{e}"]})
                return {"ok": True, "format": fmt, "segments": segments,
                        "tree": tree}
        segments.append({"title": f"ASDU（{_type_name(int(asdu.type_id))}）", "lines": _translate_asdu(asdu)})
    elif fmt == "I":
        segments.append({"title": "ASDU", "lines": ["I 帧无 ASDU"]})

    return {"ok": True, "format": fmt, "segments": segments, "tree": tree}
