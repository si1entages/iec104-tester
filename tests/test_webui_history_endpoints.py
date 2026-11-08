"""历史库查询 REST 接线测试（历史查询页）.

进程内 aiohttp TestClient 实测 /api/history/* 端点：启用/未启用形态、
过滤参数、时间/条数边界、参数校验 400、CSV 导出。
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.data.history import HistoryDB
from webui.bridge import EngineBridge
from webui.server import create_app


def _make_bridge(history_db: HistoryDB | None) -> EngineBridge:
    return EngineBridge(role="master", history_db=history_db)


def _seed(db: HistoryDB) -> None:
    # 三条数据用显式时间戳（1000/1500/2000），使「新→旧」与时间过滤可确定性断言
    db.record_data_change("yx", 100, "1", quality="good", source="spont", timestamp=1000.0)
    db.record_data_change("yc", 200, "220.5", source="gi", timestamp=1500.0)
    db.record_data_change("yc", 200, "221.0", source="spont", timestamp=2000.0)
    db.record_frame("rx", bytes.fromhex("680401000000"), frame_type="I")
    db.flush()


@pytest.mark.asyncio
async def test_history_disabled():
    bridge = _make_bridge(None)
    async with TestClient(TestServer(create_app(bridge))) as client:
        r = await client.get("/api/history/stats")
        assert r.status == 200
        body = await r.json()
        assert body["ok"] is True and body["enabled"] is False
        # 未启用时也返回与启用时同形状的零值统计（便于前端 schema 校验）
        assert body["stats"] == {
            "data_records": 0,
            "frame_records": 0,
            "buffered_data": 0,
            "buffered_frames": 0,
            "oldest_data": 0,
            "newest_data": 0,
            "db_size_bytes": 0,
            "dropped_records": 0,
        }

        r = await client.get("/api/history/data")
        body = await r.json()
        assert body["enabled"] is False and body["rows"] == []

        r = await client.get("/api/history/frames")
        body = await r.json()
        assert body["enabled"] is False and body["rows"] == []

        # 导出在未启用时明确报错（前端导出按钮已禁用，此处兜底）
        r = await client.get("/api/history/export")
        assert r.status == 400


@pytest.mark.asyncio
async def test_history_stats_and_filters():
    db = HistoryDB(":memory:")
    db.open()
    _seed(db)
    try:
        async with TestClient(TestServer(create_app(_make_bridge(db)))) as client:
            # 统计
            r = await client.get("/api/history/stats")
            body = await r.json()
            assert body["enabled"] is True
            assert body["stats"]["data_records"] == 3
            assert body["stats"]["frame_records"] == 1

            # 全量（新→旧）
            r = await client.get("/api/history/data")
            rows = (await r.json())["rows"]
            assert len(rows) == 3
            assert rows[0]["point_type"] == "yc" and rows[0]["value"] == "221.0"
            assert rows[0]["ts"] == 2000.0

            # 类型过滤
            r = await client.get("/api/history/data", params={"point_type": "yx"})
            rows = (await r.json())["rows"]
            assert len(rows) == 1 and rows[0]["ioa"] == 100

            # IOA 过滤
            r = await client.get("/api/history/data", params={"ioa": 200})
            rows = (await r.json())["rows"]
            assert len(rows) == 2

            # 时间过滤（start=1600 → 只剩 timestamp=2000 的记录；>= 为闭区间）
            r = await client.get("/api/history/data", params={"start": 1600})
            rows = (await r.json())["rows"]
            assert len(rows) == 1 and rows[0]["ts"] == 2000.0

            # start=1500 为闭区间边界 → 1500/2000 两条
            r = await client.get("/api/history/data", params={"start": 1500})
            assert len((await r.json())["rows"]) == 2

            # limit
            r = await client.get("/api/history/data", params={"limit": 1})
            assert len((await r.json())["rows"]) == 1

            # 报文：全量 + 方向过滤
            r = await client.get("/api/history/frames")
            rows = (await r.json())["rows"]
            assert len(rows) == 1 and rows[0]["hex"] == "680401000000"
            assert rows[0]["frame_type"] == "I"

            r = await client.get("/api/history/frames", params={"direction": "tx"})
            assert (await r.json())["rows"] == []
    finally:
        db.close()


@pytest.mark.asyncio
async def test_history_invalid_params():
    db = HistoryDB(":memory:")
    db.open()
    try:
        async with TestClient(TestServer(create_app(_make_bridge(db)))) as client:
            for path, params in (
                ("/api/history/data", {"ioa": "abc"}),
                ("/api/history/data", {"ioa": "-5"}),
                ("/api/history/data", {"limit": "abc"}),
                ("/api/history/data", {"limit": "0"}),
                ("/api/history/data", {"start": "xyz"}),
                ("/api/history/frames", {"start": "xyz"}),
                ("/api/history/export", {"type": "bogus"}),
            ):
                r = await client.get(path, params=params)
                assert r.status == 400, f"{path}?{params} 应 400"
                body = await r.json()
                assert body["ok"] is False and body["error"]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_history_export_csv():
    db = HistoryDB(":memory:")
    db.open()
    _seed(db)
    try:
        async with TestClient(TestServer(create_app(_make_bridge(db)))) as client:
            r = await client.get("/api/history/export", params={"type": "data"})
            assert r.status == 200
            assert "text/csv" in r.headers.get("Content-Type", "")
            assert "filename=" in r.headers.get("Content-Disposition", "")
            rows = list(csv.reader(io.StringIO(await r.text())))
            assert rows[0] == ["时间戳", "类型", "IOA", "值", "品质", "来源"]
            assert len(rows) == 4  # 表头 + 3 条

            r = await client.get("/api/history/export", params={"type": "frames"})
            rows = list(csv.reader(io.StringIO(await r.text())))
            assert rows[0] == ["时间戳", "方向", "帧类型", "HEX数据", "解析", "客户端"]
            assert len(rows) == 2

            # CSV 导出也支持过滤
            r = await client.get(
                "/api/history/export", params={"type": "data", "point_type": "yx"}
            )
            rows = list(csv.reader(io.StringIO(await r.text())))
            assert len(rows) == 2  # 表头 + 1 条
    finally:
        db.close()
