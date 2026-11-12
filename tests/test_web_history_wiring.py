"""Web 模式历史库接线（T17 决策 1）测试.

覆盖:
- ``EngineBridge(history_db=...)`` 在 ``_on_raw_frame`` 中把收发报文落盘
- 不传 ``history_db`` 时行为与改动前一致（不记录、不报错）
- 历史库异常不得影响报文主路径（WS 推送仍正常）
- ``resolve_history_path`` 按角色分文件
- ``run_server`` / ``run_web`` 的 ``history_db`` 为向后兼容可选参数
"""

from __future__ import annotations

import asyncio
import inspect
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import app as app_module
from app import resolve_history_path
from core.data.history import HistoryDB
from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from webui.bridge import EngineBridge
from webui.server import _run, run_server

FRAME = bytes.fromhex("680407000000")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 8.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _demo_point_table() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=10, yc_count=5, yk_count=3, ym_count=2)
    pt.common_addr = 1
    pt.station_name = "WebHistoryE2E"
    return pt


def _db(tmp_path, name="h.db") -> HistoryDB:
    db = HistoryDB(tmp_path / name, retention_days=0, max_size_mb=0)
    db.open()
    return db


class TestBridgeRecordsFrames:
    def test_history_db_receives_tx_and_rx(self, tmp_path):
        db = _db(tmp_path)
        bridge = EngineBridge("slave", history_db=db)

        bridge._on_raw_frame(FRAME, "rx", "c1")
        bridge._on_raw_frame(FRAME, "tx")
        db.flush()

        rows = db.query_frames()
        assert len(rows) == 2
        assert {r.direction for r in rows} == {"rx", "tx"}
        by_dir = {r.direction: r for r in rows}
        assert by_dir["rx"].hex_data == "680407000000"
        assert by_dir["rx"].client_id == "c1"
        db.close()

    def test_without_history_db_is_noop(self):
        bridge = EngineBridge("slave")
        assert bridge._history is None
        bridge._on_raw_frame(FRAME, "rx", "c1")     # 不应抛异常

    def test_history_failure_does_not_break_frame_path(self, tmp_path):
        """历史库抛错时 WS 推送仍须照常（历史库不得污染报文主路径）."""
        class _Boom:
            def record_frame(self, *a, **kw):
                raise RuntimeError("db down")

        bridge = EngineBridge("slave", history_db=_Boom())
        bridge._on_raw_frame(FRAME, "rx", "c1")

        frames = bridge.recent("frame", 10)
        assert len(frames) == 1
        assert frames[0]["data"]["hex"] == FRAME.hex()

    def test_ws_frame_payload_unchanged(self, tmp_path):
        """接线后 WS frame 报文结构不变（前端契约不受影响）."""
        db = _db(tmp_path, "c.db")
        bridge = EngineBridge("slave", history_db=db)
        bridge._on_raw_frame(FRAME, "rx", "c1")

        data = bridge.recent("frame", 1)[0]["data"]
        assert set(data) == {"direction", "len", "hex", "client"}
        assert data["len"] == len(FRAME)
        db.close()


class TestResolveHistoryPathRole:
    def test_role_suffix_default_dir(self):
        base = Path(app_module.__file__).parent / "data"
        assert resolve_history_path("", None, "master") == base / "history_master.db"
        assert resolve_history_path("", None, "slave") == base / "history_slave.db"

    def test_no_role_keeps_plain_name(self):
        assert resolve_history_path("").name == "history.db"

    def test_override_ignores_role(self):
        assert resolve_history_path("d", "x/y.db", "master") == Path("x/y.db")

    def test_cfg_dir_with_role(self):
        assert resolve_history_path("some/dir", None, "slave") == \
            Path("some/dir") / "history_slave.db"


class TestBackwardCompatibleApi:
    def test_run_server_history_db_is_optional_kwarg(self):
        sig = inspect.signature(run_server)
        assert "history_db" in sig.parameters
        assert sig.parameters["history_db"].default is None

    def test_run_history_db_is_optional_kwarg(self):
        sig = inspect.signature(_run)
        assert sig.parameters["history_db"].default is None

    def test_run_web_history_db_is_optional_kwarg(self):
        sig = inspect.signature(app_module.run_web)
        assert sig.parameters["history_db"].default is None

    def test_existing_positional_calls_still_valid(self):
        """旧调用位置参数不变：role/host/port/point_table/connection.

        D3 在尾部新增 ``app_config``，B7 再新增 ``auth_token``（均默认 None，
        纯关键字参数），既有位置参数调用不受影响；WP4a 在 auth_token 后
        插入 ``auth_config``（同样纯关键字），位置参数顺序依旧不变。
        """
        params = list(inspect.signature(run_server).parameters)
        assert params == ["role", "host", "port", "point_table",
                          "connection", "history_db", "app_config",
                          "auth_token", "auth_config", "ssl_context", "history_dbs"]


class TestWebModeEndToEnd:
    """真 TCP：Web 模式下经 EngineBridge 的子站会话收发帧落盘.

    这是决策 1 的核心验收——不只是"回调挂了"，而是"跑了真连接后库里真有帧"。
    """

    @pytest.mark.asyncio
    async def test_real_handshake_frames_persisted(self, tmp_path):
        port = _free_port()
        db = _db(tmp_path, "web_e2e.db")
        bridge = EngineBridge("slave", point_table=_demo_point_table(),
                              history_db=db)
        try:
            res = await bridge.start_slave("127.0.0.1", port, 1)
            assert res.get("ok"), res

            master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                                  auto_gi=False, reconnect=False)
            await master.start()
            try:
                # Running 态 = STARTDT 已双向确认，说明收发帧都已发生
                assert await _wait_until(lambda: master.is_running, timeout=8.0)
                assert await _wait_until(
                    lambda: (db.flush() or (
                        any(r.direction == "rx" for r in db.query_frames())
                        and any(r.direction == "tx" for r in db.query_frames())
                    )),
                    timeout=8.0,
                ), f"历史库未收到双向帧: {db.query_frames()}"
            finally:
                await master.stop()
        finally:
            await bridge.shutdown()
            db.close()

    @pytest.mark.asyncio
    async def test_no_history_db_means_no_records_possible(self, tmp_path):
        """不接线历史库时 bridge 不持有库（回归：默认行为不变）."""
        bridge = EngineBridge("slave", point_table=_demo_point_table())
        assert bridge._history is None
        await bridge.shutdown()
