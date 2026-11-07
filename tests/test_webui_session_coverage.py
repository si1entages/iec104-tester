"""WebUI 会话命令分发与报文翻译覆盖率补齐（D1）.

不启动真实引擎：用记录型假引擎覆盖 EngineSession 的命令分支、状态字段、
多站生命周期、网络模拟安装/卸载；报文翻译直接覆盖边界输入。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.config import AppConfig
from core.protocol.types import COT, CP56Time2a, TypeID
from webui import frame_translate as ft
from webui.session import EngineSession, response_behavior_to_dict

# ── 假引擎 ───────────────────────────────────────────────────────


class _RecorderEngine:
    """任意 ``await engine.method(...)`` 都记录到 calls；显式属性模拟状态."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.state = "running"
        self.is_running = True
        self.client_count = 2
        self.client_list = ["c1", "c2"]
        self.connection_stats = SimpleNamespace(frames_sent=3, frames_received=4)
        self.sequence_manager = SimpleNamespace(
            send_seq=5, recv_seq=6, unconfirmed_count=1, k=12)
        self.response_behavior = None
        self.data_store = SimpleNamespace(
            update_yc=lambda ioa, value: self.calls.append(("update_yc", ioa, value)))
        self._send_frame = lambda data: None
        self._client = SimpleNamespace(_on_frame=lambda frame: None)
        self._server = SimpleNamespace(_on_frame=lambda frame: None)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def fn(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return fn

    def set_response_behavior(self, cfg) -> None:
        self.calls.append(("set_response_behavior", cfg))


def _session(role: str = "master") -> EngineSession:
    return EngineSession(role, AppConfig(), lambda *a: None, lambda *a: None)


# ── 主站命令分发 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_master_command_dispatch():
    s = _session("master")
    eng = _RecorderEngine()
    s.engine = eng

    assert await s.general_interrogation(21) == {"ok": True}
    assert eng.calls[-1][0] == "general_interrogation"
    await s.counter_interrogation()
    await s.clock_sync()
    await s.reset_process()
    await s.test_command()
    await s.read_command(7)
    await s.send_step_command(1, 2, True)
    await s.send_bitstring(1, 0x1234)
    await s.send_delay_request(500)
    assert eng.calls[-3][0] == "regulating_step_command"
    assert eng.calls[-2][0] == "bitstring_command"
    assert eng.calls[-1][0] == "delay_command"


@pytest.mark.asyncio
async def test_yk_variants():
    s = _session()
    eng = _RecorderEngine()
    s.engine = eng
    await s.send_yk(1, 1)
    await s.send_yk(1, 1, with_time=True)
    await s.send_yk(1, 1, double=True)
    await s.send_yk(1, 1, double=True, with_time=True, deactivate=True)
    names = [c[0] for c in eng.calls]
    assert names == [
        "single_command", "single_command_with_time",
        "double_command", "double_command_with_time",
    ]


@pytest.mark.asyncio
async def test_setpoint_variants():
    s = _session()
    eng = _RecorderEngine()
    s.engine = eng
    for kind in ("short_float", "normalized", "scaled", "na", "nb"):
        await s.send_setpoint(1, 2.5, kind=kind)
        await s.send_setpoint(1, 2.5, kind=kind, with_time=True)
    names = [c[0] for c in eng.calls]
    assert names == [
        "setpoint_shortfloat", "setpoint_shortfloat_with_time",
        "setpoint_normalized", "setpoint_normalized_with_time",
        "setpoint_scaled", "setpoint_scaled_with_time",
        "setpoint_normalized", "setpoint_normalized_with_time",
        "setpoint_scaled", "setpoint_scaled_with_time",
    ]


@pytest.mark.asyncio
async def test_parameter_and_file_dispatch():
    s = _session()
    eng = _RecorderEngine()
    s.engine = eng
    for kind in ("normalized", "scaled", "float", "activation", "na", "nb", "nc", "act"):
        assert (await s.parameter_command(kind, 1, 1.0))["ok"] is True
    assert (await s.parameter_command("bad", 1, 1.0))["ok"] is False
    for action in ("directory", "dir", "select", "request", "call"):
        assert (await s.file_action(action, 1, 2))["ok"] is True
    assert (await s.file_action("bad"))["ok"] is False


def test_status_fields_with_and_without_engine():
    s = _session("master")
    st = s.status_fields()
    assert st == {"started": False, "running": False}

    s.engine = _RecorderEngine()
    st = s.status_fields()
    assert st["started"] is True and st["running"] is True
    assert st["state"] == "running"
    assert st["tx"] == 3 and st["rx"] == 4
    assert st["vs"] == 5 and st["vr"] == 6
    assert st["window"] == "1/12"

    s.engine = _RecorderEngine()
    s.engine.connection_stats = None
    s.engine.sequence_manager = None
    st = s.status_fields()
    assert "tx" not in st and "vs" not in st


@pytest.mark.asyncio
async def test_start_master_already_running():
    s = _session()
    s.engine = _RecorderEngine()
    assert await s.start_master("127.0.0.1", 2404, 1, True, None) == {
        "ok": False, "error": "already running"}


@pytest.mark.asyncio
async def test_reap_engine_paths(caplog):
    class BadScheduler:
        is_running = True

        async def stop(self):
            raise RuntimeError("scheduler boom")

    class BadBackground(_RecorderEngine):
        async def aclose_background_tasks(self):
            raise RuntimeError("tasks boom")

    s = _session()
    good = _RecorderEngine()
    good._scheduler = SimpleNamespace(is_running=False, stop=None)
    await s._reap_engine(good)

    bad = BadBackground()
    bad._scheduler = BadScheduler()
    await s._reap_engine(bad)
    assert "scheduler stop" in caplog.text

    class BadReap(_RecorderEngine):
        _scheduler = None
        async def aclose_background_tasks(self):
            raise RuntimeError("tasks boom")

    await s._reap_engine(BadReap())
    assert "background task reap" in caplog.text


# ── 多站 ─────────────────────────────────────────────────────────


class _FakeMulti:
    behavior = "ok"
    instances: list[_FakeMulti] = []

    def __init__(self, cfg):
        self.cfg = cfg
        self.start_errors: dict[str, str] = {}
        self.station_count = 2
        self.stopped = False
        self.is_running = True
        _FakeMulti.instances.append(self)

    async def start_all(self):
        if self.behavior == "raise":
            raise RuntimeError("start boom")
        if self.behavior == "zero":
            self.station_count = 0
            self.start_errors = {"s1": "tls invalid"}
        if self.behavior == "cancel":
            raise __import__("asyncio").CancelledError()

    async def stop_all(self):
        self.stopped = True
        if self.behavior == "stop_raise":
            raise RuntimeError("stop boom")

    def get_all_station_status(self):
        return []


@pytest.fixture
def fake_multi(monkeypatch):
    import webui.session as session_mod

    _FakeMulti.instances = []
    monkeypatch.setattr(session_mod, "MultiStationManager", _FakeMulti)
    return _FakeMulti


@pytest.mark.asyncio
async def test_multi_start_validation(fake_multi):
    s = _session("slave")
    assert (await s.multi_start([]))["ok"] is False
    assert (await s.multi_start([{"station_id": "a"}, {"station_id": "a"}]))["ok"] is False
    assert (await s.multi_start([{"station_id": "a", "nope": 1}]))["ok"] is False


@pytest.mark.asyncio
async def test_multi_start_success_and_status(fake_multi):
    s = _session("slave")
    fake_multi.behavior = "ok"
    assert (await s.multi_start([{"station_id": "a", "port": 0}]))["ok"] is True
    assert s.multi_station is not None
    st = s.multi_status()
    assert st["ok"] is True and st["running"] is True
    assert st["failed"] == []
    assert (await s.multi_stop())["ok"] is True


@pytest.mark.asyncio
async def test_multi_start_failure_paths(fake_multi):
    s = _session("slave")
    fake_multi.behavior = "raise"
    assert (await s.multi_start([{"station_id": "a"}]))["ok"] is False

    fake_multi.behavior = "zero"
    r = await s.multi_start([{"station_id": "a"}])
    assert r["ok"] is False and r["failed"][0]["station_id"] == "s1"

    s = _session("slave")
    fake_multi.behavior = "cancel"
    with pytest.raises(__import__("asyncio").CancelledError):
        await s.multi_start([{"station_id": "a"}])


@pytest.mark.asyncio
async def test_multi_stop_and_shutdown_errors(fake_multi, caplog):
    s = _session("slave")
    assert (await s.multi_stop())["ok"] is True

    fake_multi.behavior = "ok"
    await s.multi_start([{"station_id": "a"}])
    fake_multi.behavior = "stop_raise"
    r = await s.multi_stop()
    assert r["ok"] is False and "stop boom" in r["error"]

    await s.multi_start([{"station_id": "a"}])
    fake_multi.behavior = "stop_raise"
    await s._shutdown_multi_station()
    assert "multi-station shutdown" in caplog.text


# ── 网络异常模拟 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_network_simulation_validation():
    s = _session()
    assert (await s.set_network_simulation(True, preset="nope"))["ok"] is False
    assert (await s.set_network_simulation(True, condition=[]) )["ok"] is False
    bad_conditions = [
        {"nope": 1},
        {"direction": "sideways"},
        {"active": 1},
        {"loss_rate": True},
        {"loss_rate": 2},
        {"delay_ms": "x"},
        {"delay_ms": -1},
        {"corrupt_bits": 0},
        {"corrupt_bits": True},
        {"corrupt_bits": 1.5},
    ]
    for cond in bad_conditions:
        r = await s.set_network_simulation(True, condition=cond)
        assert r["ok"] is False, cond
    assert (await s.set_network_simulation(True, condition={"loss_rate": 0.5}))["ok"] is True
    assert s.network_simulation_status()["enabled"] is True


@pytest.mark.asyncio
async def test_network_simulation_install_remove():
    s = _session()
    eng = _RecorderEngine()
    s.engine = eng
    s._net_sim_enabled = True
    s._install_network_simulation(eng)
    assert s.network_simulation_status()["installed"] is True

    assert s.network_simulation_disconnect(0)["ok"] is False
    assert s.network_simulation_disconnect(601)["ok"] is False
    assert s.network_simulation_disconnect(1)["ok"] is True

    s._remove_network_simulation()
    assert s.network_simulation_status()["installed"] is False
    # 未安装时断开请求明确失败
    assert s.network_simulation_disconnect(1)["ok"] is False


@pytest.mark.asyncio
async def test_set_network_simulation_installs_when_engine_present():
    s = _session()
    eng = _RecorderEngine()
    s.engine = eng
    r = await s.set_network_simulation(True, condition={"active": True})
    assert r["ok"] is True
    assert s.network_simulation_status()["installed"] is True
    assert s.reset_network_simulation_stats()["ok"] is True


# ── 子站 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slave_setters_and_response():
    s = _session("slave")
    eng = _RecorderEngine()
    s.engine = eng
    assert (await s.slave_set_yx(1, True))["ok"] is True
    assert (await s.slave_set_yc(2, 3.5))["ok"] is True
    assert ("send_spontaneous_yx", (1, True), {}) in eng.calls
    assert ("update_yc", 2, 3.5) in eng.calls
    assert (await s.slave_set_ym(3, 4))["ok"] is True
    assert (await s.slave_set_step(4, 5))["ok"] is True
    assert (await s.slave_protection_event(5, 1))["ok"] is True
    assert (await s.slave_group_single_point(6, [1, 0]))["ok"] is True
    assert (await s.slave_group_single_point(6, []))["ok"] is False

    assert (await s.set_response({"delays": {"gi": 1}}))["ok"] is True
    assert ("set_response_behavior", {"delays": {"gi": 1}}) in eng.calls
    assert s.get_response()["ok"] is True

    assert (await s.stop_slave())["ok"] is True
    assert s.engine is None


@pytest.mark.asyncio
async def test_slave_methods_require_engine():
    s = _session("slave")
    with pytest.raises(RuntimeError):
        await s.slave_set_yx(1, True)
    with pytest.raises(RuntimeError):
        s.require_slave()


@pytest.mark.asyncio
async def test_simulation_scope_validation():
    s = _session("slave")
    s.engine = _RecorderEngine()
    assert (await s.set_simulation(True, yx_scope="bad"))["ok"] is False
    assert (await s.set_simulation(True, yx_scope="selected"))["ok"] is False
    assert (await s.set_simulation(
        True, yx_scope="selected", yx_ioas=[1],
        yc_scope="selected", yc_ioas=[2]))["ok"] is True
    assert (await s.set_simulation(False))["ok"] is True


# ── 序列化 ───────────────────────────────────────────────────────


def test_response_behavior_to_dict_none():
    assert response_behavior_to_dict(None) == {}


def test_response_behavior_roundtrip():
    from core.engine.slave_response import ResponseBehavior

    rb = ResponseBehavior.from_dict({"delays": {"gi": 1.5}})
    d = response_behavior_to_dict(rb)
    assert d["delays"]["gi"] == 1.5
    assert set(d) == {"delays", "errors", "quality", "connection"}


# ── 报文翻译 ─────────────────────────────────────────────────────


def test_translate_hex_invalid_and_short():
    assert ft.translate_hex("zz")["ok"] is False
    assert ft.translate_hex("6804")["ok"] is False


def test_translate_hex_s_and_u_frames():
    s = ft.translate_hex("680401000000")
    assert s["ok"] is True and s["format"] == "S"
    u = ft.translate_hex("680443000000")
    assert u["format"] == "U"
    unknown_u = ft.translate_hex("680447000000")
    assert "0x47" in unknown_u["segments"][0]["lines"][-1]


def test_translate_hex_i_frame_variants():
    # 无 ASDU 的 I 帧
    empty = ft.translate_hex("680400000000")
    assert empty["format"] == "I"
    assert "I 帧无 ASDU" in empty["segments"][1]["lines"][0]

    # 合法 GI 帧（C_IC_NA_1, COT=6, QOI=20）
    gi = ft.translate_hex("680e0400030064010600010000000014")
    assert gi["ok"] is True and gi["format"] == "I"
    assert any("QOI=20" in line for seg in gi["segments"] for line in seg["lines"])

    # ASDU 解析失败 → 降级为错误段但不抛异常
    broken = ft.translate_hex("68050400000064")
    assert broken["ok"] is True
    assert any("ASDU 解析失败" in line for seg in broken["segments"] for line in seg["lines"])


def test_cot_and_type_names():
    assert "第 5 组召唤" in ft._cot_name(25, False, False)
    assert "第 3 组累计量召唤" in ft._cot_name(40, False, False)
    assert ft._cot_name(100, False, False) == "COT 100"
    assert "测试位" in ft._cot_name(6, True, True)
    assert "否定确认" in ft._cot_name(6, True, False)
    assert ft._type_name(999) == "未知类型 TypeID 999"
    assert ft._type_name(int(TypeID.C_IC_NA_1)).startswith("C_IC_NA_1")


def test_display_value_variants():
    assert "站召唤" in ft._display_value(int(TypeID.C_IC_NA_1), b"\x14")
    assert "第 5 组召唤" in ft._display_value(int(TypeID.C_IC_NA_1), b"\x19")
    assert ft._display_value(int(TypeID.C_IC_NA_1), b"\x63").startswith("QOI=99")
    ts = CP56Time2a(millisecond=0, minute=30, hour=12, day=7, month=11, year=26)
    assert "时间=" in ft._display_value(int(TypeID.C_CS_NA_1), ts.to_bytes())
    assert ft._display_value(int(TypeID.C_CS_NA_1), b"\x00") == "00"
    assert ft._display_value(int(TypeID.C_IC_NA_1), 5) == "5"


def test_cot_enum_fallback():
    # COT(6) 在 COT_ZH 中；用枚举名兜底的分支
    assert ft._cot_name(int(COT.ACT), False, False) == "激活"
