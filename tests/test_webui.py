"""Web UI / EngineBridge 自动化测试."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from core.protocol.types import COT
from webui.bridge import EngineBridge
from webui.server import create_app

_MASTER_HTML = Path(__file__).parent.parent / "webui" / "static" / "master.html"


@pytest_asyncio.fixture
async def slave_client():
    bridge = EngineBridge("slave")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest_asyncio.fixture
async def master_client():
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield client, bridge
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
async def test_static_and_status(slave_client):
    client, bridge = slave_client
    r = await client.get("/")
    assert r.status == 200
    html = await r.text()
    assert "IEC104" in html
    r = await client.get("/static/css/app.css")
    assert r.status == 200
    r = await client.get("/static/js/app.js")
    assert r.status == 200
    r = await client.get("/api/status")
    st = await r.json()
    assert st["role"] == "slave"
    assert st["running"] is False
    assert st["points"] > 0
    assert "dropped" in st


@pytest.mark.asyncio
async def test_points_schema(slave_client):
    client, _ = slave_client
    r = await client.get("/api/points")
    pts = (await r.json())["points"]
    assert pts
    assert {"ioa", "type", "name", "group", "enabled", "value"} <= set(pts[0].keys())
    types = {p["type"] for p in pts}
    assert types >= {"YX", "YC"}


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_slave_lifecycle_yx_yc_response(slave_client):
    client, bridge = slave_client
    port = _free_port()
    r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"] is True
    assert bridge.engine is not None

    r = await client.post("/api/slave/yx", json={"ioa": 1, "value": True})
    assert (await r.json())["ok"] is True
    assert bridge.engine.data_store.get_yx(1).value is True

    pts = (await (await client.get("/api/points")).json())["points"]
    yc_ioa = next(p["ioa"] for p in pts if p["type"] == "YC")
    r = await client.post("/api/slave/yc", json={"ioa": yc_ioa, "value": 3.25})
    body = await r.json()
    assert body["ok"] is True
    d = bridge.engine.data_store.get_yc(yc_ioa)
    assert d is not None and abs(float(d.value) - 3.25) < 1e-6

    r = await client.post("/api/slave/response", json={
        "delays": {"gi": 0.5, "command": 0},
        "errors": {"drop_frames": True, "drop_rate": 0.2, "no_response": False},
    })
    assert (await r.json())["ok"] is True
    assert bridge.engine.response_behavior.gi_delay == 0.5
    assert bridge.engine.response_behavior.drop_frames is True

    r = await client.post("/api/slave/stop")
    assert (await r.json())["ok"] is True
    assert bridge.engine is None


@pytest.mark.asyncio
async def test_master_api_error_paths(master_client):
    client, bridge = master_client
    # 未连接时命令应失败但 ok=false
    r = await client.post("/api/master/gi")
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/clock")
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/ci")
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/yk", json={"ioa": 1, "state": 1})
    assert (await r.json())["ok"] is False


@pytest.mark.asyncio
async def test_master_start_stop_against_slave(slave_client, master_client):
    sc, sbridge = slave_client
    mc, mbridge = master_client
    port = _free_port()
    r = await sc.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"]
    assert sbridge.engine is not None and sbridge.engine.is_running
    try:
        r = await mc.post("/api/master/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
        assert (await r.json())["ok"] is True
        # 等待进入 Running（TCP 握手 + STARTDT）
        for _ in range(80):
            await asyncio.sleep(0.05)
            if mbridge.engine and mbridge.engine.is_running:
                break
        assert mbridge.engine and mbridge.engine.is_running
        r = await mc.post("/api/master/gi")
        assert (await r.json())["ok"] is True
        await asyncio.sleep(0.3)
        r = await mc.post("/api/master/clock")
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/ci")
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/stop")
        assert (await r.json())["ok"] is True
    finally:
        await sc.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_points_batch(slave_client):
    client, bridge = slave_client
    pts = (await (await client.get("/api/points")).json())["points"]
    yx = [p["ioa"] for p in pts if p["type"] == "YX"][:3]
    r = await client.post("/api/points/batch", json={
        "type": "YX", "ioas": yx, "action": "group", "group": 7,
    })
    body = await r.json()
    assert body["ok"] is True
    assert body["changed"] == len(yx)
    for p in bridge.point_table.get_all_yx():
        if p.ioa in set(yx):
            assert p.group == 7

    r = await client.post("/api/points/batch", json={
        "type": "YX", "ioas": yx, "action": "disable",
    })
    assert (await r.json())["ok"] is True
    for p in bridge.point_table.get_all_yx():
        if p.ioa in set(yx):
            assert p.enabled is False

    r = await client.post("/api/points/batch", json={
        "type": "YX", "ioas": yx, "action": "enable",
    })
    body = await r.json()
    assert body["ok"] is True
    assert body["changed"] == len(yx)
    for p in bridge.point_table.get_all_yx():
        if p.ioa in set(yx):
            assert p.enabled is True

    # 非法 action / 缺 group 应失败
    r = await client.post("/api/points/batch", json={"type": "YX", "ioas": yx, "action": "nope"})
    assert (await r.json())["ok"] is False
    r = await client.post("/api/points/batch", json={"type": "YX", "ioas": yx, "action": "group"})
    assert (await r.json())["ok"] is False


@pytest.mark.asyncio
async def test_pending_response_applied_on_start(slave_client):
    client, bridge = slave_client
    r = await client.post("/api/slave/response", json={"delays": {"gi": 1.25, "command": 0}})
    assert (await r.json())["ok"] is True
    port = _free_port()
    r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"] is True
    assert bridge.engine.response_behavior.gi_delay == 1.25
    await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_sim_enable_on_slave(slave_client):
    client, bridge = slave_client
    port = _free_port()
    await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    r = await client.post("/api/slave/sim", json={"enabled": True, "yx_interval": 1.0})
    assert (await r.json())["ok"] is True
    assert bridge.status().get("simulation") is True
    r = await client.post("/api/slave/sim", json={"enabled": False})
    assert (await r.json())["ok"] is True
    await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_publish_queue_backpressure_dropped(slave_client):
    _, bridge = slave_client
    q = bridge.subscribe()
    try:
        # 塞满队列后 publish 应计 dropped 且不抛异常
        for i in range(q.maxsize + 5):
            bridge._publish("event", {"type": "ui", "data": {"i": i}})
        assert bridge.status()["dropped"] > 0
    finally:
        bridge.unsubscribe(q)


@pytest.mark.asyncio
async def test_csv_includes_live_values_and_set_response_guard(slave_client, master_client):
    sc, sbridge = slave_client
    mc, mbridge = master_client
    port = _free_port()
    await sc.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    try:
        pts = (await (await sc.get("/api/points")).json())["points"]
        yc_ioa = next(p["ioa"] for p in pts if p["type"] == "YC")
        await sc.post("/api/slave/yc", json={"ioa": yc_ioa, "value": 7.5})
        csv = await (await sc.get("/api/export/points.csv")).text()
        assert "7.5" in csv or "7.50" in csv
    finally:
        await sc.post("/api/slave/stop")

    r = await mc.post("/api/slave/response", json={"delays": {"gi": 1}})
    body = await r.json()
    assert body["ok"] is False and body["error"] == "not slave"


@pytest.mark.asyncio
async def test_batch_does_not_reset_live_values(slave_client):
    client, bridge = slave_client
    port = _free_port()
    await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    try:
        pts = (await (await client.get("/api/points")).json())["points"]
        yc_ioa = next(p["ioa"] for p in pts if p["type"] == "YC")
        await client.post("/api/slave/yc", json={"ioa": yc_ioa, "value": 9.25})
        yx = [p["ioa"] for p in pts if p["type"] == "YX"][:1]
        await client.post("/api/points/batch", json={"type": "YX", "ioas": yx, "action": "group", "group": 3})
        d = bridge.engine.data_store.get_yc(yc_ioa)
        assert d is not None and abs(float(d.value) - 9.25) < 1e-6
    finally:
        await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_master_extra_commands_and_exports(master_client):
    client, bridge = master_client
    # 未连接时命令失败
    for path in ("/api/master/reset", "/api/master/test"):
        r = await client.post(path, json={})
        assert (await r.json())["ok"] is False
    r = await client.post("/api/master/read", json={"ioa": 1})
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/param", json={"kind": "float", "ioa": 1, "value": 1.0})
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/file", json={"action": "directory"})
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/file", json={"action": "nope"})
    assert (await r.json())["ok"] is False
    r = await client.post("/api/master/param", json={"kind": "nope", "ioa": 1, "value": 0})
    assert (await r.json())["ok"] is False

    # 导出不依赖连接
    r = await client.get("/api/points/yaml")
    assert r.status == 200
    assert "ioa" in (await r.text()).lower() or "YX" in (await r.text()) or "yx" in (await r.text()).lower()
    r = await client.get("/api/export/points.csv")
    csv = await r.text()
    assert csv.splitlines()[0].startswith("type,ioa")
    r = await client.get("/api/export/session.json")
    ses = await r.json()
    assert "role" in ses and ses["role"] == "master"

    # YAML 导入
    r = await client.get("/api/points/yaml")
    yaml_text = await r.text()
    r = await client.post("/api/points/yaml", data=yaml_text)
    body = await r.json()
    assert body["ok"] is True and body["points"] > 0


@pytest.mark.asyncio
async def test_master_gi_qoi_against_slave(slave_client, master_client):
    sc, sbridge = slave_client
    mc, mbridge = master_client
    port = _free_port()
    await sc.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    try:
        await mc.post("/api/master/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
        for _ in range(80):
            await asyncio.sleep(0.05)
            if mbridge.engine and mbridge.engine.is_running:
                break
        assert mbridge.engine and mbridge.engine.is_running
        r = await mc.post("/api/master/gi", json={"qoi": 20})
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/gi", json={"qoi": 1})
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/reset", json={})
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/test", json={})
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/read", json={"ioa": 1})
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/param", json={"kind": "float", "ioa": 1, "value": 1.5})
        assert (await r.json())["ok"] is True
        r = await mc.post("/api/master/file", json={"action": "directory", "ioa": 0})
        assert (await r.json())["ok"] is True
        await mc.post("/api/master/stop")
    finally:
        await sc.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_ws_snapshot(slave_client):
    client, bridge = slave_client
    async with client.ws_connect("/ws") as ws:
        msg = await ws.receive_json()
        assert msg["kind"] == "snapshot"
        assert "points" in msg["data"] and "status" in msg["data"]
        assert msg["data"]["status"]["role"] == "slave"


@pytest.mark.asyncio
async def test_sim_toggle_requires_listen(master_client):
    client, bridge = master_client
    # 主站角色不可设模拟
    r = await client.post("/api/slave/sim", json={"enabled": True})
    body = await r.json()
    assert body["ok"] is False


# ── Nit D: 前端 QOI 非法值校验 ───────────────────────────────────

def test_master_html_qoi_guard_present():
    """master.html 应对 QOI 做 1-16/20 校验，且校验先于发请求（非法值不发）."""
    html = _MASTER_HTML.read_text(encoding="utf-8")
    assert "function isValidQoi(" in html, "缺少 isValidQoi 校验函数"

    handler = html.split('$("#btn-gi-qoi").onclick', 1)[1].split("};", 1)[0]
    assert "isValidQoi(" in handler, "处理器未调用 isValidQoi"
    guard_pos = handler.index("isValidQoi(")
    api_pos = handler.index('api("/api/master/gi"')
    assert guard_pos < api_pos, "校验必须早于发请求"
    assert "return" in handler[:api_pos], "非法值应提前 return，不发请求"


_QOI_BEHAVIOUR_JS = r"""
const fs = require('fs');
const html = fs.readFileSync(process.env.MASTER_HTML, 'utf8');

