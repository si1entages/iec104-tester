"""WP2 后端：对点/传动验收数据模型、判定、持久化、导出与 API 契约测试."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.data.commission_store import CommissionStore
from core.data.commissioning import (
    CommissionItem,
    CommissionSession,
    ItemKind,
    SessionStatus,
    Verdict,
    build_items_from_points,
    judge,
    quality_bad,
)
from webui.bridge import EngineBridge
from webui.commission_export import export, export_html, export_json, export_xlsx
from webui.server import create_app

# ── 纯判定规则 ────────────────────────────────────────────────────

@pytest.mark.parametrize("q,expected", [
    ("", False), ("GOOD", False), ("good", False),
    ("IV", True), ("IV|NT", True), ("SB", True), ("BL", True), ("OV", True),
])
def test_quality_bad(q, expected):
    assert quality_bad(q) is expected


def test_judge_yc_within_tolerance_pass():
    it = CommissionItem(ioa=10, kind=ItemKind.YC, expected=100.0, tolerance=0.5)
    judge(it, observed=100.3, quality="GOOD")
    assert it.verdict == Verdict.PASS
    assert it.actual == 100.3
    assert it.rx_time > 0


def test_judge_yc_outside_tolerance_fail():
    it = CommissionItem(ioa=10, kind=ItemKind.YC, expected=100.0, tolerance=0.5)
    judge(it, observed=102.0, quality="GOOD")
    assert it.verdict == Verdict.FAIL
    assert "值不符" in it.reason


def test_judge_bool_normalization():
    it = CommissionItem(ioa=1, kind=ItemKind.YX, expected=True)
    judge(it, observed=1, quality="GOOD")
    assert it.verdict == Verdict.PASS
    it2 = CommissionItem(ioa=2, kind=ItemKind.YX, expected=False)
    judge(it2, observed=0, quality="GOOD")
    assert it2.verdict == Verdict.PASS


def test_judge_quality_bad_and_reason_always_fail():
    it = CommissionItem(ioa=1, kind=ItemKind.YX, expected=True)
    judge(it, observed=True, quality="IV|NT")
    assert it.verdict == Verdict.FAIL and "品质异常" in it.reason
    it2 = CommissionItem(ioa=2, kind=ItemKind.YK, expected=True)
    judge(it2, observed=True, reason="SBO 被拒")
    assert it2.verdict == Verdict.FAIL and "SBO" in it2.reason


def test_judge_timeout_reason_wins_over_value():
    """超时/SBO 拒绝即使观测值恰好相等也不得判通过。"""
    it = CommissionItem(ioa=1, kind=ItemKind.YX, expected=True)
    judge(it, observed=True, quality="GOOD", reason="等待回读/变位超时")
    assert it.verdict == Verdict.FAIL


def test_judge_no_expected_stays_pending():
    it = CommissionItem(ioa=1, kind=ItemKind.YX)
    judge(it, observed=True)
    assert it.verdict == Verdict.PENDING
    assert "人工复核" in it.reason


def test_build_items_from_points_ignores_ym():
    pts = [
        {"ioa": 1, "type": "YX", "name": "开关", "group": 2},
        {"ioa": 2, "type": "YC", "name": "电压", "group": 1,
         "min_value": 0, "max_value": 200},
        {"ioa": 3, "type": "YK", "name": "遥控", "group": 1},
        {"ioa": 4, "type": "YM", "name": "电度", "group": 1},
    ]
    items = build_items_from_points(pts)
    assert [i.ioa for i in items] == [1, 2, 3]
    assert items[1].tolerance == pytest.approx(1.0)  # (200-0)*0.005
    assert items[0].group == 2


def test_session_summary_and_roundtrip():
    s = CommissionSession(id="c-1", name="验收", operator="张三")
    s.items = [
        CommissionItem(ioa=1, verdict=Verdict.PASS),
        CommissionItem(ioa=2, verdict=Verdict.FAIL),
        CommissionItem(ioa=3, verdict=Verdict.MANUAL),
        CommissionItem(ioa=4),
    ]
    s.status = SessionStatus.DONE
    assert s.summary() == {"total": 4, "pending": 1, "pass": 1,
                           "fail": 1, "manual": 1, "done": 3}
    d = s.to_dict()
    assert d["status"] == "done" and len(d["items"]) == 4
    restored = CommissionItem.from_dict(d["items"][0])
    assert restored.ioa == 1 and restored.verdict == Verdict.PASS


# ── 持久化 ────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    s = CommissionStore(tmp_path / "sub" / "commission.db")
    s.open()
    yield s
    s.close()


def test_store_save_load_roundtrip(store):
    s = CommissionSession(id="c-1", name="验收", operator="李四")
    s.items = [CommissionItem(ioa=7, kind=ItemKind.YC, expected=1.5,
                              verdict=Verdict.PASS, tx_frame="6804", rx_frame="6806")]
    store.save(s)
    loaded = store.load("c-1")
    assert loaded is not None
    assert loaded.name == "验收" and loaded.operator == "李四"
    assert loaded.items[0].tx_frame == "6804"
    assert loaded.items[0].verdict == Verdict.PASS
    assert len(store.list_sessions()) == 1
    assert store.stats() == {"sessions": 1}


def test_store_set_verdict_and_delete(store):
    s = CommissionSession(id="c-2")
    s.items = [CommissionItem(ioa=9)]
    store.save(s)
    out = store.set_verdict("c-2", 9, "fail", "现场复核不通过", "王五")
    assert out["verdict"] == "fail" and out["note"] == "现场复核不通过"
    assert store.load("c-2").items[0].operator == "王五"
    with pytest.raises(ValueError):
        store.set_verdict("c-2", 9, "bogus", "", "")
    assert store.delete("c-2") is True
    assert store.load("c-2") is None


def test_store_lazy_open_no_side_effect(tmp_path):
    """构造/无访问时不建文件，避免契约自检与单测污染 data/。"""
    p = tmp_path / "lazy.db"
    s = CommissionStore(p)
    assert not p.exists()
    assert s.list_sessions() == []
    assert p.exists()


# ── 导出 ──────────────────────────────────────────────────────────

def _sample_session() -> dict:
    s = CommissionSession(id="c-test", name="110kV 验收", operator="张三",
                          status=SessionStatus.DONE, started_at=1.0, finished_at=2.0)
    s.items = [
        CommissionItem(ioa=1, name="开关A", kind=ItemKind.YX, expected=True,
                       actual=True, quality="GOOD", verdict=Verdict.PASS,
                       tx_frame="6804", rx_frame="6806", tx_time=1.1, rx_time=1.2),
        CommissionItem(ioa=2, name="电压", kind=ItemKind.YC, expected=100.0,
                       actual=101.0, quality="GOOD", verdict=Verdict.FAIL,
                       reason="值不符", tx_frame="6804", rx_frame="6806"),
    ]
    return s.to_dict()


def test_export_three_formats_same_item_count():
    s = _sample_session()
    xlsx = export_xlsx(s)
    assert xlsx[:2] == b"PK"  # zip 容器
    doc = json.loads(export_json(s))
    assert len(doc["items"]) == 2
    html = export_html(s)
    assert "110kV" in html and "开关A" in html and "不通过" in html
    assert html.count("<tr>") >= 3  # 表头 + 2 行


def test_export_dispatch_and_invalid_format():
    s = _sample_session()
    body, ctype, suffix = export(s, "json")
    assert suffix == "json" and ctype == "application/json"
    with pytest.raises(ValueError, match="unsupported"):
        export(s, "pdf")


# ── Web API 端点（契约 + 角色 + 错误路径） ─────────────────────────

@pytest.fixture
async def client(tmp_path):
    cfg = __import__("core.config", fromlist=["AppConfig"]).AppConfig()
    cfg.history.dir = str(tmp_path)
    bridge = EngineBridge(role="master", app_config=cfg)
    app = create_app(bridge)
    async with TestClient(TestServer(app)) as c:
        yield c, bridge
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_commission_api_full_flow(client):
    c, bridge = client
    # 点表：3 个 YX 点
    pt = bridge.point_table
    for ioa in (1, 2, 3):
        pt.add_yx(__import__("core.data.point_table", fromlist=["YxPointDef"]).YxPointDef(ioa=ioa))

    r = await c.post("/api/commission/sessions", json={
        "name": "测试会话", "operator": "甲", "ioas": [1, 2],
        "expected": {"1": True, "2": False},
    })
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    sid = body["session"]["id"]
    assert body["session"]["summary"]["total"] == 2

    r = await c.get("/api/commission/sessions")
    assert (await r.json())["sessions"][0]["id"] == sid

    r = await c.get(f"/api/commission/sessions/{sid}")
    assert len((await r.json())["session"]["items"]) == 2

    # 人工改判
    r = await c.post(f"/api/commission/sessions/{sid}/verdict", json={
        "ioa": 1, "verdict": "pass", "note": "现场确认", "operator": "乙"})
    assert (await r.json())["item"]["verdict"] == "pass"

    # 三种格式导出，条数一致
    for fmt, marker in (("xlsx", b"PK"), ("json", b'"items"'), ("html", b"<html")):
        r = await c.get(f"/api/commission/sessions/{sid}/export?format={fmt}")
        assert r.status == 200
        assert marker in await r.read()

    assert (await c.delete(f"/api/commission/sessions/{sid}")).status == 200
    assert (await c.get(f"/api/commission/sessions/{sid}")).status == 404


@pytest.mark.asyncio
async def test_commission_api_validation(client):
    c, _ = client
    assert (await c.post("/api/commission/sessions", json={"ioas": ["x"]})).status == 400
    assert (await c.post("/api/commission/sessions", json={"expected": []})).status == 400
    r = await c.post("/api/commission/sessions/not-exist/run", json={})
    assert r.status == 400  # 会话不存在
    r = await c.get("/api/commission/sessions/not-exist/export")
    assert r.status == 404


@pytest.mark.asyncio
async def test_commission_api_not_registered_on_bridge_role(tmp_path):
    cfg = __import__("core.config", fromlist=["AppConfig"]).AppConfig()
    cfg.history.dir = str(tmp_path)
    bridge = EngineBridge(role="bridge", app_config=cfg)
    app = create_app(bridge)
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/api/commission/sessions")).status == 404
    await bridge.shutdown()


# ── 编排状态机（fake bridge / fake engine，精确覆盖判定与中断） ────

class _FakeStore:
    """最小 data_store 桩：实现 YX/YC 读写与变位订阅。"""

    def __init__(self):
        self.values: dict[tuple[str, int], tuple] = {}
        self._subs: list = []

    def subscribe(self, cb):
        self._subs.append(cb)

    def unsubscribe(self, cb):
        if cb in self._subs:
            self._subs.remove(cb)

    def set(self, kind, ioa, value, quality="GOOD"):
        self.values[(kind, ioa)] = (value, quality)
        from core.data.data_store import DataChangeEvent
        from core.protocol.types import QualityDescriptor
        ev = DataChangeEvent(point_type=kind, ioa=ioa, old_value=None,
                             new_value=value, timestamp=0.0,
                             quality=QualityDescriptor())
        for cb in list(self._subs):
            cb(ev)

    def _get(self, kind, ioa):
        hit = self.values.get((kind, ioa))
        if hit is None:
            return None
        value, quality = hit

        class _D:
            pass
        d = _D()
        d.value = value
        d.last_state = value
        d.last_command = value
        d.quality = quality
        return d

    def get_yx(self, ioa):
        return self._get("yx", ioa)

    def get_yc(self, ioa):
        return self._get("yc", ioa)

    def get_step(self, ioa):
        return self._get("step", ioa)

    def get_yk(self, ioa):
        return self._get("yk", ioa)


class _FakeEngine:
    def __init__(self):
        self.data_store = _FakeStore()
        self.scheduler = None
        self._periodic_gi_task = None


class _FakeBus:
    def __init__(self):
        self.frames: list[dict] = []
        self.events: list[dict] = []

    def recent(self, kind, limit=100):
        return list(self.frames) if kind == "frame" else list(self.events)

    def publish(self, kind, data):
        if kind == "event":
            self.events.append(data)
        elif kind == "frame":
            self.frames.append(data)


class _FakeBridge:
    def __init__(self, points=None):
        from webui.commissioning import CommissioningService
        self.engine = _FakeEngine()
        self.bus = _FakeBus()
        self._points = points or []
        self.commands: list[tuple] = []
        self.store = CommissionStore(":memory:")
        self.store.open()
        self.service = CommissioningService(self, self.store, step_timeout=0.6)

    def snapshot_points(self):
        return list(self._points)

    def publish(self, kind, data):
        self.bus.publish(kind, data)

    def recent(self, kind, limit=100):
        return self.bus.recent(kind, limit)

    async def send_yk(self, ioa, state, *a, **kw):
        self.commands.append(("yk", ioa, state))
        self.bus.publish("frame", {"direction": "tx", "hex": "6804", "len": 4})
        # 模拟子站回送变位 + ACTCON
        self.engine.data_store.values[("yk", ioa)] = ("ack", "")
        if kw.get("deactivate"):
            return {"ok": True}
        self.engine.data_store.set("yx", ioa, bool(state))
        self.bus.publish("frame", {"direction": "rx", "hex": "6806", "len": 4})
        return {"ok": True}

    async def send_setpoint(self, ioa, value, *a, **kw):
        self.commands.append(("setpoint", ioa, value))
        self.engine.data_store.set("yc", ioa, float(value))
        return {"ok": True}

    async def read_command(self, ioa):
        self.commands.append(("read", ioa))
        return {"ok": True}

    async def send_step_command(self, ioa, state, *a, **kw):
        self.commands.append(("step", ioa, state))
        self.engine.data_store.set("step", ioa, 1 if state == 2 else -1)
        return {"ok": True}


def _service_points():
    return [
        {"ioa": 1, "type": "YX", "name": "开关A", "group": 1},
        {"ioa": 2, "type": "YC", "name": "电压", "group": 1,
         "min_value": 0, "max_value": 200},
        {"ioa": 3, "type": "YK", "name": "遥控", "group": 1},
    ]


@pytest.mark.asyncio
async def test_orchestrator_auto_judges_all_items_and_keeps_evidence():
    from webui.commissioning import CommissioningService
    b = _FakeBridge(_service_points())
    svc: CommissioningService = b.service
    s = svc.create_session("闭环", operator="甲",
                           expected={1: True, 2: 100.0, 3: True})
    svc.run(s["id"])
    # 等后台任务完成
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = svc.get_session(s["id"])
    assert out["status"] == "done"
    assert out["summary"]["total"] == 3
    assert out["summary"]["pass"] == 3, out["items"]
    assert all(i["tx_frame"] and i["rx_frame"] for i in out["items"])
    assert [c[0] for c in b.commands] == ["yk", "setpoint", "read", "yk"]
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_command_ioa_differs_from_read_ioa():
    """现场遥控与其回读遥信异址：命令必须打到 command_ioa，回读按 ioa。"""
    b = _FakeBridge(_service_points()[:1])
    svc = b.service
    s = svc.create_session("异址", expected={1: True},
                           command_ioas={1: 9001})
    assert s["items"][0]["command_ioa"] == 9001
    svc.run(s["id"])
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = svc.get_session(s["id"])
    # 命令打到 9001；回读仍看 ioa=1（fake 在 9001 上模拟变位，故等待超时 → fail）
    assert b.commands[0] == ("yk", 9001, True)
    assert out["items"][0]["verdict"] == "fail"  # 异址未按映射回读，正确判不通过
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_yk_nack_is_always_fail():
    class _NackBridge(_FakeBridge):
        async def send_yk(self, ioa, state, *a, **kw):
            self.commands.append(("yk", ioa, state))
            self.engine.data_store.values[("yk", ioa)] = ("nack", "")
            return {"ok": True}

    b = _NackBridge([{"ioa": 3, "type": "YK", "name": "遥控", "group": 1}])
    svc = b.service
    s = svc.create_session("NACK", expected={3: True})
    svc.run(s["id"])
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = svc.get_session(s["id"])
    assert out["items"][0]["verdict"] == "fail"
    assert "SBO" in out["items"][0]["reason"] or "否定确认" in out["items"][0]["reason"]
    await svc.shutdown()


class _SlowBridge(_FakeBridge):
    """每步下发前 sleep，让 stop() 有机会在编排中途生效。"""

    async def send_yk(self, ioa, state, *a, **kw):
        await asyncio.sleep(0.05)
        return await super().send_yk(ioa, state, *a, **kw)

    async def send_setpoint(self, ioa, value, *a, **kw):
        await asyncio.sleep(0.05)
        return await super().send_setpoint(ioa, value, *a, **kw)


@pytest.mark.asyncio
async def test_orchestrator_stop_marks_remaining_pending():
    b = _SlowBridge(_service_points())
    svc = b.service
    s = svc.create_session("中止", expected={1: True, 2: 1.0, 3: True})
    svc.run(s["id"])
    await asyncio.sleep(0.01)  # 让任务进入第一点
    svc.stop()
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = svc.get_session(s["id"])
    assert out["status"] == "stopped"
    assert out["summary"]["pending"] >= 1
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_no_expected_becomes_manual_without_sending():
    b = _FakeBridge(_service_points())
    svc = b.service
    s = svc.create_session("无期望")
    svc.run(s["id"])
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = svc.get_session(s["id"])
    assert all(i["verdict"] == "manual" for i in out["items"])
    assert b.commands == []
    await svc.shutdown()


# ── 编排器边界分支（覆盖率门禁） ──────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_run_guards():
    b = _SlowBridge(_service_points()[:1])
    svc = b.service
    s = svc.create_session("守卫", expected={1: True})
    with pytest.raises(KeyError):
        svc.run("missing")
    # 完成后不可重跑
    svc.run(s["id"])
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    with pytest.raises(RuntimeError, match="已完成"):
        svc.run(s["id"])
    # 未运行时 stop 幂等
    assert svc.stop()["ok"] is True
    # 运行中重复 run 被拒
    s2 = svc.create_session("重复", expected={1: True})
    svc.run(s2["id"])
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="已有正在运行"):
        svc.run(s2["id"])
    svc.stop()
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_stop_sends_deact_for_pending_yk():
    """中止时对所有仍 PENDING 的 YK 点发 DEACT，清掉悬空选择。"""
    b = _SlowBridge([{"ioa": 3, "type": "YK", "name": "遥控", "group": 1},
                     {"ioa": 4, "type": "YK", "name": "遥控2", "group": 1}])
    svc = b.service
    s = svc.create_session("DEACT", expected={3: True, 4: True})
    svc.run(s["id"])
    await asyncio.sleep(0.01)
    svc.stop()
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    deacts = [c for c in b.commands if c[0] == "yk" and len(c) > 2 and c[2] == 0]
    assert len(deacts) >= 1
    assert svc.get_session(s["id"])["status"] == "stopped"
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_pause_resume_periodic_gi():
    class _Sched:
        def __init__(self):
            self.tasks = [type("T", (), {"name": "periodic_gi", "enabled": True})()]
            self.enabled_calls = []

        def get_all_tasks(self):
            return self.tasks

        def disable_task(self, name):
            self.tasks[0].enabled = False
            return True

        def enable_task(self, name):
            self.enabled_calls.append(name)
            return True

    b = _FakeBridge(_service_points()[:1])
    sched = _Sched()
    b.engine.scheduler = sched
    svc = b.service
    s = svc.create_session("GI", expected={1: True})
    svc.run(s["id"])
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    assert sched.tasks[0].enabled is False
    assert "periodic_gi" in sched.enabled_calls
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_emit_publish_failure_is_swallowed():
    b = _FakeBridge(_service_points()[:1])
    svc = b.service

    def boom(*a, **kw):
        raise RuntimeError("bus down")

    b.publish = boom
    s = svc.create_session("广播失败", expected={1: True})
    svc.run(s["id"])
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    assert svc.get_session(s["id"])["status"] == "done"
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_deact_cleanup_failure_is_swallowed():
    class _FailDeact(_SlowBridge):
        async def send_yk(self, ioa, state, *a, **kw):
            if kw.get("deactivate"):
                raise RuntimeError("cleanup failed")
            return await super().send_yk(ioa, state, *a, **kw)

    b = _FailDeact([{"ioa": 3, "type": "YK", "name": "遥控", "group": 1}])
    svc = b.service
    s = svc.create_session("DEACT 失败", expected={3: True})
    svc.run(s["id"])
    await asyncio.sleep(0.01)
    svc.stop()
    for _ in range(100):
        if not svc.status()["running"]:
            break
        await asyncio.sleep(0.02)
    assert svc.get_session(s["id"])["status"] == "stopped"
    await svc.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_no_engine_raises():
    b = _FakeBridge(_service_points()[:1])
    b.engine = None
    svc = b.service
    s = svc.create_session("无引擎")
    with pytest.raises(RuntimeError, match="未连接"):
        svc.run(s["id"])
    await svc.shutdown()


def test_export_html_escapes_and_empty_session():
    """HTML 报告转义 XSS 且空会话不崩。"""
    s = _sample_session()
    s["name"] = "<script>alert(1)</script>"
    s["items"][0]["name"] = "<img src=x>"
    out = export_html(s)
    assert "<script>" not in out and "&lt;script&gt;" in out
    empty = CommissionSession(id="c-empty").to_dict()
    assert "无记录" in export_html(empty)


def test_store_corrupt_payload_skipped(tmp_path):
    """单条损坏记录不影响会话列表。"""
    s = CommissionStore(tmp_path / "c.db")
    s.open()
    s.conn.execute("INSERT INTO commission_sessions VALUES (?,?,?,?,?)",
                   ("bad", "x", 1.0, "done", "not-json"))
    s.conn.commit()
    assert s.list_sessions() == []
    s.close()


# ── 剩余分支（覆盖率门禁 91%） ────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrator_timeout_is_fail():
    class _NoReplyBridge(_FakeBridge):
        async def send_yk(self, ioa, state, *a, **kw):
            self.commands.append(("yk", ioa, state))
            return {"ok": True}  # 不产生任何变位/确认

    b = _NoReplyBridge([{"ioa": 1, "type": "YX", "name": "开关", "group": 1}])
    b.service._step_timeout = 0.15
    s = b.service.create_session("超时", expected={1: True})
    b.service.run(s["id"])
    for _ in range(100):
        if not b.service.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = b.service.get_session(s["id"])
    assert out["items"][0]["verdict"] == "fail"
    assert "超时" in out["items"][0]["reason"]
    await b.service.shutdown()


@pytest.mark.asyncio
async def test_orchestrator_send_failure_is_fail():
    class _FailBridge(_FakeBridge):
        async def send_yk(self, ioa, state, *a, **kw):
            raise RuntimeError("socket closed")

    b = _FailBridge([{"ioa": 1, "type": "YX", "name": "开关", "group": 1}])
    s = b.service.create_session("下发失败", expected={1: True})
    b.service.run(s["id"])
    for _ in range(100):
        if not b.service.status()["running"]:
            break
        await asyncio.sleep(0.02)
    out = b.service.get_session(s["id"])
    assert out["items"][0]["verdict"] == "fail"
    assert "命令下发失败" in out["items"][0]["reason"]
    await b.service.shutdown()


def test_judge_non_numeric_values_and_quality_object():
    """值类型异常 / 品质对象字符串化的边界。"""
    it = CommissionItem(ioa=1, kind=ItemKind.YC, expected="abc")
    judge(it, observed=1.0)
    assert it.verdict == Verdict.FAIL
    it2 = CommissionItem(ioa=2, kind=ItemKind.YX, expected=True)
    judge(it2, observed=None)
    assert it2.verdict == Verdict.FAIL
    it3 = CommissionItem(ioa=3, kind=ItemKind.STEP, expected="x")
    judge(it3, observed="x")
    assert it3.verdict == Verdict.PASS


def test_read_value_branches():
    b = _FakeBridge()
    store = b.engine.data_store
    svc = b.service
    for kind, ioa, val, mk in (
        ("yx", 1, True, lambda: CommissionItem(1, kind=ItemKind.YX)),
        ("yc", 2, 3.5, lambda: CommissionItem(2, kind=ItemKind.YC)),
        ("step", 3, 2, lambda: CommissionItem(3, kind=ItemKind.STEP)),
    ):
        store.set(kind, ioa, val)
        hit = svc._read_value(store, mk())
        assert hit is not None and hit[0] == val
    assert svc._read_value(store, CommissionItem(99, kind=ItemKind.YX)) is None
    assert svc._read_value(store, CommissionItem(1, kind=ItemKind.YK)) is None


def test_make_callback_exception_is_swallowed():
    b = _FakeBridge()
    svc = b.service
    loop = asyncio.new_event_loop()
    fut = loop.create_future()
    item = CommissionItem(1, kind=ItemKind.YX, expected=True)
    cb = svc._make_callback(item, fut, loop)
    # event 缺 new_value / quality 字段 → 内部异常被吞，不抛给引擎
    cb(type("E", (), {"ioa": 1})())
    assert not fut.done()
    loop.close()


def test_pause_gi_with_live_task_and_broken_scheduler():
    b = _FakeBridge()
    svc = b.service

    class _Task:
        def done(self):
            return False

        def cancel(self):
            pass

    b.engine._periodic_gi_task = _Task()

    class _BrokenSched:
        def get_all_tasks(self):
            raise RuntimeError("boom")

    b.engine.scheduler = _BrokenSched()
    assert svc._pause_periodic_gi(b.engine) is True
    svc._paused_gi = True
    svc._resume_periodic_gi(b.engine)  # 异常被吞
    svc._paused_gi = False
    svc._resume_periodic_gi(b.engine)  # 提前返回分支


@pytest.mark.asyncio
async def test_shutdown_cancels_running_task():
    b = _SlowBridge(_service_points())
    svc = b.service
    s = svc.create_session("关停", expected={1: True, 2: 1.0, 3: True})
    svc.run(s["id"])
    await asyncio.sleep(0.01)
    assert svc.get_session(s["id"]) is not None
    await svc.shutdown()
    assert svc.status()["running"] is False


def test_export_json_and_html_with_special_chars():
    s = _sample_session()
    s["items"][0]["note"] = '含 "引号" & <标签>'
    assert '"items"' in export_json(s)
    assert "&lt;标签&gt;" in export_html(s)
    _, ctype, suffix = export(s, "html")
    assert ctype == "text/html" and suffix == "html"
