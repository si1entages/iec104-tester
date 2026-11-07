"""报文录制/回放 Web 服务（E2）: 录制 → 文件 → pcap 导出 → 回放."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from webui.bridge import EngineBridge
from webui.capture import CaptureService
from webui.server import create_app

FRAME = bytes.fromhex("680401000000")  # S 帧（合法 APCI）


@pytest_asyncio.fixture
async def capture_client(tmp_path):
    bridge = EngineBridge("master")
    bridge.ensure_demo_points()
    bridge.captures = CaptureService(tmp_path, "master")
    client = TestClient(TestServer(create_app(bridge)))
    await client.start_server()
    yield client, bridge, tmp_path
    await bridge.shutdown()
    await client.close()


@pytest.mark.asyncio
async def test_record_stop_and_files(capture_client):
    client, bridge, tmp = capture_client

    r = await client.post("/api/capture/start", json={})
    body = await r.json()
    assert body["ok"] is True and body["recording"] is True
    name = body["file"]
    assert name.endswith(".i104")

    # 两个方向各喂一帧
    bridge._on_raw_frame(FRAME, "rx", "c1")
    bridge._on_raw_frame(FRAME, "tx")

    r = await client.get("/api/capture/status")
    st = await r.json()
    assert st["recording"] is True and st["frames"] == 2
    assert st["rx"] == 1 and st["tx"] == 1

    r = await client.post("/api/capture/stop")
    body = await r.json()
    assert body["ok"] is True and body["frames"] == 2
    path = tmp / name
    assert path.is_file() and path.stat().st_size > 0

    r = await client.get("/api/capture/files")
    files = (await r.json())["files"]
    assert [f["name"] for f in files] == [name]

    # 重复 stop → 400
    assert (await client.post("/api/capture/stop")).status == 400


@pytest.mark.asyncio
async def test_pause_resume(capture_client):
    client, bridge, _ = capture_client
    await client.post("/api/capture/start", json={})
    assert (await client.post("/api/capture/pause")).status == 200
    bridge._on_raw_frame(FRAME, "rx")
    st = await (await client.get("/api/capture/status")).json()
    assert st["frames"] == 0 and st["paused"] is True
    assert (await client.post("/api/capture/resume")).status == 200
    bridge._on_raw_frame(FRAME, "rx")
    st = await (await client.get("/api/capture/status")).json()
    assert st["frames"] == 1
    await client.post("/api/capture/stop")


@pytest.mark.asyncio
async def test_export_pcap_and_download(capture_client):
    client, bridge, tmp = capture_client
    body = await (await client.post("/api/capture/start", json={})).json()
    name = body["file"]
    bridge._on_raw_frame(FRAME, "rx")
    await client.post("/api/capture/stop")

    r = await client.post("/api/capture/export", json={"name": name, "format": "pcap"})
    out = await r.json()
    assert out["ok"] is True and out["file"].endswith("_pcap.pcap")
    assert (tmp / out["file"]).is_file()

    r = await client.get(f"/api/capture/download/{out['file']}")
    assert r.status == 200
    assert "attachment" in r.headers["Content-Disposition"]
    assert len(await r.read()) > 0

    assert (await client.post(
        "/api/capture/export", json={"name": name, "format": "zip"})).status == 400
    assert (await client.get("/api/capture/download/nope.i104")).status == 404


@pytest.mark.asyncio
async def test_load_frames_step_and_play(capture_client):
    client, bridge, _ = capture_client
    body = await (await client.post("/api/capture/start", json={})).json()
    name = body["file"]
    bridge._on_raw_frame(FRAME, "rx")
    bridge._on_raw_frame(FRAME, "tx")
    await client.post("/api/capture/stop")

    r = await client.post("/api/capture/load", json={"name": name})
    loaded = await r.json()
    assert loaded["ok"] is True and loaded["total"] == 2

    r = await client.get("/api/capture/frames", params={"offset": 0, "limit": 1})
    rows = (await r.json())["rows"]
    assert len(rows) == 1 and rows[0]["hex"] == FRAME.hex().upper()

    r = await client.post("/api/capture/step", json={"direction": "forward"})
    assert (await r.json())["index"] == 1
    r = await client.post("/api/capture/step", json={"direction": "backward"})
    assert (await r.json())["index"] == 0

    assert (await client.post("/api/capture/play", json={"speed": "x"})).status == 400
    assert (await client.post("/api/capture/play", json={"speed": 0})).status == 400
    r = await client.post("/api/capture/play", json={"speed": 2})
    assert (await r.json())["ok"] is True
    await asyncio.sleep(0.1)
    st = await (await client.get("/api/capture/status")).json()
    assert st["playback"]["loaded"] is True
    assert (await client.post("/api/capture/playback/stop")).status == 200


@pytest.mark.asyncio
async def test_capture_endpoint_validation(capture_client):
    client, _, _ = capture_client
    assert (await client.post("/api/capture/start", data=b"{bad",
                              headers={"Content-Type": "application/json"})).status == 400
    assert (await client.post("/api/capture/load", data=b"{bad",
                              headers={"Content-Type": "application/json"})).status == 400
    assert (await client.post("/api/capture/load", json={})).status == 400
    assert (await client.get("/api/capture/frames")).status == 400
    assert (await client.get("/api/capture/frames", params={"limit": "x"})).status == 400
    assert (await client.post("/api/capture/step", json={"direction": "x"})).status == 400
    assert (await client.post("/api/capture/playback/pause")).status == 400
