"""值守告警引擎测试（T93）.

四类规则各一条触发/解除证据（用可控快照直接评估，不起真实引擎）：
限值越限 / 死值陈旧 / 突变 / 通信中断；生命周期（ack/去抖/clear）与 REST 接线。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from webui.alarms import AlarmService
from webui.bridge import EngineBridge
from webui.server import create_app


class _FakeBridge:
    """最小桥：供 AlarmService 直接评估（role + status + points 快照可控）."""

    def __init__(self, role: str = "master") -> None:
        self.role = role
        self._status: dict[str, Any] = {"running": True, "state": "Running", "rx": 0}
        self._points: list[dict[str, Any]] = []

    def status(self) -> dict:
        return dict(self._status)

    def snapshot_points(self) -> list[dict]:
        return list(self._points)


def _svc(**kw: float) -> AlarmService:
    bridge = _FakeBridge()
    return AlarmService(bridge, **kw)


def test_limit_rule_fires_and_clears_with_debounce():
    svc = _svc(debounce=2)
    svc.bridge._points = [{"ioa": 101, "type": "YC", "value": 150.0,
                           "min_value": 0.0, "max_value": 100.0, "ts": time.time() * 1000}]
    svc.evaluate()
    assert ("limit", 101) not in svc.active  # 第一次评估未到去抖阈值
    svc.evaluate()
    assert ("limit", 101) in svc.active
    assert "超出" in svc.active[("limit", 101)].message
    # 恢复到限值内 → 自动解除
    svc.bridge._points[0]["value"] = 50.0
    svc.evaluate()
    assert ("limit", 101) not in svc.active
    assert svc.history[-1].cleared_ts is not None


def test_stale_rule_uses_last_update_ts():
    svc = _svc(stale_seconds=60)
    old_ms = (time.time() - 120) * 1000
    fresh_ms = time.time() * 1000
    svc.bridge._points = [
        {"ioa": 1, "type": "YX", "value": "ON", "ts": old_ms},
        {"ioa": 2, "type": "YX", "value": "OFF", "ts": fresh_ms},
        {"ioa": 3, "type": "YX", "value": "OFF", "ts": 0},  # 从未收到数据：不告警
    ]
    svc.evaluate()
    svc.evaluate()
    assert ("stale", 1) in svc.active
    assert ("stale", 2) not in svc.active
    assert ("stale", 3) not in svc.active
    assert "未更新" in svc.active[("stale", 1)].message


def test_jump_rule_requires_config_and_cooldown():
    svc = _svc()  # jump_delta 未配置 → 不告警
    now_ms = time.time() * 1000
    svc.bridge._points = [{"ioa": 101, "type": "YC", "value": 1.0, "ts": now_ms}]
    svc.evaluate()
    svc.bridge._points[0]["value"] = 999.0
    svc.evaluate()
    assert ("jump", 101) not in svc.active

    svc2 = _svc(jump_delta=10.0)
    svc2.bridge._points = [{"ioa": 101, "type": "YC", "value": 1.0, "ts": now_ms}]
    svc2.evaluate()
    svc2.bridge._points[0]["value"] = 999.0
    svc2.evaluate()
    assert ("jump", 101) in svc2.active
    assert "突变" in svc2.active[("jump", 101)].message


def test_comm_rule_tracks_rx_stall():
    svc = _svc(comm_seconds=10.0)
    svc.bridge._status = {"running": True, "state": "Running", "rx": 100}
    svc.evaluate()
    svc.bridge._status["rx"] = 100  # rx 无增长
    svc._rx_stall_since = time.time() - 20  # 模拟停振 20s
    svc.evaluate()
    assert ("comm", None) in svc.active
    assert "通信中断" in svc.active[("comm", None)].message
    # rx 恢复增长 → 解除
    svc.bridge._status["rx"] = 101
    svc._rx_stall_since = None
    svc.evaluate()
    assert ("comm", None) not in svc.active
    # 非 Running 不评估
    svc2 = _svc(comm_seconds=5.0)
    svc2.bridge._status = {"running": False, "state": "Stopped", "rx": 0}
    svc2._rx_stall_since = time.time() - 30
    svc2.evaluate()
    assert ("comm", None) not in svc2.active


def test_ack_and_history_bounds():
    svc = _svc(debounce=1, stale_seconds=10)
    svc.bridge._points = [{"ioa": 1, "type": "YX", "value": "ON", "ts": (time.time() - 100) * 1000}]
    svc.evaluate()
    alarm = svc.active[("stale", 1)]
    assert svc.ack(alarm.id) is True
    assert svc.ack(99999) is False
    assert svc.active[("stale", 1)].acked is True
    assert svc.history_list(10)["total"] == 1


@pytest.mark.asyncio
async def test_alarm_rest_endpoints():
    bridge = EngineBridge(role="slave")
    async with TestClient(TestServer(create_app(bridge))) as client:
        # bridge 角色之外都应有告警服务（slave 无 comm 规则但端点可用）
        r = await client.get("/api/alarms")
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is True and body["active"] == []
        assert body["config"]["stale_seconds"] == 60.0

        r = await client.get("/api/alarms/history")
        assert (await r.json())["ok"] is True

        r = await client.post("/api/alarms/ack", json={"id": 1})
        assert (await r.json())["ok"] is False  # 无此告警

        r = await client.post("/api/alarms/config", json={"stale_seconds": 30})
        cfg = (await r.json())["config"]
        assert cfg["stale_seconds"] == 30.0
