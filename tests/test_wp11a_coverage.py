"""WP11a ③ 单模块覆盖率补盲.

聚焦 `core/engine/master_protocol.py::process_interrogation_response` 的多类型
分支（tests/README 清单里最实的缺口）：按 TypeID 表驱动构造 ASDU，逐类型断言
数据入库结果。以及 `handle_standard_error_reply` 的 COT 42/43/44 与计时器回调。

按「不为刷数字编测试」原则：每条断言都对应一个可观察的行为（点值/品质/事件），
不做无意义的「调用一下不抛异常」式覆盖。
"""

from __future__ import annotations

import pytest

from core.engine.master import MasterEngine
from core.engine.master_protocol import MasterProtocolHandler
from core.protocol.asdu import ASDU, InformationObject
from core.protocol.types import (
    COT,
    BitString32,
    CounterValue,
    DoublePoint,
    GroupSinglePointWithStatus,
    NormalizedValue,
    QualityDescriptor,
    ScaledValue,
    ShortFloat,
    SinglePoint,
    StepPosition,
    TypeID,
)


def _engine():
    eng = MasterEngine()
    return eng, MasterProtocolHandler(eng)


def _asdu(obj) -> ASDU:
    a = ASDU(type_id=TypeID.M_SP_NA_1, sq=False, num=1,
             cot=COT.INTROGEN, common_addr=1)
    a.objects.append(InformationObject(ioa=1001, data=obj))
    return a


class TestInterrogationResponseBranches:
    """9 类信息对象逐类型断言入库值/品质."""

    @pytest.mark.parametrize("value,expected", [
        (SinglePoint(value=True, quality=QualityDescriptor(0)), True),
        (SinglePoint(value=False, quality=QualityDescriptor(0x80)), False),
    ])
    def test_single_point(self, value, expected):
        eng, h = _engine()
        h.process_interrogation_response(_asdu(value))
        yx = eng.data_store.get_yx(1001)
        assert yx is not None and bool(yx.value) is expected

    @pytest.mark.parametrize("state,expected", [(1, False), (2, True)])
    def test_double_point(self, state, expected):
        eng, h = _engine()
        h.process_interrogation_response(_asdu(
            DoublePoint(value=state, quality=QualityDescriptor(0))))
        yx = eng.data_store.get_yx(1001)
        assert yx is not None and bool(yx.value) is expected

    @pytest.mark.parametrize("data,expected", [
        (NormalizedValue(value=0.5, quality=QualityDescriptor(0)), 0.5),
        (ScaledValue(value=-123, quality=QualityDescriptor(0)), -123.0),
        (ShortFloat(value=3.25, quality=QualityDescriptor(0)), 3.25),
        (StepPosition(value=7, quality=QualityDescriptor(0)), 7.0),
        (BitString32(value=0xDEADBEEF), float(0xDEADBEEF)),
    ])
    def test_measured_values(self, data, expected):
        eng, h = _engine()
        h.process_interrogation_response(_asdu(data))
        yc = eng.data_store.get_yc(1001)
        assert yc is not None and float(yc.value) == pytest.approx(expected)

    def test_counter_value(self):
        eng, h = _engine()
        h.process_interrogation_response(_asdu(
            CounterValue(value=9876, quality=QualityDescriptor(0))))
        ym = eng.data_store.get_ym(1001)
        assert ym is not None and int(ym.value) == 9876

    def test_group_single_point_expands_addresses(self):
        eng, h = _engine()
        h.process_interrogation_response(_asdu(
            GroupSinglePointWithStatus(points=[(True, False), (False, True),
                                              (True, True)])))
        assert [bool(eng.data_store.get_yx(1001 + i).value) for i in range(3)] == [
            True, False, True]

    def test_unknown_object_type_is_ignored(self):
        eng, h = _engine()
        a = _asdu(object())
        h.process_interrogation_response(a)  # 不抛异常，也不入库
        assert eng.data_store.get_yx(1001) is None

    def test_empty_asdu_noop(self):
        eng, h = _engine()
        h.process_interrogation_response(
            ASDU(type_id=TypeID.M_SP_NA_1, sq=False, num=0,
                 cot=COT.INTROGEN, common_addr=1))
        assert eng.data_store.get_yx(1001) is None


class TestStandardErrorReply:
    @pytest.mark.parametrize("cot", [COT.UNKNOWN_TYPE, COT.UNKNOWN_COT,
                                     COT.UNKNOWN_CA])
    def test_known_error_cots_recorded(self, cot):
        eng, h = _engine()
        events: list = []
        eng.set_event_callback(lambda e, d: events.append((e, d)))
        h.handle_standard_error_reply(
            ASDU(type_id=TypeID.C_IC_NA_1, cot=cot, common_addr=1))
        assert events, f"COT={cot} 应触发事件"

    def test_other_cot_ignored(self):
        eng, h = _engine()
        events: list = []
        eng.set_event_callback(lambda e, d: events.append((e, d)))
        h.handle_standard_error_reply(
            ASDU(type_id=TypeID.C_IC_NA_1, cot=COT.ACT, common_addr=1))
        assert not [e for e in events if "unknown" in str(e).lower()]
