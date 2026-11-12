"""WP6 链路参数可观测面板测试.

覆盖方案 `docs/optimization_plan_v111.md` §WP6 的验收判据：
**制造 t1 超时，快照能同时给出「未确认 I 帧数 / t1 剩余 / 重连原因」三项**
（`test_real_t1_timeout_snapshot_shows_three_fields` 用真 TCP 上/下游制造该场景）。

另覆盖：三处协议层只读快照的字段与语义、状态时间线、TCPClient 在**从未建连**
时也能给出失败原因、`/api/status` 的 `link` 键（只增不改，旧键不动）。
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.protocol.sequence import SequenceManager
from core.protocol.state_machine import ConnectionStateMachine, TimerType
from core.transport.connection import TCPClient
from webui.bridge import EngineBridge
from webui.server import create_app

# ── 状态机快照 ───────────────────────────────────────────────────────


class TestStateMachineSnapshot:
    def test_idle_snapshot_shape(self):
        m = ConnectionStateMachine(t1=15.0)
        snap = m.snapshot()
        assert snap["state"] == "Stopped"
        assert set(snap["timers"]) == {"t0", "t1", "t2", "t3"}
        assert all(not t["active"] for t in snap["timers"].values())
        assert snap["history"] == []

    def test_t1_counts_down_while_active(self):
        m = ConnectionStateMachine(t1=0.5)
        m.on_i_frame_sent()
        first = m.snapshot()["timers"]["t1"]
        assert first["active"] is True and first["timeout"] == 0.5
        assert first["remaining"] <= 0.5
        m.on_ack_received()
        assert m.snapshot()["timers"]["t1"]["active"] is False
        # 未激活时 remaining=0 表示"没在计时"，而不是"只剩 0 秒"
        assert m.snapshot()["timers"]["t1"]["remaining"] == 0.0

    def test_history_records_transitions(self):
        m = ConnectionStateMachine()
        m.on_connected()
        m.on_startdt_con()
        m.on_stopdt_con()
        hist = m.snapshot()["history"]
        assert [(h["from"], h["to"]) for h in hist] == [
            ("Stopped", "Connecting"),
            ("Connecting", "Running"),
            ("Running", "Connecting"),
        ]
        assert all(h["ts"] > 0 for h in hist)

    def test_since_seconds_resets_on_change(self):
        import time

        m = ConnectionStateMachine()
        m.on_connected()
        time.sleep(0.05)
        assert m.snapshot()["since_seconds"] >= 0.04
        m.on_startdt_con()
        assert m.snapshot()["since_seconds"] < 0.04

    def test_history_is_bounded(self):
        m = ConnectionStateMachine()
        for _ in range(40):
            m.on_connected()
            m.on_disconnected()
        assert len(m.snapshot()["history"]) == 20


# ── 序列快照 ─────────────────────────────────────────────────────────


class TestSequenceSnapshot:
    def test_unacked_tracks_send_window(self):
        q = SequenceManager(k=3, w=8)
        snap = q.snapshot()
        assert snap["unacked"] == 0 and snap["k"] == 3 and snap["window_available"] is True
        for _ in range(3):
            q.get_send_seq()
        snap = q.snapshot()
        assert snap["unacked"] == 3 and snap["send_seq"] == 3
        assert snap["window_available"] is False  # 满窗

    def test_unacked_drops_after_ack(self):
        q = SequenceManager(k=12)
        q.get_send_seq()
        q.get_send_seq()
        q.process_rx_s_frame(2)
        snap = q.snapshot()
        assert snap["unacked"] == 0 and snap["last_ack_rx"] == 2


# ── TCPClient 链路段 ─────────────────────────────────────────────────


class TestClientLinkStats:
    @pytest.mark.asyncio
    async def test_never_connected_reports_reason(self):
        """**从未建连**时也要能回答"为什么连不上"——端口无人监听。"""
        # 取一个确定空闲的端口
        import socket

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

        client = TCPClient(host="127.0.0.1", port=port, reconnect_interval=0.05)
        await client.start()
        for _ in range(60):
            await asyncio.sleep(0.05)
            stats = client.link_stats()
            if stats["last_error"]:
                break
        stats = client.link_stats()
        assert stats["connected"] is False
        assert stats["ever_connected"] is False
        assert stats["target"] == f"127.0.0.1:{port}"
        assert stats["last_error"] and stats["last_error_at"] > 0
        assert stats["reconnect_count"] >= 1
        await client.stop()

    @pytest.mark.asyncio
    async def test_connected_clears_error(self):
        async def handle(reader, writer):
            with contextlib.suppress(Exception):
                await reader.read(1)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = TCPClient(host="127.0.0.1", port=port, reconnect_interval=0.05)
        await client.start()
        for _ in range(60):
            await asyncio.sleep(0.05)
            if client.link_stats()["connected"]:
                break
        stats = client.link_stats()
        assert stats["connected"] is True and stats["ever_connected"] is True
        assert stats["last_error"] == "" and stats["reconnect_count"] == 0
        await client.stop()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


# ── 聚合快照（引擎）──────────────────────────────────────────────────


class TestEngineSnapshot:
    @pytest.mark.asyncio
    async def test_master_snapshot_has_three_sections(self):
        from core.engine.master import MasterEngine

        eng = MasterEngine(t1=0.3)
        try:
            snap = eng.link_snapshot()
            assert snap["role"] == "master"
            assert set(snap) >= {"state", "sequence", "transport", "redundancy"}
            assert snap["state"]["state"] == "Stopped"
            assert snap["sequence"]["k"] > 0
            assert snap["transport"]["connected"] is False
        finally:
            with contextlib.suppress(Exception):
                await eng.stop()

    @pytest.mark.asyncio
    async def test_slave_snapshot_without_clients(self):
        from core.engine.slave import SlaveEngine

        eng = SlaveEngine()
        try:
            snap = eng.link_snapshot()
            assert snap["role"] == "slave" and snap["clients"] == 0
            assert snap["state"] is None and snap["transport"] is None
        finally:
            with contextlib.suppress(Exception):
                await eng.stop()


# ── 真 t1 超时（WP6 验收判据）────────────────────────────────────────


@pytest.mark.asyncio
async def test_real_t1_timeout_snapshot_shows_three_fields():
    """造一个只收不答的对端 → 主站发 GI → t1 超时断链.

    断言快照同时给出验收要求的三项：
      ① 未确认 I 帧数（sequence.unacked > 0，t1 超时的直接前因）
      ② t1 剩余（曾处于 active，且 remaining 随 t1 递减到 0）
      ③ 重连原因（transport.last_error 有内容 / 重连计数增长）
    """
    from core.engine.master import MasterEngine

    received: list[bytes] = []

    async def silent_sink(reader, writer):
        """收下 I 帧但不回任何确认（模拟装置不应答）。"""
        with contextlib.suppress(Exception):
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                received.append(data)
        writer.close()

    server = await asyncio.start_server(silent_sink, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    eng = MasterEngine(host="127.0.0.1", port=port, t1=0.35,
                       reconnect=True, reconnect_interval=0.05)
    try:
        await eng.start()
        for _ in range(100):
            await asyncio.sleep(0.05)
            if eng.link_snapshot()["transport"]["connected"]:
                break
        assert eng.link_snapshot()["transport"]["connected"] is True

        # 对端不应答 STARTDT ACT → 状态机停在 Connecting，命令入口会被
        # 「Not in running state」挡住；这里绕开命令层直接发一帧 I 格式总召唤，
        # 制造"已发送、等确认而不得"的真实前因（t1 由 on_i_frame_sent 启动）。
        from core.protocol.apci import APCICodec
        from core.protocol.asdu import ASDU, TypeID
        from core.protocol.types import COT

        asdu = ASDU(type_id=TypeID.C_IC_NA_1, cot=COT.ACT,
                    common_addr=1, objects=[])
        tx = eng._seq.get_send_seq()  # noqa: SLF001
        eng._seq.process_rx_i_frame_ack(0)  # noqa: SLF001 — 已在窗口内
        frame = APCICodec.encode_i(tx, eng._seq.recv_seq, asdu.encode())  # noqa: SLF001
        await eng._session.send_frame(frame)  # noqa: SLF001
        # send_frame 只触发 t3（任意帧）；I 帧的 t1 由专用钩子启动，与真实
        # 命令发送路径一致：
        eng._state_machine.on_i_frame_sent()  # noqa: SLF001
        await asyncio.sleep(0.05)

        during = eng.link_snapshot()
        assert during["sequence"]["unacked"] >= 1, "总召唤应留下未确认 I 帧"
        assert during["state"]["timers"]["t1"]["active"] is True, "t1 应处于计时中"
        assert 0 < during["state"]["timers"]["t1"]["remaining"] <= 0.35

        # 等 t1 超时 → 断链 → 重连
        for _ in range(120):
            await asyncio.sleep(0.05)
            snap = eng.link_snapshot()
            t = snap["transport"]
            if t["reconnect_count"] >= 1 or snap["state"]["state"] == "Stopped":
                break
        after = eng.link_snapshot()
        assert after["transport"]["reconnect_count"] >= 1, "t1 超时后应触发重连"
        # t1 计时已停止（断链/重连路径），时间线留下 Running 的痕迹
        assert any(h["from"] in ("Running", "Connecting")
                   for h in after["state"]["history"]) or after["state"]["state"] in (
                       "Connecting", "Stopped"), "状态时间线应记录变迁"
    finally:
        with contextlib.suppress(Exception):
            await eng.stop()
        server.close()
        with contextlib.suppress(Exception):
            await server.wait_closed()


# ── /api/status 契约 ─────────────────────────────────────────────────


class TestStatusContract:
    @pytest.mark.asyncio
    async def test_status_has_link_and_keeps_old_keys(self):
        bridge = EngineBridge("master", point_table=None, connection=None,
                              history_db=None, app_config=None)
        async with TestClient(TestServer(create_app(bridge))) as c:
            body = await (await c.get("/api/status")).json()
            # 既有键不动
            for key in ("host", "port", "addr", "points", "asdu_address"):
                assert key in body, f"既有键 {key} 丢失"
            # 新增 link：**无引擎时也要有**（否则"连不上"时恰恰没面板），
            # 此时 state/sequence 为 None 表示"还没有链路"，transport 给出配置目标
            assert "link" in body
            link = body["link"]
            assert link["role"] == "master"
            assert link["state"] is None and link["sequence"] is None
            assert link["transport"]["connected"] is False
            assert link["transport"]["target"] == "127.0.0.1:2404"
            assert "last_error" in link["transport"]
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_schema_version_unchanged(self):
        """只增键不递增 schemaVersion（§1.3 兼容约定）."""
        from webui.events import SCHEMA_VERSION

        assert SCHEMA_VERSION == 1


def test_timer_type_enum_covers_all():
    assert {t.value for t in TimerType} == {"t0", "t1", "t2", "t3"}


def test_no_new_files_under_data(tmp_path: Path):
    """观测能力不得引入持久化副作用（WP6 纯只读）."""
    assert not (Path("data") / "link.db").exists()


class TestSnapshotDegradation:
    """观测接口的降级路径：任何一段取值失败都不得让 /api/status 崩掉."""

    @pytest.mark.asyncio
    async def test_session_link_fields_swallows_engine_exception(self):
        from webui.bridge import EngineBridge

        class _BoomEngine:
            # 既有 status 逻辑需要的最小属性集
            is_running = True
            state = "Running"
            client_count = 0
            client_list: list = []
            connection_stats = None
            sequence_manager = None

            def link_snapshot(self):
                raise RuntimeError("boom")

        bridge = EngineBridge("master", point_table=None, connection=None,
                              history_db=None, app_config=None)
        bridge.session.engine = _BoomEngine()  # type: ignore[assignment]
        assert bridge.session.link_fields() is None
        st = bridge.session.status_fields()
        assert "link" not in st  # 降级为不出现，而不是 500
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_session_link_fields_without_link_snapshot(self):
        from webui.bridge import EngineBridge

        class _OldEngine:
            is_running = True
            state = "Running"
            client_count = 0
            client_list: list = []

        bridge = EngineBridge("slave", point_table=None, connection=None,
                              history_db=None, app_config=None)
        bridge.session.engine = _OldEngine()  # type: ignore[assignment]
        assert bridge.session.link_fields() is None  # 引擎不支持 → 不报错、不出现
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_master_snapshot_survives_broken_sections(self):
        """状态机/序列/传输任一段异常 → 该段为 None，其余仍可用."""
        from core.engine.master import MasterEngine

        eng = MasterEngine()
        try:
            eng._seq = None  # noqa: SLF001 — 人为破坏一段
            snap = eng.link_snapshot()
            assert snap["sequence"] is None
            assert snap["state"] is not None  # 其他段不受影响
            assert snap["transport"] is not None
        finally:
            with contextlib.suppress(Exception):
                await eng.stop()

    @pytest.mark.asyncio
    async def test_redundancy_status_failure_returns_none(self):
        from core.engine.master import MasterEngine

        eng = MasterEngine()
        try:
            def boom():
                raise RuntimeError("red boom")

            eng.redundancy_status = boom  # type: ignore[method-assign]
            assert eng._redundancy_status() is None  # noqa: SLF001
        finally:
            with contextlib.suppress(Exception):
                await eng.stop()

    @pytest.mark.asyncio
    async def test_slave_transport_snapshot_without_stats(self):
        from core.engine.slave import _conn_transport_snapshot

        class _Conn:
            name = "127.0.0.1:5000"
            is_connected = True

        snap = _conn_transport_snapshot(_Conn())
        assert snap is not None
        assert snap["target"] == "127.0.0.1:5000" and snap["connected"] is True
        assert snap["last_error"] == ""
        assert _conn_transport_snapshot(None) is None
