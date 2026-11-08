"""SCD/CID/ICD（IEC 61850-6 SCL）→ IEC 60870-5-104 点表导入.

两条映射路径（IEC 61850-80-1）：

1. **精确映射**：信号 DO 结构里内嵌
   ``<Private type="IEC_60870_5_104"><eTr_104:Address casdu=".." ioa=".." ti=".."/></Private>``
   （ti 即 104 类型标识，见 :data:`core.protocol.types.TypeID`）。此时 ioa/casdu
   原样采用，类别与子类型由 ti 决定——**ti 优先于 CDC 推断**（工程中 ENS 枚举
   映射为标度化遥测等情况存在）。
2. **推断映射**（无 104 Address）：按 DOType 的 ``cdc`` 属性推断类别
   （SPC/SPS/INS/ENS→遥信、DPS→双点遥信、MV/WYE/DEL 系→遥测、BCR→遥脉、
   BSC→步位置），IOA 按类别基数自动分配。控制/设点类 CDC（ENC/ISC/APC/ASG 等）
   单向推断不可靠，跳过并给出告警（提示补 80-1 映射）。

公共地址（ASDU）约束：104 点表模型每个站只有一个 ``common_addr``。SCD 里若出现
多个 ``casdu``，默认采用出现最多的一个，其余点剔除并记录告警（明细含 casdu）。

输出为 :meth:`core.data.point_table.PointTable.load_yaml` 同构的 dict
（键 ``station_name/common_addr/yx/yc/yk/ym/step``），可直接
``yaml.safe_dump`` 后走现有 ``POST /api/points/import?format=yaml``。
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

SCL_NS = "http://www.iec.ch/61850/2003/SCL"
PRIVATE_104 = "IEC_60870_5_104"

# ── ti → (点类别, 子类型) 映射（依据 core.protocol.types.TypeID）────────
# 类别与点表 YAML 顶层键一致：yx/yc/yk/ym/step
TI_MAP: dict[int, tuple[str, str]] = {
    # 遥信（单点/双点，含带时标与保护单点变体）
    1: ("yx", "single"), 2: ("yx", "single"), 30: ("yx", "single"),
    20: ("yx", "single"), 71: ("yx", "single"),
    3: ("yx", "double"), 4: ("yx", "double"), 31: ("yx", "double"),
    # 步位置（监视方向）
    5: ("step", ""), 6: ("step", ""), 32: ("step", ""),
    # 遥测（归一化/标度化/短浮点，含带时标与 M_ME_ND）
    9: ("yc", "normalized"), 10: ("yc", "normalized"), 21: ("yc", "normalized"),
    34: ("yc", "normalized"),
    11: ("yc", "scaled"), 12: ("yc", "scaled"), 35: ("yc", "scaled"),
    13: ("yc", "short_float"), 14: ("yc", "short_float"), 36: ("yc", "short_float"),
    # 遥脉/累计量
    15: ("ym", ""), 16: ("ym", ""), 37: ("ym", ""),
    # 遥控
    45: ("yk", "single"), 58: ("yk", "single"),
    46: ("yk", "double"), 59: ("yk", "double"),
    # 升降命令 → 步位置点
    47: ("step", ""), 60: ("step", ""),
    # 设点命令 → 遥测点（本仓设点目标即 YC 点）
    48: ("yc", "normalized"), 61: ("yc", "normalized"),
    49: ("yc", "scaled"), 62: ("yc", "scaled"),
    50: ("yc", "short_float"), 63: ("yc", "short_float"),
}

# 无 104 Address 时的 CDC → (类别, 子类型) 推断（保守：控制/设点类不推断）
CDC_MAP: dict[str, tuple[str, str]] = {
    "SPC": ("yx", "single"), "SPS": ("yx", "single"), "INS": ("yx", "single"),
    "ENS": ("yx", "single"), "ACT": ("yx", "single"), "ACD": ("yx", "single"),
    "DPS": ("yx", "double"),
    "MV": ("yc", "short_float"), "WYE": ("yc", "short_float"),
    "DEL": ("yc", "short_float"), "HMV": ("yc", "short_float"),
    "HWYE": ("yc", "short_float"), "HDEL": ("yc", "short_float"),
    "SEQ": ("yc", "short_float"), "APC": ("yc", "short_float"),
    "HST": ("yc", "short_float"),
    "BCR": ("ym", ""),
    "BSC": ("step", ""),
}

# 推断模式下各类别的 IOA 分配基数（电力行业常见分区惯例），可被调用方覆盖
DEFAULT_IOA_BASES: dict[str, int] = {
    "yx": 1, "yc": 4097, "yk": 8193, "ym": 12289, "step": 16385,
}

_MAX_IOA = 16777215  # 3 字节信息对象地址上限

_LN_TAGS = ("LN", "LN0")


@dataclass
class ScdAddress:
    """80-1 精确映射地址."""
    casdu: int
    ioa: int
    ti: int


@dataclass
class ScdSignal:
    """SCD 中的一个可映射信号.

    精确映射信号：DOI 内带 80-1 Address 的 DAI/BDA（``address`` 非 None）；
    推断信号：整个 DOI（``address`` 为 None，按 ``cdc`` 推断）。
    """
    ied: str
    ld_inst: str
    ln_path: str            # prefix+lnClass+inst
    ln_desc: str
    ln_type: str            # LNodeType id（CDC 解析用）
    do_name: str
    do_desc: str
    da_path: str            # DAI/BDA 相对 DOI 的 name 链，如 stVal / phsA.cVal.mag.f
    cdc: str = ""           # DOType cdc（解析后由模板回填）
    address: ScdAddress | None = None

    def signal_path(self) -> str:
        """完整信号路径，如 ``B1/LD0/GGIO1.Ind1.stVal``."""
        base = f"{self.ied}/{self.ld_inst}/{self.ln_path}.{self.do_name}"
        return f"{base}.{self.da_path}" if self.da_path else base

    def display_name(self) -> str:
        """点表 name：desc 优先（DOI→LN），否则完整信号路径."""
        for desc in (self.do_desc, self.ln_desc):
            desc = (desc or "").strip()
            if desc:
                return desc
        return self.signal_path()


@dataclass
class ScdImportResult:
    """SCD 导入结果：信号清单 + 点表 dict + 告警 + 计数."""
    signals: list[ScdSignal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    station_name: str = ""
    common_addr: int = 1
    points: dict = field(default_factory=dict)


def _local(tag: str) -> str:
    """去掉 XML 命名空间，返回 local name."""
    return tag.rsplit("}", 1)[-1]


def parse_scl(text: str) -> tuple[list[ScdSignal], dict[str, dict[str, str]], dict[str, str], str]:
    """流式解析 SCL 文本.

    返回 ``(signals, lntype_dos, dotype_cdc, station_name)``：

    - ``signals``：精确映射信号（DOI 内带 80-1 Address 的 DAI/BDA，每个地址一条）
      与推断候选信号（每个 DOI 一条，``address=None``，CDC 稍后回填）；
    - ``lntype_dos``：LNodeType id → {DO name → DOType id}；
    - ``dotype_cdc``：DOType id → cdc；
    - ``station_name``：首个 Substation 的 name（可能为空）。

    SCD 可达数十 MB：iterparse 流式读取，IED/LN/DOI 处理完即清空子树。
    """
    signals: list[ScdSignal] = []
    lntype_dos: dict[str, dict[str, str]] = {}
    dotype_cdc: dict[str, str] = {}
    station_name = ""
    ln_by_key: dict[tuple[str, str, str], str] = {}  # (ied, ld, ln_path) -> lnType

    ied = ld_inst = ln_path = ln_desc = ln_type = ""
    do_stack: dict | None = None   # 当前 DOI 上下文 {name, desc, precise, has_precise}
    da_name_stack: list[str] = []  # DOI 内 SDI/DAI/BDA 嵌套 name 栈

    try:
        stream = ET.iterparse(io.StringIO(text), events=("start", "end"))
        for event, elem in stream:
            tag = _local(elem.tag)
            if event == "start":
                if tag == "IED":
                    ied = elem.get("name", "")
                elif tag == "LDevice":
                    ld_inst = elem.get("inst", "")
                elif tag in _LN_TAGS:
                    ln_path = f"{elem.get('prefix') or ''}{elem.get('lnClass')}{elem.get('inst')}"
                    ln_desc = elem.get("desc") or ""
                    ln_type = elem.get("lnType") or ""
                    ln_by_key[(ied, ld_inst, ln_path)] = ln_type
                elif tag == "DOI":
                    do_stack = {"name": elem.get("name", ""), "desc": elem.get("desc") or "",
                                "precise": [], "has_precise": False}
                elif do_stack is not None and tag in ("SDI", "DAI", "BDA"):
                    # 结构化实例链：DOI → SDI(Oper) → DAI(ctlVal)，深路径逐级记名
                    da_name_stack.append(elem.get("name") or "")
                continue

            # ── end 事件 ──
            if tag in ("SDI", "DAI", "BDA"):
                if do_stack is not None:
                    if tag in ("DAI", "BDA"):
                        addr = _extract_104_address(elem)
                        if addr is not None:
                            do_stack["precise"].append((".".join(da_name_stack), addr))
                            do_stack["has_precise"] = True
                    if da_name_stack:
                        da_name_stack.pop()
            elif tag == "DOI":
                if do_stack is not None:
                    if do_stack["has_precise"]:
                        for da_path, addr in do_stack["precise"]:
                            signals.append(ScdSignal(
                                ied=ied, ld_inst=ld_inst, ln_path=ln_path,
                                ln_desc=ln_desc, ln_type=ln_type,
                                do_name=do_stack["name"], do_desc=do_stack["desc"],
                                da_path=da_path, address=addr,
                            ))
                    else:
                        # 无精确映射的 DOI 作为推断候选（CDC 回填在 scd_to_points）
                        signals.append(ScdSignal(
                            ied=ied, ld_inst=ld_inst, ln_path=ln_path,
                            ln_desc=ln_desc, ln_type=ln_type,
                            do_name=do_stack["name"], do_desc=do_stack["desc"],
                            da_path="",
                        ))
                    do_stack = None
                    da_name_stack.clear()
                elem.clear()
            elif tag in _LN_TAGS:
                ln_path, ln_desc, ln_type = "", "", ""
                elem.clear()
            elif tag == "IED":
                ied = ""
                elem.clear()
            elif tag == "LNodeType":
                lntype_dos[elem.get("id", "")] = {
                    d.get("name", ""): d.get("type", "")
                    for d in elem.findall(f"{{{SCL_NS}}}DO")
                }
                elem.clear()
            elif tag == "DOType":
                dotype_cdc[elem.get("id", "")] = elem.get("cdc", "")
                elem.clear()
            elif tag == "Substation":
                if not station_name:
                    station_name = elem.get("name", "")
                elem.clear()
    except ET.ParseError as e:
        raise ValueError(f"SCD/SCL XML 解析失败: {e}") from e

    return signals, lntype_dos, dotype_cdc, station_name


def _extract_104_address(elem: ET.Element) -> ScdAddress | None:
    """从 DAI/BDA 子树提取 80-1 Address（兼容带/不带命名空间两种写法）."""
    for priv in elem.findall(f"{{{SCL_NS}}}Private"):
        if priv.get("type") != PRIVATE_104:
            continue
        for child in priv:
            if _local(child.tag) != "Address":
                continue
            try:
                return ScdAddress(
                    casdu=int(child.get("casdu", "0")),
                    ioa=int(child.get("ioa", "0")),
                    ti=int(child.get("ti", "0")),
                )
            except ValueError:
                return None
    return None


def import_scd(
    text: str,
    *,
    station_name: str = "",
    common_addr: int | None = None,
    ioa_bases: dict[str, int] | None = None,
) -> ScdImportResult:
    """一站式入口：解析 SCL 文本 → 信号抽取 → 104 点表 dict + 告警.

    ``common_addr`` 缺省取 SCD 中出现最多的 casdu；
    ``ioa_bases`` 覆盖推断模式的各类别 IOA 起始地址。
    """
    signals, lntype_dos, dotype_cdc, scd_station = parse_scl(text)

    # 回填 CDC（推断路径需要）
    for sig in signals:
        if sig.address is None and not sig.cdc:
            do_type = lntype_dos.get(sig.ln_type, {}).get(sig.do_name, "")
            sig.cdc = dotype_cdc.get(do_type, "")

    return _to_points(
        signals,
        station_name=station_name or scd_station,
        common_addr=common_addr,
        ioa_bases=ioa_bases,
    )


def _to_points(
    signals: list[ScdSignal],
    *,
    station_name: str,
    common_addr: int | None,
    ioa_bases: dict[str, int] | None,
) -> ScdImportResult:
    """信号清单 → 点表 dict（load_yaml 同构），处理 casdu 归并与 IOA 分配."""
    result = ScdImportResult(signals=signals, station_name=station_name)
    warnings: list[str] = []
    bases = dict(DEFAULT_IOA_BASES)
    if ioa_bases:
        bases.update(ioa_bases)

    # ── 公共地址归并 ──
    casdu_counter = Counter(s.address.casdu for s in signals if s.address)
    if common_addr is None:
        common_addr = casdu_counter.most_common(1)[0][0] if casdu_counter else 1
    result.common_addr = common_addr
    dropped = [s for s in signals if s.address and s.address.casdu != common_addr]
    if dropped:
        for casdu, n in sorted(Counter(s.address.casdu for s in dropped).items()):
            warnings.append(
                f"存在多个公共地址：casdu={casdu} 的 {n} 个信号未导入"
                f"（本站公共地址取 {common_addr}）"
            )
    usable = [s for s in signals if s.address is None or s.address.casdu == common_addr]

    # ── 分类 + 去重 + IOA 分配 ──
    used_ioa: set[int] = set()
    seen_precise: dict[tuple[str, int], str] = {}
    buckets: dict[str, list[dict]] = {"yx": [], "yc": [], "yk": [], "ym": [], "step": []}
    ti_unsupported: Counter = Counter()

    for sig in usable:
        if sig.address is not None:
            mapped = TI_MAP.get(sig.address.ti)
            if mapped is None:
                ti_unsupported[sig.address.ti] += 1
                continue
            kind, subtype = mapped
            ioa = sig.address.ioa
            key = (kind, ioa)
            if key in seen_precise:
                warnings.append(
                    f"IOA 冲突：{kind} {ioa} 已分配给 {seen_precise[key]}，"
                    f"忽略 {sig.signal_path()}（ti={sig.address.ti}）"
                )
                continue
            if not 0 < ioa <= _MAX_IOA:
                warnings.append(f"IOA 越界：{sig.signal_path()} ioa={ioa}，已忽略")
                continue
            seen_precise[key] = sig.signal_path()
        else:
            inferred = CDC_MAP.get(sig.cdc)
            if inferred is None:
                warnings.append(
                    f"CDC={sig.cdc or '未知'} 的 {sig.signal_path()} 无法单向推断"
                    f"（控制/设点方向需 80-1 映射），已跳过"
                )
                continue
            kind, subtype = inferred
            ioa = bases[kind]
            while ioa in used_ioa and ioa <= _MAX_IOA:
                ioa += 1
            if ioa > _MAX_IOA:
                warnings.append(f"{kind} IOA 地址空间耗尽，{sig.signal_path()} 未导入")
                continue
            bases[kind] = ioa + 1

        used_ioa.add(ioa)
        name = sig.display_name()
        if kind == "yx":
            point = {"ioa": ioa, "name": name, "group": 1, "enabled": True,
                     "type": subtype or "single", "initial_value": False,
                     "inverted": False}
        elif kind == "yc":
            point = {"ioa": ioa, "name": name, "group": 1, "enabled": True,
                     "type": subtype or "short_float", "initial_value": 0.0,
                     "min_value": -99999.0, "max_value": 99999.0,
                     "dead_band": 0.0, "unit": "", "scale": 1.0, "offset": 0.0,
                     "decimal_places": 2}
        elif kind == "yk":
            point = {"ioa": ioa, "name": name, "group": 1, "enabled": True,
                     "type": subtype or "single", "sbo": True, "timeout_ms": 10000}
        elif kind == "ym":
            point = {"ioa": ioa, "name": name, "group": 1, "enabled": True,
                     "initial_value": 0}
        else:  # step
            point = {"ioa": ioa, "name": name, "group": 1, "enabled": True,
                     "initial_value": 0, "min_value": -64, "max_value": 63,
                     "step_size": 1, "transient": False}
        buckets[kind].append(point)

    if ti_unsupported:
        detail = "、".join(f"ti={ti}×{n}" for ti, n in sorted(ti_unsupported.items()))
        warnings.append(f"本仓点表不支持的信息类型已跳过：{detail}（如比特串/保护事件）")

    for kind in buckets:
        buckets[kind].sort(key=lambda p: p["ioa"])

    result.warnings = warnings
    result.stats = {k: len(v) for k, v in buckets.items()} | {
        "signals_total": len(signals),
        "dropped_other_casdu": len(dropped),
    }
    result.points = {
        "station_name": station_name,
        "common_addr": common_addr,
        "yx": buckets["yx"],
        "yc": buckets["yc"],
        "yk": buckets["yk"],
        "ym": buckets["ym"],
        "step": buckets["step"],
    }
    return result
