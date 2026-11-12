"""WP5 工程配置方案管理测试.

覆盖方案 `docs/optimization_plan_v111.md` §WP5 的验收判据：
- **3 套方案切换，刷新后参数/阈值/点表全部还原**（apply 把连接/链路参数/
  ASDU 地址长度/告警阈值/点表都写回运行态）；
- 方案名非法（路径穿越、空、点/下划线开头）一律拒绝；
- 导入导出往返；坏文件不影响列表；
- 未配置方案时行为与历史一致；旧版 `--config` 单文件仍可直接启动
  （方案文件本身就是合法 AppConfig YAML，双向兼容）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer

from core.config import load_config
from core.data.profiles import (
    ProfileNameError,
    ProfileStore,
    summarize,
    validate_name,
)
from webui.bridge import EngineBridge
from webui.server import create_app

# ── 方案名校验 ───────────────────────────────────────────────────────


class TestNameValidation:
    @pytest.mark.parametrize("ok", ["a", "1号线主站", "device_A-2", "带 空格", "x.y"])
    def test_valid(self, ok):
        assert validate_name(ok) == ok

    @pytest.mark.parametrize("bad", [
        "", "   ", "../etc/passwd", "a/b", "a\\b", ".hidden", "_state",
        "a:b", "a*b", "a?b", 'a"b', "a<b", "x" * 65,
    ])
    def test_invalid(self, bad):
        with pytest.raises(ProfileNameError):
            validate_name(bad)

    def test_path_traversal_never_escapes(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "profiles")
        with pytest.raises(ProfileNameError):
            st.path_of("../../evil")
        with pytest.raises(ProfileNameError):
            st.save("../evil", {})


# ── 存取与列表 ───────────────────────────────────────────────────────


class TestStore:
    def test_save_load_list_delete(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "p")
        assert st.list_profiles() == [] and st.active() == ""
        st.save("甲站", {"mode": "master", "connection": {"host": "10.0.0.1", "port": 2404}})
        st.save("乙站", {"mode": "slave", "connection": {"host": "10.0.0.2", "port": 2405}})
        names = [p.name for p in st.list_profiles()]
        assert names == ["乙站", "甲站"] or names == ["甲站", "乙站"]
        assert len(names) == 2

        data = st.load("甲站")
        assert data["connection"]["host"] == "10.0.0.1"

        assert st.delete("甲站") is True
        assert st.load("甲站") is None
        assert st.delete("甲站") is False
        assert [p.name for p in st.list_profiles()] == ["乙站"]

    def test_broken_file_does_not_break_listing(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "p")
        st.save("good", {"mode": "master"})
        (tmp_path / "p" / "broken.yaml").write_text("::: not yaml ::\n\t", encoding="utf-8")
        names = [p.name for p in st.list_profiles()]
        assert "good" in names and "broken" in names

    def test_state_file_not_listed(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "p")
        st.save("a", {})
        st.set_active("a")
        assert (tmp_path / "p" / "_active.yaml").is_file()
        assert [p.name for p in st.list_profiles()] == ["a"]
        assert st.active() == "a"

    def test_active_cleared_on_delete(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "p")
        st.save("a", {})
        st.set_active("a")
        st.delete("a")
        assert st.active() == ""

    def test_active_ignores_missing_target(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "p")
        (tmp_path / "p").mkdir(parents=True)
        (tmp_path / "p" / "_active.yaml").write_text("active: ghost\n", encoding="utf-8")
        assert st.active() == ""

    def test_yaml_roundtrip_and_bad_import(self, tmp_path: Path):
        st = ProfileStore(tmp_path / "p")
        st.save("a", {"mode": "master", "note": "现场甲"})
        text = st.to_yaml("a")
        assert "现场甲" in text
        assert st.from_yaml(text)["mode"] == "master"
        for bad in ("", "   ", "[]", "- a\n- b\n", "just a string"):
            with pytest.raises(ValueError):
                st.from_yaml(bad)

    def test_summarize_partial(self):
        s = summarize({})
        assert s["mode"] == "" and s["port"] is None and s["timers"] == {}
        s2 = summarize({"connection": {"host": "h", "port": 1},
                        "asdu_address": {"ca_length": 1, "ioa_length": 2, "cot_length": 2}})
        assert s2["host"] == "h" and s2["ca_length"] == 1


# ── 服务层 ───────────────────────────────────────────────────────────


def _bridge(tmp_path: Path, role: str = "master") -> EngineBridge:
    """桥 + 独立方案目录（不碰项目 configs/）。"""
    from core.data.audit import AuditStore
    from webui.audit import AuditService

    b = EngineBridge(role, point_table=None, connection=None,
                     history_db=None, app_config=None)
    b.profiles.store = ProfileStore(tmp_path / "profiles")
    store = AuditStore(tmp_path / "audit.db")
    store.open()
    b.audit = AuditService(store)
    return b


class TestService:
    @pytest.mark.asyncio
    async def test_capture_reflects_config(self, tmp_path: Path):
        from webui.alarms import AlarmService

        b = _bridge(tmp_path)
        # create_app 才会挂 AlarmService；这里显式挂上以覆盖阈值捕获分支
        b.alarms = AlarmService(b)
        b.config.connection.host = "10.1.2.3"
        b.config.connection.port = 2405
        b.config.connection.common_addr = 7
        b.config.asdu_address = type(b.config.asdu_address)(1, 2, 2)
        snap = b.profiles.capture()
        assert snap["connection"]["host"] == "10.1.2.3"
        assert snap["connection"]["port"] == 2405
        assert snap["asdu_address"] == {"ca_length": 1, "ioa_length": 2, "cot_length": 2}
        assert "alarms" in snap
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_three_profiles_switch_restores_all(self, tmp_path: Path):
        """验收判据：设 3 套方案切换，连接/链路参数/ASDU 长度/阈值全部还原."""
        from webui.alarms import AlarmService

        b = _bridge(tmp_path)
        b.alarms = AlarmService(b)
        specs = [
            ("甲站", "10.0.0.1", 2404, 1, (2, 3, 2), 10.0),
            ("乙站", "10.0.0.2", 2405, 2, (1, 2, 2), 20.0),
            ("丙站", "10.0.0.3", 2406, 3, (2, 2, 1), 30.0),
        ]
        for name, host, port, addr, cai, stale in specs:
            b.profiles.save(name, {
                "mode": "master",
                "connection": {"host": host, "port": port, "common_addr": addr},
                "timers": {"t0": 30.0, "t1": 15.0, "t2": 10.0, "t3": float(cai[2])},
                "flow_control": {"k": cai[1], "w": 8},
                "asdu_address": {"ca_length": cai[0], "ioa_length": cai[1],
                                 "cot_length": cai[2]},
                "alarms": {"stale_seconds": stale},
            })

        from core.protocol.address import get_default

        for name, host, port, addr, cai, stale in specs:
            r = b.profiles.apply(name)
            assert r["ok"] is True
            assert b.config.connection.host == host
            assert b.config.connection.port == port
            assert b.config.connection.common_addr == addr
            assert b.config.timers.t3 == float(cai[2])
            assert b.config.flow_control.k == cai[1]
            # WP1：进程级默认同步（编解码立刻按新长度工作）
            assert get_default().ca_length == cai[0]
            assert get_default().ioa_length == cai[1]
            assert get_default().cot_length == cai[2]
            # 阈值还原（告警服务 configure 生效）
            assert b.alarms.config.stale_seconds == stale
            # status 反映新连接参数（前端刷新后显示的就是它）
            assert b.status()["host"] == host and b.status()["port"] == port

        assert b.profiles.store.active() == "丙站"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_apply_restores_point_table(self, tmp_path: Path):
        b = _bridge(tmp_path)
        pt = tmp_path / "pts.yaml"
        pt.write_text("common_addr: 5\nyx:\n  - ioa: 11\n    name: 甲\n", encoding="utf-8")
        b.profiles.save("带点表", {"mode": "master", "point_table": {"file": str(pt)}})
        r = b.profiles.apply("带点表")
        assert "point_table" in r["applied"]
        pts = b.snapshot_points()
        assert any(p["ioa"] == 11 for p in pts)
        assert b.config.point_table.file == str(pt)
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_apply_missing_point_table_skips_gracefully(self, tmp_path: Path):
        b = _bridge(tmp_path)
        b.profiles.save("缺文件", {"mode": "master",
                                   "point_table": {"file": str(tmp_path / "nope.yaml")}})
        r = b.profiles.apply("缺文件")
        assert r["ok"] is True and "point_table" not in r["applied"]
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_restore_active_and_none(self, tmp_path: Path):
        b = _bridge(tmp_path)
        assert b.profiles.restore_active() is None
        b.profiles.save("甲", {"connection": {"host": "9.9.9.9"}})
        b.profiles.apply("甲")
        b.config.connection.host = "changed"
        out = b.profiles.restore_active()
        assert out is not None and b.config.connection.host == "9.9.9.9"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_save_without_config_captures_current(self, tmp_path: Path):
        b = _bridge(tmp_path)
        b.config.connection.host = "1.2.3.4"
        b.profiles.save("快照")
        assert b.profiles.get("快照")["config"]["connection"]["host"] == "1.2.3.4"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_export_import_roundtrip(self, tmp_path: Path):
        b = _bridge(tmp_path)
        b.profiles.save("源", {"mode": "slave", "connection": {"host": "h1", "port": 2404}})
        text, ctype, suffix = b.profiles.export("源")
        assert suffix == "yaml" and "h1" in text
        b.profiles.import_yaml("副本", text)
        assert b.profiles.get("副本")["config"]["connection"]["host"] == "h1"
        await b.shutdown()

    def test_profile_yaml_is_valid_appconfig(self, tmp_path: Path):
        """旧版 `--config` 单文件仍可直接启动：方案文件本身能被 load_config 读."""
        st = ProfileStore(tmp_path / "p")
        st.save("兼容", {
            "mode": "master",
            "connection": {"host": "10.0.0.9", "port": 2407, "common_addr": 3},
            "timers": {"t0": 30.0, "t1": 15.0, "t2": 10.0, "t3": 20.0},
            "flow_control": {"k": 12, "w": 8},
            "asdu_address": {"ca_length": 2, "ioa_length": 3, "cot_length": 2},
        })
        cfg = load_config(st.path_of("兼容"))
        assert cfg.connection.host == "10.0.0.9"
        assert cfg.connection.port == 2407
        assert cfg.connection.common_addr == 3
        assert cfg.asdu_address.ca_length == 2


# ── API ──────────────────────────────────────────────────────────────


class TestApi:
    async def _client(self, tmp_path: Path, **kw):
        b = _bridge(tmp_path, role=kw.pop("role", "master"))
        return b, TestClient(TestServer(create_app(b, **kw)))

    @pytest.mark.asyncio
    async def test_full_flow(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            # 空列表
            body = await (await c.get("/api/profiles")).json()
            assert body["profiles"] == [] and body["active"] == ""

            # 保存当前（capture）
            r = await c.post("/api/profiles/甲站", json={})
            assert (await r.json())["ok"] is True

            # 列表可见且带摘要
            body = await (await c.get("/api/profiles")).json()
            assert [p["name"] for p in body["profiles"]] == ["甲站"]
            assert body["profiles"][0]["summary"]["mode"] == "master"

            # 详情
            detail = await (await c.get("/api/profiles/甲站")).json()
            assert detail["ok"] is True and "connection" in detail["config"]

            # 应用 → 成为活动方案
            r = await c.post("/api/profiles/甲站/apply")
            applied = await r.json()
            assert applied["ok"] is True and "connection" in applied["applied"]
            assert (await (await c.get("/api/profiles")).json())["active"] == "甲站"

            # restore 返回同一方案
            r = await c.post("/api/profiles/restore")
            assert (await r.json())["ok"] is True

            # 导出 / 导入
            r = await c.get("/api/profiles/甲站/export")
            assert r.status == 200 and "yaml" in r.content_type
            text = await r.text()
            r = await c.post("/api/profiles/import?name=副本", data=text)
            assert (await r.json())["ok"] is True
            assert (await (await c.get("/api/profiles/副本")).json())["ok"] is True

            # 删除
            r = await c.delete("/api/profiles/甲站")
            assert (await r.json())["ok"] is True
            assert (await (await c.get("/api/profiles/甲站")).json())["ok"] is False
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_errors(self, tmp_path: Path):
        b, client = await self._client(tmp_path)
        async with client as c:
            assert (await c.get("/api/profiles/ghost")).status == 404
            assert (await c.post("/api/profiles/ghost/apply")).status == 404
            assert (await c.get("/api/profiles/ghost/export")).status == 404
            assert (await c.post("/api/profiles/bad%2Fname", json={})).status == 400
            assert (await c.post("/api/profiles/ok", json={"config": []})).status == 400
            r = await c.post("/api/profiles/import?name=坏", data="not: [valid")
            assert r.status == 400
            # 无活动方案时 restore 返回 ok=false（不是错误）
            r = await c.post("/api/profiles/restore")
            assert (await r.json())["ok"] is False
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_operator_write_denied_but_read_allowed(self, tmp_path: Path):
        """三角色矩阵（§2.4d）：方案是管理动作 → operator 只读；viewer 只读."""
        from webui.audit import OperatorRegistry

        users = tmp_path / "users.yaml"
        users.write_text(
            "users:\n"
            "  - name: 管理员\n    token: a\n    role: admin\n"
            "  - name: 操作员\n    token: o\n    role: operator\n",
            encoding="utf-8")
        b, client = await self._client(
            tmp_path, operators=OperatorRegistry.from_yaml(str(users)))
        async with client as c:
            h = {"X-Auth-Token": "o"}
            assert (await c.get("/api/profiles", headers=h)).status == 200
            assert (await c.post("/api/profiles/x", json={}, headers=h)).status == 403
            assert (await c.delete("/api/profiles/x", headers=h)).status == 403
            ha = {"X-Auth-Token": "a"}
            assert (await c.post("/api/profiles/x", json={}, headers=ha)).status == 200
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_audit_records_profile_changes(self, tmp_path: Path):
        from webui.audit import Identity, set_operator_context

        b, client = await self._client(tmp_path)
        set_operator_context(Identity(name="检修张", role="admin"))
        try:
            async with client as c:
                await c.post("/api/profiles/甲", json={})
                await c.post("/api/profiles/甲/apply")
                await c.delete("/api/profiles/甲")
        finally:
            set_operator_context(None)
        actions = [r["action"] for r in b.audit.list_records(limit=10)]
        assert actions == ["profiles/delete", "profiles/apply", "profiles/save"]
        row = b.audit.list_records(limit=10)[-1]
        assert row["operator"] == "检修张" and row["target"] == "甲"
        await b.shutdown()

    @pytest.mark.asyncio
    async def test_no_profiles_dir_is_not_an_error(self, tmp_path: Path):
        """未配置任何方案：列表为空且不报错（默认零影响）."""
        b = _bridge(tmp_path)
        b.profiles.store = ProfileStore(tmp_path / "never-created")
        async with TestClient(TestServer(create_app(b))) as c:
            body = await (await c.get("/api/profiles")).json()
            assert body == {"ok": True, "profiles": [], "active": ""}
        await b.shutdown()


class TestCliProfileOverlay:
    """``--profile``：方案文件叠加到 --config（工程参数生效，显示/TLS 不动）."""

    def test_overlay_sections(self, tmp_path: Path):
        from core.config import AppConfig, apply_profile

        prof = tmp_path / "p.yaml"
        prof.write_text(yaml.dump({
            "mode": "slave",
            "connection": {"host": "10.9.9.9", "port": 2409, "common_addr": 9},
            "timers": {"t0": 31.0, "t1": 16.0, "t2": 11.0, "t3": 21.0},
            "flow_control": {"k": 7, "w": 5},
            "asdu_address": {"ca_length": 1, "ioa_length": 3, "cot_length": 2},
            "point_table": {"file": "configs/demo_points.yaml"},
            "display": {"theme": "light"},
            "tls": {"enabled": True, "certfile": "/secret.pem"},
        }), encoding="utf-8")

        cfg = AppConfig()
        cfg.display.theme = "dark"
        cfg.tls.enabled = False
        applied = apply_profile(cfg, prof)

        assert cfg.connection.host == "10.9.9.9"
        assert cfg.timers.t1 == 16.0 and cfg.flow_control.k == 7
        assert cfg.asdu_address.ca_length == 1 and cfg.asdu_address.ioa_length == 3
        assert cfg.point_table.file == "configs/demo_points.yaml"
        # 显示偏好与 TLS 不被方案覆盖（避免方案悄悄改证书/主题）
        assert cfg.display.theme == "dark"
        assert cfg.tls.enabled is False
        assert "display" not in applied and "tls" not in applied

    def test_missing_profile_raises(self, tmp_path: Path):
        from core.config import AppConfig, apply_profile

        with pytest.raises(FileNotFoundError):
            apply_profile(AppConfig(), tmp_path / "nope.yaml")


def test_shipped_profile_dir_is_valid():
    """仓库内 configs/profiles 下的方案（若有）必须能被 parse 出来."""
    root = Path("configs/profiles")
    if not root.is_dir():
        pytest.skip("尚无随仓方案目录")
    st = ProfileStore(root)
    for info in st.list_profiles():
        data = st.load(info.name)
        assert isinstance(data, dict)
        assert yaml.safe_dump(data)
