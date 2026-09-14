"""响应行为配置单元测试."""

from core.engine.slave import ResponseBehavior, SlaveEngine
from core.data.point_table import PointTable


def test_response_behavior_from_dict():
    cfg = {
        "delays": {"gi": 0.5, "command": 0.2, "data": 1.0},
        "errors": {
            "drop_frames": True,
            "drop_rate": 0.3,
            "corrupt": True,
            "no_response": True,
            "wrong_cot": True,
        },
        "quality": {
            "invalid": True,
            "blocked": False,
            "not_topical": True,
            "overflow": False,
        },
        "connection": {
            "reject_startdt": True,
            "auto_stopdt": False,
            "send_testfr": True,
            "testfr_interval": 15,
        },
    }
    rb = ResponseBehavior.from_dict(cfg)
    assert rb.gi_delay == 0.5
    assert rb.command_delay == 0.2
    assert rb.data_delay == 1.0
    assert rb.drop_frames is True
    assert rb.drop_rate == 0.3
    assert rb.corrupt is True
    assert rb.no_response is True
    assert rb.wrong_cot is True
    assert rb.force_invalid is True
    assert rb.force_not_topical is True
    assert rb.reject_startdt is True
    assert rb.send_testfr is True
    assert rb.testfr_interval == 15
    # IV=0x80 + NT=0x40
    assert rb.quality_mask() == 0xC0


def test_response_behavior_defaults():
    rb = ResponseBehavior()
    assert rb.gi_delay == 0.0
    assert rb.drop_frames is False
    assert rb.quality_mask() == 0
    assert not rb.has_delay()


def test_apply_quality_mask():
    engine = SlaveEngine(port=0, point_table=PointTable())
    engine.set_response_behavior({
        "quality": {"invalid": True, "overflow": True},
    })
    # 原始品质 0 → 强制 IV|OV
    assert engine._apply_quality(0) == (0x80 | 0x04)
    # 原始品质已有 BL → 再叠加 IV
    engine.set_response_behavior({"quality": {"invalid": True}})
    assert engine._apply_quality(0x10) == (0x10 | 0x80)


def test_maybe_drop_frame():
    engine = SlaveEngine(port=0, point_table=PointTable())
    # 默认不丢
    assert engine._maybe_drop_frame() is False

    engine.set_response_behavior({
        "errors": {"drop_frames": True, "drop_rate": 0},
    })
    # rate=0 但 drop_frames=True → 总是丢
    assert engine._maybe_drop_frame() is True

    engine.set_response_behavior({
        "errors": {"drop_frames": False, "drop_rate": 1.0},
    })
    assert engine._maybe_drop_frame() is False


def test_set_response_behavior_from_dataclass():
    engine = SlaveEngine(port=0, point_table=PointTable())
    rb = ResponseBehavior(gi_delay=1.0, no_response=True)
    engine.set_response_behavior(rb)
    assert engine.response_behavior.gi_delay == 1.0
    assert engine.response_behavior.no_response is True
