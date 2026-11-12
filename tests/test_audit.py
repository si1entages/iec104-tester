"""WP4a 操作审计 + 多用户三角色测试.

覆盖方案 `docs/optimization_plan_v111.md` §WP4 的测试下限：
- 哈希链追加 / 篡改检测（改一条 → hash_mismatch；删一条 → chain_break 报断点 id）；
- 三角色权限矩阵（viewer 只读 / operator 操作 / admin 全权）；
- 兼容模式（无 --auth-token 无 --auth-config）行为不变；
- 验收判据：viewer 调 /api/master/yk 403 且链上无该动作；
- WP2 传动联动：REST 命令经 _cmd 落链带操作人/帧证据。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from core.data.audit import (
    GENESIS_HASH,
    AuditRecord,
    AuditStore,
    canonical_record,
    chain_hash,
)
from webui.audit import OperatorRegistry, role_allowed
from webui.bridge import EngineBridge
from webui.server import create_app

# ── 本地夹具 ─────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path: Path) -> AuditStore:
    s = AuditStore(tmp_path / "audit.db")
    s.open()
    yield s
    s.close()


def _rec(**kw) -> AuditRecord:
    kw.setdefault("ts", 1700000000.0)
    kw.setdefault("action", "master.yk")
    kw.setdefault("result", "ok")
    return AuditRecord(**kw)


# ── 哈希链核心 ───────────────────────────────────────────────────────


class TestHashChain:
    def test_genesis_and_append(self, store: AuditStore):
        r1 = store.append(_rec(operator="张三"))
        assert r1.prev_hash == GENESIS_HASH
        assert len(r1.hash) == 64
        r2 = store.append(_rec(operator="李四", ts=1700000001.0))
        assert r2.prev_hash == r1.hash

    def test_canonical_stable_and_order_independent(self):
        a = canonical_record(1.0, "op", "admin", "1.2.3.4", "a.yk", "1", "ok", "", "ff", "ee")
        b = canonical_record(1.0, "op", "admin", "1.2.3.4", "a.yk", "1", "ok", "", "ff", "ee")
        assert a == b
        # ts 微小差异会进入哈希（防重放语义），但 round(6) 内一致
        c = canonical_record(1.0000001, "op", "admin", "1.2.3.4", "a.yk", "1", "ok", "", "ff", "ee")
        assert c == a

    def test_chain_hash_known_shape(self):
        h = chain_hash(GENESIS_HASH, "x")
        assert h != GENESIS_HASH and len(h) == 64
        assert h == chain_hash(GENESIS_HASH, "x")

    def test_verify_clean(self, store: AuditStore):
        for i in range(5):
            store.append(_rec(ts=1700000000.0 + i))
        out = store.verify()
        assert out["ok"] is True and out["valid"] is True
        assert out["total"] == 5 and out["broken_at"] is None

    def test_verify_detects_content_tamper(self, store: AuditStore):
        for i in range(3):
            store.append(_rec(ts=1700000000.0 + i, operator=f"op{i}"))
        # 直接改库模拟篡改（改第 2 条的操作人）
        with store._lock:
            store.conn.execute(
                "UPDATE audit_records SET operator = 'attacker' WHERE id = 2")
            store.conn.commit()
        out = store.verify()
        assert out["ok"] is False and out["broken_at"] == 2
        assert "hash_mismatch" in out["reason"]

    def test_verify_detects_delete(self, store: AuditStore):
        for i in range(4):
            store.append(_rec(ts=1700000000.0 + i))
        with store._lock:
            store.conn.execute("DELETE FROM audit_records WHERE id = 2")
            store.conn.commit()
        out = store.verify()
        assert out["ok"] is False and out["broken_at"] == 3
        assert "chain_break" in out["reason"]

    def test_frame_hex_truncated(self, store: AuditStore):
        r = store.append(_rec(tx_frame="ab" * 1000))
        assert len(r.tx_frame) == 512

    def test_list_filters_and_limit(self, store: AuditStore):
        for i, (op, act, res) in enumerate([
            ("a", "master.yk", "ok"), ("b", "master.yk", "fail"),
            ("a", "slave.yx", "ok"), ("a", "master.sp", "ok"),
        ]):
            store.append(_rec(operator=op, action=act, result=res,
                              ts=1700000000.0 + i))
        assert len(store.list_records(limit=2)) == 2
        assert all(r.operator == "a" for r in store.list_records(operator="a"))
        assert [r.action for r in store.list_records(action="slave.yx")] == ["slave.yx"]
        assert all(r.result == "ok" for r in store.list_records(result="ok"))
        late = store.list_records(since=1700000002.0)
        assert all(r.ts >= 1700000002.0 for r in late)

    def test_stats(self, store: AuditStore):
        store.append(_rec(operator="a", result="ok"))
        store.append(_rec(operator="b", result="fail", ts=1700000001.0))
        st = store.stats()
        assert st["total"] == 2 and st["operators"] == 2 and st["fails"] == 1
        assert st["last_ts"] == 1700000001.0


# ── OperatorRegistry 与权限矩阵 ──────────────────────────────────────


class TestOperators:
    def _write_yaml(self, tmp_path: Path, content: str) -> str:
        p = tmp_path / "users.yaml"
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_load_and_authenticate(self, tmp_path: Path):
        path = self._write_yaml(tmp_path, (
            "users:\n"
            "  - name: 检修张\n"
            "    token: tok-admin\n"
            "    role: admin\n"
            "  - name: 运行李\n"
            "    token: tok-op\n"
            "    role: operator\n"
            "  - name: 监王\n"
            "    token: tok-view\n"
            "    role: viewer\n"
        ))
        reg = OperatorRegistry.from_yaml(path)
        assert len(reg) == 3
        ident = reg.authenticate("tok-op")
        assert ident is not None and ident.name == "运行李" and ident.role == "operator"
        assert reg.authenticate("wrong") is None
        assert reg.authenticate("") is None
        # 角色列表不含任何 token 材料
        roles = reg.roles()
        assert {"name": "检修张", "role": "admin"} in roles
        assert all("token" not in u for u in roles)

    def test_invalid_role_rejected(self, tmp_path: Path):
        path = self._write_yaml(tmp_path,
                                "users:\n  - name: x\n    token: t\n    role: root\n")
        with pytest.raises(ValueError, match="角色非法"):
            OperatorRegistry.from_yaml(path)

    def test_missing_token_rejected(self, tmp_path: Path):
        path = self._write_yaml(tmp_path, "users:\n  - name: x\n    role: viewer\n")
        with pytest.raises(ValueError, match="name/token"):
            OperatorRegistry.from_yaml(path)

    def test_empty_users_rejected(self, tmp_path: Path):
        path = self._write_yaml(tmp_path, "users: []\n")
        with pytest.raises(ValueError, match="未定义任何用户"):
            OperatorRegistry.from_yaml(path)

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(OSError):
            OperatorRegistry.from_yaml(tmp_path / "nope.yaml")


class TestRoleMatrix:
    def test_admin_all(self):
        for m, p in [("GET", "/api/points"), ("POST", "/api/points/import"),
                     ("DELETE", "/api/commission/sessions/x"), ("POST", "/api/auth/users")]:
            assert role_allowed("admin", m, p) is True

    def test_viewer_read_only(self):
        assert role_allowed("viewer", "GET", "/api/points") is True
        assert role_allowed("viewer", "GET", "/api/audit/verify") is True
        for m, p in [("POST", "/api/master/yk"), ("DELETE", "/api/audit/x"),
                     ("POST", "/api/slave/yx")]:
            assert role_allowed("viewer", m, p) is False

    def test_operator_commands_yes_config_no(self):
        # 命令/模拟/传动/桥操作放行
        for p in ["/api/master/yk", "/api/master/gi", "/api/slave/yx",
                  "/api/commission/sessions", "/api/commission/sessions/x/run",
                  "/api/bridge/start", "/api/tests/run"]:
            assert role_allowed("operator", "POST", p) is True
        # 点表写入 / 用户管理（含 GET）/ 删除拒绝
        for m, p in [("POST", "/api/points/import"), ("POST", "/api/points/yaml"),
                     ("POST", "/api/points/design"), ("POST", "/api/points/batch"),
                     ("POST", "/api/auth/users"), ("GET", "/api/auth/users"),
                     ("DELETE", "/api/commission/sessions/x")]:
            assert role_allowed("operator", m, p) is False


# ── API 集成（TestClient + 真 EngineBridge）─────────────────────────


def _make_bridge(role: str = "master") -> EngineBridge:
    return EngineBridge(role, point_table=None, connection=None,
                        history_db=None, app_config=None)


def _isolate_audit(bridge: EngineBridge, tmp_path: Path) -> None:
    """把 bridge 的审计库指到测试临时目录（默认 data/ 会污染项目目录）."""
    from webui.audit import AuditService

    store = AuditStore(tmp_path / "audit.db")
    bridge.audit = AuditService(store)
    store.open()


def _client(bridge: EngineBridge, tmp_path: Path, **kw) -> TestClient:
    _isolate_audit(bridge, tmp_path)
    app = create_app(bridge, **kw)
    server = TestServer(app)
    return TestClient(server)


def _users_yaml(tmp_path: Path) -> str:
    p = tmp_path / "users.yaml"
    p.write_text(
        "users:\n"
        "  - name: 管理员\n    token: tok-a\n    role: admin\n"
        "  - name: 操作员\n    token: tok-o\n    role: operator\n"
        "  - name: 监视员\n    token: tok-v\n    role: viewer\n",
        encoding="utf-8",
    )
    return str(p)


class TestCompatMode:
    """验收判据：兼容模式（无 auth）下既有行为完全不变."""

    @pytest.mark.asyncio
    async def test_no_auth_passthrough(self, tmp_path: Path):
        bridge = _make_bridge()
        client = _client(bridge, tmp_path)
        async with client as c:
            r = await c.get("/api/status")
            assert r.status == 200
            r = await c.post("/api/master/yk", json={"ioa": 1, "state": 1})
            assert r.status == 200  # 无引擎 → 业务错误 200 {ok:false}
            body = await r.json()
            assert body["ok"] is False
            # 无身份上下文：不落审计链
            r = await c.get("/api/audit/records")
            assert (await r.json())["stats"]["total"] == 0
        await bridge.shutdown()


class TestOperatorsMode:
    @pytest.mark.asyncio
    async def test_viewer_yk_forbidden_and_not_in_chain(self, tmp_path: Path):
        """方案验收判据 1：viewer 调 /api/master/yk 403，且链上无该动作."""
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, operators=OperatorRegistry.from_yaml(
            _users_yaml(tmp_path)))
        async with client as c:
            r = await c.post("/api/master/yk", json={"ioa": 1, "state": 1},
                             headers={"X-Auth-Token": "tok-v"})
            assert r.status == 403
            r = await c.get("/api/audit/records",
                            headers={"X-Auth-Token": "tok-a"})
            body = await r.json()
            assert body["stats"]["total"] == 0
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_operator_command_recorded_with_evidence(self, tmp_path: Path):
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, operators=OperatorRegistry.from_yaml(
            _users_yaml(tmp_path)))
        async with client as c:
            r = await c.post("/api/master/yk", json={"ioa": 100, "state": 1},
                             headers={"X-Auth-Token": "tok-o"})
            assert r.status == 200
            recs = (await (await c.get(
                "/api/audit/records", headers={"X-Auth-Token": "tok-o"})).json())
            assert recs["stats"]["total"] == 1
            row = recs["records"][0]
            assert row["action"] == "master/yk"
            assert row["operator"] == "操作员"
            assert row["role"] == "operator"
            assert row["target"] == "100"
            assert row["result"] in ("ok", "fail")  # 无引擎 → fail + reason
            # 链校验通过
            v = await (await c.get(
                "/api/audit/verify", headers={"X-Auth-Token": "tok-a"})).json()
            assert v["ok"] is True
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_wrong_token_401_and_mode_probe(self, tmp_path: Path):
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, operators=OperatorRegistry.from_yaml(
            _users_yaml(tmp_path)))
        async with client as c:
            r = await c.get("/api/status", headers={"X-Auth-Token": "bad"})
            assert r.status == 401
            r = await c.get("/api/auth")
            body = await r.json()
            assert body["required"] is True and body["mode"] == "users"
            assert body["valid"] is False
            r = await c.get("/api/auth", headers={"X-Auth-Token": "tok-o"})
            body = await r.json()
            assert body["valid"] is True
            assert body["operator"] == "操作员" and body["role"] == "operator"
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_users_endpoint_admin_only(self, tmp_path: Path):
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, operators=OperatorRegistry.from_yaml(
            _users_yaml(tmp_path)))
        async with client as c:
            r = await c.get("/api/auth/users", headers={"X-Auth-Token": "tok-o"})
            assert r.status == 403
            r = await c.get("/api/auth/users", headers={"X-Auth-Token": "tok-a"})
            body = await r.json()
            assert body["ok"] is True and len(body["users"]) == 3
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_x_operator_ignored_in_users_mode(self, tmp_path: Path):
        """多用户模式以 token 映射为准，防 X-Operator 冒名."""
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, operators=OperatorRegistry.from_yaml(
            _users_yaml(tmp_path)))
        async with client as c:
            await c.post("/api/master/yk", json={"ioa": 1, "state": 1},
                         headers={"X-Auth-Token": "tok-o", "X-Operator": "冒名者"})
            row = (await (await c.get(
                "/api/audit/records", headers={"X-Auth-Token": "tok-a"})).json())["records"][0]
            assert row["operator"] == "操作员"
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_compat_single_token_admin_and_x_operator(self, tmp_path: Path):
        """兼容单 token：匿名 admin + X-Operator 头补充操作人姓名."""
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, auth_token="secret")
        async with client as c:
            r = await c.get("/api/status", headers={"X-Auth-Token": "secret"})
            assert r.status == 200
            r = await c.post("/api/master/yk", json={"ioa": 7, "state": 1},
                             headers={"X-Auth-Token": "secret", "X-Operator": "现场张"})
            assert r.status == 200
            row = (await (await c.get(
                "/api/audit/records", headers={"X-Auth-Token": "secret"})).json())["records"][0]
            assert row["operator"] == "现场张" and row["role"] == "admin"
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_audit_export_and_forbidden_format(self, tmp_path: Path):
        bridge = _make_bridge()
        client = _client(bridge, tmp_path, operators=OperatorRegistry.from_yaml(
            _users_yaml(tmp_path)))
        async with client as c:
            await c.post("/api/master/yk", json={"ioa": 1, "state": 1},
                         headers={"X-Auth-Token": "tok-o"})
            r = await c.get("/api/audit/export?format=json",
                            headers={"X-Auth-Token": "tok-a"})
            assert r.status == 200
            body = json.loads(await r.text())
            assert len(body["records"]) == 1
            r = await c.get("/api/audit/export?format=csv",
                            headers={"X-Auth-Token": "tok-a"})
            assert "text/csv" in r.content_type
            text = await r.text()
            assert "master/yk" in text
            r = await c.get("/api/audit/export?format=xml",
                            headers={"X-Auth-Token": "tok-a"})
            assert r.status == 400
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_auth_config_invalid_exits(self, tmp_path: Path):
        from webui.server import _load_operators

        with pytest.raises(SystemExit, match="auth-config"):
            _load_operators(str(tmp_path / "missing.yaml"))


class TestCommissionLinkage:
    @pytest.mark.asyncio
    async def test_send_writes_audit_with_session_operator(self, tmp_path: Path):
        """WP2 联动：编排 _send 复用同一条审计链（operator=会话检查人）."""
        from core.data.commissioning import CommissionItem, CommissionSession, ItemKind
        from webui.commissioning import CommissioningService

        bridge = _make_bridge()
        _isolate_audit(bridge, tmp_path)
        store_spy: list[str] = []

        class _FakeStore:
            def save(self, s):
                store_spy.append(s.id)

        svc = CommissioningService(bridge, _FakeStore())
        s = CommissionSession(id="s1", name="n")
        s.operator = "传动王"
        item = CommissionItem(ioa=1, name="p", kind=ItemKind.YK, group=0,
                              expected=1)
        s.items = [item]
        # send_yk 走真 bridge._cmd（无引擎 → fail），应落审计链
        await svc._send(bridge, item, operator=s.operator)
        recs = bridge.audit.list_records(limit=10)
        assert len(recs) == 1
        assert recs[0]["action"] == "commission/yk"
        assert recs[0]["operator"] == "传动王"
        assert recs[0]["role"] == "system"
        assert recs[0]["target"] == "1"
        await bridge.shutdown()


class TestCoveragePatches:
    """零散分支：to_dict 可选键 / lazy conn / 导出非法格式 / 记录失败不外抛."""

    def test_to_dict_optional_keys(self):
        r = AuditRecord(ts=1.0, extra={"k": "v"})
        d = r.to_dict()
        assert d["extra"] == {"k": "v"}
        assert "id" not in d and "hash" not in d and "prev_hash" not in d
        r2 = AuditRecord(ts=1.0, id=7, prev_hash="p", hash="h")
        d2 = r2.to_dict()
        assert d2["id"] == 7 and d2["prev_hash"] == "p" and d2["hash"] == "h"

    def test_lazy_conn_creates_parent_dir(self, tmp_path: Path):
        from core.data.audit import AuditStore as S

        store = S(tmp_path / "sub" / "dir" / "a.db")
        conn = store.conn  # 触发 lazy open + 逐级建目录
        assert conn is not None
        assert (tmp_path / "sub" / "dir" / "a.db").exists()
        store.close()

    def test_now_ts_monotonic_enough(self):
        from core.data.audit import now_ts

        assert abs(now_ts() - time.time()) < 5.0

    def test_service_export_bad_format_raises(self, tmp_path: Path):
        from webui.audit import AuditService

        svc = AuditService(AuditStore(tmp_path / "a.db"))
        with pytest.raises(ValueError, match="unsupported"):
            svc.export("xml")

    def test_service_record_swallows_store_errors(self):
        from webui.audit import AuditService

        class _Boom:
            def append(self, _record):
                raise RuntimeError("disk full")

        svc = AuditService(_Boom())
        assert svc.record("master/yk", "ok") is False
