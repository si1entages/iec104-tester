"""一键诊断包端点测试（``GET /api/diagnostics/export``）."""

from __future__ import annotations

import io
import json
import zipfile

from aiohttp.test_utils import TestClient, TestServer

from core.config import AppConfig
from webui.bridge import EngineBridge
from webui.server import create_app


async def test_diagnostics_export_contains_context_and_redacts_key() -> None:
    config = AppConfig()
    config.tls.keyfile = "C:/secret/client-key.pem"
    config.connection.host = "127.0.0.1"
    config.connection.port = 2404

    bridge = EngineBridge("master", app_config=config)
    bridge.point_table.generate_demo_points(
        yx_count=3, yc_count=2, yk_count=1, ym_count=1, step_count=0,
    )
    bridge.points.refresh_count()
    try:
        async with TestClient(TestServer(create_app(bridge))) as client:
            resp = await client.get("/api/diagnostics/export")
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("application/zip")
            assert "attachment" in resp.headers["Content-Disposition"]
            payload = await resp.read()
    finally:
        await bridge.shutdown()

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert {
            "README.txt", "manifest.json", "status.json", "config.json",
            "logs.json", "frames.json", "events.json", "points.json",
            "history.json",
        } <= names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["kind"] == "iec104-diagnostics"
        assert manifest["role"] == "master"
        assert manifest["schemaVersion"] >= 1
        assert manifest["counts"]["points"] == 7

        status = json.loads(zf.read("status.json"))
        assert status["role"] == "master"
        assert status["points"] == 7

        exported_config = json.loads(zf.read("config.json"))
        assert exported_config["tls"]["keyfile"] == "<redacted>"
        assert exported_config["connection"]["port"] == 2404

        assert json.loads(zf.read("history.json")) == {"enabled": False}
        assert isinstance(json.loads(zf.read("logs.json")), list)
        assert len(json.loads(zf.read("points.json"))) == 7
