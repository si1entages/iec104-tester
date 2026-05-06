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
from typing import Any, Optional

from .constants import (
    VSQ_SQ_BIT, VSQ_NUM_MASK,
)
from .types import (
    TypeID, COT, QualityDescriptor,
    SinglePoint, DoublePoint, StepPosition,
    NormalizedValue, ScaledValue, ShortFloat,
    CounterValue, BitString32,
    SingleCommand, DoubleCommand,
    SetpointCommandN, SetpointCommandS,
    CP24Time2a, CP56Time2a,
    QualifierOfInterrogation, QualifierOfCounterInterrogation,
)


@dataclass
class InformationObject:
    """信息对象 — ASDU 的基本数据单元."""
    ioa: int = 0                # 信息对象地址 (1-3字节)
    data: Any = None            # 具体数据 (SinglePoint/NormalizedValue/etc.)
    time_tag: Optional[CP56Time2a] = None  # 时标（可选）


@dataclass
class ASDU:
    """Application Service Data Unit."""
    type_id: TypeID = TypeID.M_SP_NA_1
    sq: bool = False            # 结构限定词: True=连续, False=单独
    num: int = 1                # 信息对象数量
    cot: int = COT.SPONT        # 传送原因
    origin_addr: int = 0        # 发起地址
    common_addr: int = 1        # 公共地址 (站地址)
    objects: list[InformationObject] = field(default_factory=list)

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
        buf.append(self.cot & 0x3F)
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
                buf.extend(self._encode_data(obj.data))

            # Time tag
            if obj.time_tag is not None:
                buf.extend(obj.time_tag.to_bytes())

        return bytes(buf)

    def _encode_data(self, data: Any) -> bytes:
        """编码信息对象数据."""
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

        # Type ID
        type_id = TypeID(data[pos]); pos += 1

        # VSQ
        vsq = data[pos]; pos += 1
        sq = bool(vsq & VSQ_SQ_BIT)
        num = vsq & VSQ_NUM_MASK

        # COT
        cot = data[pos] & 0x3F; pos += 1
        origin_addr = data[pos]; pos += 1

        # Common Address
        if ca_length == 2:
            common_addr = data[pos] | (data[pos + 1] << 8); pos += 2
        else:
            common_addr = data[pos]; pos += 1

        asdu = cls(
            type_id=type_id,
            sq=sq,
            num=num,
            cot=cot,
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

        return asdu

    @classmethod
    def _decode_object_data(cls, type_id: TypeID, data: bytes, cot: int
                             ) -> tuple[Any, Optional[CP56Time2a], int]:
        """解码信息对象的数据部分.

        Returns:
            (data, time_tag, consumed_bytes)
        """
        # 根据类型标识确定数据长度和解析方式
        handlers = {
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
            TypeID.M_ME_ND_1: (2, lambda d: NormalizedValue.from_bytes(d)),

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
            TypeID.M_IT_TB_1: (5, lambda d: CounterValue.from_bytes(d)),

            # ── 控制命令 ──
            TypeID.C_SC_NA_1: (1, lambda d: SingleCommand.from_bytes(d)),
            TypeID.C_DC_NA_1: (1, lambda d: DoubleCommand.from_bytes(d)),
            TypeID.C_RC_NA_1: (1, lambda d: None),  # 升降命令
            TypeID.C_SE_NA_1: (3, lambda d: SetpointCommandN.from_bytes(d)),
            TypeID.C_SE_NB_1: (3, lambda d: ScaledValue.from_bytes(d)),
            TypeID.C_SE_NC_1: (5, lambda d: SetpointCommandS.from_bytes(d)),
            TypeID.C_BO_NA_1: (4, lambda d: BitString32.from_bytes(d)),

            # ── 系统命令 ──
            TypeID.C_IC_NA_1: (1, lambda d: d),      # 总召唤
            TypeID.C_CI_NA_1: (1, lambda d: d),      # 累计量召唤
            TypeID.C_RD_NA_1: (0, lambda d: None),   # 读命令
            TypeID.C_CS_NA_1: (7, lambda d: d),      # 时钟同步
            TypeID.C_TS_NA_1: (2, lambda d: d),      # 测试命令
            TypeID.C_RP_NA_1: (1, lambda d: d),      # 复位进程
            TypeID.C_CD_NA_1: (2, lambda d: d),      # 延时获得
            TypeID.C_TS_TA_1: (9, lambda d: d),      # 带时标测试
        }

        # 带时标的类型
        timed_types = {
            TypeID.M_SP_TA_1, TypeID.M_SP_TB_1,
            TypeID.M_DP_TA_1, TypeID.M_DP_TB_1,
            TypeID.M_ST_TA_1, TypeID.M_ST_TB_1,
            TypeID.M_BO_TA_1, TypeID.M_BO_TB_1,
            TypeID.M_ME_TA_1, TypeID.M_ME_TD_1,
            TypeID.M_ME_TB_1, TypeID.M_ME_TE_1,
            TypeID.M_ME_TC_1, TypeID.M_ME_TF_1,
            TypeID.M_IT_TA_1, TypeID.M_IT_TB_1,
        }

        # 使用CP56Time2a的类型
        cp56_types = {
            TypeID.M_SP_TB_1, TypeID.M_DP_TB_1,
            TypeID.M_ST_TB_1, TypeID.M_BO_TB_1,
            TypeID.M_ME_TD_1, TypeID.M_ME_TE_1,
            TypeID.M_ME_TF_1, TypeID.M_IT_TB_1,
        }

        if type_id not in handlers:
            # 未知类型 — 跳过
            return None, None, 0

        data_size, decoder = handlers[type_id]
        if len(data) < data_size:
            return None, None, 0

        obj_data = decoder(data[:data_size])
        consumed = data_size

        # 时标
        time_tag = None
        if type_id in timed_types:
            if type_id in cp56_types:
                if len(data) >= consumed + 7:
                    time_tag = CP56Time2a.from_bytes(data, consumed)
                    consumed += 7
            else:
                # CP24Time2a (旧类型)
                if len(data) >= consumed + 3:
                    time_tag = CP56Time2a.from_bytes(data, consumed)
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
            qoi: 限定词 (20=站召唤, 1-16=组召唤)
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
    def build_general_interrogation_ack(common_addr: int, qoi: int = 20) -> bytes:
        """构造总召唤确认."""
        return ASDUBuilder.build_general_interrogation(
            common_addr, qoi, cot=COT.ACTCON
        )

    @staticmethod
    def build_general_interrogation_end(common_addr: int, qoi: int = 20) -> bytes:
        """构造总召唤结束."""
        return ASDUBuilder.build_general_interrogation(
            common_addr, qoi, cot=COT.ACTTERM
        )

    @staticmethod
    def build_clock_sync(common_addr: int, time_tag: Optional[CP56Time2a] = None) -> bytes:
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
            data=time_tag.to_bytes(),
            time_tag=time_tag,
        ))
        return asdu.encode()

    @staticmethod
    def build_clock_sync_ack(common_addr: int, time_tag: Optional[CP56Time2a] = None) -> bytes:
        """构造时钟同步确认."""
        if time_tag is None:
            time_tag = CP56Time2a.now()
        asdu = ASDU(
            type_id=TypeID.C_CS_NA_1,
            sq=False,
            num=1,
            cot=COT.ACTCON,
            common_addr=common_addr,
        )
        asdu.objects.append(InformationObject(
            ioa=0,
            data=time_tag.to_bytes(),
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
    def build_single_command(common_addr: int, ioa: int, state: bool,
                              select: bool = False, qu: int = 0) -> bytes:
        """构造单命令 (C_SC_NA_1)."""
        asdu = ASDU(
            type_id=TypeID.C_SC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        sc = SingleCommand(ioa=ioa, state=state, select=select, qu=qu)
        asdu.objects.append(InformationObject(ioa=ioa, data=sc))
        return asdu.encode()

    @staticmethod
    def build_double_command(common_addr: int, ioa: int, state: int,
                              select: bool = False, qu: int = 0) -> bytes:
        """构造双命令 (C_DC_NA_1)."""
        asdu = ASDU(
            type_id=TypeID.C_DC_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        dc = DoubleCommand(ioa=ioa, state=state, select=select, qu=qu)
        asdu.objects.append(InformationObject(ioa=ioa, data=dc))
        return asdu.encode()

    @staticmethod
    def build_setpoint_normalized(common_addr: int, ioa: int, value: float,
                                    select: bool = False) -> bytes:
        """构造归一化设点命令 (C_SE_NA_1)."""
        asdu = ASDU(
            type_id=TypeID.C_SE_NA_1,
            sq=False,
            num=1,
            cot=COT.ACT,
            common_addr=common_addr,
        )
        sn = SetpointCommandN(ioa=ioa, value=value, select=select)
        asdu.objects.append(InformationObject(ioa=ioa, data=sn))
        return asdu.encode()

    @staticmethod
    def build_setpoint_shortfloat(common_addr: int, ioa: int, value: float,
                                    select: bool = False) -> bytes:
        """构造短浮点设点命令 (C_SE_NC_1)."""
        asdu = ASDU(
            type_id=TypeID.C_SE_NC_1,
            sq=False,
            num=1,
            cot=COT.ACT,
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


# ═══════════════════════════════════════════════════════════════════
#  完整 APDU 编解码（APCI + ASDU）
# ═══════════════════════════════════════════════════════════════════

@dataclass
class APDU:
    """完整 APDU = APCI + ASDU."""
    tx_seq: int = 0
    rx_seq: int = 0
    asdu: Optional[ASDU] = None
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
