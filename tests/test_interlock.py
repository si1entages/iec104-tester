"""WP4b 防误操作闭锁测试.

覆盖方案 `docs/optimization_plan_v111.md` §WP4 WP4b 的测试下限：
- 条件解析（合法/非法配置）；非法配置抛 ValueError 不静默；
- 求值：命中 / 未命中 / 值未知（安全取向为不满足）/ 多条件 AND；
- 点表 YAML 往返（interlock 读写、非空才写）；
- 下发前闭锁：不满足时**链路上不发任何命令帧**（验收判据）；
- 强制解锁：需 admin；放行并写审计；非 admin 拒绝且不发帧；
- 未配置闭锁 / 无身份（兼容模式）行为与历史一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.data.point_table import PointTable, YkPointDef
from core.engine.interlock import (
    InterlockCondition,
    dump_interlock,
    evaluate,
    parse_interlock,
)
from webui.audit import Identity, set_operator_context
from webui.bridge import EngineBridge

# ── 解析 ─────────────────────────────────────────────────────────────


class TestParse:
    def test_none_and_empty(self):
        assert parse_interlock(None) == ()
        assert parse_interlock([]) == ()

    def test_plain_and_string_bools(self):
        c = parse_interlock([{"ioa": 100, "value": True},
                             {"ioa": 101, "value": "off", "label": "刀闸"}])
        assert c[0] == InterlockCondition(ioa=100, value=True, label="")
        assert c[1].value is False and c[1].label == "刀闸"

    def test_chinese_bool_words(self):
        assert parse_interlock([{"ioa": 1, "value": "合"}])[0].value is True
        assert parse_interlock([{"ioa": 1, "value": "分位"}])[0].value is False

    @pytest.mark.parametrize("bad", [
        "not-a-list",
        [{"ioa": -1, "value": True}],
        [{"ioa": True, "value": True}],
        [{"value": True}],
        [{"ioa": 1}],
        [{"ioa": 1, "value": "maybe"}],
        ["x"],
    ])
    def test_invalid_rejected(self, bad):
        with pytest.raises(ValueError):
            parse_interlock(bad)

    def test_roundtrip_dump(self):
        conds = parse_interlock([{"ioa": 5, "value": False, "label": "L"}])
        assert dump_interlock(conds) == [{"ioa": 5, "value": False, "label": "L"}]
        assert dump_interlock(parse_interlock([])) == []


# ── 求值 ─────────────────────────────────────────────────────────────


class TestEvaluate:
    COND = parse_interlock([{"ioa": 1001, "value": False, "label": "刀闸"}])

    def test_no_conditions_never_blocks(self):
        r = evaluate((), lambda _i: True)
        assert r.blocked is False and r.conditions == ()

    def test_satisfied_passes(self):
        r = evaluate(self.COND, lambda _i: False)
        assert r.blocked is False and r.reason == ""
        assert r.observed == ((1001, False),)

    def test_violated_blocks_with_reason(self):
        r = evaluate(self.COND, lambda _i: True)
        assert r.blocked is True
        assert "须为分位" in r.reason and "实测为合位" in r.reason
        assert r.as_dict()["blocked"] is True

    def test_unknown_value_blocks(self):
        r = evaluate(self.COND, lambda _i: None)
        assert r.blocked is True and "未知" in r.reason

    def test_read_exception_treated_as_unknown(self):
        def boom(_i):
            raise RuntimeError("no store")

        r = evaluate(self.COND, boom)
        assert r.blocked is True and "未知" in r.reason

    def test_multi_conditions_and(self):
        conds = parse_interlock([{"ioa": 1, "value": True},
                                 {"ioa": 2, "value": True, "label": "B"}])
        assert evaluate(conds, lambda i: True).blocked is False
        assert evaluate(conds, lambda i: i == 1).blocked is True


# ── 点表往返 ─────────────────────────────────────────────────────────


class TestPointTableYaml:
    def test_yaml_roundtrip_keeps_interlock(self, tmp_path: Path):
        t = PointTable()
        t.add_yk(YkPointDef(ioa=2001, name="合闸", interlock=parse_interlock(
            [{"ioa": 1001, "value": False, "label": "刀闸"}])))
        t.add_yk(YkPointDef(ioa=2002, name="无闭锁"))
        path = tmp_path / "p.yaml"
        t.save_yaml(path)

        text = path.read_text(encoding="utf-8")
        assert "interlock" in text
        # 未配置闭锁的点不写该字段（保持既有 YAML 干净）
        assert text.count("interlock") == 1

        t2 = PointTable()
        t2.load_yaml(path)
        assert t2.get_yk(2001).interlock[0].ioa == 1001
        assert t2.get_yk(2001).interlock[0].value is False
        assert t2.get_yk(2002).interlock == ()

    def test_invalid_yaml_interlock_raises(self, tmp_path: Path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            "yk:\n  - ioa: 1\n    interlock:\n      - ioa: 2\n        value: maybe\n",
            encoding="utf-8")
        with pytest.raises(ValueError):
            PointTable().load_yaml(path)

    def test_legacy_yaml_without_interlock_ok(self, tmp_path: Path):
        path = tmp_path / "legacy.yaml"
        path.write_text("yk:\n  - ioa: 1\n    name: 老点表\n", encoding="utf-8")
        t = PointTable()
        t.load_yaml(path)
        assert t.get_yk(1).interlock == ()


# ── 下发前闭锁（bridge 门面）─────────────────────────────────────────


class _Store:
    def __init__(self, values: dict[int, bool]):
        self._values = values

    def get_yx(self, ioa: int):
        if ioa not in self._values:
            return None
        return type("D", (), {"value": self._values[ioa]})()


class _Engine:
    def __init__(self, table: PointTable, values: dict[int, bool]):
        self._point_table = table
        self.data_store = _Store(values)


def _bridge_with(table: PointTable, values: dict[int, bool]) -> EngineBridge:
    """构造桥并把审计库指向独立临时目录（避免污染项目 data/ 且用例间互不干扰）."""
    import tempfile
    from pathlib import Path as _Path

    from core.data.audit import AuditStore
    from webui.audit import AuditService

    b = EngineBridge("master", point_table=table, connection=None,
                     history_db=None, app_config=None)
    b.session.engine = _Engine(table, values)  # type: ignore[assignment]
    store = AuditStore(_Path(tempfile.mkdtemp()) / "audit.db")
    store.open()
    b.audit = AuditService(store)
    b.commission_store.close()
    return b


def _send_spy(bridge: EngineBridge) -> list[dict]:
    """替换 session 命令方法，记录"是否真的下发帧". """
    sent: list[dict] = []

    async def yk(ioa, state, select=False, double=False, with_time=False,
                 deactivate=False):
        sent.append({"cmd": "yk", "ioa": ioa, "state": state})
        return {"ok": True}

    async def sp(ioa, value, select=False, kind="short_float", with_time=False,
                 deactivate=False):
        sent.append({"cmd": "setpoint", "ioa": ioa, "value": value})
        return {"ok": True}

    async def step(ioa, state, select=False):
        sent.append({"cmd": "step", "ioa": ioa, "state": state})
        return {"ok": True}

    async def bitstring(ioa, value):
        sent.append({"cmd": "bitstring", "ioa": ioa})
        return {"ok": True}

    bridge.session.send_yk = yk  # type: ignore[method-assign]
    bridge.session.send_setpoint = sp  # type: ignore[method-assign]
    bridge.session.send_step_command = step  # type: ignore[method-assign]
    bridge.session.send_bitstring = bitstring  # type: ignore[method-assign]
    return sent


def _table_with_interlock() -> PointTable:
    t = PointTable()
    t.add_yk(YkPointDef(ioa=2001, name="合闸", interlock=parse_interlock(
        [{"ioa": 1001, "value": False, "label": "刀闸"}])))
    t.add_yk(YkPointDef(ioa=2002, name="常规点"))
    return t


class TestGate:
    @pytest.mark.asyncio
    async def test_no_interlock_passes_and_sends(self):
        t = PointTable()
        t.add_yk(YkPointDef(ioa=2002))
        b = _bridge_with(t, {})
        sent = _send_spy(b)
        r = await b.send_yk(2002, 1)
        assert r["ok"] is True and len(sent) == 1
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_blocked_sends_no_frame(self):
        """验收判据：闭锁不满足时链路上没有任何命令帧."""
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: True})  # 刀闸在合位 → 不允许合闸
        sent = _send_spy(b)
        r = await b.send_yk(2001, 1)
        assert r["ok"] is False and "联锁不满足" in r["error"]
        assert r["interlock"]["blocked"] is True
        assert sent == [], "闭锁不满足时不得下发任何帧"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_satisfied_passes(self):
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: False})
        sent = _send_spy(b)
        r = await b.send_yk(2001, 1)
        assert r["ok"] is True and len(sent) == 1
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_unknown_state_blocks(self):
        t = _table_with_interlock()
        b = _bridge_with(t, {})  # 遥信未上送
        sent = _send_spy(b)
        r = await b.send_yk(2001, 1)
        assert r["ok"] is False and sent == []
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_blocked_writes_audit_reject(self):
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: True})
        _send_spy(b)
        await b.send_yk(2001, 1)
        recs = b.audit.list_records(limit=5)
        assert len(recs) == 1
        assert recs[0]["action"] == "yk/interlock-blocked"
        assert recs[0]["result"] == "fail"
        assert recs[0]["target"] == "2001"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_setpoint_and_step_gated(self):
        t = PointTable()
        t.add_yk(YkPointDef(ioa=3001, interlock=parse_interlock(
            [{"ioa": 99, "value": True}])))
        from core.data.point_table import StepPointDef

        t.add_step(StepPointDef(ioa=3002, interlock=parse_interlock(
            [{"ioa": 99, "value": True}])))
        b = _bridge_with(t, {99: False})
        r1 = await b.send_setpoint(3001, 1.5)
        r2 = await b.send_step_command(3002, 2)
        assert r1["ok"] is False and r2["ok"] is False
        await b.shutdown()


    @pytest.mark.asyncio
    async def test_deactivate_bypasses_interlock(self):
        """DEACT 撤销帧是安全清理动作，闭锁不满足也必须能发."""
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: True})
        sent = _send_spy(b)
        r = await b.send_yk(2001, 0, deactivate=True)
        assert r["ok"] is True and len(sent) == 1
        await b.shutdown()


class TestForceUnlock:
    @pytest.mark.asyncio
    async def test_admin_force_passes_and_audits(self):
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: True})
        sent = _send_spy(b)
        set_operator_context(Identity(name="检修张", role="admin", source_ip="1.2.3.4"))
        try:
            r = await b.send_yk(2001, 1, force=True)
        finally:
            set_operator_context(None)
        assert r["ok"] is True and len(sent) == 1
        recs = b.audit.list_records(limit=5)
        assert recs[0]["action"] == "yk/force-unlock"
        assert recs[0]["operator"] == "检修张" and recs[0]["role"] == "admin"
        assert "强制解锁" in recs[0]["reason"]
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_operator_force_denied_no_frame(self):
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: True})
        sent = _send_spy(b)
        set_operator_context(Identity(name="运行李", role="operator"))
        try:
            r = await b.send_yk(2001, 1, force=True)
        finally:
            set_operator_context(None)
        assert r["ok"] is False and "admin" in r["error"]
        assert sent == []
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_no_identity_force_allowed_compat(self):
        """未启用认证（兼容模式）= 全权，与 WP4a role_allowed 取向一致."""
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: True})
        sent = _send_spy(b)
        r = await b.send_yk(2001, 1, force=True)
        assert r["ok"] is True and len(sent) == 1
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_force_when_not_blocked_is_noop(self):
        t = _table_with_interlock()
        b = _bridge_with(t, {1001: False})
        sent = _send_spy(b)
        r = await b.send_yk(2001, 1, force=True)
        assert r["ok"] is True and len(sent) == 1
        assert b.audit.list_records(limit=5) == []  # 未触发解锁不写记录
        await b.shutdown()


# ── API 级：force 透传与契约响应（契约 §2.4e）────────────────────────


class TestApi:
    async def _client(self, table: PointTable, values: dict[int, bool]):
        from aiohttp.test_utils import TestClient, TestServer

        from webui.server import create_app

        b = _bridge_with(table, values)
        return b, TestClient(TestServer(create_app(b)))

    @pytest.mark.asyncio
    async def test_blocked_returns_200_with_interlock_payload(self):
        t = _table_with_interlock()
        b, client = await self._client(t, {1001: True})
        async with client as c:
            r = await c.post("/api/master/yk", json={"ioa": 2001, "state": 1})
            assert r.status == 200, "闭锁拒绝是业务错误，HTTP 仍 200"
            body = await r.json()
            assert body["ok"] is False
            assert "联锁不满足" in body["error"]
            assert body["interlock"]["blocked"] is True
            assert body["interlock"]["observed"] == [{"ioa": 1001, "value": True}]
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_force_flag_accepted_by_endpoint(self):
        t = _table_with_interlock()
        b, client = await self._client(t, {1001: True})
        sent = _send_spy(b)
        async with client as c:
            r = await c.post("/api/master/yk",
                             json={"ioa": 2001, "state": 1, "force": True})
            body = await r.json()
            assert body["ok"] is True and len(sent) == 1
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_points_snapshot_exposes_interlock(self):
        t = _table_with_interlock()
        b, client = await self._client(t, {})
        async with client as c:
            body = await (await c.get("/api/points")).json()
            yk = {p["ioa"]: p for p in body["points"] if p["type"] == "YK"}
            assert yk[2001]["interlock"] == [
                {"ioa": 1001, "value": False, "label": "刀闸"}]
            assert yk[2002]["interlock"] == []
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_setpoint_endpoint_force_and_deactivate(self):
        t = PointTable()
        t.add_yk(YkPointDef(ioa=5001, interlock=parse_interlock(
            [{"ioa": 7, "value": True}])))
        b, client = await self._client(t, {7: False})
        sent = _send_spy(b)
        async with client as c:
            r = await c.post("/api/master/setpoint",
                             json={"ioa": 5001, "value": 1.0, "force": True})
            assert (await r.json())["ok"] is True and len(sent) == 1
            r = await c.post("/api/master/setpoint",
                             json={"ioa": 5001, "value": 1.0, "deactivate": True})
            assert (await r.json())["ok"] is True and len(sent) == 2
        await b.shutdown()
