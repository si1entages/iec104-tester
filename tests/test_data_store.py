"""`core/data/data_store.py` 单元测试.

补齐 get_all_*/引用获取、变化集合消费、快照、订阅去重与异常吞噬、
最近事件、统计与清空、YxData.state_str 等分支。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.data.data_store import RealtimeDB, YxData


def test_yx_state_str_branches():
    point = YxData()
    point.value = True
    assert point.state_str == "合(ON)"
    point.value = False
    assert point.state_str == "分(OFF)"

    point.double_state = 1
    assert point.state_str == "分(OFF)"
    point.double_state = 2
    assert point.state_str == "合(ON)"
    point.double_state = 3
    assert point.state_str == "中间"
    point.double_state = 9
    assert point.state_str == "?"


def test_accessors_and_get_all():
    db = RealtimeDB()
    db.update_yx(1, True)
    db.update_yc(2, 1.5, scale=2.0, offset=1.0)
    db.update_yk(3, "select")
    db.update_ym(4, 100)
    db.update_step(5, -3, transient=True)

    assert db.get_all_yx()[1].value is True
    assert db.get_all_yc()[2].value == 4.0
    assert db.get_all_yk()[3].select_pending is True
    assert db.get_all_ym()[4].value == 100
    assert db.get_all_step()[5].value == -3
    assert db.get_all_step()[5].transient is True

    # *_ref 返回同一份引用（无拷贝）
    assert db.get_yx_ref()[1] is db.get_yx(1)
    assert db.get_yc_ref()[2] is db.get_yc(2)
    assert db.get_yk_ref()[3] is db.get_yk(3)
    assert db.get_ym_ref()[4] is db.get_ym(4)
    assert db.get_step_ref()[5] is db.get_step(5)

    # 未命中返回 None
    assert db.get_yx(999) is None
    assert db.get_yc(999) is None
    assert db.get_yk(999) is None
    assert db.get_ym(999) is None
    assert db.get_step(999) is None


def test_update_yk_select_and_execute_clear_pending():
    db = RealtimeDB()
    db.update_yk(10, "select")
    assert db.get_yk(10).select_pending is True
    db.update_yk(10, "execute", state=True)
    assert db.get_yk(10).select_pending is False
    assert db.get_yk(10).last_command == "execute"
    assert db.get_yk(10).last_state is True
    db.update_yk(10, "select")
    db.update_yk(10, "cancel")
    assert db.get_yk(10).select_pending is False


def test_get_changed_ioas_clears_sets():
    db = RealtimeDB()
    db.update_yx(1, True)
    db.update_yc(2, 1.0)
    db.update_ym(3, 5)

    assert db.get_changed_ioas() == ({1}, {2}, {3})
    # 消费后清空
    assert db.get_changed_ioas() == (set(), set(), set())


def test_snapshot_stats_and_clear():
    db = RealtimeDB()
    db.update_yx(1, True)
    db.update_yc(2, 2.0)

    snapshot = db.get_snapshot()
    assert snapshot["yx"][1].value is True
    assert snapshot["yc"][2].value == 2.0
    assert snapshot["stats"]["yx_count"] == 1
    assert snapshot["stats"]["yc_count"] == 1
    assert snapshot["stats"]["total_updates"] == 2
    assert snapshot["stats"]["total_changes"] == 2

    stats = db.stats
    assert stats["total_updates"] == 2
    assert stats["event_buffer_size"] == 2

    db.clear()
    assert db.stats["yx_count"] == 0
    assert db.stats["yc_count"] == 0
    assert db.stats["total_updates"] == 0
    assert db.stats["total_changes"] == 0
    assert db.get_recent_events() == []


def test_subscribe_dedup_unsubscribe_and_swallow_errors():
    db = RealtimeDB()
    seen = []

    def on_change(event):
        seen.append(event.ioa)

    def bad_callback(event):
        raise RuntimeError("callback failure")

    db.subscribe(on_change)
    db.subscribe(on_change)     # 去重：同一回调只注册一次
    db.subscribe(bad_callback)  # 异常必须被吞掉，不影响其它订阅者

    db.update_yx(7, True)
    assert seen == [7]

    db.unsubscribe(on_change)
    db.unsubscribe(on_change)   # 幂等
    db.update_yx(8, True)
    assert seen == [7]


def test_recent_events_limit_and_full_list():
    db = RealtimeDB()
    for ioa in range(5):
        db.update_yx(ioa, True)

    recent = db.get_recent_events(2)
    assert [e.ioa for e in recent] == [3, 4]
    assert len(db.get_recent_events(100)) == 5


def test_init_from_point_table_populates_all_types():
    from core.data.point_table import PointTable

    table = PointTable()
    table.generate_demo_points(yx_count=2, yc_count=2, yk_count=2, ym_count=2, step_count=2)

    db = RealtimeDB()
    db.init_from_point_table(table)

    assert len(db.get_all_yx()) == 2
    assert len(db.get_all_yc()) == 2
    assert len(db.get_all_yk()) == 2
    assert len(db.get_all_ym()) == 2
    assert len(db.get_all_step()) == 2
