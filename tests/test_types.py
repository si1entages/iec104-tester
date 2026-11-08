"""数据类型编解码测试."""

from core.protocol.types import (
    BitString32,
    CounterValue,
    CP24Time2a,
    CP56Time2a,
    DoublePoint,
    NormalizedValue,
    QualityDescriptor,
    ScaledValue,
    ShortFloat,
    SinglePoint,
    StepPosition,
)


def test_single_point():
    """测试单点信息编解码."""
    print("=== Single Point Tests ===")

    for value in [True, False]:
        sp = SinglePoint(value=value)
        data = sp.to_bytes()
        assert len(data) == 1

        sp2 = SinglePoint.from_bytes(data)
        assert sp2.value == value

    # 带品质
    sp = SinglePoint(value=True, quality=QualityDescriptor(0x80))  # IV (bit7)
    data = sp.to_bytes()
    sp2 = SinglePoint.from_bytes(data)
    assert sp2.value == True
    assert sp2.quality.invalid == True

    print("  ✅ All single point tests passed")


def test_double_point():
    """测试双点信息编解码."""
    print("=== Double Point Tests ===")

    for val in [0, 1, 2, 3]:
        dp = DoublePoint(value=val)
        data = dp.to_bytes()
        dp2 = DoublePoint.from_bytes(data)
        assert dp2.value == val

    print("  ✅ All double point tests passed")


def test_normalized_value():
    """测试归一化值编解码."""
    print("=== Normalized Value Tests ===")

    for val in [0.0, 0.5, -0.5, 1.0, -1.0]:
        nv = NormalizedValue(value=val)
        data = nv.to_bytes()
        assert len(data) == 3

        nv2 = NormalizedValue.from_bytes(data)
        assert abs(nv2.value - val) < 0.001, f"Expected {val}, got {nv2.value}"

    print("  ✅ All normalized value tests passed")


def test_short_float():
    """测试短浮点数编解码."""
    print("=== Short Float Tests ===")

    for val in [0.0, 3.14, -273.15, 100.0, 0.001]:
        sf = ShortFloat(value=val)
        data = sf.to_bytes()
        assert len(data) == 5

        sf2 = ShortFloat.from_bytes(data)
        assert abs(sf2.value - val) < 0.001, f"Expected {val}, got {sf2.value}"

    print("  ✅ All short float tests passed")


def test_scaled_value():
    """测试标度化值编解码."""
    print("=== ScaledValue Tests ===")

    # 测试正值
    sv = ScaledValue(value=12345, quality=QualityDescriptor())
    data = sv.to_bytes()
    sv2 = ScaledValue.from_bytes(data)
    assert sv2.value == 12345
    assert sv2.quality.is_good

    # 测试负值
    sv = ScaledValue(value=-12345, quality=QualityDescriptor())
    data = sv.to_bytes()
    sv2 = ScaledValue.from_bytes(data)
    assert sv2.value == -12345

    # 测试边界值
    for val in [-32768, 32767, 0]:
        sv = ScaledValue(value=val)
        data = sv.to_bytes()
        sv2 = ScaledValue.from_bytes(data)
        assert sv2.value == val

    print("  ✅ ScaledValue tests passed")


def test_step_position():
    """测试步位置信息编解码."""
    print("=== StepPosition Tests ===")

    # 测试正值
    sp = StepPosition(value=32, quality=QualityDescriptor(), transient=False)
    data = sp.to_bytes()
    sp2 = StepPosition.from_bytes(data)
    assert sp2.value == 32
    assert sp2.transient == False

    # 测试负值
    sp = StepPosition(value=-32, quality=QualityDescriptor(), transient=False)
    data = sp.to_bytes()
    sp2 = StepPosition.from_bytes(data)
    assert sp2.value == -32

    # 测试transient标志
    sp = StepPosition(value=10, quality=QualityDescriptor(), transient=True)
    data = sp.to_bytes()
    sp2 = StepPosition.from_bytes(data)
    assert sp2.transient == True

    print("  ✅ StepPosition tests passed")


def test_bitstring32():
    """测试32比特串编解码."""
    print("=== BitString32 Tests ===")

    bs = BitString32(value=0x12345678)
    data = bs.to_bytes()
    bs2 = BitString32.from_bytes(data)
    assert bs2.value == 0x12345678

    # 测试边界值
    for val in [0, 0xFFFFFFFF, 0x80000000]:
        bs = BitString32(value=val)
        data = bs.to_bytes()
        bs2 = BitString32.from_bytes(data)
        assert bs2.value == val

    print("  ✅ BitString32 tests passed")


def test_counter_value():
    """测试累计量编解码."""
    print("=== CounterValue Tests ===")

    cv = CounterValue(value=123456, quality=QualityDescriptor(), sequence=5)
    data = cv.to_bytes()
    cv2 = CounterValue.from_bytes(data)
    assert cv2.value == 123456
    assert cv2.sequence == 5

    # 测试负值
    cv = CounterValue(value=-123456, quality=QualityDescriptor())
    data = cv.to_bytes()
    cv2 = CounterValue.from_bytes(data)
    assert cv2.value == -123456

    print("  ✅ CounterValue tests passed")


def test_cp56time2a():
    """测试 CP56Time2a 时标编解码."""
    print("=== CP56Time2a Tests ===")

    t = CP56Time2a(
        millisecond=12345,
        minute=30,
        hour=14,
        day=15,
        month=6,
        year=25,
        weekday=7,
    )
    data = t.to_bytes()
    assert len(data) == 7

    t2 = CP56Time2a.from_bytes(data)
    assert t2.millisecond == 12345
    assert t2.minute == 30
    assert t2.hour == 14
    assert t2.day == 15
    assert t2.month == 6
    assert t2.year == 25

    # now()
    now = CP56Time2a.now()
    assert 1 <= now.month <= 12
    assert 1 <= now.day <= 31
    assert 0 <= now.hour <= 23

    print("  ✅ All CP56Time2a tests passed")


def test_cp24time2a():
    """测试CP24Time2a时标编解码."""
    print("=== CP24Time2a Tests ===")

    ct = CP24Time2a(millisecond=12345, minute=30, invalid=False)
    data = ct.to_bytes()
    ct2 = CP24Time2a.from_bytes(data)
    assert ct2.millisecond == 12345
    assert ct2.minute == 30
    assert ct2.invalid == False

    # 测试无效标志
    ct = CP24Time2a(millisecond=0, minute=0, invalid=True)
    data = ct.to_bytes()
    ct2 = CP24Time2a.from_bytes(data)
    assert ct2.invalid == True

    print("  ✅ CP24Time2a tests passed")
