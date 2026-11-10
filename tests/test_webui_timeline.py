"""T97 桥注入时间线 + 自动判定：合成证据锁死判定口径（防误报）+ 端点接线.

「合成帧序列锁死防误报」：用 ComplianceMonitor 喂合成帧序列产生真实违规证据，
验证 judge 只认窗口内证据；丢包/断链按增量归窗；none 口径零证据才通过。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.engine.compliance_monitor import ComplianceMonitor
from core.protocol.apci import APCICodec
from webui.bridge import EngineBridge
from webui.report import build_session_report_html
from webui.server import create_app
from webui.timeline import TimelineService

# ── judge 判定矩阵（纯函数） ────────────────────────────────────────────


def test_judge_matrix():
    j = TimelineService.judge
    assert j("none", dropped_delta=0, disconnect_delta=0, kinds=[])[0] is True
    ok, detail = j("none", dropped_delta=3, disconnect_delta=0, kinds=[])
    assert ok is False and "丢帧" in detail
    ok, detail = j("none", dropped_delta=0, disconnect_delta=0, kinds=["t1"])
    assert ok is False  # 窗口内有违规即不算干净
    assert j("loss", dropped_delta=2, disconnect_delta=0, kinds=[])[0] is True
    assert j("loss", dropped_delta=0, disconnect_delta=0, kinds=[])[0] is False
    assert j("k-exceed", dropped_delta=9, disconnect_delta=0, kinds=["k-exceed"])[0] is True
    assert j("k-exceed", dropped_delta=9, disconnect_delta=0, kinds=["t1"])[0] is False
    assert j("t1", dropped_delta=0, disconnect_delta=0, kinds=["t1", "k-exceed"])[0] is True
    assert j("disconnect", dropped_delta=0, disconnect_delta=1, kinds=[])[0] is True
    assert j("disconnect", dropped_delta=0, disconnect_delta=0, kinds=[])[0] is False
    assert j("bogus", dropped_delta=0, disconnect_delta=0, kinds=[])[0] is False


# ── 合成帧序列：真实 ComplianceMonitor 证据 + 窗口归集 ───────────────────


def _u(func: int) -> bytes:
    return APCICodec.encode_u(func)


def _i(ns: int, nr: int) -> bytes:
    return APCICodec.encode_i(ns, nr, b"")


class _MonitorBridge(SimpleNamespace):
    """最小桥桩：只暴露 timeline 依赖的 tcp_bridge/compliance/bus."""


def _make_bridge(monitor: ComplianceMonitor) -> _MonitorBridge:
    published: list[tuple[str, dict]] = []

    class _Tcp:
        def __init__(self):
            self.dropped = 0
            self.disconnects = 0
            self.stats = SimpleNamespace(clients_total=2)

        def set_condition(self, cond):
            self.last_condition = cond  # 记录供断言

        def injection_stats(self):
            return {"dropped": self.dropped, "disconnects": self.disconnects}

    tcp = _Tcp()
    bus = SimpleNamespace(publish=lambda kind, data: published.append((kind, data)))
    return _MonitorBridge(tcp_bridge=tcp, compliance=monitor, bus=bus), published, tcp


@pytest.mark.asyncio
async def test_run_two_steps_synthetic_evidence():
    """步骤1 干净（expect=none 过）；步骤2 合成 k-exceed 违规落入窗口（expect 过）."""
    monitor = ComplianceMonitor()
    bridge, published, tcp = _make_bridge(monitor)
    svc = TimelineService(bridge)
    svc.tick_s = 0.01
    svc.configure([
        {"label": "基线", "duration_s": 0.5, "condition": {}, "expect": "none"},
        {"label": "丢包", "duration_s": 0.5, "condition": {"loss_rate": 1.0},
         "expect": "k-exceed"},
    ])
    # 步骤1共 0.5/0.01=50 个 tick；第 55 次睡醒时已在步骤2窗口内：
    # 合成「主站狂发 I 帧无人确认」→ 监视器记 k-exceed（ts 落在步骤2窗口）
    calls = 0

    async def fake_sleep(_t):
        nonlocal calls
        calls += 1
        if calls == 55:
            monitor.observe("tx", _u(0x07), 100.0)
            monitor.observe("rx", _u(0x0B), 100.1)
            for seq in range(15):  # k=12 → 第 13 帧超窗
                monitor.observe("tx", _i(seq, 0), 200.0 + seq * 0.01)
            tcp.dropped += 40
        await asyncio.sleep(0)

    svc._sleep = fake_sleep
    r = await svc.run()
    assert r["ok"] is True and svc.running is True
    for _ in range(500):
        if not svc.running:
            break
        await asyncio.sleep(0.02)
    result = svc.last_result
    assert result["ok"] is True and len(result["steps"]) == 2
    s0, s1 = result["steps"]
    assert s0["ok"] is True and s0["label"] == "基线"
    assert s1["ok"] is True and "k-exceed" in s1["detail"]
    # 结束后复位干净链路
    assert tcp.last_condition.has_any() is False
    # 事件发布：逐步 + 结束
    assert published and published[-1][0] == "timeline"


@pytest.mark.asyncio
async def test_window_attribution_rejects_out_of_window_evidence():
    """运行起点吃掉历史违规游标：步骤1(none) 不被历史证据误伤；
    步骤2 无**新**违规 → expect=k-exceed 判 False（窗口外证据不参与）."""
    monitor = ComplianceMonitor()
    bridge, _, _ = _make_bridge(monitor)
    svc = TimelineService(bridge)
    svc.tick_s = 0.01
    svc.configure([
        {"label": "基线", "duration_s": 0.5, "condition": {}, "expect": "none"},
        {"label": "后续窗", "duration_s": 0.5, "condition": {"loss_rate": 1.0},
         "expect": "k-exceed"},
    ])
    # 运行前历史违规（ts≈1.0，早于本次运行全部窗口）：序号跳变 + 确认超前，
    # 均为瞬时违规、不留持久未确认态（避免 t1/t2 真证据混入）
    monitor.observe("tx", _u(0x07), 0.0)
    monitor.observe("rx", _u(0x0B), 0.1)
    monitor.observe("tx", _i(0, 0), 1.0)
    monitor.observe("tx", _i(7, 0), 1.01)   # seq-jump
    monitor.observe("rx", APCICodec.encode_s(50), 1.02)  # ack-ahead
    await svc.run()
    for _ in range(500):
        if not svc.running:
            break
        await asyncio.sleep(0.02)
    result = svc.last_result
    assert result["steps"][0]["ok"] is True, "历史违规不得误伤 none 判定"
    assert result["steps"][1]["ok"] is False, "窗口外证据不参与 k-exceed 判定"
    assert result["ok"] is False


# ── 编排校验 ────────────────────────────────────────────────────────────


def test_configure_validation():
    svc = TimelineService(SimpleNamespace())
    assert svc.configure([])["ok"] is False
    assert svc.configure([{}])["ok"] is False  # duration 非法
    assert svc.configure([{"duration_s": 0.1}])["ok"] is False  # < 0.5
    assert svc.configure([{"duration_s": 9999}])["ok"] is False
    assert svc.configure([{"duration_s": 1, "expect": "nope"}])["ok"] is False
    assert svc.configure([{"duration_s": 1, "condition": {"loss_rate": "x"}}])["ok"] is False
    assert svc.configure([{"duration_s": 1} for _ in range(51)])["ok"] is False
    r = svc.configure([
        {"label": "x" * 100, "duration_s": 2, "condition": {"loss_rate": 1, "direction": "dn"},
         "expect": "K-EXCEED"},
        {"duration_s": 1.5},
    ])
    assert r["ok"] is True and len(svc.steps) == 2
    st = svc.steps[0]
    assert st["label"].startswith("x") and len(st["label"]) == 80
    assert st["expect"] == "k-exceed" and st["condition"]["direction"] == "both"
    assert svc.steps[1]["label"] == "步骤2" and svc.steps[1]["expect"] == "none"


@pytest.mark.asyncio
async def test_run_guards_and_stop():
    svc = TimelineService(SimpleNamespace(tcp_bridge=None))
    svc.configure([{"duration_s": 1}])
    assert (await svc.run())["ok"] is False  # 桥未启动
    assert svc.stop()["ok"] is False  # 未在运行
    bridge, _, _ = _make_bridge(ComplianceMonitor())
    svc2 = TimelineService(bridge)
    svc2.tick_s = 0.01
    svc2.configure([{"label": "长步", "duration_s": 5, "condition": {},
                     "expect": "none"}])
    r = await svc2.run()
    assert r["ok"] is True and svc2.running is True
    assert (await svc2.run())["ok"] is False  # 运行中重复启动
    assert svc2.stop()["ok"] is True
    for _ in range(600):
        if not svc2.running:
            break
        await asyncio.sleep(0.02)
    assert svc2.last_result["stopped"] is True
    assert svc2.last_result["steps"][0].get("skipped") is True


@pytest.mark.asyncio
async def test_condition_set_failure_recorded():
    class _BadTcp:
        def set_condition(self, cond):
            raise RuntimeError("boom")

        def injection_stats(self):
            return {"dropped": 0, "disconnects": 0}

    bridge = _MonitorBridge(tcp_bridge=_BadTcp(), compliance=None,
                            bus=SimpleNamespace(publish=lambda k, d: None))
    svc = TimelineService(bridge)
    svc.tick_s = 0.01
    svc.configure([{"label": "坏条件", "duration_s": 0.5, "expect": "none"}])
    await svc.run()
    for _ in range(300):
        if not svc.running:
            break
        await asyncio.sleep(0.02)
    assert svc.last_result["steps"][0]["ok"] is False and "异常" in svc.last_result["steps"][0]["detail"]


# ── 端点接线（bridge 角色业务拒绝 / bridge 角色可用） ────────────────────


@pytest.mark.asyncio
async def test_timeline_endpoints():
    bridge = EngineBridge("bridge")
    async with TestClient(TestServer(create_app(bridge))) as client:
        r = await client.get("/api/bridge/timeline")
        body = await r.json()
        assert body["ok"] is True and body["running"] is False and body["steps"] == []
        r = await client.post("/api/bridge/timeline", json={"steps": [
            {"label": "丢包", "duration_s": 1, "condition": {"loss_rate": 1.0},
             "expect": "k-exceed"}]})
        assert (await r.json())["ok"] is True
        r = await client.post("/api/bridge/timeline", json={"steps": "bad"})
        assert (await r.json())["ok"] is False
        r = await client.post("/api/bridge/timeline/run")
        assert (await r.json())["ok"] is False  # 桥未启动
        r = await client.post("/api/bridge/timeline/stop")
        assert (await r.json())["ok"] is False  # 未在运行
    # 非 bridge 角色：业务拒绝（200 + ok:false）
    bridge2 = EngineBridge("master")
    bridge2.ensure_demo_points()
    async with TestClient(TestServer(create_app(bridge2))) as client:
        r = await client.post("/api/bridge/timeline", json={"steps": []})
        body = await r.json()
        assert body["ok"] is False and "仅 bridge 角色" in body["error"]


# ── 报告段 ──────────────────────────────────────────────────────────────


def test_report_timeline_section():
    html = build_session_report_html(
        "bridge", {"role": "bridge"}, [], [],
        timeline={"ok": True, "started_at": 0, "duration_s": 6.0,
                  "steps": [
                      {"label": "基线", "condition": "(clean)", "expect": "none",
                       "ok": True, "detail": "窗口内零丢帧/零断链/零违规"},
                      {"label": "丢包", "condition": "丢帧100%", "expect": "k-exceed",
                       "ok": True, "detail": "窗口内违规 kinds=['k-exceed']"},
                  ]})
    assert "11. 注入时间线" in html and "2 步全部符合预期" in html
    html2 = build_session_report_html(
        "bridge", {"role": "bridge"}, [], [],
        timeline={"ok": False, "steps": [
            {"label": "a", "condition": "", "expect": "none", "ok": False, "detail": "x"},
        ]})
    assert "0/1 步符合预期" in html2
    # 无时间线 → 无该段
    html3 = build_session_report_html("master", {"role": "master"}, [], [])
    assert "注入时间线" not in html3



@pytest.mark.asyncio
async def test_configure_extra_validation_branches():
    """非对象步骤 / duration 非法类型 / 未编排 run / 桩异常分支."""
    svc = TimelineService(SimpleNamespace())
    assert svc.configure([["不是对象"]])["ok"] is False
    assert svc.configure([{"duration_s": "abc"}])["ok"] is False
    # run：桥在但未编排
    bridge, _, _ = _make_bridge(ComplianceMonitor())
    svc2 = TimelineService(bridge)
    assert (await svc2.run())["ok"] is False and "未编排" in (await svc2.run())["error"]
    # 运行起点游标：compliance.violation_list 抛异常 → 0.0
    bad = SimpleNamespace(violation_list=lambda n: (_ for _ in ()).throw(RuntimeError("x")))
    assert TimelineService(SimpleNamespace(compliance=bad))._latest_violation_ts() == 0.0
    # _window_violations：无 compliance → ([], cursor)
    fresh, cursor = TimelineService(SimpleNamespace())._window_violations(5.0)
    assert fresh == [] and cursor == 5.0
    # 运行中 stop 的 break 路径：假 sleep 第 3 次触发停止
    bridge2, published, tcp = _make_bridge(ComplianceMonitor())
    svc3 = TimelineService(bridge2)
    svc3.tick_s = 0.01
    svc3.configure([{"label": "长", "duration_s": 2, "condition": {}, "expect": "none"}])
    calls = 0

    async def fake_sleep(_t):
        nonlocal calls
        calls += 1
        if calls == 3:
            svc3._stop_requested = True
        await asyncio.sleep(0)

    svc3._sleep = fake_sleep
    await svc3.run()
    for _ in range(300):
        if not svc3.running:
            break
        await asyncio.sleep(0.02)
    assert svc3.last_result["stopped"] is True
    # bus.publish 抛异常被吞 + 无 bus → 直接返回
    boom = SimpleNamespace(publish=lambda k, d: (_ for _ in ()).throw(RuntimeError("boom")))
    TimelineService(SimpleNamespace(tcp_bridge=None, compliance=None, bus=boom))._publish(None, {})
    TimelineService(SimpleNamespace(tcp_bridge=None, compliance=None))._publish(None, {})
