"""ASDU (Application Service Data Unit) — 报文编解码器.

ASDU 结构:
  ┌──────────────┬─────┬──────────┬──────────────┬───────────────────────┐
  │ Type ID      │ VSQ │ COT      │ Common Addr  │ Information Objects   │
  │ 1 byte       │ 1B  │ 2 bytes  │ 2 bytes      │ (IOA + Data) × N      │
  └──────────────┴─────┴──────────┴──────────────┴───────────────────────┘
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .constants import (
    MAX_ASDU_LENGTH,
    VSQ_NUM_MASK,
    VSQ_SQ_BIT,
)
from .types import (
    COT,
    AckFileSection,
    BitString32,
    BitString32Command,
    CallDirectory,
    ClockSyncCommand,
    CounterValue,
    CP24Time2a,
    CP56Time2a,
    DelayCommand,
    DirectoryEntry,
    DoubleCommand,
    DoublePoint,
    FileReady,
    FileReadyAck,
    FileSegment,
    FileSelectCallGet,
    GroupSinglePointWithStatus,
    InitializationEnd,
    LastSection,
    NormalizedValue,
    ParameterActivation,
    ParameterCommandFloat,
    ParameterCommandNormalized,
    ParameterCommandNormalizedNoQuality,
    ProtectionEvent,
    QualityDescriptor,
    RegulatingStepCommand,
    ScaledValue,
    SectionReady,
    SectionReadyAck,
    SetpointCommandN,
    SetpointCommandS,
    SetpointCommandScaled,
    ShortFloat,
    SingleCommand,
    SinglePoint,
    StepPosition,
    TestCommandBitPattern,
    TypeID,
)
from .types import (
    ParameterCommandScaled as ParamCmdScaled,
)


@dataclass
class InformationObject:
    """信息对象 — ASDU 的基本数据单元."""
    ioa: int = 0                # 信息对象地址 (1-3字节)
    data: Any = None            # 具体数据 (SinglePoint/NormalizedValue/etc.)
    time_tag: CP56Time2a | None = None  # 时标（可选）


# ═══════════════════════════════════════════════════════════════════
#  自定义（非标准厂商私有）TypeID 支持（T22）
# ═══════════════════════════════════════════════════════════════════
#
# 现场存在厂商私有类型（如 71/108/109/128/129）。标准 72 类型之外的 TypeID
# 默认无法解码 → 触发 COT=42（未知类型标识）错误应答。本模块提供**按配置注册**
# 自定义类型的机制，使这类报文可编解码往返；**未注册**的类型行为保持不变
# （仍回 COT=42/43/44），标准类型不受影响。
#
# 配置形态（YAML / dict / JSON）二选一：
#
#   custom_types:                # 列表式
#     - type_id: 128
#       name: VendorAlarm
#       fields:
#         - {name: level, type: u8}
#         - {name: value, type: i16}
#         - {name: qds,   type: qds}     # 品质描述词(1B)
#         - {name: ts,    type: cp56}    # CP56Time2a 时标(7B)
#
#   128: {name: VendorAlarm, fields: [...]}   # 映射式（键即 type_id）
#
# 字段类型（小端编码，符合 IEC 104 数值约定）：
#   u8/i8/bool/qds(1B)  u16/i16(2B)  u32/i32/f32(4B)  f64(8B)
#   cp56(7B)  cp24(3B)  bytes(需 length)
#
# 注：自定义类型的时标以显式字段（cp56/cp24）表达，而非 ASDU 通用时标机制；
# 这样无需改动 *_TIMED_TYPES 集合，语义更直白，也避免与标准类型交叉影响。

_CUSTOM_FIELD_SIZES: dict[str, int] = {
    "u8": 1, "i8": 1, "bool": 1, "qds": 1,
    "u16": 2, "i16": 2,
    "u32": 4, "i32": 4, "f32": 4,
    "f64": 8,
    "cp56": 7, "cp24": 3,
}
_CUSTOM_FIELD_FMT: dict[str, str] = {
    "u8": "<B", "i8": "<b", "bool": "<B", "qds": "<B",
    "u16": "<H", "i16": "<h",
    "u32": "<I", "i32": "<i", "f32": "<f", "f64": "<d",
}


@dataclass
class CustomField:
    """自定义类型的一个字段描述."""
    name: str
    type: str = "u8"
    length: int = 0     # 仅 type == "bytes" 有效

    def size(self) -> int:
        if self.type == "bytes":
            if self.length <= 0:
                raise ValueError(f"field '{self.name}': bytes 类型需 length>0")
            return self.length
        if self.type not in _CUSTOM_FIELD_SIZES:
            raise ValueError(f"field '{self.name}': 未知字段类型 '{self.type}'")
        return _CUSTOM_FIELD_SIZES[self.type]


@dataclass
class CustomTypeDef:
    """自定义 TypeID 的结构定义."""
    type_id: int
    name: str = ""
    fields: list[CustomField] = field(default_factory=list)

    def data_size(self) -> int:
        """信息体数据段固定长度（不含 IOA）."""
        return sum(f.size() for f in self.fields)


@dataclass
class CustomObject:
    """自定义类型的信息体数据对象（``values`` 按字段名取值）."""
    type_id: int = 0
    values: dict = field(default_factory=dict)

    def to_bytes(self) -> bytes:
        """按注册的结构定义编码为字节（小端）."""
        typedef = CUSTOM_TYPES.get(self.type_id)
        if typedef is None:
            raise ValueError(f"custom type {self.type_id} 未注册")
        out = bytearray()
        for f in typedef.fields:
            v = self.values.get(f.name)
            if f.type == "bytes":
                b = bytes(v or b"")
                out += b[:f.length].ljust(f.length, b"\x00")
            elif f.type == "cp56":
                out += (v if isinstance(v, CP56Time2a) else CP56Time2a.now()).to_bytes()
            elif f.type == "cp24":
                out += (v if isinstance(v, CP24Time2a) else CP24Time2a.now()).to_bytes()
            elif f.type == "bool":
                out += struct.pack(_CUSTOM_FIELD_FMT["bool"], 1 if v else 0)
            else:
                out += struct.pack(_CUSTOM_FIELD_FMT[f.type], v if v is not None else 0)
        return bytes(out)

    @classmethod
    def decode(cls, type_id: int, data: bytes,
               typedef: CustomTypeDef) -> tuple[CustomObject, int]:
        """按结构定义解码，返回 (对象, 消耗字节数)."""
        obj = cls(type_id=int(type_id), values={})
        pos = 0
        for f in typedef.fields:
            size = f.size()
            if len(data) - pos < size:
                raise ValueError(
                    f"custom type {type_id} 数据不足: 字段 '{f.name}' 需 {size}B"
                )
            chunk = data[pos:pos + size]
            pos += size
            if f.type == "bytes":
                obj.values[f.name] = bytes(chunk)
            elif f.type == "cp56":
                obj.values[f.name] = CP56Time2a.from_bytes(chunk)
            elif f.type == "cp24":
                obj.values[f.name] = CP24Time2a.from_bytes(chunk)
            elif f.type == "bool":
                obj.values[f.name] = bool(struct.unpack(_CUSTOM_FIELD_FMT["bool"], chunk)[0])
            else:
                obj.values[f.name] = struct.unpack(_CUSTOM_FIELD_FMT[f.type], chunk)[0]
        return obj, pos


def _custom_typedef_from_dict(d: dict) -> CustomTypeDef:
    fields: list[CustomField] = []
    for fs in d.get("fields", []) or []:
        if isinstance(fs, str):
            fields.append(CustomField(name=fs, type="u8"))
        else:
            fields.append(CustomField(
                name=str(fs.get("name", "")),
                type=str(fs.get("type", "u8")).lower(),
                length=int(fs.get("length", 0) or 0),
            ))
    return CustomTypeDef(
        type_id=int(d["type_id"]),
        name=str(d.get("name", "")),
        fields=fields,
    )


class CustomTypeRegistry:
    """自定义 TypeID 注册表.

    注册后 ``ASDU.decode`` 即可解析对应类型；``unregister`` / ``clear`` 可撤销。
    标准类型（``TypeID`` 已定义者）**不允许**注册为自定义，避免遮蔽既有语义。
    """

    def __init__(self) -> None:
        self._defs: dict[int, CustomTypeDef] = {}

    def register(self, typedef: CustomTypeDef) -> None:
        tid = int(typedef.type_id)
        if tid < 0 or tid > 255:
            raise ValueError(f"type_id {tid} 超出 0-255")
        try:
            TypeID(tid)
        except ValueError:
            pass
        else:
            raise ValueError(f"type_id {tid} 是标准类型，不能注册为自定义类型")
        for f in typedef.fields:      # 触发字段类型校验
            f.size()
        self._defs[tid] = typedef

    def unregister(self, type_id: int) -> bool:
        return self._defs.pop(int(type_id), None) is not None

    def get(self, type_id: int) -> CustomTypeDef | None:
        try:
            return self._defs.get(int(type_id))
        except (TypeError, ValueError):
            return None

    def clear(self) -> None:
        self._defs.clear()

    def ids(self) -> list[int]:
        return sorted(self._defs)

    def load_dict(self, config: dict) -> int:
        """从 dict 装载（支持 ``{custom_types: [...]}`` 或 ``{type_id: {...}}``），返回加载数."""
        entries: Any = config
        if isinstance(config, dict) and "custom_types" in config:
            entries = config["custom_types"]
        count = 0
        if isinstance(entries, list):
            for item in entries:
                self.register(_custom_typedef_from_dict(item))
                count += 1
        elif isinstance(entries, dict):
            for key, item in entries.items():
                d = dict(item or {})
                d.setdefault("type_id", int(key))
                self.register(_custom_typedef_from_dict(d))
                count += 1
        return count

    def load_yaml(self, path) -> int:
        """从 YAML 文件装载配置."""
        import yaml

        with open(path, encoding="utf-8") as f:
            return self.load_dict(yaml.safe_load(f) or {})

    def load_json(self, path) -> int:
        """从 JSON 文件装载配置."""
        import json

        with open(path, encoding="utf-8") as f:
            return self.load_dict(json.load(f) or {})


# 全局默认注册表（引擎/ASDU 编解码共用）
CUSTOM_TYPES = CustomTypeRegistry()


@dataclass
class ASDU:
    """Application Service Data Unit."""
    type_id: TypeID = TypeID.M_SP_NA_1
    sq: bool = False            # 结构限定词: True=连续, False=单独
    num: int = 1                # 信息对象数量
    cot: int = COT.SPONT        # 传送原因 (bit0-5: 原因码)
    pn: bool = False            # 否定确认标志 (COT bit6): False=肯定, True=否定
    test: bool = False          # 试验标志 (COT bit7): True=试验报文，非真实数据
    origin_addr: int = 0        # 发起地址
    common_addr: int = 1        # 公共地址 (站地址)
    objects: list[InformationObject] = field(default_factory=list)

    # ── 类级缓存（lazy init）──────────────────────────────────────
    _DECODERS: ClassVar[dict | None] = None
    _TIMED_TYPES: ClassVar[set | None] = None
    _CP56_TYPES: ClassVar[set | None] = None

    @classmethod
    def _ensure_decoders(cls) -> None:
        """延迟初始化解码器字典和类型集合，避免每次调用重建."""
        if cls._DECODERS is not None:
            return
        cls._DECODERS = {
            # ── 单点信息 ──
            TypeID.M_SP_NA_1: (1, lambda d: SinglePoint.from_bytes(d)),
            TypeID.M_SP_TA_1: (1, lambda d: SinglePoint.from_bytes(d)),
            TypeID.M_SP_TB_1: (1, lambda d: SinglePoint.from_bytes(d)),

            # ── 双点信息 ──
            TypeID.M_DP_NA_1: (1, lambda d: DoublePoint.from_bytes(d)),
            TypeID.M_DP_TA_1: (1, lambda d: DoublePoint.from_bytes(d)),
            TypeID.M_DP_TB_1: (1, lambda d: DoublePoint.from_bytes(d)),

            # ── 步位置 ──
            TypeID.M_ST_NA_1: (2, lambda d: StepPosition.from_bytes(d)),
            TypeID.M_ST_TB_1: (2, lambda d: StepPosition.from_bytes(d)),

            # ── 32比特串 ──
            TypeID.M_BO_NA_1: (4, lambda d: BitString32.from_bytes(d)),
            TypeID.M_BO_TB_1: (4, lambda d: BitString32.from_bytes(d)),

            # ── 归一化值 ──
            TypeID.M_ME_NA_1: (3, lambda d: NormalizedValue.from_bytes(d)),
            TypeID.M_ME_TA_1: (3, lambda d: NormalizedValue.from_bytes(d)),
            TypeID.M_ME_TD_1: (3, lambda d: NormalizedValue.from_bytes(d)),
            # M_ME_ND_1 不带品质描述词：仅 2 字节 NVA。
            # 安全性来源：解码器只拿到 2 字节切片，而 NormalizedValue.from_bytes
            # 有长度保护（len(data) > offset+2 才读品质），故品质恒为 GOOD、
            # 不会读到下一对象首字节。显式补 0 品质字节使语义更直白，并防止
            # 将来去掉该保护时被污染。
            TypeID.M_ME_ND_1: (2, lambda d: NormalizedValue.from_bytes(d[:2] + b"\x00")),

            # ── 标度化值 ──
            TypeID.M_ME_NB_1: (3, lambda d: ScaledValue.from_bytes(d)),
            TypeID.M_ME_TB_1: (3, lambda d: ScaledValue.from_bytes(d)),
            TypeID.M_ME_TE_1: (3, lambda d: ScaledValue.from_bytes(d)),

            # ── 短浮点数 ──
            TypeID.M_ME_NC_1: (5, lambda d: ShortFloat.from_bytes(d)),
            TypeID.M_ME_TC_1: (5, lambda d: ShortFloat.from_bytes(d)),
            TypeID.M_ME_TF_1: (5, lambda d: ShortFloat.from_bytes(d)),

            # ── 累计量 ──
            TypeID.M_IT_NA_1: (5, lambda d: CounterValue.from_bytes(d)),
            TypeID.M_IT_TA_1: (5, lambda d: CounterValue.from_bytes(d)),
            TypeID.M_IT_TB_1: (5, lambda d: CounterValue.from_bytes(d)),

            # ── 控制命令 ──
            TypeID.C_SC_NA_1: (1, lambda d: SingleCommand.from_bytes(d)),
            TypeID.C_DC_NA_1: (1, lambda d: DoubleCommand.from_bytes(d)),
            TypeID.C_RC_NA_1: (1, lambda d: RegulatingStepCommand.from_bytes(d)),
            TypeID.C_SE_NA_1: (3, lambda d: SetpointCommandN.from_bytes(d)),
            TypeID.C_SE_NB_1: (3, lambda d: SetpointCommandScaled.from_bytes(d)),
            TypeID.C_SE_NC_1: (5, lambda d: SetpointCommandS.from_bytes(d)),
            TypeID.C_BO_NA_1: (4, lambda d: BitString32Command.from_bytes(d)),

            # ── 控制命令（带时标 CP56Time2a，数据体 = 命令 + 7字节时标）──
            TypeID.C_SC_TA_1: (1, lambda d: SingleCommand.from_bytes(d)),
            TypeID.C_DC_TA_1: (1, lambda d: DoubleCommand.from_bytes(d)),
            TypeID.C_RC_TA_1: (1, lambda d: RegulatingStepCommand.from_bytes(d)),
            TypeID.C_SE_TA_1: (3, lambda d: SetpointCommandN.from_bytes(d)),
            TypeID.C_SE_TB_1: (3, lambda d: SetpointCommandScaled.from_bytes(d)),
            TypeID.C_SE_TC_1: (5, lambda d: SetpointCommandS.from_bytes(d)),
            TypeID.C_BO_TA_1: (4, lambda d: BitString32Command.from_bytes(d)),

            # ── 系统命令 ──
            TypeID.C_IC_NA_1: (1, lambda d: d),      # 总召唤
            TypeID.C_CI_NA_1: (1, lambda d: d),      # 累计量召唤
            TypeID.C_RD_NA_1: (0, lambda d: None),   # 读命令
            TypeID.C_CS_NA_1: (7, lambda d: ClockSyncCommand.from_bytes(d)),  # 时钟同步
            TypeID.C_TS_NA_1: (2, lambda d: d),      # 测试命令
            TypeID.C_RP_NA_1: (1, lambda d: d),      # 复位进程
            # 延时获得：解成 DelayCommand（原为原始字节，导致子站读不到 delay_ms）
            TypeID.C_CD_NA_1: (2, lambda d: DelayCommand.from_bytes(d)),
            TypeID.C_TS_TA_1: (9, lambda d: d),      # 带时标测试

            # ── 步位置（带时标）──
            TypeID.M_ST_TA_1: (2, lambda d: StepPosition.from_bytes(d)),

            # ── 32比特串（带时标）──
            TypeID.M_BO_TA_1: (4, lambda d: BitString32.from_bytes(d)),

            # ── 继电保护事件（数据体 = SEP/QDP 2+1 字节，时标由通用时标机制追加）──
            TypeID.M_EP_TA_1: (3, lambda d: ProtectionEvent.from_bytes_short_time(d)),
            TypeID.M_EP_TB_1: (3, lambda d: ProtectionEvent.from_bytes_short_time(d)),
            TypeID.M_EP_TC_1: (3, lambda d: ProtectionEvent.from_bytes_short_time(d)),
            TypeID.M_EP_TD_1: (3, lambda d: ProtectionEvent.from_bytes_long_time(d)),
            TypeID.M_EP_TE_1: (3, lambda d: ProtectionEvent.from_bytes_long_time(d)),
            TypeID.M_EP_TF_1: (3, lambda d: ProtectionEvent.from_bytes_long_time(d)),

            # ── 成组单点 ──
            TypeID.M_PS_NA_1: (2, lambda d: GroupSinglePointWithStatus.from_bytes(d)),
            TypeID.M_PS_TB_1: (2, lambda d: GroupSinglePointWithStatus.from_bytes(d)),

            # ── 初始化结束 ──
            TypeID.M_EI_NA_1: (1, lambda d: InitializationEnd.from_bytes(d)),

            # ── 测试命令（位模式）──
            TypeID.C_TS_NB_1: (2, lambda d: TestCommandBitPattern.from_bytes(d)),

            # ── 参数命令 ──
            TypeID.P_ME_NA_1: (3, lambda d: ParameterCommandNormalized.from_bytes(d)),
            TypeID.P_ME_NB_1: (3, lambda d: ParamCmdScaled.from_bytes(d)),
            TypeID.P_ME_NC_1: (5, lambda d: ParameterCommandFloat.from_bytes(d)),
            TypeID.P_ME_ND_1: (2, lambda d: ParameterCommandNormalizedNoQuality.from_bytes(d)),
            TypeID.P_AC_NA_1: (1, lambda d: ParameterActivation.from_bytes(d)),

            # ── 文件传输 ──
            # 信息体长度（不含 IOA）：LOF 为 24 位 → F_FR=6、F_SR=7、F_DR=13
            TypeID.F_FR_NA_1: (6, lambda d: FileReady.from_bytes(d)),
            TypeID.F_SR_NA_1: (7, lambda d: SectionReady.from_bytes(d)),
            TypeID.F_SC_NA_1: (4, lambda d: CallDirectory.from_bytes(d)),
            TypeID.F_LS_NA_1: (5, lambda d: LastSection.from_bytes(d)),
            TypeID.F_AF_NA_1: (4, lambda d: AckFileSection.from_bytes(d)),
            TypeID.F_SG_NA_1: (-1, lambda d: FileSegment.from_bytes(d)),  # 可变长度
            TypeID.F_DR_TA_1: (13, lambda d: DirectoryEntry.from_bytes(d)),
            TypeID.F_SC_NB_1: (4, lambda d: FileSelectCallGet.from_bytes(d)),
            TypeID.F_FR_NB_1: (6, lambda d: FileReadyAck.from_bytes(d)),
            TypeID.F_SR_NB_1: (7, lambda d: SectionReadyAck.from_bytes(d)),
        }
        cls._TIMED_TYPES = {
            TypeID.M_SP_TA_1, TypeID.M_SP_TB_1,
            TypeID.M_DP_TA_1, TypeID.M_DP_TB_1,
            TypeID.M_ST_TA_1, TypeID.M_ST_TB_1,
            TypeID.M_BO_TA_1, TypeID.M_BO_TB_1,
            TypeID.M_ME_TA_1, TypeID.M_ME_TD_1,
            TypeID.M_ME_TB_1, TypeID.M_ME_TE_1,
            TypeID.M_ME_TC_1, TypeID.M_ME_TF_1,
            TypeID.M_IT_TA_1, TypeID.M_IT_TB_1,
            TypeID.M_EP_TA_1, TypeID.M_EP_TB_1, TypeID.M_EP_TC_1,
            TypeID.M_EP_TD_1, TypeID.M_EP_TE_1, TypeID.M_EP_TF_1,
            TypeID.M_PS_TB_1,
            TypeID.C_SC_TA_1, TypeID.C_DC_TA_1, TypeID.C_RC_TA_1,
            TypeID.C_SE_TA_1, TypeID.C_SE_TB_1, TypeID.C_SE_TC_1,
            TypeID.C_BO_TA_1,
        }
        cls._CP56_TYPES = {
            TypeID.M_SP_TB_1, TypeID.M_DP_TB_1,
            TypeID.M_ST_TB_1, TypeID.M_BO_TB_1,
            TypeID.M_ME_TD_1, TypeID.M_ME_TE_1,
            TypeID.M_ME_TF_1, TypeID.M_IT_TB_1,
            TypeID.M_EP_TD_1, TypeID.M_EP_TE_1, TypeID.M_EP_TF_1,
            TypeID.M_PS_TB_1,
            TypeID.C_SC_TA_1, TypeID.C_DC_TA_1, TypeID.C_RC_TA_1,
            TypeID.C_SE_TA_1, TypeID.C_SE_TB_1, TypeID.C_SE_TC_1,
            TypeID.C_BO_TA_1,
        }

    @classmethod
    def _coerce_type_id(cls, raw: int):
        """把原始 TypeID 字节转为 ``TypeID``；**已注册**的自定义类型返回整数值.

        未注册（既非标准 ``TypeID``、也不在 ``CUSTOM_TYPES`` 中）时抛出
        ``ValueError``，与既有行为一致（调用方据此回送 COT=42 未知类型标识）。
        """
        try:
            return TypeID(raw)
        except ValueError:
            if CUSTOM_TYPES.get(raw) is not None:
                return int(raw)
            raise

    # ── 编码 ────────────────────────────────────────────────────────

    def encode(self) -> bytes:
        """编码 ASDU 为字节序列."""
        buf = bytearray()

        # Type ID
        buf.append(self.type_id)

        # VSQ
        vsq = self.num & VSQ_NUM_MASK
        if self.sq:
            vsq |= VSQ_SQ_BIT
        buf.append(vsq)

        # COT (2 bytes: cause + origin)
        # bit0-5: 传送原因码; bit6: P/N 否定确认; bit7: T 测试位
        cot_byte = (self.cot & 0x3F) | (0x40 if self.pn else 0) | (0x80 if self.test else 0)
        buf.append(cot_byte)
        buf.append(self.origin_addr & 0xFF)

        # Common Address (2 bytes, little-endian)
        buf.append(self.common_addr & 0xFF)
        buf.append((self.common_addr >> 8) & 0xFF)

        # Information Objects
        for i, obj in enumerate(self.objects):
            # IOA (3 bytes, little-endian) — 仅在非SQ模式或第一个对象时写入
            if not self.sq or i == 0:
                ioa = obj.ioa + i if self.sq else obj.ioa
                buf.append(ioa & 0xFF)
                buf.append((ioa >> 8) & 0xFF)
                buf.append((ioa >> 16) & 0xFF)

            # Data
            if obj.data is not None:
                buf.extend(self._encode_data(obj.data, self.type_id))

            # Time tag
            if obj.time_tag is not None:
                buf.extend(obj.time_tag.to_bytes())

        # 长度上限：ASDU 最大 253 字节（APDU 255 - APCI 2 字节的 0x68/长度域）
        if len(buf) > MAX_ASDU_LENGTH:
            raise ValueError(
                f"ASDU too long: {len(buf)} bytes > {MAX_ASDU_LENGTH} "
                f"(type={self.type_id}, num={self.num}, sq={self.sq})"
            )
        return bytes(buf)

    def _encode_data(self, data: Any, type_id: TypeID | None = None) -> bytes:
        """编码信息对象数据.

        Args:
            data: 待编码对象
            type_id: 所属类型标识（用于区分同结构但长度不同的类型，如 M_ME_ND_1）
        """
        # M_ME_ND_1: 测量值不带品质描述词 — 仅 2 字节 NVA，无 QDS
        if type_id == TypeID.M_ME_ND_1:
            raw = data.to_bytes()
            return raw[:2]
        if hasattr(data, 'to_bytes'):
            return data.to_bytes()
        elif isinstance(data, bytes):
            return data
        raise TypeError(f"Cannot encode data type: {type(data)}")

    # ── 解码 ────────────────────────────────────────────────────────

    @classmethod
    def decode(cls, data: bytes, ca_length: int = 2) -> ASDU:
        """从字节序列解码 ASDU.

        Args:
            data: ASDU 字节数据（不含APCI头）
            ca_length: 公共地址长度 (1或2)
        """
        if len(data) < 4 + ca_length:
            raise ValueError(f"ASDU too short: {len(data)} bytes")

        pos = 0

        # Type ID（未注册的自定义类型会抛出 ValueError，行为与既有一致）
        raw_type = data[pos]
        type_id = cls._coerce_type_id(raw_type)
        pos += 1

        # VSQ
        vsq = data[pos]
        pos += 1
        sq = bool(vsq & VSQ_SQ_BIT)
        num = vsq & VSQ_NUM_MASK

        # COT (bit0-5: 原因码, bit6: P/N 否定确认, bit7: T 测试位)
        cot_byte = data[pos]
        pn = bool(cot_byte & 0x40)
        test = bool(cot_byte & 0x80)
        cot = cot_byte & 0x3F
        pos += 1
        origin_addr = data[pos]
        pos += 1

        # Common Address
        if ca_length == 2:
            common_addr = data[pos] | (data[pos + 1] << 8)
            pos += 2
        else:
            common_addr = data[pos]
            pos += 1

        asdu = cls(
            type_id=type_id,
            sq=sq,
            num=num,
            cot=cot,
            pn=pn,
            test=test,
            origin_addr=origin_addr,
            common_addr=common_addr,
        )

        # Information Objects
        ioa_size = 3  # 标准IOA长度3字节
        remaining = data[pos:]
        base_ioa = 0

        for i in range(num):
            # SQ=1: 仅第一个对象有IOA字段，后续对象地址 = base + i
            if not sq or i == 0:
                if len(remaining) < ioa_size:
                    break
                base_ioa = remaining[0] | (remaining[1] << 8) | (remaining[2] << 16)
                remaining = remaining[ioa_size:]

            ioa = base_ioa + i if sq else base_ioa

            # Data + Time tag
            obj_data, time_tag, consumed = cls._decode_object_data(
                type_id, remaining, cot
            )

            asdu.objects.append(InformationObject(
                ioa=ioa,
                data=obj_data,
                time_tag=time_tag,
            ))
            remaining = remaining[consumed:]

        if len(asdu.objects) != num:
            raise ValueError(
                f"Truncated ASDU: expected {num} objects, decoded {len(asdu.objects)}"
            )

        return asdu

    @classmethod
    def decode_header(cls, data: bytes, ca_length: int = 2) -> ASDU:
        """仅解析 ASDU 头部（TypeID / VSQ / COT+PN / CA），不解析信息体.

        用于信息体类型未知或无法解析时仍能提取头部字段，以便按标准
        回送 "未知类型标识/未知传送原因/未知公共地址" 应答。

        Args:
            data: ASDU 字节数据（不含APCI头）
            ca_length: 公共地址长度 (1或2)

        Returns:
            仅含头部字段、objects 为空的 ASDU；
            未知 TypeID 时 type_id 保存原始整数值。
        """
        if len(data) < 4 + ca_length:
            raise ValueError(f"ASDU too short: {len(data)} bytes")

        pos = 0

        raw_type = data[pos]
        pos += 1
        try:
            type_id: Any = TypeID(raw_type)
        except ValueError:
            type_id = raw_type  # 未知类型标识：保留原始整数值

        vsq = data[pos]
        pos += 1
        sq = bool(vsq & VSQ_SQ_BIT)
        num = vsq & VSQ_NUM_MASK

        cot_byte = data[pos]
        pn = bool(cot_byte & 0x40)
        test = bool(cot_byte & 0x80)
        cot = cot_byte & 0x3F
        pos += 1
        origin_addr = data[pos]
        pos += 1

        if ca_length == 2:
            common_addr = data[pos] | (data[pos + 1] << 8)
        else:
            common_addr = data[pos]

        return cls(
            type_id=type_id,
            sq=sq,
            num=num,
            cot=cot,
            pn=pn,
            test=test,
            origin_addr=origin_addr,
            common_addr=common_addr,
        )

    @classmethod
    def _decode_object_data(cls, type_id: TypeID, data: bytes, cot: int
                             ) -> tuple[Any, CP56Time2a | None, int]:
        """解码信息对象的数据部分.

        Returns:
            (data, time_tag, consumed_bytes)
        """
        cls._ensure_decoders()

        if type_id not in cls._DECODERS:
            typedef = CUSTOM_TYPES.get(type_id)
            if typedef is not None:
                obj, consumed = CustomObject.decode(type_id, data, typedef)
                return obj, None, consumed
            # 未注册的未知类型 — 跳过（调用方据解码失败回 COT=42）
            return None, None, 0

        data_size, decoder = cls._DECODERS[type_id]

        # 可变长度类型（如FileSegment）
        if data_size == -1:
            # 对于可变长度类型，传递所有剩余数据给decoder
            obj_data = decoder(data)
            # 计算实际消耗的字节数
            if hasattr(obj_data, 'to_bytes'):
                consumed = len(obj_data.to_bytes())
            else:
                consumed = len(data)
        else:
            if len(data) < data_size:
                # 固定长度对象数据不足：显式报错，避免截断帧被静默吞掉
                raise ValueError(
                    f"Insufficient data for {type_id}: need {data_size}B, "
                    f"have {len(data)}B"
                )
            obj_data = decoder(data[:data_size])
            consumed = data_size

        # 时标
        time_tag = None
        if type_id in cls._TIMED_TYPES:
            if type_id in cls._CP56_TYPES:
                if len(data) >= consumed + 7:
                    time_tag = CP56Time2a.from_bytes(data, consumed)
                    consumed += 7
            else:
                # CP24Time2a (短时标, 3 字节) — 保持原始类型，
                # 避免转换为 CP56Time2a 后回编码时标长度由 3 膨胀为 7
                if len(data) >= consumed + 3:
                    time_tag = CP24Time2a.from_bytes(data, consumed)
                    consumed += 3

        return obj_data, time_tag, consumed


# ═══════════════════════════════════════════════════════════════════
#  ASDU Builder — 快速构造常用报文
# ═══════════════════════════════════════════════════════════════════

class ASDUBuilder:
    """ASDU 报文构建器，提供常用报文的快捷构造方法."""

    @staticmethod
    def build_general_interrogation(common_addr: int, qoi: int = 20,
                                     cot: int = COT.ACT) -> bytes:
        """构造总召唤命令 (C_IC_NA_1).

        Args:
            common_addr: 站地址
            qoi: 限定词 (20=站召唤, 21-36=第1-16组召唤)
            cot: 传送原因
        """
        asdu = ASDU(
            type_id=TypeID.C_IC_NA_1,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        obj = InformationObject(
            ioa=0,
            data=bytes([qoi]),  # QOI 限定词
        )
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_general_interrogation_ack(common_addr: int, qoi: int = 20,
                                         cot: int = COT.ACTCON) -> bytes:
        """构造总召唤确认（cot 可覆盖，供错误 COT 注入测试使用）."""
        return ASDUBuilder.build_general_interrogation(
            common_addr, qoi, cot=cot
        )

    @staticmethod
    def build_general_interrogation_end(common_addr: int, qoi: int = 20,
                                         cot: int = COT.ACTTERM) -> bytes:
        """构造总召唤结束（cot 可覆盖，供错误 COT 注入测试使用）."""
        return ASDUBuilder.build_general_interrogation(
            common_addr, qoi, cot=cot
        )

    @staticmethod
    def build_clock_sync(common_addr: int, time_tag: CP56Time2a | None = None) -> bytes:
        """构造时钟同步命令 (C_CS_NA_1)."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(
            type_id=TypeID.C_CS_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(
            ioa=0,
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_clock_sync_ack(common_addr: int, time_tag: CP56Time2a | None = None,
                              cot: int = COT.ACTCON) -> bytes:
        """构造时钟同步确认（cot 可覆盖，供错误 COT 注入测试使用）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(
            type_id=TypeID.C_CS_NA_1,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(
            ioa=0,
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_counter_interrogation(common_addr: int,
                                     qcc: int = 0) -> bytes:
        """构造累计量召唤命令 (C_CI_NA_1)."""
        asdu = ASDU(
            type_id=TypeID.C_CI_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(
            ioa=0,
            data=bytes([qcc]),
        ))
        return asdu.encode()

    @staticmethod
    def build_reset_process(common_addr: int, qrp: int = 1) -> bytes:
        """构造复位进程命令 (C_RP_NA_1).

        qrp: 1=进程总复位, 2=复位事件缓冲区
        """
        asdu = ASDU(
            type_id=TypeID.C_RP_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(
            ioa=0,
            data=bytes([qrp]),
        ))
        return asdu.encode()

    @staticmethod
    def build_test_command(common_addr: int) -> bytes:
        """构造测试命令 (C_TS_NA_1)."""
        asdu = ASDU(
            type_id=TypeID.C_TS_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(
            ioa=0,
            data=bytes([0xAA, 0x55]),  # 固定测试字
        ))
        return asdu.encode()

    @staticmethod
    def build_single_point_sequence(common_addr: int, points: list[tuple[int, bool, int]],
                                     cot: int = COT.INTROGEN) -> bytes:
        """构造单点遥信序列 (M_SP_NA_1, SQ=1).

        Args:
            points: [(ioa, value, quality), ...] 必须按ioa连续排列
        """
        asdu = ASDU(
            type_id=TypeID.M_SP_NA_1,
            sq=True,
            num=len(points),
            cot=cot,
            common_addr=common_addr,
        )
        for ioa, value, quality in points:
            sp = SinglePoint(value=value, quality=QualityDescriptor(quality))
            asdu.objects.append(InformationObject(ioa=ioa, data=sp))
        return asdu.encode()

    @staticmethod
    def build_short_float_sequence(common_addr: int, points: list[tuple[int, float, int]],
                                    cot: int = COT.INTROGEN) -> bytes:
        """构造短浮点遥测序列 (M_ME_NC_1, SQ=1).

        Args:
            points: [(ioa, value, quality), ...] 必须按ioa连续排列
        """
        asdu = ASDU(
            type_id=TypeID.M_ME_NC_1,
            sq=True,
            num=len(points),
            cot=cot,
            common_addr=common_addr,
        )
        for ioa, value, quality in points:
            sf = ShortFloat(value=value, quality=QualityDescriptor(quality))
            asdu.objects.append(InformationObject(ioa=ioa, data=sf))
        return asdu.encode()

    @staticmethod
    def build_single_point(common_addr: int, ioa: int, value: bool,
                            quality: int = 0, cot: int = COT.SPONT,
                            with_time: bool = False) -> bytes:
        """构造单点遥信 (M_SP_NA_1 或 M_SP_TB_1)."""
        if with_time:
            type_id = TypeID.M_SP_TB_1
        else:
            type_id = TypeID.M_SP_NA_1

        asdu = ASDU(
            type_id=type_id,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        sp = SinglePoint(value=value, quality=QualityDescriptor(quality))
        obj = InformationObject(ioa=ioa, data=sp)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_normalized_value(common_addr: int, ioa: int, value: float,
                                quality: int = 0, cot: int = COT.SPONT,
                                with_time: bool = False) -> bytes:
        """构造归一化遥测 (M_ME_NA_1 或 M_ME_TD_1)."""
        if with_time:
            type_id = TypeID.M_ME_TD_1
        else:
            type_id = TypeID.M_ME_NA_1

        asdu = ASDU(
            type_id=type_id,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        nv = NormalizedValue(value=value, quality=QualityDescriptor(quality))
        obj = InformationObject(ioa=ioa, data=nv)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_short_float(common_addr: int, ioa: int, value: float,
                           quality: int = 0, cot: int = COT.SPONT,
                           with_time: bool = False) -> bytes:
        """构造短浮点遥测 (M_ME_NC_1 或 M_ME_TF_1)."""
        if with_time:
            type_id = TypeID.M_ME_TF_1
        else:
            type_id = TypeID.M_ME_NC_1

        asdu = ASDU(
            type_id=type_id,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        sf = ShortFloat(value=value, quality=QualityDescriptor(quality))
        obj = InformationObject(ioa=ioa, data=sf)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_scaled_value(common_addr: int, ioa: int, value: int,
                            quality: int = 0, cot: int = COT.SPONT,
                            with_time: bool = False,
                            time_tag: CP56Time2a | None = None) -> bytes:
        """构造标度化遥测 (M_ME_NB_1 或带 CP56 时标的 M_ME_TE_1).

        与前两个遥测构造器（归一化 / 短浮点）保持对称，补齐 CP56 时标变体。
        """
        type_id = TypeID.M_ME_TE_1 if with_time else TypeID.M_ME_NB_1
        asdu = ASDU(type_id=type_id, sq=False, num=1, cot=cot,
                    common_addr=common_addr)
        sv = ScaledValue(value=value, quality=QualityDescriptor(quality))
        obj = InformationObject(ioa=ioa, data=sv)
        if with_time:
            obj.time_tag = time_tag if time_tag is not None else CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_initialization_end(common_addr: int, cot: int = COT.INIT,
                                  cause: int = 0) -> bytes:
        """构造初始化结束 (M_EI_NA_1 = 70，子站 STARTDT 激活后上送)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_EI_NA_1, common_addr, 0,
            InitializationEnd(cause=cause), cot)

    @staticmethod
    def build_single_command(common_addr: int, ioa: int, state: bool,
                              select: bool = False, qu: int = 0,
                              cot: int = COT.ACT) -> bytes:
        """构造单命令 (C_SC_NA_1).

        Args:
            cot: 传送原因；默认 ACT(6)，撤销（去激活）传 DEACT(8)（D1）。
        """
        asdu = ASDU(
            type_id=TypeID.C_SC_NA_1,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        sc = SingleCommand(ioa=ioa, state=state, select=select, qu=qu)
        asdu.objects.append(InformationObject(ioa=ioa, data=sc))
        return asdu.encode()

    @staticmethod
    def build_double_command(common_addr: int, ioa: int, state: int,
                              select: bool = False, qu: int = 0,
                              cot: int = COT.ACT) -> bytes:
        """构造双命令 (C_DC_NA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        asdu = ASDU(
            type_id=TypeID.C_DC_NA_1,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        dc = DoubleCommand(ioa=ioa, state=state, select=select, qu=qu)
        asdu.objects.append(InformationObject(ioa=ioa, data=dc))
        return asdu.encode()

    @staticmethod
    def build_setpoint_normalized(common_addr: int, ioa: int, value: float,
                                    select: bool = False,
                                    cot: int = COT.ACT) -> bytes:
        """构造归一化设点命令 (C_SE_NA_1)；``cot`` 传 DEACT(8) 表示撤销（D1，
        IEC 60870-5-101/104 中设点命令允许 DEACT 传输原因）."""
        asdu = ASDU(
            type_id=TypeID.C_SE_NA_1,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        sn = SetpointCommandN(ioa=ioa, value=value, select=select)
        asdu.objects.append(InformationObject(ioa=ioa, data=sn))
        return asdu.encode()

    @staticmethod
    def build_setpoint_shortfloat(common_addr: int, ioa: int, value: float,
                                    select: bool = False,
                                    cot: int = COT.ACT) -> bytes:
        """构造短浮点设点命令 (C_SE_NC_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        asdu = ASDU(
            type_id=TypeID.C_SE_NC_1,
            sq=False,
            num=1,
            cot=cot,
            common_addr=common_addr,
        )
        ss = SetpointCommandS(ioa=ioa, value=value, select=select)
        asdu.objects.append(InformationObject(ioa=ioa, data=ss))
        return asdu.encode()

    @staticmethod
    def build_group_response(common_addr: int, group: int,
                              objects: list[InformationObject]) -> bytes:
        """构造组召唤响应."""
        cot = COT.group_response(group)
        asdu = ASDU(
            type_id=TypeID.M_SP_NA_1,  # 实际类型取决于组内容
            sq=True,
            num=len(objects),
            cot=cot,
            common_addr=common_addr,
        )
        asdu.objects = objects
        return asdu.encode()

    @staticmethod
    def build_spontaneous_single_point(common_addr: int, ioa: int,
                                         value: bool, quality: int = 0) -> bytes:
        """构造自发单点遥信 (SOE)."""
        return ASDUBuilder.build_single_point(
            common_addr, ioa, value, quality,
            cot=COT.SPONT, with_time=True
        )

    @staticmethod
    def build_scaled_values_sequence(common_addr: int, ioa_base: int,
                                      values: list[int],
                                      cot: int = COT.INTROGEN) -> bytes:
        """构造标度化值序列 (SQ=1)."""
        asdu = ASDU(
            type_id=TypeID.M_ME_NB_1,
            sq=True,
            num=len(values),
            cot=cot,
            common_addr=common_addr,
        )
        for v in values:
            sv = ScaledValue(value=v)
            asdu.objects.append(InformationObject(ioa=ioa_base, data=sv))
        return asdu.encode()

    @staticmethod
    def build_counter_sequence(common_addr: int, points: list[tuple[int, int, int, int]],
                                cot: int = COT.INTROGEN) -> bytes:
        """构造累计量序列 (M_IT_NA_1, SQ=1).

        Args:
            common_addr: 公共地址
            points: [(ioa, value, quality, sequence), ...] 必须按ioa连续排列
            cot: 传送原因
        """
        asdu = ASDU(
            type_id=TypeID.M_IT_NA_1,
            sq=True,
            num=len(points),
            cot=cot,
            common_addr=common_addr,
        )
        for ioa, value, quality, sequence in points:
            cv = CounterValue(value=value, quality=QualityDescriptor(quality), sequence=sequence)
            asdu.objects.append(InformationObject(ioa=ioa, data=cv))
        return asdu.encode()

    @staticmethod
    def build_double_point(common_addr: int, ioa: int, value: int,
                            quality: int = 0, cot: int = COT.SPONT,
                            with_time: bool = False) -> bytes:
        """构造双点遥信 (M_DP_NA_1 或 M_DP_TB_1)."""
        type_id = TypeID.M_DP_TB_1 if with_time else TypeID.M_DP_NA_1
        asdu = ASDU(type_id=type_id, sq=False, num=1, cot=cot, common_addr=common_addr)
        dp = DoublePoint(value=value, quality=QualityDescriptor(quality))
        obj = InformationObject(ioa=ioa, data=dp)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_step_position(common_addr: int, ioa: int, value: int,
                             quality: int = 0, transient: bool = False,
                             cot: int = COT.SPONT, with_time: bool = False) -> bytes:
        """构造步位置信息 (M_ST_NA_1 或 M_ST_TB_1)."""
        type_id = TypeID.M_ST_TB_1 if with_time else TypeID.M_ST_NA_1
        asdu = ASDU(type_id=type_id, sq=False, num=1, cot=cot, common_addr=common_addr)
        sp = StepPosition(value=value, quality=QualityDescriptor(quality), transient=transient)
        obj = InformationObject(ioa=ioa, data=sp)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_bitstring32(common_addr: int, ioa: int, value: int,
                           quality: int = 0, cot: int = COT.SPONT,
                           with_time: bool = False) -> bytes:
        """构造32比特串 (M_BO_NA_1 或 M_BO_TB_1)."""
        type_id = TypeID.M_BO_TB_1 if with_time else TypeID.M_BO_NA_1
        asdu = ASDU(type_id=type_id, sq=False, num=1, cot=cot, common_addr=common_addr)
        bs = BitString32(value=value)
        obj = InformationObject(ioa=ioa, data=bs)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_counter_value(common_addr: int, ioa: int, value: int,
                             quality: int = 0, sequence: int = 0,
                             cot: int = COT.SPONT, with_time: bool = False) -> bytes:
        """构造累计量 (M_IT_NA_1 或 M_IT_TB_1)."""
        type_id = TypeID.M_IT_TB_1 if with_time else TypeID.M_IT_NA_1
        asdu = ASDU(type_id=type_id, sq=False, num=1, cot=cot, common_addr=common_addr)
        cv = CounterValue(value=value, quality=QualityDescriptor(quality), sequence=sequence)
        obj = InformationObject(ioa=ioa, data=cv)
        if with_time:
            obj.time_tag = CP56Time2a.now()
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_regulating_step_command(common_addr: int, ioa: int, state: int,
                                        select: bool = False, qu: int = 0,
                                        cot: int = COT.ACT) -> bytes:
        """构造升降命令 (C_RC_NA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        asdu = ASDU(type_id=TypeID.C_RC_NA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        rc = RegulatingStepCommand(ioa=ioa, state=state, select=select, qu=qu)
        asdu.objects.append(InformationObject(ioa=ioa, data=rc))
        return asdu.encode()

    @staticmethod
    def build_bitstring_command(common_addr: int, ioa: int, value: int,
                                 cot: int = COT.ACT) -> bytes:
        """构造比特串命令 (C_BO_NA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        asdu = ASDU(type_id=TypeID.C_BO_NA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        bc = BitString32Command(ioa=ioa, value=value)
        asdu.objects.append(InformationObject(ioa=ioa, data=bc))
        return asdu.encode()

    # ── 带时标 CP56Time2a 的控制命令 (TypeID 58-64) ──────────────

    @staticmethod
    def build_single_command_with_time(common_addr: int, ioa: int, state: bool,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None,
                                        cot: int = COT.ACT) -> bytes:
        """构造带时标单命令 (C_SC_TA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_SC_TA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=SingleCommand(ioa=ioa, state=state, select=select, qu=qu),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_double_command_with_time(common_addr: int, ioa: int, state: int,
                                        select: bool = False, qu: int = 0,
                                        time_tag: CP56Time2a | None = None,
                                        cot: int = COT.ACT) -> bytes:
        """构造带时标双命令 (C_DC_TA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_DC_TA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=DoubleCommand(ioa=ioa, state=state, select=select, qu=qu),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_regulating_step_command_with_time(common_addr: int, ioa: int, state: int,
                                                 select: bool = False, qu: int = 0,
                                                 time_tag: CP56Time2a | None = None,
                                                 cot: int = COT.ACT) -> bytes:
        """构造带时标升降命令 (C_RC_TA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_RC_TA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=RegulatingStepCommand(ioa=ioa, state=state, select=select, qu=qu),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_setpoint_normalized_with_time(common_addr: int, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None,
                                             cot: int = COT.ACT) -> bytes:
        """构造带时标归一化设点命令 (C_SE_TA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_SE_TA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=SetpointCommandN(ioa=ioa, value=value, select=select),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_setpoint_scaled_with_time(common_addr: int, ioa: int, value: int,
                                         select: bool = False,
                                         time_tag: CP56Time2a | None = None,
                                         cot: int = COT.ACT) -> bytes:
        """构造带时标标度化设点命令 (C_SE_TB_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_SE_TB_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=SetpointCommandScaled(ioa=ioa, value=value, select=select),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_setpoint_shortfloat_with_time(common_addr: int, ioa: int, value: float,
                                             select: bool = False,
                                             time_tag: CP56Time2a | None = None,
                                             cot: int = COT.ACT) -> bytes:
        """构造带时标短浮点设点命令 (C_SE_TC_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_SE_TC_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=SetpointCommandS(ioa=ioa, value=value, select=select),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_bitstring_command_with_time(common_addr: int, ioa: int, value: int,
                                           time_tag: CP56Time2a | None = None,
                                           cot: int = COT.ACT) -> bytes:
        """构造带时标比特串命令 (C_BO_TA_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_BO_TA_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=ioa, data=BitString32Command(ioa=ioa, value=value),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_read_command(common_addr: int, ioa: int) -> bytes:
        """构造读命令 (C_RD_NA_1)."""
        asdu = ASDU(type_id=TypeID.C_RD_NA_1, sq=False, num=1, cot=COT.REQ, common_addr=common_addr)
        asdu.objects.append(InformationObject(ioa=ioa, data=b''))
        return asdu.encode()

    @staticmethod
    def build_test_command_with_time(common_addr: int, time_tag: CP56Time2a | None = None) -> bytes:
        """构造带时标测试命令 (C_TS_TA_1)."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(type_id=TypeID.C_TS_TA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        data = bytes([0xAA, 0x55]) + time_tag.to_bytes()
        asdu.objects.append(InformationObject(ioa=0, data=data))
        return asdu.encode()

    @staticmethod
    def build_delay_command(common_addr: int, delay_ms: int) -> bytes:
        """构造延时获得命令 (C_CD_NA_1)."""
        asdu = ASDU(type_id=TypeID.C_CD_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        asdu.objects.append(InformationObject(
            ioa=0, data=DelayCommand(ioa=0, delay_ms=delay_ms)))
        return asdu.encode()

    @staticmethod
    def build_counter_interrogation_ack(common_addr: int, qcc: int = 0,
                                         cot: int = COT.ACTCON) -> bytes:
        """构造累计量召唤确认（COT=ACTCON，修正原先误用 COT=ACT 的问题）."""
        asdu = ASDU(
            type_id=TypeID.C_CI_NA_1, sq=False, num=1,
            cot=cot, common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(ioa=0, data=bytes([qcc])))
        return asdu.encode()

    @staticmethod
    def build_counter_interrogation_end(common_addr: int, qcc: int = 0) -> bytes:
        """构造累计量召唤结束."""
        asdu = ASDU(type_id=TypeID.C_CI_NA_1, sq=False, num=1, cot=COT.ACTTERM, common_addr=common_addr)
        asdu.objects.append(InformationObject(ioa=0, data=bytes([qcc])))
        return asdu.encode()

    @staticmethod
    def build_setpoint_scaled(common_addr: int, ioa: int, value: int,
                                select: bool = False,
                                cot: int = COT.ACT) -> bytes:
        """构造标度化设点命令 (C_SE_NB_1)；``cot`` 传 DEACT(8) 表示撤销（D1）."""
        asdu = ASDU(type_id=TypeID.C_SE_NB_1, sq=False, num=1, cot=cot, common_addr=common_addr)
        ss = SetpointCommandScaled(ioa=ioa, value=value, select=select)
        asdu.objects.append(InformationObject(ioa=ioa, data=ss))
        return asdu.encode()

    @staticmethod
    def build_reset_process_ack(common_addr: int, qrp: int = 1) -> bytes:
        """构造复位进程确认."""
        asdu = ASDU(type_id=TypeID.C_RP_NA_1, sq=False, num=1, cot=COT.ACTCON, common_addr=common_addr)
        asdu.objects.append(InformationObject(ioa=0, data=bytes([qrp])))
        return asdu.encode()

    @staticmethod
    def build_test_command_ack(common_addr: int) -> bytes:
        """构造测试命令确认."""
        return ASDUBuilder.build_test_command(common_addr)

    # ── 参数命令构建方法 ──────────────────────────────────────────

    @staticmethod
    def build_parameter_normalized(common_addr: int, ioa: int, value: float,
                                    param_change: int = 0) -> bytes:
        """构造测量值参数-归一化 (P_ME_NA_1).

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            value: 归一化值 (-1.0..+1.0)
            param_change: 参数变更标志 (0=未用, 1=运行中使用, 2=运行中不使用)
        """
        asdu = ASDU(type_id=TypeID.P_ME_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        pc = ParameterCommandNormalized(ioa=ioa, value=value, param_change=param_change)
        asdu.objects.append(InformationObject(ioa=ioa, data=pc))
        return asdu.encode()

    @staticmethod
    def build_parameter_scaled(common_addr: int, ioa: int, value: int,
                                param_change: int = 0) -> bytes:
        """构造测量值参数-标度化 (P_ME_NB_1).

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            value: 标度化值 (-32768..+32767)
            param_change: 参数变更标志
        """
        asdu = ASDU(type_id=TypeID.P_ME_NB_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        ps = ParamCmdScaled(ioa=ioa, value=value, param_change=param_change)
        asdu.objects.append(InformationObject(ioa=ioa, data=ps))
        return asdu.encode()

    @staticmethod
    def build_parameter_float(common_addr: int, ioa: int, value: float,
                               param_change: int = 0) -> bytes:
        """构造测量值参数-短浮点 (P_ME_NC_1).

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            value: 短浮点值
            param_change: 参数变更标志
        """
        asdu = ASDU(type_id=TypeID.P_ME_NC_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        pf = ParameterCommandFloat(ioa=ioa, value=value, param_change=param_change)
        asdu.objects.append(InformationObject(ioa=ioa, data=pf))
        return asdu.encode()

    @staticmethod
    def build_parameter_normalized_no_quality(common_addr: int, ioa: int, value: float) -> bytes:
        """构造不带品质描述词的测量值参数-归一化 (P_ME_ND_1).

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            value: 归一化值 (-1.0..+1.0)
        """
        asdu = ASDU(type_id=TypeID.P_ME_ND_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        pn = ParameterCommandNormalizedNoQuality(ioa=ioa, value=value)
        asdu.objects.append(InformationObject(ioa=ioa, data=pn))
        return asdu.encode()

    @staticmethod
    def build_parameter_activation(common_addr: int, ioa: int, qualifier: int = 1) -> bytes:
        """构造参数激活 (P_AC_NA_1).

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            qualifier: 0=未用/取消, 1=激活/周期, 2=去激活
        """
        asdu = ASDU(type_id=TypeID.P_AC_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        pa = ParameterActivation(ioa=ioa, qualifier=qualifier)
        asdu.objects.append(InformationObject(ioa=ioa, data=pa))
        return asdu.encode()

    # ── 文件传输构建方法 ──────────────────────────────────────────

    @staticmethod
    def build_file_ready(common_addr: int, ioa: int, file_name: int,
                          file_length: int, status: int = 0) -> bytes:
        """构造文件准备就绪 (F_FR_NA_1).

        信息体 = NOF(2) + LOF(3) + FRQ(1) = 6 字节（LOF 为 24 位）。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            file_length: 文件长度 (24-bit, 3 字节, LOF)
            status: FRQ 文件准备就绪限定词 (0=肯定, 0x80=否定)
        """
        asdu = ASDU(type_id=TypeID.F_FR_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        fr = FileReady(ioa=ioa, file_name=file_name, file_length=file_length, status=status)
        asdu.objects.append(InformationObject(ioa=ioa, data=fr))
        return asdu.encode()

    @staticmethod
    def build_section_ready(common_addr: int, ioa: int, file_name: int,
                             section_name: int, section_length: int, status: int = 0) -> bytes:
        """构造节准备就绪 (F_SR_NA_1).

        信息体 = NOF(2) + NOS(1) + LOF(3) + SRQ(1) = 7 字节（LOF 为 24 位）。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            section_name: 节名 (8-bit, NOS)
            section_length: 节长度 (24-bit, 3 字节, LOF)
            status: SRQ 节准备就绪限定词
        """
        asdu = ASDU(type_id=TypeID.F_SR_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        sr = SectionReady(ioa=ioa, file_name=file_name, section_name=section_name,
                          section_length=section_length, status=status)
        asdu.objects.append(InformationObject(ioa=ioa, data=sr))
        return asdu.encode()

    @staticmethod
    def build_call_directory(common_addr: int, ioa: int, file_name: int = 0,
                              section_name: int = 0, qualifier: int = 5) -> bytes:
        """构造召唤目录/选择文件/召唤文件 (F_SC_NA_1).

        信息体 = NOF(2) + NOS(1) + SCQ(1)。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            section_name: 节名 (8-bit, NOS)
            qualifier: SCQ — 1=选择文件, 2=请求文件, 3=去激活文件, 4=删除文件,
                5=选择节, 6=请求节, 7=去激活节（见 ``types.SCQ_NAMES``）
        """
        asdu = ASDU(type_id=TypeID.F_SC_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        cd = CallDirectory(ioa=ioa, file_name=file_name, section_name=section_name, qualifier=qualifier)
        asdu.objects.append(InformationObject(ioa=ioa, data=cd))
        return asdu.encode()

    @staticmethod
    def build_last_section(common_addr: int, ioa: int, file_name: int,
                            section_name: int, lsq: int, chs: int = 0) -> bytes:
        """构造最后的节/最后的段 (F_LS_NA_1).

        信息体 = NOF(2) + NOS(1) + LSQ(1) + CHS(1) = 5 字节。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            section_name: 节名 (8-bit, NOS)
            lsq: LSQ 最后的节/段限定词 (0-4；仅 1/2 表示整个文件传输结束)
            chs: CHS 本节校验和（算法见 ``file_transfer.section_checksum``）
        """
        asdu = ASDU(type_id=TypeID.F_LS_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        ls = LastSection(ioa=ioa, file_name=file_name, section_name=section_name,
                         lsq=lsq, chs=chs)
        asdu.objects.append(InformationObject(ioa=ioa, data=ls))
        return asdu.encode()

    @staticmethod
    def build_ack_file_section(common_addr: int, ioa: int, file_name: int,
                                section_name: int, qualifier: int = 0) -> bytes:
        """构造确认文件/确认节 (F_AF_NA_1).

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit)
            section_name: 节名 (8-bit)
            qualifier: 0=缺省, 1=肯定文件, 2=否定文件, 3=肯定节, 4=否定节
        """
        asdu = ASDU(type_id=TypeID.F_AF_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        af = AckFileSection(ioa=ioa, file_name=file_name, section_name=section_name, qualifier=qualifier)
        asdu.objects.append(InformationObject(ioa=ioa, data=af))
        return asdu.encode()

    @staticmethod
    def build_file_segment(common_addr: int, ioa: int, file_name: int,
                            section_name: int, data: bytes) -> bytes:
        """构造段 (F_SG_NA_1).

        信息体 = NOF(2) + NOS(1) + LOS(1) + 数据；**没有段号字段**。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            section_name: 节名 (8-bit, NOS)
            data: 段数据 (LOS = 本段字节数，1 字节 → 最多 255 字节)
        """
        asdu = ASDU(type_id=TypeID.F_SG_NA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        sg = FileSegment(ioa=ioa, file_name=file_name, section_name=section_name, data=data)
        asdu.objects.append(InformationObject(ioa=ioa, data=sg))
        return asdu.encode()

    @staticmethod
    def build_directory_entry(common_addr: int, ioa: int, file_name: int,
                               file_length: int, status: int = 0,
                               time_tag: CP56Time2a | None = None) -> bytes:
        """构造目录 (F_DR_TA_1).

        信息体 = NOF(2) + LOF(3) + SOF(1) + CP56Time2a(7) = 13 字节（LOF 为 24 位）。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            file_length: 文件长度 (24-bit, 3 字节, LOF)
            status: SOF 文件状态
            time_tag: 时标
        """
        asdu = ASDU(type_id=TypeID.F_DR_TA_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        if time_tag is None:
            time_tag = CP56Time2a.now()
        de = DirectoryEntry(ioa=ioa, file_name=file_name, file_length=file_length,
                            status=status, time_tag=time_tag)
        asdu.objects.append(InformationObject(ioa=ioa, data=de))
        return asdu.encode()

    @staticmethod
    def build_file_select_call_get(common_addr: int, ioa: int, file_name: int,
                                    section_name: int = 0, qualifier: int = 0) -> bytes:
        """构造文件选择/召唤/获取 (F_SC_NB_1).

        信息体 = NOF(2) + NOS(1) + SCQ(1)。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            section_name: 节名 (8-bit, NOS)
            qualifier: SCQ — 1=选择文件, 2=请求文件, 3=去激活文件, 4=删除文件,
                5=选择节, 6=请求节, 7=去激活节（见 ``types.SCQ_NAMES``）
        """
        asdu = ASDU(type_id=TypeID.F_SC_NB_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        fs = FileSelectCallGet(ioa=ioa, file_name=file_name, section_name=section_name, qualifier=qualifier)
        asdu.objects.append(InformationObject(ioa=ioa, data=fs))
        return asdu.encode()

    @staticmethod
    def build_file_ready_ack(common_addr: int, ioa: int, file_name: int,
                              file_length: int, status: int = 0) -> bytes:
        """构造文件准备就绪-确认 (F_FR_NB_1).

        信息体 = NOF(2) + LOF(3) + FRQ(1)（LOF 为 24 位）。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            file_length: 文件长度 (24-bit, 3 字节, LOF)
            status: FRQ
        """
        asdu = ASDU(type_id=TypeID.F_FR_NB_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        fra = FileReadyAck(ioa=ioa, file_name=file_name, file_length=file_length, status=status)
        asdu.objects.append(InformationObject(ioa=ioa, data=fra))
        return asdu.encode()

    @staticmethod
    def build_section_ready_ack(common_addr: int, ioa: int, file_name: int,
                                 section_name: int, section_length: int, status: int = 0) -> bytes:
        """构造节准备就绪-确认 (F_SR_NB_1).

        信息体 = NOF(2) + NOS(1) + LOF(3) + SRQ(1)（LOF 为 24 位）。

        Args:
            common_addr: 公共地址
            ioa: 信息对象地址
            file_name: 文件名 (16-bit, NOF)
            section_name: 节名 (8-bit, NOS)
            section_length: 节长度 (24-bit, 3 字节, LOF)
            status: SRQ
        """
        asdu = ASDU(type_id=TypeID.F_SR_NB_1, sq=False, num=1, cot=COT.ACT, common_addr=common_addr)
        sra = SectionReadyAck(ioa=ioa, file_name=file_name, section_name=section_name,
                              section_length=section_length, status=status)
        asdu.objects.append(InformationObject(ioa=ioa, data=sra))
        return asdu.encode()

    # ══════════════════════════════════════════════════════════════
    #  带时标测量值/状态量 — 覆盖 CP24Time2a（短时标）与 CP56Time2a
    #
    #  IEC 60870-5-104 的完整类型表含两类时标变体：…_TA_1/TB_1/TC_1 用 CP24
    #  （3 字节短时标，源自 101），…_TB_1/TD_1/TE_1/TF_1 用 CP56（7 字节）。
    #  本工具两种都能**解析**，故构造侧也必须齐备，否则无法模拟对端行为。
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def _single_object_asdu(type_id: TypeID, common_addr: int, ioa: int, data: Any,
                            cot: int = COT.SPONT, time_tag: Any = None,
                            pn: bool = False) -> bytes:
        """构造仅含 1 个信息对象、可选时标的 ASDU（内部复用）."""
        asdu = ASDU(type_id=type_id, sq=False, num=1, cot=cot, pn=pn,
                    common_addr=common_addr)
        obj = InformationObject(ioa=ioa, data=data)
        if time_tag is not None:
            obj.time_tag = time_tag
        asdu.objects.append(obj)
        return asdu.encode()

    @staticmethod
    def build_single_point_cp24(common_addr: int, ioa: int, value: bool,
                                 quality: int = 0, cot: int = COT.SPONT,
                                 time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的单点遥信 (M_SP_TA_1 = 2)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_SP_TA_1, common_addr, ioa,
            SinglePoint(value=value, quality=QualityDescriptor(quality)), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_double_point_cp24(common_addr: int, ioa: int, value: int,
                                 quality: int = 0, cot: int = COT.SPONT,
                                 time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的双点遥信 (M_DP_TA_1 = 4)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_DP_TA_1, common_addr, ioa,
            DoublePoint(value=value, quality=QualityDescriptor(quality)), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_step_position_cp24(common_addr: int, ioa: int, value: int,
                                  quality: int = 0, transient: bool = False,
                                  cot: int = COT.SPONT,
                                  time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的步位置信息 (M_ST_TA_1 = 6)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_ST_TA_1, common_addr, ioa,
            StepPosition(value=value, quality=QualityDescriptor(quality),
                         transient=transient), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_bitstring_cp24(common_addr: int, ioa: int, value: int,
                              cot: int = COT.SPONT,
                              time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的 32 位比特串 (M_BO_TA_1 = 8).

        注意：比特串信息（M_BO_*）按标准**不带品质描述词**，故无 quality 参数。
        """
        return ASDUBuilder._single_object_asdu(
            TypeID.M_BO_TA_1, common_addr, ioa, BitString32(value=value), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_normalized_cp24(common_addr: int, ioa: int, value: float,
                               quality: int = 0, cot: int = COT.SPONT,
                               time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的归一化测量值 (M_ME_TA_1 = 10)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_ME_TA_1, common_addr, ioa,
            NormalizedValue(value=value, quality=QualityDescriptor(quality)), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_scaled_cp24(common_addr: int, ioa: int, value: int,
                           quality: int = 0, cot: int = COT.SPONT,
                           time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的标度化测量值 (M_ME_TB_1 = 12)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_ME_TB_1, common_addr, ioa,
            ScaledValue(value=value, quality=QualityDescriptor(quality)), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_short_float_cp24(common_addr: int, ioa: int, value: float,
                                quality: int = 0, cot: int = COT.SPONT,
                                time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的短浮点测量值 (M_ME_TC_1 = 14)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_ME_TC_1, common_addr, ioa,
            ShortFloat(value=value, quality=QualityDescriptor(quality)), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    @staticmethod
    def build_counter_cp24(common_addr: int, ioa: int, value: int,
                            quality: int = 0, sequence: int = 0,
                            cot: int = COT.SPONT,
                            time_tag: CP24Time2a | None = None) -> bytes:
        """构造带 CP24 短时标的累计量 (M_IT_TA_1 = 16)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.M_IT_TA_1, common_addr, ioa,
            CounterValue(value=value, quality=QualityDescriptor(quality),
                         sequence=sequence), cot,
            time_tag if time_tag is not None else CP24Time2a.now(),
        )

    # ── 继电保护设备事件（M_EP_*）──────────────────────────────────

    @staticmethod
    def build_protection_event(common_addr: int, ioa: int, event_value: int,
                                quality: int = 0, elapsed_time: int = 0,
                                group_start_info: int = 0, group_output_info: int = 0,
                                cot: int = COT.SPONT,
                                time_tag: CP24Time2a | CP56Time2a | None = None,
                                with_time: bool = True) -> bytes:
        """构造继电保护设备事件.

        Args:
            with_time: True → CP56Time2a 变体 (M_EP_TD_1 = 38)；
                False → CP24Time2a 变体 (M_EP_TA_1 = 17)。
            event_value: 16 位事件值（保护动作/启动/输出电路的状态位）。
        """
        if with_time:
            type_id = TypeID.M_EP_TD_1
            tag = time_tag if time_tag is not None else CP56Time2a.now()
        else:
            type_id = TypeID.M_EP_TA_1
            tag = time_tag if time_tag is not None else CP24Time2a.now()
        ev = ProtectionEvent(
            ioa=ioa, event_value=event_value,
            quality=QualityDescriptor(quality), elapsed_time=elapsed_time,
            group_start_info=group_start_info, group_output_info=group_output_info,
        )
        return ASDUBuilder._single_object_asdu(
            type_id, common_addr, ioa, ev, cot, tag)

    @staticmethod
    def build_protection_events_start(common_addr: int, ioa: int,
                                       group_start_info: int, elapsed_time: int = 0,
                                       quality: int = 0, event_value: int = 0,
                                       cot: int = COT.SPONT,
                                       time_tag: CP24Time2a | CP56Time2a | None = None,
                                       with_time: bool = True) -> bytes:
        """构造继电保护设备成组启动事件 (M_EP_TE_1 = 39 / M_EP_TB_1 = 18)."""
        type_id = TypeID.M_EP_TE_1 if with_time else TypeID.M_EP_TB_1
        tag = (time_tag if time_tag is not None
               else (CP56Time2a.now() if with_time else CP24Time2a.now()))
        ev = ProtectionEvent(
            ioa=ioa, event_value=event_value, quality=QualityDescriptor(quality),
            elapsed_time=elapsed_time, group_start_info=group_start_info,
        )
        return ASDUBuilder._single_object_asdu(type_id, common_addr, ioa, ev, cot, tag)

    @staticmethod
    def build_protection_events_output(common_addr: int, ioa: int,
                                        group_output_info: int,
                                        quality: int = 0, event_value: int = 0,
                                        cot: int = COT.SPONT,
                                        time_tag: CP24Time2a | CP56Time2a | None = None,
                                        with_time: bool = True) -> bytes:
        """构造继电保护设备成组输出电路信息 (M_EP_TF_1 = 40 / M_EP_TC_1 = 19)."""
        type_id = TypeID.M_EP_TF_1 if with_time else TypeID.M_EP_TC_1
        tag = (time_tag if time_tag is not None
               else (CP56Time2a.now() if with_time else CP24Time2a.now()))
        ev = ProtectionEvent(
            ioa=ioa, event_value=event_value, quality=QualityDescriptor(quality),
            group_output_info=group_output_info,
        )
        return ASDUBuilder._single_object_asdu(type_id, common_addr, ioa, ev, cot, tag)

    # ── 成组单点信息（带状态检出）──────────────────────────────────

    @staticmethod
    def build_group_single_point(common_addr: int, ioa: int,
                                  points: list[tuple[bool, bool]],
                                  cot: int = COT.SPONT,
                                  time_tag: CP56Time2a | None = None,
                                  with_time: bool = False) -> bytes:
        """构造带状态检出的成组单点信息.

        Args:
            points: [(状态, 状态检出), ...] 最多 8 个。
            with_time: True → M_PS_TB_1 (71, 带 CP56 时标)；False → M_PS_NA_1 (20)。
        """
        gsp = GroupSinglePointWithStatus(ioa=ioa, points=list(points)[:8])
        if with_time and time_tag is None:
            time_tag = CP56Time2a.now()      # M_PS_TB_1 必须带 CP56 时标
        return ASDUBuilder._single_object_asdu(
            TypeID.M_PS_TB_1 if with_time else TypeID.M_PS_NA_1,
            common_addr, ioa, gsp, cot, time_tag,
        )

    @staticmethod
    def build_normalized_no_quality(common_addr: int, ioa: int, value: float,
                                     cot: int = COT.SPONT) -> bytes:
        """构造不带品质描述词的归一化测量值 (M_ME_ND_1 = 21)."""
        nv = NormalizedValue(value=value)
        return ASDUBuilder._single_object_asdu(
            TypeID.M_ME_ND_1, common_addr, ioa, nv, cot)

    @staticmethod
    def build_parameter_no_quality(common_addr: int, ioa: int, value: float,
                                    cot: int = COT.ACT) -> bytes:
        """构造不带品质的参数-归一化 (P_ME_ND_1 = 109)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.P_ME_ND_1, common_addr, ioa,
            ParameterCommandNormalizedNoQuality(ioa=ioa, value=value), cot)

    @staticmethod
    def build_test_command_bit_pattern(common_addr: int, pattern_low: int = 0x55,
                                        pattern_high: int = 0xAA,
                                        cot: int = COT.ACT) -> bytes:
        """构造位模式测试命令 (C_TS_NB_1 = 108，IEC 60870-5-101)."""
        return ASDUBuilder._single_object_asdu(
            TypeID.C_TS_NB_1, common_addr, 0,
            TestCommandBitPattern(test_pattern_low=pattern_low,
                                  test_pattern_high=pattern_high), cot)


# ═══════════════════════════════════════════════════════════════════
#  完整 APDU 编解码（APCI + ASDU）
# ═══════════════════════════════════════════════════════════════════

@dataclass
class APDU:
    """完整 APDU = APCI + ASDU."""
    tx_seq: int = 0
    rx_seq: int = 0
    asdu: ASDU | None = None
    # U-frame
    u_func: int = 0
    is_i_frame: bool = True

    def encode(self) -> bytes:
        """编码完整 APDU."""
        from .apci import APCICodec

        if self.is_i_frame and self.asdu is not None:
            asdu_data = self.asdu.encode()
            return APCICodec.encode_i(self.tx_seq, self.rx_seq, asdu_data)
        else:
            return APCICodec.encode_u(self.u_func)

    @classmethod
    def decode(cls, data: bytes, ca_length: int = 2) -> APDU:
        """解码完整 APDU."""
        from .apci import APCICodec

        apci, consumed = APCICodec.decode(data)

        apdu = cls()
        apdu.tx_seq = apci.tx_seq
        apdu.rx_seq = apci.rx_seq
        apdu.is_i_frame = apci.is_i_frame

        if apci.is_i_frame:
            asdu_data = data[6:6 + apci.asdu_length]
            apdu.asdu = ASDU.decode(asdu_data, ca_length)
        elif apci.is_u_frame:
            apdu.u_func = apci.u_func

        return apdu
