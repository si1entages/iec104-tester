"""自动化测试中心（E1）：脚本列表、子进程运行、报告下载、停止."""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.server import create_app
from webui.testcenter import TestCenterService as CenterService

SCRIPT_YAML = textwrap.dedent("""
    name: fake-script
    description: fake for test
    role: master
    timeout: 10
    steps:
      - action: connect
        description: connect
""").strip()

FAKE_RUNNER = textwrap.dedent("""
    import sys
    from pathlib import Path

    report = Path(sys.argv[-1])
    report.mkdir(parents=True, exist_ok=True)
    print("▶ Running: fake-script")
    print("✅ fake-script (0.01s)")
    print("📊 Summary: 1 scripts, 1 passed, 0 failed")
    (report / "fake-script.html").write_text("<html>ok</html>", encoding="utf-8")
    (report / "fake-script.json").write_text("{}", encoding="utf-8")
""").strip()

SLOW_RUNNER = textwrap.dedent("""
    import time
    print("started", flush=True)
    time.sleep(30)
""").strip()


@pytest.fixture
def env(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "fake.yaml").write_text(SCRIPT_YAML, encoding="utf-8")
    reports = tmp_path / "reports"
    fake = tmp_path / "fake_runner.py"
    fake.write_text(FAKE_RUNNER, encoding="utf-8")
    return {
        "scripts": scripts,
        "reports": reports,
        "runner": [sys.executable, "-u", str(fake)],
        "tmp": tmp_path,
    }


@pytest.fixture
def service(env):
    return CenterService(
        scripts_dir=env["scripts"], reports_dir=env["reports"],
        runner_cmd=env["runner"])


async def _wait_done(service: CenterService, timeout: float = 10.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        st = service.status()
        if not st["running"]:
            return st
        await asyncio.sleep(0.05)
    raise AssertionError(f"test run did not finish: {service.status()}")


@pytest.mark.asyncio
async def test_list_run_report(service):
    scripts = service.list_scripts()
    assert [s["id"] for s in scripts] == ["fake.yaml"]
    assert scripts[0]["steps"] == 1

    started = service.start(["fake.yaml"])
    assert started["ok"] is True
    st = await _wait_done(service)
    run = st["run"]
    assert run["status"] == "passed"
    assert run["summary"] == {"scripts": 1, "passed": 1, "failed": 0}
    assert any("Summary" in line for line in run["lines"])
    names = [r["name"] for r in run["reports"]]
    assert "fake-script.html" in names

    path = service.report_path(run["id"], "fake-script.html")
    assert path is not None and path.read_text(encoding="utf-8") == "<html>ok</html>"


@pytest.mark.asyncio
async def test_invalid_names(service):
    assert service.start([])["ok"] is False
    assert service.start(["../evil.yaml"])["ok"] is False
    assert service.start(["missing.yaml"])["ok"] is False
    assert service.status()["running"] is False


@pytest.mark.asyncio
async def test_stop_running(env):
    slow = env["tmp"] / "slow_runner.py"
    slow.write_text(SLOW_RUNNER, encoding="utf-8")
    service = CenterService(
        scripts_dir=env["scripts"], reports_dir=env["reports"],
        runner_cmd=[sys.executable, "-u", str(slow)])
    service.start(["fake.yaml"])
    assert service.running is True
    await asyncio.sleep(0.2)
    assert service.stop()["ok"] is True
    st = await _wait_done(service)
    assert st["run"]["status"] == "stopped"
    assert service.stop()["ok"] is False


@pytest_asyncio.fixture
async def client(env):
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    bridge.testcenter = CenterService(
        scripts_dir=env["scripts"], reports_dir=env["reports"],
        runner_cmd=env["runner"])
    test_client = TestClient(TestServer(create_app(bridge)))
    await test_client.start_server()
    yield test_client, bridge
    await bridge.shutdown()
    await test_client.close()


@pytest.mark.asyncio
async def test_endpoints(client):
    c, _ = client
    r = await c.get("/api/tests/scripts")
    assert [s["id"] for s in (await r.json())["scripts"]] == ["fake.yaml"]

    r = await c.post("/api/tests/run", json={"scripts": ["fake.yaml"]})
    assert r.status == 200
    run_id = (await r.json())["run"]["id"]

    for _ in range(100):
        st = await (await c.get("/api/tests/status")).json()
        if not st["running"]:
            break
        await asyncio.sleep(0.05)
    assert st["run"]["status"] == "passed"

    r = await c.get(f"/api/tests/reports/{run_id}/fake-script.html")
    assert r.status == 200 and "<html>ok</html>" in await r.text()
    assert (await c.get(f"/api/tests/reports/{run_id}/nope.html")).status == 404
    assert (await c.get("/api/tests/reports/..%2F..%2Fx/a.html")).status == 404

    assert (await c.post("/api/tests/run", json={"scripts": []})).status == 400
    assert (await c.post("/api/tests/run", data=b"{bad",
                         headers={"Content-Type": "application/json"})).status == 400
    assert (await c.post("/api/tests/stop")).status == 400
