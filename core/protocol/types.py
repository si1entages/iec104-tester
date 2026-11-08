"""IEC 60870-5-104 Type Definitions and Enums."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════════════
#  Type Identification (类型标识)
# ═══════════════════════════════════════════════════════════════════

class TypeID(enum.IntEnum):
    """ASDU Type Identification — IEC 60870-5-104 Table 1-97."""
    # ── 监控方向（过程信息，子站→主站）──
    M_SP_NA_1 = 1       # 单点信息
    M_SP_TA_1 = 2       # 带时标的单点信息
    M_DP_NA_1 = 3       # 双点信息
    M_DP_TA_1 = 4       # 带时标的双点信息
    M_ST_NA_1 = 5       # 步位置信息
    M_ST_TA_1 = 6       # 带时标的步位置信息
    M_BO_NA_1 = 7       # 32比特串
    M_BO_TA_1 = 8       # 带时标的32比特串
    M_ME_NA_1 = 9       # 测量值，归一化值
    M_ME_TA_1 = 10      # 带时标的测量值，归一化值
    M_ME_NB_1 = 11      # 测量值，标度化值
    M_ME_TB_1 = 12      # 带时标的测量值，标度化值
    M_ME_NC_1 = 13      # 测量值，短浮点数
    M_ME_TC_1 = 14      # 带时标的测量值，短浮点数
    M_IT_NA_1 = 15      # 累计量
    M_IT_TA_1 = 16      # 带时标的累计量
    M_EP_TA_1 = 17      # 带时标的继电保护设备事件
    M_EP_TB_1 = 18      # 带时标的继电保护设备成组启动事件
    M_EP_TC_1 = 19      # 带时标的继电保护设备成组输出电路信息
    M_PS_NA_1 = 20      # 带状态检出的成组单点信息
    M_ME_ND_1 = 21      # 测量值，不带品质描述词的归一化值
    # 22-29: 保留
    M_SP_TB_1 = 30      # 带时标CP56Time2a的单点信息
    M_DP_TB_1 = 31      # 带时标CP56Time2a的双点信息
    M_ST_TB_1 = 32      # 带时标CP56Time2a的步位置信息
    M_BO_TB_1 = 33      # 带时标CP56Time2a的32比特串
    M_ME_TD_1 = 34      # 带时标CP56Time2a的测量值，归一化值
    M_ME_TE_1 = 35      # 带时标CP56Time2a的测量值，标度化值
    M_ME_TF_1 = 36      # 带时标CP56Time2a的测量值，短浮点数
    M_IT_TB_1 = 37      # 带时标CP56Time2a的累计量
    M_EP_TD_1 = 38      # 带时标CP56Time2a的继电保护设备事件
    M_EP_TE_1 = 39      # 带时标CP56Time2a的继电保护设备成组启动事件
    M_EP_TF_1 = 40      # 带时标CP56Time2a的继电保护设备成组输出电路信息
    # 41-44: 保留
    M_PS_TB_1 = 71      # 带时标CP56Time2a的带状态检出成组单点信息 (IEC 60870-5-101)

    # ── 控制方向（控制命令，主站→子站）──
    C_SC_NA_1 = 45      # 单命令
    C_DC_NA_1 = 46      # 双命令
    C_RC_NA_1 = 47      # 升降命令
    C_SE_NA_1 = 48      # 设点命令，归一化值
    C_SE_NB_1 = 49      # 设点命令，标度化值
    C_SE_NC_1 = 50      # 设点命令，短浮点数
    C_BO_NA_1 = 51      # 32比特串
    # ── 控制方向（带时标CP56Time2a的控制命令）──
    C_SC_TA_1 = 58      # 单命令带时标CP56Time2a
    C_DC_TA_1 = 59      # 双命令带时标CP56Time2a
    C_RC_TA_1 = 60      # 升降命令带时标CP56Time2a
    C_SE_TA_1 = 61      # 设点命令，归一化值，带时标CP56Time2a
    C_SE_TB_1 = 62      # 设点命令，标度化值，带时标CP56Time2a
    C_SE_TC_1 = 63      # 设点命令，短浮点数，带时标CP56Time2a
    C_BO_TA_1 = 64      # 32比特串命令带时标CP56Time2a
    M_EI_NA_1 = 70  # 初始化结束

    # ── 系统命令 ──
    C_IC_NA_1 = 100     # 总召唤命令
    C_CI_NA_1 = 101     # 累计量召唤命令
    C_RD_NA_1 = 102     # 读命令
    C_CS_NA_1 = 103     # 时钟同步命令
    C_TS_NA_1 = 104     # 测试命令
    C_RP_NA_1 = 105     # 复位进程命令
    C_CD_NA_1 = 106     # 延时获得命令
    C_TS_TA_1 = 107     # 带时标CP56Time2a的测试命令
    C_TS_NB_1 = 108     # 测试命令（位模式，无时标）(IEC 60870-5-101)
    P_ME_ND_1 = 109     # 不带品质描述词的测量值参数，归一化值 (IEC 60870-5-101)

    # ── 参数命令 ──
    P_ME_NA_1 = 110     # 测量值参数，归一化值
    P_ME_NB_1 = 111     # 测量值参数，标度化值
    P_ME_NC_1 = 112     # 测量值参数，短浮点数
    P_AC_NA_1 = 113     # 参数激活

    # ── 文件传输 ──
    F_FR_NA_1 = 120     # 文件准备就绪
    F_SR_NA_1 = 121     # 节准备就绪
    F_SC_NA_1 = 122     # 召唤目录/选择文件/召唤文件
    F_LS_NA_1 = 123     # 最后的节/最后的段
    F_AF_NA_1 = 124     # 确认文件/确认节
    F_SG_NA_1 = 125     # 段
    F_DR_TA_1 = 126     # 目录
    F_SC_NB_1 = 127     # 文件选择/召唤/获取
    F_FR_NB_1 = 128     # 文件准备就绪（确认）(IEC 60870-5-101)
    F_SR_NB_1 = 129     # 节准备就绪（确认）(IEC 60870-5-101)


# ═══════════════════════════════════════════════════════════════════
#  Cause of Transmission (传送原因)
# ═══════════════════════════════════════════════════════════════════

class COT(enum.IntEnum):
    """Cause of Transmission — IEC 60870-5-104 Table 1-72."""
    NOT_USED    = 0     # 未用
    PERIODIC    = 1     # 周期、循环
    BACK        = 2     # 背景扫描
    SPONT       = 3     # 突发
    INIT        = 4     # 初始化
    REQ         = 5     # 请求或被请求
    ACT         = 6     # 激活
    ACTCON      = 7     # 激活确认
    DEACT       = 8     # 停止激活
    DEACTCON    = 9     # 停止激活确认
    ACTTERM     = 10    # 激活终止
    RETREM      = 11    # 远方命令引起的返送信息
    RETLOC      = 12    # 当地命令引起的返送信息
    FILE        = 13    # 文件传输
    # 14-19: 保留
    INTROGEN    = 20    # 响应站召唤 (COT=20)
    # 21-36: 响应第1-16组召唤 (COT = 20 + 组号)
    COUNTER_REQ = 37    # 响应累计量总召唤（总请求）(COT=37)
    # 38-41: 响应第1-4组累计量召唤 (COT = 37 + 组号)
    UNKNOWN_TYPE = 42   # 未知类型标识 (IEC 60870-5-104 Table 1-72)
    UNKNOWN_COT  = 43   # 未知传送原因
    UNKNOWN_CA   = 44   # 未知公共地址
    UNKNOWN_IOA  = 45   # 未知信息对象地址
    # 46-47: 保留

    @classmethod
    def group_response(cls, group: int) -> int:
        """返回第 group 组召唤响应的传送原因 (21-36).

        标准 (IEC 60870-5-104 Table 1-72): 组召唤响应的 COT = 20 + 组号，
        组号取值 1-16 → COT 21-36。
        """
        if not 1 <= group <= 16:
            raise ValueError(f"Group must be 1-16, got {group}")
        return 20 + group

    @classmethod
    def is_group_response(cls, cot: int) -> bool:
        """判断传送原因是否为组召唤响应 (21-36)."""
        return 21 <= cot <= 36

    @classmethod
    def get_group_number(cls, cot: int) -> int:
        """从组召唤响应传送原因中提取组号 (1-16)."""
        if not 21 <= cot <= 36:
            raise ValueError(f"Not a group response COT: {cot}")
        return cot - 20

    @classmethod
    def counter_group_response(cls, group: int) -> int:
        """返回第 group 组累计量召唤响应的传送原因 (38-41).

        标准: 累计量召唤响应的 COT = 37 + 组号，组号取值 1-4 → COT 38-41。
        """
        if not 1 <= group <= 4:
            raise ValueError(f"Counter group must be 1-4, got {group}")
        return 37 + group

    @classmethod
    def is_counter_group_response(cls, cot: int) -> bool:
        """判断传送原因是否为组累计量召唤响应 (38-41)."""
        return 38 <= cot <= 41

    @classmethod
    def is_counter_response(cls, cot: int) -> bool:
        """判断传送原因是否为累计量召唤响应 (37 或 38-41)."""
        return cot == int(cls.COUNTER_REQ) or cls.is_counter_group_response(cot)


# ═══════════════════════════════════════════════════════════════════
#  Quality Descriptor (品质描述词)
# ═══════════════════════════════════════════════════════════════════

class QualityFlag(enum.IntFlag):
    """Quality descriptor flags — IEC 60870-5-101 QDS/SIQ/DIQ.

    位序（bit7..bit0）：``IV NT SB BL 0 0 0 OV``。OV 只用于 QDS；
    SIQ/DIQ 的 bit0 是值本身。
    """
    OV = 0x01       # bit0: 溢出位 (Overflow)
    # bit1-3: 保留
    BL = 0x10       # bit4: 闭锁位 (Blocked)
    SB = 0x20       # bit5: 取代位 (Substituted)
    NT = 0x40       # bit6: 非当前值 (Not Topical)
    IV = 0x80       # bit7: 无效位 (Invalid)


@dataclass
class QualityDescriptor:
    """品质描述词解析（位定义见 :class:`QualityFlag`）."""
    raw: int = 0

    @property
    def overflow(self) -> bool:
        return bool(self.raw & QualityFlag.OV)

    @property
    def blocked(self) -> bool:
        return bool(self.raw & QualityFlag.BL)

    @property
    def substituted(self) -> bool:
        return bool(self.raw & QualityFlag.SB)

    @property
    def not_topical(self) -> bool:
        return bool(self.raw & QualityFlag.NT)

    @property
    def invalid(self) -> bool:
        return bool(self.raw & QualityFlag.IV)

    @property
    def is_good(self) -> bool:
        return self.raw == 0

    def to_int(self) -> int:
        """回到线上字节（必须保留 bit7：IV=0x80 不能被截掉）."""
        return self.raw & 0xFF

    def __str__(self) -> str:
        # 按严重度排列：无效 > 非当前 > 取代 > 闭锁 > 溢出
        flags = []
        if self.invalid:
            flags.append("IV")
        if self.not_topical:
            flags.append("NT")
        if self.substituted:
            flags.append("SB")
        if self.blocked:
            flags.append("BL")
        if self.overflow:
            flags.append("OV")
        return "|".join(flags) if flags else "GOOD"


# ═══════════════════════════════════════════════════════════════════
#  Time Tags (时标)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class CP24Time2a:
    """24-bit time tag (3 bytes) — 短时标."""
    millisecond: int = 0    # 0-59999 ms (2 bytes, little-endian)
    minute: int = 0         # 0-59
    invalid: bool = False   # IV flag (bit7 of minute byte)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> CP24Time2a:
        if len(data) < offset + 3:
            raise ValueError(f"CP24Time2a needs 3 bytes, got {len(data) - offset}")
        ms = data[offset] | (data[offset + 1] << 8)
        minute_byte = data[offset + 2]
        return cls(
            millisecond=ms,
            minute=minute_byte & 0x3F,
            invalid=bool(minute_byte & 0x80),
        )

    def to_bytes(self) -> bytes:
        minute_byte = (self.minute & 0x3F) | (0x80 if self.invalid else 0)
        return bytes([
            self.millisecond & 0xFF,
            (self.millisecond >> 8) & 0xFF,
            minute_byte,
        ])

    @classmethod
    def now(cls) -> CP24Time2a:
        t = time.localtime()
        return cls(
            millisecond=t.tm_sec * 1000,
            minute=t.tm_min,
        )


@dataclass
class CP56Time2a:
    """56-bit time tag (7 bytes) — 长时标,带年月日."""
    millisecond: int = 0    # 0-59999
    minute: int = 0         # 0-59
    hour: int = 0           # 0-23
    day: int = 1            # 1-31
    month: int = 1          # 1-12
    year: int = 0           # 0-99 (年份后两位)
    weekday: int = 0        # 1-7 (1=周一), bit0-2 of month extra byte
    invalid: bool = False   # IV flag

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> CP56Time2a:
        if len(data) < offset + 7:
            raise ValueError(f"CP56Time2a needs 7 bytes, got {len(data) - offset}")
        ms = data[offset] | (data[offset + 1] << 8)
        minute_byte = data[offset + 2]
        hour_byte = data[offset + 3]
        day_byte = data[offset + 4]
        month_byte = data[offset + 5]
        year_byte = data[offset + 6]
        return cls(
            millisecond=ms,
            minute=minute_byte & 0x3F,
            hour=hour_byte & 0x1F,
            day=day_byte & 0x1F,
            month=month_byte & 0x0F,
            year=year_byte & 0x7F,
            weekday=(month_byte >> 5) & 0x07,
            invalid=bool(minute_byte & 0x80),
        )

    def to_bytes(self) -> bytes:
        minute_byte = (self.minute & 0x3F) | (0x80 if self.invalid else 0)
        hour_byte = self.hour & 0x1F
        day_byte = self.day & 0x1F
        month_byte = (self.month & 0x0F) | ((self.weekday & 0x07) << 5)
        year_byte = self.year & 0x7F
        return bytes([
            self.millisecond & 0xFF,
            (self.millisecond >> 8) & 0xFF,
            minute_byte,
            hour_byte,
            day_byte,
            month_byte,
            year_byte,
        ])

    @classmethod
    def now(cls) -> CP56Time2a:
        t = time.localtime()
        return cls(
            millisecond=t.tm_sec * 1000,
            minute=t.tm_min,
            hour=t.tm_hour,
            day=t.tm_mday,
            month=t.tm_mon,
            year=t.tm_year % 100,
            weekday=t.tm_wday + 1,
        )

    def to_epoch(self) -> float:
        """转 epoch 秒（时钟偏差测量 T80 用；年份 0-99 按 2000-2099 解析）."""
        from datetime import datetime

        dt = datetime(2000 + self.year, self.month, self.day,
                      self.hour, self.minute, self.millisecond // 1000,
                      self.millisecond % 1000 * 1000)
        return dt.timestamp()

    def to_datetime_str(self) -> str:
        return (f"20{self.year:02d}-{self.month:02d}-{self.day:02d} "
                f"{self.hour:02d}:{self.minute:02d}:{self.millisecond // 1000:02d}"
                f".{self.millisecond % 1000:03d}")


# ═══════════════════════════════════════════════════════════════════
#  Information Object (信息对象)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class SinglePoint:
    """单点信息 (M_SP_NA_1)."""
    value: bool = False
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> SinglePoint:
        b = data[offset]
        return cls(
            value=bool(b & 0x01),
            quality=QualityDescriptor(b & 0xF0),
        )

    def to_bytes(self) -> bytes:
        return bytes([(0x01 if self.value else 0x00) | self.quality.to_int()])


@dataclass
class DoublePoint:
    """双点信息 (M_DP_NA_1)."""
    value: int = 0          # 0=不确定, 1=开, 2=合, 3=中间状态
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> DoublePoint:
        b = data[offset]
        return cls(
            value=b & 0x03,
            quality=QualityDescriptor(b & 0xF0),
        )

    def to_bytes(self) -> bytes:
        return bytes([(self.value & 0x03) | self.quality.to_int()])

    @property
    def state_str(self) -> str:
        return {0: "不确定", 1: "分(OFF)", 2: "合(ON)", 3: "中间"}.get(self.value, "?")


@dataclass
class StepPosition:
    """步位置信息 (M_ST_NA_1)."""
    value: int = 0          # -64..+63 (7bit有符号)
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    transient: bool = False # T标志, bit7

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> StepPosition:
        b = data[offset]
        val = b & 0x7F
        if val & 0x40:      # 符号扩展
            val -= 128
        return cls(
            value=val,
            quality=QualityDescriptor(data[offset + 1]) if len(data) > offset + 1 else QualityDescriptor(),
            transient=bool(b & 0x80),
        )

    def to_bytes(self) -> bytes:
        b = (self.value & 0x7F) | (0x80 if self.transient else 0)
        return bytes([b, self.quality.to_int()])


@dataclass
class NormalizedValue:
    """归一化值 (M_ME_NA_1) — -1..+1 范围."""
    value: float = 0.0      # 归一化到 -1.0 .. +1.0
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> NormalizedValue:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        return cls(
            value=signed_val / 32767.0,
            quality=QualityDescriptor(data[offset + 2]) if len(data) > offset + 2 else QualityDescriptor(),
        )

    def to_bytes(self) -> bytes:
        raw = int(self.value * 32767)
        raw = max(-32768, min(32767, raw))
        if raw < 0:
            raw += 0x10000
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF, self.quality.to_int()])


@dataclass
class ScaledValue:
    """标度化值 (M_ME_NB_1) — -32768..+32767."""
    value: int = 0
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> ScaledValue:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        return cls(
            value=signed_val,
            quality=QualityDescriptor(data[offset + 2]) if len(data) > offset + 2 else QualityDescriptor(),
        )

    def to_bytes(self) -> bytes:
        raw = self.value
        if raw < 0:
            raw += 0x10000
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF, self.quality.to_int()])


@dataclass
class ShortFloat:
    """短浮点数 (M_ME_NC_1) — IEEE 754 单精度."""
    value: float = 0.0
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> ShortFloat:
        import struct
        val = struct.unpack_from('<f', data, offset)[0]
        return cls(
            value=val,
            quality=QualityDescriptor(data[offset + 4]) if len(data) > offset + 4 else QualityDescriptor(),
        )

    def to_bytes(self) -> bytes:
        import struct
        return struct.pack('<f', self.value) + bytes([self.quality.to_int()])


@dataclass
class CounterValue:
    """累计量/电度值 (M_IT_NA_1)."""
    value: int = 0          # 32-bit 有符号
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    sequence: int = 0       # 顺序号 (0-31)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> CounterValue:
        import struct
        val = struct.unpack_from('<i', data, offset)[0]
        seq = data[offset + 4] if len(data) > offset + 4 else 0
        return cls(
            value=val,
            quality=QualityDescriptor(seq & 0xE0),
            sequence=seq & 0x1F,
        )

    def to_bytes(self) -> bytes:
        import struct
        seq_byte = (self.sequence & 0x1F) | self.quality.to_int()
        return struct.pack('<i', self.value) + bytes([seq_byte])


@dataclass
class BitString32:
    """32比特串 (M_BO_NA_1)."""
    value: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> BitString32:
        import struct
        val = struct.unpack_from('<I', data, offset)[0]
        return cls(value=val)

    def to_bytes(self) -> bytes:
        import struct
        return struct.pack('<I', self.value)


# ═══════════════════════════════════════════════════════════════════
#  Command Objects (控制命令)
# ═══════════════════════════════════════════════════════════════════

class SCO(enum.IntFlag):
    """Single Command qualifier — 单命令限定词."""
    SELECT = 0x80       # S/E: 1=选择, 0=执行
    QU_SHIFT = 2        # QU: bit2-5, 遥控限定词
    QU_MASK = 0x3C


class DCO(enum.IntFlag):
    """Double Command qualifier — 双命令限定词."""
    SELECT = 0x80
    QU_SHIFT = 2
    QU_MASK = 0x3C


class RCO(enum.IntFlag):
    """Regulating Step Command qualifier — 升降命令限定词."""
    SELECT = 0x80
    QU_SHIFT = 2
    QU_MASK = 0x3C


@dataclass
class SingleCommand:
    """单命令 (C_SC_NA_1)."""
    ioa: int = 0
    state: bool = False       # OFF/ON
    select: bool = False      # S/E: True=选择, False=执行
    qu: int = 0               # 限定词 (0-31)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> SingleCommand:
        b = data[offset]
        return cls(
            ioa=ioa,
            state=bool(b & 0x01),
            select=bool(b & 0x80),
            qu=(b >> 2) & 0x1F,
        )

    def to_bytes(self) -> bytes:
        b = (0x01 if self.state else 0x00)
        b |= 0x80 if self.select else 0x00
        b |= (self.qu & 0x1F) << 2
        return bytes([b])

    @property
    def action_str(self) -> str:
        return "选择" if self.select else "执行"


@dataclass
class DoubleCommand:
    """双命令 (C_DC_NA_1)."""
    ioa: int = 0
    state: int = 0            # 0=不允许, 1=分, 2=合, 3=不允许
    select: bool = False
    qu: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> DoubleCommand:
        b = data[offset]
        return cls(
            ioa=ioa,
            state=b & 0x03,
            select=bool(b & 0x80),
            qu=(b >> 2) & 0x1F,
        )

    def to_bytes(self) -> bytes:
        b = self.state & 0x03
        b |= 0x80 if self.select else 0x00
        b |= (self.qu & 0x1F) << 2
        return bytes([b])


@dataclass
class SetpointCommandN:
    """设点命令-归一化 (C_SE_NA_1)."""
    ioa: int = 0
    value: float = 0.0       # -1..+1
    select: bool = False
    qu: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> SetpointCommandN:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        q = data[offset + 2]
        return cls(
            ioa=ioa,
            value=signed_val / 32767.0,
            select=bool(q & 0x80),
            qu=(q >> 2) & 0x1F,
        )

    def to_bytes(self) -> bytes:
        raw = int(self.value * 32767)
        raw = max(-32768, min(32767, raw))
        if raw < 0:
            raw += 0x10000
        q = (0x80 if self.select else 0x00) | ((self.qu & 0x1F) << 2)
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF, q])


@dataclass
class SetpointCommandS:
    """设点命令-短浮点 (C_SE_NC_1)."""
    ioa: int = 0
    value: float = 0.0
    select: bool = False
    qu: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> SetpointCommandS:
        import struct
        val = struct.unpack_from('<f', data, offset)[0]
        q = data[offset + 4]
        return cls(
            ioa=ioa,
            value=val,
            select=bool(q & 0x80),
            qu=(q >> 2) & 0x1F,
        )

    def to_bytes(self) -> bytes:
        import struct
        q = (0x80 if self.select else 0x00) | ((self.qu & 0x1F) << 2)
        return struct.pack('<f', self.value) + bytes([q])


@dataclass
class SetpointCommandScaled:
    """设点命令-标度化值 (C_SE_NB_1) — -32768..+32767."""
    ioa: int = 0
    value: int = 0           # -32768..+32767
    select: bool = False     # S/E: 1=选择, 0=执行
    qu: int = 0              # 限定词 (0-31)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> SetpointCommandScaled:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        q = data[offset + 2]
        return cls(
            ioa=ioa,
            value=signed_val,
            select=bool(q & 0x80),
            qu=(q >> 2) & 0x1F,
        )

    def to_bytes(self) -> bytes:
        raw = self.value
        if raw < 0:
            raw += 0x10000
        q = (0x80 if self.select else 0x00) | ((self.qu & 0x1F) << 2)
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF, q])


@dataclass
class RegulatingStepCommand:
    """升降命令 (C_RC_NA_1) — 控制步位置升降."""
    ioa: int = 0
    state: int = 0           # 0=不允许, 1=降一步, 2=升一步, 3=不允许
    select: bool = False     # S/E: 1=选择, 0=执行
    qu: int = 0              # 限定词 (0-31)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> RegulatingStepCommand:
        b = data[offset]
        return cls(
            ioa=ioa,
            state=b & 0x03,
            select=bool(b & 0x80),
            qu=(b >> 2) & 0x1F,
        )

    def to_bytes(self) -> bytes:
        b = self.state & 0x03
        b |= 0x80 if self.select else 0x00
        b |= (self.qu & 0x1F) << 2
        return bytes([b])

    @property
    def state_str(self) -> str:
        return {0: "不允许", 1: "降一步", 2: "升一步", 3: "不允许"}.get(self.state, "?")

    @property
    def action_str(self) -> str:
        return "选择" if self.select else "执行"


@dataclass
class BitString32Command:
    """32比特串命令 (C_BO_NA_1) — 控制方向的比特串."""
    ioa: int = 0
    value: int = 0           # 32-bit 无符号

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> BitString32Command:
        import struct
        val = struct.unpack_from('<I', data, offset)[0]
        return cls(ioa=ioa, value=val)

    def to_bytes(self) -> bytes:
        import struct
        return struct.pack('<I', self.value)


@dataclass
class ProtectionEvent:
    """继电保护设备事件 (M_EP_TA_1 / M_EP_TB_1 / M_EP_TC_1 / M_EP_TD_1 / M_EP_TE_1 / M_EP_TF_1).

    - M_EP_TA_1 (17): 带时标CP24Time2a的继电保护设备事件
    - M_EP_TB_1 (18): 带时标CP24Time2a的继电保护设备成组启动事件
    - M_EP_TC_1 (19): 带时标CP24Time2a的继电保护设备成组输出电路信息
    - M_EP_TD_1 (38): 带时标CP56Time2a的继电保护设备事件
    - M_EP_TE_1 (39): 带时标CP56Time2a的继电保护设备成组启动事件
    - M_EP_TF_1 (40): 带时标CP56Time2a的继电保护设备成组输出电路信息
    """
    ioa: int = 0
    event_value: int = 0     # 16-bit 事件值 (2 bytes)
    quality: QualityDescriptor = field(default_factory=QualityDescriptor)
    # 继电器保护设备附加信息
    elapsed_time: int = 0    # 动作时间 (M_EP_TB_1 / M_EP_TE_1)
    # 成组启动事件 / 成组输出电路信息
    group_start_info: int = 0    # 成组启动信息 (M_EP_TB_1 / M_EP_TE_1)
    group_output_info: int = 0   # 成组输出电路信息 (M_EP_TC_1 / M_EP_TF_1)
    # 时标
    time_short: CP24Time2a | None = None    # M_EP_TA_1/TB_1/TC_1
    time_long: CP56Time2a | None = None     # M_EP_TD_1/TE_1/TF_1

    @classmethod
    def from_bytes_short_time(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ProtectionEvent:
        """解析带CP24Time2a的继电保护事件 (M_EP_TA_1)."""
        event_val = data[offset] | (data[offset + 1] << 8)
        q = QualityDescriptor(data[offset + 2]) if len(data) > offset + 2 else QualityDescriptor()
        time_tag = CP24Time2a.from_bytes(data, offset + 3) if len(data) >= offset + 6 else None
        return cls(
            ioa=ioa,
            event_value=event_val,
            quality=q,
            time_short=time_tag,
        )

    @classmethod
    def from_bytes_long_time(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ProtectionEvent:
        """解析带CP56Time2a的继电保护事件 (M_EP_TD_1)."""
        event_val = data[offset] | (data[offset + 1] << 8)
        q = QualityDescriptor(data[offset + 2]) if len(data) > offset + 2 else QualityDescriptor()
        time_tag = CP56Time2a.from_bytes(data, offset + 3) if len(data) >= offset + 10 else None
        return cls(
            ioa=ioa,
            event_value=event_val,
            quality=q,
            time_long=time_tag,
        )

    def to_bytes(self) -> bytes:
        """编码继电保护事件数据体 (event 2字节 + quality 1字节).

        注意: 时标 (CP24Time2a / CP56Time2a) 由 ASDU 编码层作为
        InformationObject.time_tag 统一追加，此处**不包含时标**，
        以避免与通用时标机制重复写入（时标长度由类型决定）。
        """
        return bytes([
            self.event_value & 0xFF,
            (self.event_value >> 8) & 0xFF,
            self.quality.to_int(),
        ])

    def to_bytes_short_time(self) -> bytes:
        result = bytes([self.event_value & 0xFF, (self.event_value >> 8) & 0xFF, self.quality.to_int()])
        if self.time_short:
            result += self.time_short.to_bytes()
        return result

    def to_bytes_long_time(self) -> bytes:
        result = bytes([self.event_value & 0xFF, (self.event_value >> 8) & 0xFF, self.quality.to_int()])
        if self.time_long:
            result += self.time_long.to_bytes()
        return result

    @property
    def has_short_time(self) -> bool:
        return self.time_short is not None

    @property
    def has_long_time(self) -> bool:
        return self.time_long is not None


@dataclass
class GroupSinglePointWithStatus:
    """带状态检出的成组单点信息 (M_PS_NA_1 = 20 / M_PS_TB_1 = 71).

    每个信息对象包含最多 8 个单点的状态和状态检出标志。
    """
    ioa: int = 0
    points: list = field(default_factory=list)  # list of (state: bool, detected: bool)
    time_long: CP56Time2a | None = None      # M_PS_TB_1 带时标

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0, count: int = 8) -> GroupSinglePointWithStatus:
        """解析成组单点信息，每组最多8个点。"""
        # 状态检出标志 (1 byte)
        detected_byte = data[offset]
        # 状态字节 (1 byte)
        state_byte = data[offset + 1]
        points = []
        for i in range(min(count, 8)):
            state = bool(state_byte & (1 << i))
            detected = bool(detected_byte & (1 << i))
            points.append((state, detected))
        return cls(ioa=ioa, points=points)

    @classmethod
    def from_bytes_with_time(cls, data: bytes, offset: int = 0, ioa: int = 0, count: int = 8) -> GroupSinglePointWithStatus:
        """解析带CP56Time2a的成组单点信息 (M_PS_TB_1 = 71)."""
        detected_byte = data[offset]
        state_byte = data[offset + 1]
        points = []
        for i in range(min(count, 8)):
            state = bool(state_byte & (1 << i))
            detected = bool(detected_byte & (1 << i))
            points.append((state, detected))
        time_tag = CP56Time2a.from_bytes(data, offset + 2) if len(data) >= offset + 9 else None
        return cls(ioa=ioa, points=points, time_long=time_tag)

    def to_bytes(self) -> bytes:
        detected_byte = 0
        state_byte = 0
        for i, (state, detected) in enumerate(self.points[:8]):
            if state:
                state_byte |= (1 << i)
            if detected:
                detected_byte |= (1 << i)
        result = bytes([detected_byte, state_byte])
        if self.time_long:
            result += self.time_long.to_bytes()
        return result


@dataclass
class InitializationEnd:
    """初始化结束 (M_EI_NA_1 = 70)."""
    ioa: int = 0
    cause: int = 0           # 0=当地电源合上, 1=当地手动复位, 2=远方复位

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> InitializationEnd:
        return cls(ioa=ioa, cause=data[offset] & 0x0F)

    def to_bytes(self) -> bytes:
        return bytes([self.cause & 0x0F])

    @property
    def cause_str(self) -> str:
        return {
            0: "当地电源合上",
            1: "当地手动复位",
            2: "远方复位",
        }.get(self.cause, f"未知({self.cause})")


@dataclass
class InterrogationCommand:
    """总召唤命令 (C_IC_NA_1 = 100)."""
    ioa: int = 0
    qoi: int = 20            # 限定词 (20=站召唤, 21-36=第1-16组召唤)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> InterrogationCommand:
        return cls(ioa=ioa, qoi=data[offset] & 0xFF)

    def to_bytes(self) -> bytes:
        return bytes([self.qoi & 0xFF])

    @property
    def qoi_str(self) -> str:
        if self.qoi == 20:
            return "站召唤"
        elif 21 <= self.qoi <= 36:
            return f"第{self.qoi - 20}组召唤"
        else:
            return f"未知({self.qoi})"


@dataclass
class TestCommand:
    """测试命令 (C_TS_NA_1 = 104)."""
    ioa: int = 0
    test_pattern: int = 0x55AA  # 默认测试模式

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> TestCommand:
        val = data[offset] | (data[offset + 1] << 8)
        return cls(ioa=ioa, test_pattern=val)

    def to_bytes(self) -> bytes:
        return bytes([self.test_pattern & 0xFF, (self.test_pattern >> 8) & 0xFF])


@dataclass
class TestCommandWithTime:
    """带时标CP56Time2a的测试命令 (C_TS_TA_1 = 107)."""
    ioa: int = 0
    test_pattern: int = 0x55AA
    time_tag: CP56Time2a = field(default_factory=CP56Time2a)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> TestCommandWithTime:
        val = data[offset] | (data[offset + 1] << 8)
        tt = CP56Time2a.from_bytes(data, offset + 2) if len(data) >= offset + 9 else CP56Time2a()
        return cls(ioa=ioa, test_pattern=val, time_tag=tt)

    def to_bytes(self) -> bytes:
        return bytes([self.test_pattern & 0xFF, (self.test_pattern >> 8) & 0xFF]) + self.time_tag.to_bytes()


@dataclass
class ReadCommand:
    """读命令 (C_RD_NA_1 = 102)."""
    ioa: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ReadCommand:
        return cls(ioa=ioa)

    def to_bytes(self) -> bytes:
        return b''  # 读命令的信息体为空（仅依赖IOA）


@dataclass
class ClockSyncCommand:
    """时钟同步命令 (C_CS_NA_1 = 103)."""
    ioa: int = 0
    time_tag: CP56Time2a = field(default_factory=CP56Time2a.now)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ClockSyncCommand:
        tt = CP56Time2a.from_bytes(data, offset) if len(data) >= offset + 7 else CP56Time2a()
        return cls(ioa=ioa, time_tag=tt)

    def to_bytes(self) -> bytes:
        return self.time_tag.to_bytes()


@dataclass
class ResetProcessCommand:
    """复位进程命令 (C_RP_NA_1 = 105)."""
    ioa: int = 0
    qualifier: int = 0       # 复位限定词 (0=未用)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ResetProcessCommand:
        return cls(ioa=ioa, qualifier=data[offset])

    def to_bytes(self) -> bytes:
        return bytes([self.qualifier])


@dataclass
class ParameterCommandNormalized:
    """测量值参数-归一化 (P_ME_NA_1 = 110)."""
    ioa: int = 0
    value: float = 0.0       # -1..+1
    param_change: int = 0    # bit0-1: 0=未用, 1=运行中使用, 2=运行中不使用

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ParameterCommandNormalized:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        q = data[offset + 2]
        return cls(
            ioa=ioa,
            value=signed_val / 32767.0,
            param_change=q & 0x03,
        )

    def to_bytes(self) -> bytes:
        raw = int(self.value * 32767)
        raw = max(-32768, min(32767, raw))
        if raw < 0:
            raw += 0x10000
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF, self.param_change & 0x03])


@dataclass
class ParameterCommandScaled:
    """测量值参数-标度化 (P_ME_NB_1 = 111)."""
    ioa: int = 0
    value: int = 0           # -32768..+32767
    param_change: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ParameterCommandScaled:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        q = data[offset + 2]
        return cls(ioa=ioa, value=signed_val, param_change=q & 0x03)

    def to_bytes(self) -> bytes:
        raw = self.value
        if raw < 0:
            raw += 0x10000
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF, self.param_change & 0x03])


@dataclass
class ParameterCommandFloat:
    """测量值参数-短浮点 (P_ME_NC_1 = 112)."""
    ioa: int = 0
    value: float = 0.0
    param_change: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ParameterCommandFloat:
        import struct
        val = struct.unpack_from('<f', data, offset)[0]
        q = data[offset + 4]
        return cls(ioa=ioa, value=val, param_change=q & 0x03)

    def to_bytes(self) -> bytes:
        import struct
        return struct.pack('<f', self.value) + bytes([self.param_change & 0x03])


@dataclass
class ParameterActivation:
    """参数激活 (P_AC_NA_1 = 113)."""
    ioa: int = 0
    qualifier: int = 0       # 0=未用/取消, 1=激活/周期, 2=去激活

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ParameterActivation:
        return cls(ioa=ioa, qualifier=data[offset] & 0x03)

    def to_bytes(self) -> bytes:
        return bytes([self.qualifier & 0x03])

    @property
    def action_str(self) -> str:
        return {0: "未用", 1: "激活", 2: "去激活"}.get(self.qualifier, f"未知({self.qualifier})")


@dataclass
class CounterInterrogationCommand:
    """累计量召唤命令 (C_CI_NA_1 = 101)."""
    ioa: int = 0
    qcc: int = 0             # 累计量召唤限定词 (高5位=冻结, 低3位=组号)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> CounterInterrogationCommand:
        return cls(ioa=ioa, qcc=data[offset])

    def to_bytes(self) -> bytes:
        return bytes([self.qcc])

    @property
    def freeze_code(self) -> int:
        """冻结码 (bit7-5): 0=读, 1=计数器冻结不复位, 2=计数器冻结复位, 3=计数器复位."""
        return (self.qcc >> 5) & 0x07

    @property
    def group(self) -> int:
        """组号 (bit2-0): 0=站召唤, 1-4=组召唤."""
        return self.qcc & 0x07

    @property
    def freeze_str(self) -> str:
        return {0: "读", 1: "冻结不复位", 2: "冻结复位", 3: "复位"}.get(self.freeze_code, f"未知({self.freeze_code})")


@dataclass
class DelayCommand:
    """延时获得命令 (C_CD_NA_1 = 106)."""
    ioa: int = 0
    delay_ms: int = 0        # 延时值 (毫秒, 16-bit)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> DelayCommand:
        val = data[offset] | (data[offset + 1] << 8)
        return cls(ioa=ioa, delay_ms=val)

    def to_bytes(self) -> bytes:
        return bytes([self.delay_ms & 0xFF, (self.delay_ms >> 8) & 0xFF])


@dataclass
class TestCommandBitPattern:
    """测试命令-位模式，无时标 (C_TS_NB_1 = 108) — IEC 60870-5-101."""
    ioa: int = 0
    test_pattern_low: int = 0x55   # 低位字节
    test_pattern_high: int = 0xAA  # 高位字节

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> TestCommandBitPattern:
        return cls(ioa=ioa, test_pattern_low=data[offset], test_pattern_high=data[offset + 1])

    def to_bytes(self) -> bytes:
        return bytes([self.test_pattern_low, self.test_pattern_high])

    @property
    def pattern(self) -> int:
        return self.test_pattern_low | (self.test_pattern_high << 8)


@dataclass
class ParameterCommandNormalizedNoQuality:
    """不带品质描述词的测量值参数-归一化 (P_ME_ND_1 = 109) — IEC 60870-5-101."""
    ioa: int = 0
    value: float = 0.0       # -1..+1, 仅2字节归一化值，无品质描述词

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> ParameterCommandNormalizedNoQuality:
        raw = data[offset] | (data[offset + 1] << 8)
        signed_val = raw if raw < 0x8000 else raw - 0x10000
        return cls(ioa=ioa, value=signed_val / 32767.0)

    def to_bytes(self) -> bytes:
        raw = int(self.value * 32767)
        raw = max(-32768, min(32767, raw))
        if raw < 0:
            raw += 0x10000
        return bytes([raw & 0xFF, (raw >> 8) & 0xFF])


# ═══════════════════════════════════════════════════════════════════
#  File Transfer Objects (文件传输)
#
#  信息体（不含 IOA）字段布局依据（见 docs/file_transfer_fls.md §2.2，多个互相
#  独立的字节级参考实现 + 厂商公开手册共同印证）：
#    F_FR_NA_1  = NOF(2,LE) + LOF(3,LE) + FRQ(1)
#    F_SR_NA_1  = NOF(2) + NOS(1) + LOF(3) + SRQ(1)
#    F_SC_NA_1  = NOF(2) + NOS(1) + SCQ(1)
#    F_LS_NA_1  = NOF(2) + NOS(1) + LSQ(1) + CHS(1)
#    F_AF_NA_1  = NOF(2) + NOS(1) + AFQ(1)
#    F_SG_NA_1  = NOF(2) + NOS(1) + LOS(1) + 数据      （**无段号字段**）
#    F_DR_TA_1  = NOF(2) + LOF(3) + SOF(1) + CP56Time2a(7)
#  其中 **LOF（文件/节长度）为 24 位（3 字节）**；`FileSegment` 的 LOS 亦为 1 字节。
# ═══════════════════════════════════════════════════════════════════

def _encode_u24le(value: int) -> bytes:
    """24 位无符号整数 → 3 字节小端（LOF 为 24 位）."""
    return bytes([value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF])


def _decode_u24le(data: bytes, offset: int) -> int:
    """3 字节小端 → 24 位无符号整数（LOF 为 24 位）."""
    return data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)


def _require_len(data: bytes, offset: int, size: int, name: str) -> None:
    """信息体解析前的长度护栏：不足时抛 ``ValueError`` 而不是 ``IndexError``.

    协议解析器面对截断/脏帧必须给出可诊断的 ``ValueError``（上层据此回
    COT=42 或记录解码错误）；直接下标访问会让异常类型随实现细节漂移。
    """
    if offset < 0 or len(data) - offset < size:
        available = max(0, len(data) - max(offset, 0))
        raise ValueError(f"{name}: need {size} bytes at offset {offset}, have {available}")


@dataclass
class FileReady:
    """文件准备就绪 (F_FR_NA_1 = 120).

    信息体 = ``NOF(2) + LOF(3) + FRQ(1)`` = 6 字节。``status`` 即 FRQ
    （0=肯定，最高位 0x80=否定）。
    """
    ioa: int = 0
    file_name: int = 0       # NOF: 文件名 (16-bit)
    file_length: int = 0     # LOF: 文件长度 (24-bit, 3 字节)
    status: int = 0          # FRQ: 文件准备就绪限定词

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> FileReady:
        _require_len(data, offset, 6, "FileReady")
        fn = data[offset] | (data[offset + 1] << 8)
        fl = _decode_u24le(data, offset + 2)
        st = data[offset + 5]
        return cls(ioa=ioa, file_name=fn, file_length=fl, status=st)

    def to_bytes(self) -> bytes:
        return (bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF])
                + _encode_u24le(self.file_length)
                + bytes([self.status]))

    @property
    def status_str(self) -> str:
        return {0: "缺省", 1: "请求/读", 2: "停止", 3: "删除", 4: "选择"}.get(self.status, f"未知({self.status})")


@dataclass
class SectionReady:
    """节准备就绪 (F_SR_NA_1 = 121).

    信息体 = ``NOF(2) + NOS(1) + LOF(3) + SRQ(1)`` = 7 字节。``status`` 即 SRQ
    （0=肯定，最高位 0x80=否定）。
    """
    ioa: int = 0
    file_name: int = 0
    section_name: int = 0    # NOS: 节名 (8-bit)
    section_length: int = 0  # LOF: 节长度 (24-bit, 3 字节)
    status: int = 0          # SRQ: 节准备就绪限定词

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> SectionReady:
        _require_len(data, offset, 7, "SectionReady")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        sl = _decode_u24le(data, offset + 3)
        st = data[offset + 6]
        return cls(ioa=ioa, file_name=fn, section_name=sn, section_length=sl, status=st)

    def to_bytes(self) -> bytes:
        return (bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF, self.section_name])
                + _encode_u24le(self.section_length)
                + bytes([self.status]))


#: SCQ（选择与召唤限定词）取值 → 名称。
#: 依据：lib60870.NET ``enum SelectAndCallQualifier`` + go-iecp5 ``FileCallOrSelect``
#: （两个互相独立的字节级实现取值一致，见 docs/file_transfer_fls.md §2.6）。
SCQ_NAMES: dict[int, str] = {
    0: "缺省",
    1: "选择文件",
    2: "请求文件",
    3: "去激活文件",
    4: "删除文件",
    5: "选择节",
    6: "请求节",
    7: "去激活节",
}


@dataclass
class CallDirectory:
    """召唤目录/选择文件/召唤文件 (F_SC_NA_1 = 122).

    信息体 = ``NOF(2) + NOS(1) + SCQ(1)``。``qualifier`` 即 SCQ，取值表见 ``SCQ_NAMES``。
    """
    ioa: int = 0
    file_name: int = 0       # NOF: 文件名 (16-bit)
    section_name: int = 0    # NOS: 节名 (8-bit)
    qualifier: int = 0       # SCQ: 见 SCQ_NAMES

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> CallDirectory:
        _require_len(data, offset, 4, "CallDirectory")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        q = data[offset + 3]
        return cls(ioa=ioa, file_name=fn, section_name=sn, qualifier=q)

    def to_bytes(self) -> bytes:
        return bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF, self.section_name, self.qualifier])

    @property
    def qualifier_str(self) -> str:
        return SCQ_NAMES.get(self.qualifier, f"未知({self.qualifier})")


#: F_LS_NA_1 的 LSQ（最后的节/段限定词）取值 → 名称。
#: 依据：lib60870.NET ``enum LastSectionOrSegmentQualifier``。
LSQ_NAMES: dict[int, str] = {
    0: "NOT_USED",
    1: "FILE_TRANSFER_WITHOUT_DEACT",
    2: "FILE_TRANSFER_WITH_DEACT",
    3: "SECTION_TRANSFER_WITHOUT_DEACT",
    4: "SECTION_TRANSFER_WITH_DEACT",
}


@dataclass
class LastSection:
    """最后的节/最后的段 (F_LS_NA_1 = 123).

    信息体 = ``NOF(2) + NOS(1) + LSQ(1) + CHS(1)`` = 5 字节。

    - ``lsq``：最后的节/段限定词（0-4），取值/语义见 ``LSQ_NAMES``；
      **仅 LSQ=1/2 表示"整个文件传输结束"**（见 ``core.protocol.file_transfer``）；
    - ``chs``：本节校验和（CHS），算法见 ``core.protocol.file_transfer``。
    """
    ioa: int = 0
    file_name: int = 0
    section_name: int = 0
    lsq: int = 0             # LSQ: 最后的节/段限定词 (8-bit, 0-4)
    chs: int = 0             # CHS: 本节校验和 (8-bit)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> LastSection:
        _require_len(data, offset, 5, "LastSection")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        lsq = data[offset + 3]
        chs = data[offset + 4]
        return cls(ioa=ioa, file_name=fn, section_name=sn, lsq=lsq, chs=chs)

    def to_bytes(self) -> bytes:
        return bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF,
                      self.section_name, self.lsq, self.chs])

    @property
    def lsq_str(self) -> str:
        return LSQ_NAMES.get(self.lsq, f"未定义({self.lsq})")


@dataclass
class AckFileSection:
    """确认文件/确认节 (F_AF_NA_1 = 124)."""
    ioa: int = 0
    file_name: int = 0
    section_name: int = 0
    qualifier: int = 0       # 0=缺省, 1=肯定文件, 2=否定文件, 3=肯定节, 4=否定节

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> AckFileSection:
        _require_len(data, offset, 4, "AckFileSection")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        q = data[offset + 3]
        return cls(ioa=ioa, file_name=fn, section_name=sn, qualifier=q)

    def to_bytes(self) -> bytes:
        return bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF, self.section_name, self.qualifier])

    @property
    def qualifier_str(self) -> str:
        return {0: "缺省", 1: "肯定文件", 2: "否定文件", 3: "肯定节", 4: "否定节"}.get(self.qualifier, f"未知({self.qualifier})")


@dataclass
class FileSegment:
    """段 (F_SG_NA_1 = 125).

    信息体 = ``NOF(2) + NOS(1) + LOS(1) + 数据``，**没有段号字段**（标准即如此，
    见 docs/file_transfer_fls.md §5.2）；``LOS`` = 本段数据长度 (1 字节)。
    """
    ioa: int = 0
    file_name: int = 0
    section_name: int = 0
    data: bytes = b''        # 段数据 (可变长度；受 LOS 1 字节限制，最多 255 字节)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0, length: int = 0) -> FileSegment:
        _require_len(data, offset, 4, "FileSegment")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        los = data[offset + 3]
        # LOS 声明的段长度必须完整存在：截断帧不得静默返回半段数据
        _require_len(data, offset + 4, los, "FileSegment")
        seg_data = data[offset + 4:offset + 4 + los]
        return cls(ioa=ioa, file_name=fn, section_name=sn, data=seg_data)

    def to_bytes(self) -> bytes:
        return (bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF,
                       self.section_name, len(self.data) & 0xFF])
                + self.data)


@dataclass
class DirectoryEntry:
    """目录 (F_DR_TA_1 = 126) — 带时标CP56Time2a.

    信息体 = ``NOF(2) + LOF(3) + SOF(1) + CP56Time2a(7)`` = 13 字节。
    """
    ioa: int = 0
    file_name: int = 0
    file_length: int = 0     # LOF: 文件长度 (24-bit, 3 字节)
    status: int = 0          # SOF: 文件状态
    time_tag: CP56Time2a = field(default_factory=CP56Time2a)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> DirectoryEntry:
        _require_len(data, offset, 13, "DirectoryEntry")
        fn = data[offset] | (data[offset + 1] << 8)
        fl = _decode_u24le(data, offset + 2)
        st = data[offset + 5]
        tt = CP56Time2a.from_bytes(data, offset + 6)
        return cls(ioa=ioa, file_name=fn, file_length=fl, status=st, time_tag=tt)

    def to_bytes(self) -> bytes:
        return (bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF])
                + _encode_u24le(self.file_length)
                + bytes([self.status])
                + self.time_tag.to_bytes())


@dataclass
class FileSelectCallGet:
    """文件选择/召唤/获取 (F_SC_NB_1 = 127).

    信息体 = ``NOF(2) + NOS(1) + SCQ(1)``。
    """
    ioa: int = 0
    file_name: int = 0
    section_name: int = 0
    qualifier: int = 0       # SCQ: 见 SCQ_NAMES

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> FileSelectCallGet:
        _require_len(data, offset, 4, "FileSelectCallGet")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        q = data[offset + 3]
        return cls(ioa=ioa, file_name=fn, section_name=sn, qualifier=q)

    def to_bytes(self) -> bytes:
        return bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF, self.section_name, self.qualifier])

    @property
    def qualifier_str(self) -> str:
        return SCQ_NAMES.get(self.qualifier, f"未知({self.qualifier})")


@dataclass
class FileReadyAck:
    """文件准备就绪-确认 (F_FR_NB_1 = 128) — IEC 60870-5-101.

    信息体 = ``NOF(2) + LOF(3) + FRQ(1)``，LOF 为 24 位。
    """
    ioa: int = 0
    file_name: int = 0
    file_length: int = 0     # LOF: 24-bit
    status: int = 0          # FRQ

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> FileReadyAck:
        _require_len(data, offset, 6, "FileReadyAck")
        fn = data[offset] | (data[offset + 1] << 8)
        fl = _decode_u24le(data, offset + 2)
        st = data[offset + 5]
        return cls(ioa=ioa, file_name=fn, file_length=fl, status=st)

    def to_bytes(self) -> bytes:
        return (bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF])
                + _encode_u24le(self.file_length)
                + bytes([self.status]))


@dataclass
class SectionReadyAck:
    """节准备就绪-确认 (F_SR_NB_1 = 129) — IEC 60870-5-101.

    信息体 = ``NOF(2) + NOS(1) + LOF(3) + SRQ(1)``，LOF 为 24 位。
    """
    ioa: int = 0
    file_name: int = 0
    section_name: int = 0    # NOS
    section_length: int = 0  # LOF: 24-bit
    status: int = 0          # SRQ

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0, ioa: int = 0) -> SectionReadyAck:
        _require_len(data, offset, 7, "SectionReadyAck")
        fn = data[offset] | (data[offset + 1] << 8)
        sn = data[offset + 2]
        sl = _decode_u24le(data, offset + 3)
        st = data[offset + 6]
        return cls(ioa=ioa, file_name=fn, section_name=sn, section_length=sl, status=st)

    def to_bytes(self) -> bytes:
        return (bytes([self.file_name & 0xFF, (self.file_name >> 8) & 0xFF, self.section_name])
                + _encode_u24le(self.section_length)
                + bytes([self.status]))


# ═══════════════════════════════════════════════════════════════════
#  Type ID Registry (类型标识注册表)
# ═══════════════════════════════════════════════════════════════════

# 类型标识 → 数据类的映射（用于自动解码ASDU信息体）
TYPE_REGISTRY: dict[int, type] = {
    # 监控方向 - 基础类型
    TypeID.M_SP_NA_1: SinglePoint,
    TypeID.M_SP_TA_1: SinglePoint,
    TypeID.M_DP_NA_1: DoublePoint,
    TypeID.M_DP_TA_1: DoublePoint,
    TypeID.M_ST_NA_1: StepPosition,
    TypeID.M_ST_TA_1: StepPosition,
    TypeID.M_BO_NA_1: BitString32,
    TypeID.M_BO_TA_1: BitString32,
    TypeID.M_ME_NA_1: NormalizedValue,
    TypeID.M_ME_TA_1: NormalizedValue,
    TypeID.M_ME_NB_1: ScaledValue,
    TypeID.M_ME_TB_1: ScaledValue,
    TypeID.M_ME_NC_1: ShortFloat,
    TypeID.M_ME_TC_1: ShortFloat,
    TypeID.M_IT_NA_1: CounterValue,
    TypeID.M_IT_TA_1: CounterValue,
    TypeID.M_ME_ND_1: NormalizedValue,   # 不带品质描述词，但结构兼容
    TypeID.M_PS_NA_1: GroupSinglePointWithStatus,
    TypeID.M_PS_TB_1: GroupSinglePointWithStatus,
    # 继电保护
    TypeID.M_EP_TA_1: ProtectionEvent,
    TypeID.M_EP_TB_1: ProtectionEvent,
    TypeID.M_EP_TC_1: ProtectionEvent,
    TypeID.M_EP_TD_1: ProtectionEvent,
    TypeID.M_EP_TE_1: ProtectionEvent,
    TypeID.M_EP_TF_1: ProtectionEvent,
    # 带CP56Time2a的监控类型
    TypeID.M_SP_TB_1: SinglePoint,
    TypeID.M_DP_TB_1: DoublePoint,
    TypeID.M_ST_TB_1: StepPosition,
    TypeID.M_BO_TB_1: BitString32,
    TypeID.M_ME_TD_1: NormalizedValue,
    TypeID.M_ME_TE_1: ScaledValue,
    TypeID.M_ME_TF_1: ShortFloat,
    TypeID.M_IT_TB_1: CounterValue,
    # 控制方向
    TypeID.C_SC_NA_1: SingleCommand,
    TypeID.C_DC_NA_1: DoubleCommand,
    TypeID.C_RC_NA_1: RegulatingStepCommand,
    TypeID.C_SE_NA_1: SetpointCommandN,
    TypeID.C_SE_NB_1: SetpointCommandScaled,
    TypeID.C_SE_NC_1: SetpointCommandS,
    TypeID.C_BO_NA_1: BitString32Command,
    # 控制方向（带时标CP56Time2a）
    TypeID.C_SC_TA_1: SingleCommand,
    TypeID.C_DC_TA_1: DoubleCommand,
    TypeID.C_RC_TA_1: RegulatingStepCommand,
    TypeID.C_SE_TA_1: SetpointCommandN,
    TypeID.C_SE_TB_1: SetpointCommandScaled,
    TypeID.C_SE_TC_1: SetpointCommandS,
    TypeID.C_BO_TA_1: BitString32Command,
    # 系统命令
    TypeID.C_IC_NA_1: InterrogationCommand,  # 总召唤命令
    TypeID.C_CI_NA_1: CounterInterrogationCommand,
    TypeID.C_RD_NA_1: ReadCommand,
    TypeID.C_CS_NA_1: ClockSyncCommand,
    TypeID.C_TS_NA_1: TestCommand,
    TypeID.C_TS_TA_1: TestCommandWithTime,
    TypeID.C_TS_NB_1: TestCommandBitPattern,
    TypeID.C_RP_NA_1: ResetProcessCommand,
    TypeID.C_CD_NA_1: DelayCommand,
    TypeID.M_EI_NA_1: InitializationEnd,
    # 参数命令
    TypeID.P_ME_NA_1: ParameterCommandNormalized,
    TypeID.P_ME_NB_1: ParameterCommandScaled,
    TypeID.P_ME_NC_1: ParameterCommandFloat,
    TypeID.P_ME_ND_1: ParameterCommandNormalizedNoQuality,
    TypeID.P_AC_NA_1: ParameterActivation,
    # 文件传输
    TypeID.F_FR_NA_1: FileReady,
    TypeID.F_SR_NA_1: SectionReady,
    TypeID.F_SC_NA_1: CallDirectory,
    TypeID.F_LS_NA_1: LastSection,
    TypeID.F_AF_NA_1: AckFileSection,
    TypeID.F_SG_NA_1: FileSegment,
    TypeID.F_DR_TA_1: DirectoryEntry,
    TypeID.F_SC_NB_1: FileSelectCallGet,
    TypeID.F_FR_NB_1: FileReadyAck,
    TypeID.F_SR_NB_1: SectionReadyAck,
}


def get_type_info(type_id: int) -> str:
    """返回类型标识的中文描述."""
    try:
        tid = TypeID(type_id)
        return tid.name
    except ValueError:
        return f"未知类型({type_id})"


# ═══════════════════════════════════════════════════════════════════
#  Group Call Definitions
# ═══════════════════════════════════════════════════════════════════

class QualifierOfInterrogation(enum.IntEnum):
    """总召唤限定词 — IEC 60870-5-104 Table 1-75.

    站召唤 QOI=20；组召唤 QOI=20+组号（第1-16组 → 21-36）。
    """
    STATION = 20       # 站召唤（全局）
    GROUP_1 = 21       # 第1组 (QOI=20+1)
    GROUP_2 = 22
    GROUP_3 = 23
    GROUP_4 = 24
    GROUP_5 = 25
    GROUP_6 = 26
    GROUP_7 = 27
    GROUP_8 = 28
    GROUP_9 = 29
    GROUP_10 = 30
    GROUP_11 = 31
    GROUP_12 = 32
    GROUP_13 = 33
    GROUP_14 = 34
    GROUP_15 = 35
    GROUP_16 = 36      # 第16组 (QOI=20+16)

    @classmethod
    def is_valid(cls, qoi: int) -> bool:
        """判断限定词是否有效 (20 或 21-36)."""
        return qoi == 20 or (21 <= qoi <= 36)

    @classmethod
    def get_group_number(cls, qoi: int) -> int | None:
        """提取组号 (1-16), 站召唤返回 None."""
        if 21 <= qoi <= 36:
            return qoi - 20
        return None


class QualifierOfCounterInterrogation(enum.IntEnum):
    """累计量召唤限定词 — IEC 60870-5-104 Table 1-76."""
    STATION = 0        # 站召唤
    GROUP_1 = 1        # 第1组
    GROUP_2 = 2        # 第2组
    GROUP_3 = 3        # 第3组
    GROUP_4 = 4        # 第4组
    REQUEST_GROUP_1 = 5   # 请求第1组
    REQUEST_GROUP_2 = 6   # 请求第2组
    REQUEST_GROUP_3 = 7   # 请求第3组
    REQUEST_GROUP_4 = 8   # 请求第4组

    @classmethod
    def is_freeze_request(cls, qcc: int) -> bool:
        """判断是否为冻结请求 (5-8)."""
        return 5 <= qcc <= 8


# ═══════════════════════════════════════════════════════════════════
#  Connection State Machine
# ═══════════════════════════════════════════════════════════════════

class ConnState(enum.Enum):
    """连接状态."""
    STOPPED     = "Stopped"
    CONNECTING  = "Connecting"
    RUNNING     = "Running"
    DISCONNECTING = "Disconnecting"


class APDUType(enum.Enum):
    """APDU 帧类型."""
    I = "I-frame"  # noqa: E741 — I/S/U 是 IEC 104 标准帧型命名
    S = "S-frame"
    U = "U-frame"
