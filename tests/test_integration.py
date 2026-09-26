"""集成测试."""

from core.protocol.apci import APCICodec
from core.protocol.asdu import ASDU, ASDUBuilder
from core.protocol.types import COT, TypeID


def test_full_apdu_roundtrip():
    """测试完整 APDU 编解码往返."""
    print("=== Full APDU Roundtrip ===")

    # I帧
    asdu_data = ASDUBuilder.build_short_float(1, 1001, 220.5, cot=COT.SPONT)
    frame = APCICodec.encode_i(42, 10, asdu_data)

    apci, _ = APCICodec.decode(frame)
    assert apci.is_i_frame
    assert apci.tx_seq == 42
    assert apci.rx_seq == 10

    asdu = ASDU.decode(frame[6:6 + apci.asdu_length])
    assert asdu.type_id == TypeID.M_ME_NC_1
    assert abs(asdu.objects[0].data.value - 220.5) < 0.1

    print("  ✅ Full APDU roundtrip test passed")