const fn = html.match(/function isValidQoi\(v\)\s*\{[\s\S]*?\n\}/);
const handlerSrc = html.match(/\$\("#btn-gi-qoi"\)\.onclick\s*=\s*async\s*\(\)\s*=>\s*\{[\s\S]*?\n\};/);
if (!fn || !handlerSrc) { console.log('FAIL:extract'); process.exit(2); }
eval(fn[0]);

const el = {};
global.$ = (s) => (el[s] ??= {});
let calls = [];
let toasts = [];
global.api = async (u, p) => { calls.push([u, p]); return { ok: true }; };
global.toast = (m) => toasts.push(m);
eval(handlerSrc[0]);

const truth = [[1,true],[16,true],[20,true],[17,false],[18,false],[19,false],
               [0,false],[21,false],[1.5,false],['',false]];
let bad = '';
for (const [v, exp] of truth) {
  if (isValidQoi(v) !== exp) bad += `isValidQoi(${JSON.stringify(v)})!=${exp};`;
}

(async () => {
  const run = async (v) => {
    el['#qoi'] = { value: v };
    calls = []; toasts = [];
    await el['#btn-gi-qoi'].onclick();
    return { calls, toasts };
  };
  let r = await run('17');
  if (r.calls.length !== 0) bad += '17-sent;';
  if (!(r.toasts.length === 1 && r.toasts[0].includes('1-16'))) bad += '17-no-toast;';
  r = await run('19');
  if (r.calls.length !== 0) bad += '19-sent;';
  r = await run('');
  if (r.calls.length !== 0) bad += 'empty-sent;';
  r = await run('1');
  if (!(r.calls.length === 1 && r.calls[0][0] === '/api/master/gi' && r.calls[0][1].qoi === 1)) bad += '1-wrong;';
  r = await run('20');
  if (!(r.calls.length === 1 && r.calls[0][1].qoi === 20)) bad += '20-wrong;';
  console.log(bad ? 'FAIL:' + bad : 'OK');
  process.exit(bad ? 1 : 0);
})();
"""


def test_master_html_qoi_behavioural():
    """Nit D 行为级验证 (需 node): 输入 17 不发请求且出提示；1/16/20 正常发.

    前置条件用**硬断言**而非 pytest.skip：node 缺失属 CI 配置缺陷，静默跳过会
    让「前端行为无人验证」长期潜伏（同 test_frontend_inline_scripts_*）。
    """
    node = shutil.which("node")
    assert node is not None, (
        "未找到 node（Node.js）。本用例需 PATH 中可用 node；"
        "CI 的 test job 必须提供 Node.js（参见 .github/workflows/ci.yml）。"
    )
    env = {**os.environ, "MASTER_HTML": str(_MASTER_HTML)}
    proc = subprocess.run(
        [node, "-e", _QOI_BEHAVIOUR_JS],
        capture_output=True, text=True, timeout=30, env=env,
        cwd=str(_MASTER_HTML.parent.parent),
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "OK" in proc.stdout


# ── favicon 路由 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_favicon_routes_served(master_client):
    """浏览器会请求 /favicon.ico，此前返回 404；现应返回 SVG 图标."""
    client, _ = master_client
    for path in ("/favicon.ico", "/favicon.svg"):
        r = await client.get(path)
        assert r.status == 200, f"{path} -> {r.status}"
        ctype = r.headers.get("Content-Type", "")
        assert "svg" in ctype, f"{path} Content-Type={ctype}"
        body = await r.text()
        assert "<svg" in body


@pytest.mark.asyncio
async def test_html_declares_icon(master_client):
    """页面 <head> 需声明图标，否则浏览器仍走默认 404 探测."""
    client, _ = master_client
    r = await client.get("/")
    html = await r.text()
    assert 'rel="icon"' in html
    assert "/favicon.svg" in html


# ── 错误 COT 注入（Web 全链路） ────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_cot_api_path(slave_client):
    """UI 开关 → /api/slave/response → 引擎 ResponseBehavior 全链路生效."""
    client, bridge = slave_client
    port = _free_port()
    r = await client.post("/api/slave/response", json={
        "errors": {"wrong_cot": True},
    })
    assert (await r.json())["ok"] is True

    r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"] is True
    try:
        engine = bridge.engine
        assert engine.response_behavior.wrong_cot is True
        assert engine._reply_cot(COT.ACTCON) == int(COT.ACTCON) + 1
    finally:
        await client.post("/api/slave/stop")

    # 关闭后恢复标准 COT（引擎已停，校验暂存配置）
    r = await client.post("/api/slave/response", json={"errors": {"wrong_cot": False}})
    assert (await r.json())["ok"] is True
    assert bridge.session.pending_response["errors"]["wrong_cot"] is False


@pytest.mark.asyncio
async def test_stop_without_engine_still_notifies_clients(slave_client):
    """空操作分支也必须广播事件.

    否则"以为还连着"的页面点「断开/停止」后收不到任何推送，永远停在旧状态，
    表现为「按钮能点，点了没效果」（实机反馈过的缺陷）。
    """
    client, bridge = slave_client
    q = bridge.subscribe()
    try:
        r = await client.post("/api/slave/stop")
        assert (await r.json())["ok"] is True
        assert not q.empty(), "未广播任何事件，客户端无法重新对齐状态"
        assert q.get_nowait()["kind"] == "event"
    finally:
        bridge.unsubscribe(q)


@pytest.mark.asyncio
async def test_start_twice_notifies_on_already_running(slave_client):
    """重复启动（already running）也要广播，让页面把按钮对齐到真实状态."""
    client, bridge = slave_client
    port = _free_port()
    body = {"host": "127.0.0.1", "port": port, "addr": 1}
    assert (await (await client.post("/api/slave/start", json=body)).json())["ok"] is True
    try:
        q = bridge.subscribe()
        try:
            r = await client.post("/api/slave/start", json=body)
            res = await r.json()
            assert res["ok"] is False and "already" in res["error"]
            assert not q.empty(), "already running 分支未广播事件"
        finally:
            bridge.unsubscribe(q)
    finally:
        await client.post("/api/slave/stop")


@pytest.mark.asyncio
async def test_status_started_flag_tracks_session(slave_client):
    """`status.started` 必须如实反映会话是否已启动.

    前端用它同步「启动监听/停止」（主站为「连接/断开」）的可用状态：页面刷新后
    若引擎仍在运行而按钮停在初始 disabled，用户就会"点不了停止/断开"
    （实机反馈过的缺陷）。
    """
    client, _ = slave_client
    assert (await (await client.get("/api/status")).json())["started"] is False

    port = _free_port()
    r = await client.post("/api/slave/start", json={"host": "127.0.0.1", "port": port, "addr": 1})
    assert (await r.json())["ok"] is True
    try:
        st = await (await client.get("/api/status")).json()
        assert st["started"] is True and st["running"] is True
    finally:
        await client.post("/api/slave/stop")

    st = await (await client.get("/api/status")).json()
    assert st["started"] is False and st["running"] is False


@pytest.mark.asyncio
async def test_pages_and_static_disable_heuristic_cache(slave_client):
    """页面与 app.js 必须带 no-cache，否则前端修复会被浏览器启发式缓存挡住."""
    client, _ = slave_client
    for path in ("/", "/static/js/app.js"):
        r = await client.get(path)
        assert r.status == 200, f"{path} -> {r.status}"
        cc = r.headers.get("Cache-Control", "")
        assert "no-cache" in cc, f"{path} Cache-Control={cc!r}"


def test_frontend_inline_scripts_wire_buttons_and_live_refresh():
    """真跑前端脚本（Node 沙箱）：按钮必须绑上 onclick，WS 报文必须触发刷新.

    背景：`app.js` 曾未把 `$` 暴露到 window，两页内联脚本首句即 ReferenceError，
    所有按钮静默失效、点值只能靠刷新页面更新——Python 端 HTML 字符串断言看不到这类问题。

    前置条件是**硬断言而非 skip**：脚本必须随仓库受版本控制（`tests/frontend/`，
    此前放在被 .gitignore 的 `qa_verify/`，导致干净克隆 / CI 中本用例必红），
    node 必须可用。二者缺失均属 CI 配置缺陷，静默跳过只会让缺陷长期潜伏。
    """
    script = Path(__file__).parent / "frontend" / "qa_webui_dom.mjs"
    assert script.is_file(), (
        f"前端沙箱脚本缺失: {script}\n"
        "该脚本须纳入版本控制（tests/frontend/），否则干净克隆 / CI 中本用例必然失败。"
    )
    node = shutil.which("node")
    assert node is not None, (
        "未找到 node（Node.js）。本用例需 PATH 中可用 node；"
        "CI 的 test job 必须提供 Node.js（参见 .github/workflows/ci.yml）。"
    )
    proc = subprocess.run(
        [node, str(script)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, f"前端沙箱验证失败:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.asyncio
async def test_slave_page_exposes_wrong_cot_control(slave_client):
    """子站页需提供「返回错误COT」开关并与 API 字段名一致（防止 UI 与后端脱节）."""
    client, _ = slave_client
    html = await (await client.get("/")).text()
    assert 'id="wrong-cot"' in html
    assert '"#wrong-cot"' in html
    assert "wrong_cot:" in html


# ── CLI 点表传递到 Web 会话 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_bridge_accepts_external_point_table():
    """EngineBridge 传入外部点表后，不得再生成演示点表覆盖它."""
    from core.data.point_table import PointTable

    table = PointTable()
    table.load_yaml(str(Path(__file__).parent.parent / "configs" / "demo_points.yaml"))
    before = table.yx_count

    bridge = EngineBridge("master", point_table=table)
    bridge.ensure_demo_points()          # 不应覆盖
    assert bridge.point_table is table
    assert bridge.point_table.yx_count == before
    # demo_points.yaml 有 4 个显式 sbo=true 的遥控点
    yk = bridge.point_table.get_all_yk()
    assert len(yk) == 4
    assert all(p.select_before_execute for p in yk)
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_bridge_without_table_generates_demo():
    """不传点表时保持原行为：自动生成演示点表."""
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    assert bridge.point_table.yx_count > 0
    assert bridge.points.count > 0
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_web_server_threads_point_table_to_engine():
    """--point-table 传递链末端：bridge 点表须注入主站引擎用于 SBO 决策."""
    from core.data.point_table import PointTable

    table = PointTable()
    table.load_yaml(str(Path(__file__).parent.parent / "configs" / "demo_points.yaml"))
    bridge = EngineBridge("master", point_table=table)
    bridge.ensure_demo_points()
    app = create_app(bridge)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        r = await client.get("/api/points")
        pts = (await r.json())["points"]
        yk_ioas = sorted(p["ioa"] for p in pts if p["type"] == "YK")
        assert yk_ioas == [2001, 2002, 2003, 2004], yk_ioas
    finally:
        await bridge.shutdown()
        await client.close()
