"""IEC 60870-5-104 Type Definitions and Enums."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional
import time


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

    # ── 控制方向（控制命令，主站→子站）──
    C_SC_NA_1 = 45      # 单命令
    C_DC_NA_1 = 46      # 双命令
    C_RC_NA_1 = 47      # 升降命令
    C_SE_NA_1 = 48      # 设点命令，归一化值
    C_SE_NB_1 = 49      # 设点命令，标度化值
    C_SE_NC_1 = 50      # 设点命令，短浮点数
    C_BO_NA_1 = 51      # 32比特串

    # ── 系统命令 ──
    C_IC_NA_1 = 100     # 总召唤命令
    C_CI_NA_1 = 101     # 累计量召唤命令
    C_RD_NA_1 = 102     # 读命令
    C_CS_NA_1 = 103     # 时钟同步命令
    C_TS_NA_1 = 104     # 测试命令
    C_RP_NA_1 = 105     # 复位进程命令
    C_CD_NA_1 = 106     # 延时获得命令
    C_TS_TA_1 = 107     # 带时标CP56Time2a的测试命令

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
    INTROGEN    = 20    # 响应总召唤
    # 21-31: 特殊用途（兼容范围 32-47, 48-63）
    # 41: 响应第1组召唤
    # 42: 响应第2组召唤
    # ...
    # 63: 响应第23组召唤

    @classmethod
    def group_response(cls, group: int) -> int:
        """返回组召唤响应的传送原因 (41-63)."""
        if not 1 <= group <= 23:
            raise ValueError(f"Group must be 1-23, got {group}")
        return 40 + group


# ═══════════════════════════════════════════════════════════════════
#  Quality Descriptor (品质描述词)
# ═══════════════════════════════════════════════════════════════════

class QualityFlag(enum.IntFlag):
    """Quality descriptor flags — IEC 60870-5-104 Table 1-45/46."""
    OV = 0x01       # bit0: 溢出位
    # bit1-2: 保留
    BL = 0x10       # bit4: 闭锁位 (Blocked)
    NT = 0x20       # bit5: 非当前值 (Not Topical)
    IV = 0x40       # bit6: 无效位 (Invalid)
    # bit7: 保留


@dataclass
class QualityDescriptor:
    """品质描述词解析."""
    raw: int = 0

    @property
    def overflow(self) -> bool:
        return bool(self.raw & 0x01)

    @property
    def blocked(self) -> bool:
        return bool(self.raw & 0x10)

    @property
    def not_topical(self) -> bool:
        return bool(self.raw & 0x20)

    @property
    def invalid(self) -> bool:
        return bool(self.raw & 0x40)

    @property
    def is_good(self) -> bool:
        return self.raw == 0

    def to_int(self) -> int:
        return self.raw & 0x7F

    def __str__(self) -> str:
        flags = []
        if self.overflow: flags.append("OV")
        if self.blocked:  flags.append("BL")
        if self.not_topical: flags.append("NT")
        if self.invalid:  flags.append("IV")
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


# ═══════════════════════════════════════════════════════════════════
#  Group Call Definitions
# ═══════════════════════════════════════════════════════════════════

class QualifierOfInterrogation(enum.IntEnum):
    """总召唤限定词."""
    STATION = 20       # 站召唤
    GROUP_1 = 1        # 第1组
    GROUP_2 = 2        # 第2组
    GROUP_3 = 3
    GROUP_4 = 4
    GROUP_5 = 5
    GROUP_6 = 6
    GROUP_7 = 7
    GROUP_8 = 8
    GROUP_9 = 9
    GROUP_10 = 10
    GROUP_11 = 11
    GROUP_12 = 12
    GROUP_13 = 13
    GROUP_14 = 14
    GROUP_15 = 15
    GROUP_16 = 16


class QualifierOfCounterInterrogation(enum.IntEnum):
    """累计量召唤限定词."""
    STATION = 0        # 站召唤
    GROUP_1 = 1
    GROUP_2 = 2
    GROUP_3 = 3
    GROUP_4 = 4
    REQUEST_1 = 5      # 请求第1组
    REQUEST_2 = 6
    REQUEST_3 = 7
    REQUEST_4 = 8


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
    I = "I-frame"
    S = "S-frame"
    U = "U-frame"
