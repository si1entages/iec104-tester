"""`core/engine/multi_station.py` 单元测试.

用假 SlaveEngine（不建真监听）覆盖：TLS 配置归一化、start_all 成功/逐站 TLS
失败/其他异常回滚、stop_all 回收兜底（stop 失败、监听器关闭、回调解绑）、
状态/汇总/模拟/事件聚合。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.config import TlsConfig
from core.engine.multi_station import (
    MultiStationConfig,
    MultiStationManager,
    StationConfig,
    _coerce_tls_config,
)
from core.transport.connection import TlsConfigError


class _FakeSlaveEngine:
    """假子站引擎：记录启动/停止/模拟调用，可注入启动/停止失败."""

    instances: list[_FakeSlaveEngine] = []
    fail_ports: set[int] = set()
    fail_stop = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_running = False
        self.client_count = 0
        self.data_store = types.SimpleNamespace(stats={
            "yx_count": 10, "yc_count": 5, "yk_count": 2, "ym_count": 1})
        self._server = types.SimpleNamespace(is_running=False, stop=AsyncMock())
        self.aclose_background_tasks = AsyncMock()
        self.start_simulation = AsyncMock()
        self.stop_simulation = AsyncMock()
        self.event_callback = None
        self.started = False
        self.stopped = False
        _FakeSlaveEngine.instances.append(self)

    def set_event_callback(self, callback):
        self.event_callback = callback

    async def start(self):
        if self.kwargs.get("port") in _FakeSlaveEngine.fail_ports:
            raise RuntimeError("port busy")
        self.started = True
        self.is_running = True

    async def stop(self):
        if _FakeSlaveEngine.fail_stop:
            raise RuntimeError("stop failed")
        self.stopped = True
        self.is_running = False


@pytest.fixture(autouse=True)
def _isolate_fake(monkeypatch):
    _FakeSlaveEngine.instances = []
    _FakeSlaveEngine.fail_ports = set()
    _FakeSlaveEngine.fail_stop = False
    monkeypatch.setattr("core.engine.multi_station.SlaveEngine", _FakeSlaveEngine)
    yield


def _station(station_id: str, port: int, **over) -> StationConfig:
    return StationConfig(
        station_id=station_id, port=port,
        yx_count=2, yc_count=2, yk_count=1, ym_count=1,
        **over,
    )


def _manager(*stations: StationConfig) -> MultiStationManager:
    return MultiStationManager(MultiStationConfig(stations=list(stations)))


# ── 配置归一化 ───────────────────────────────────────────────────────────


def test_coerce_tls_config_forms():
    assert _coerce_tls_config(None) is None

    cfg = TlsConfig(enabled=True, certfile="a.pem")
    assert _coerce_tls_config(cfg) is cfg

    from_dict = _coerce_tls_config({"enabled": True, "certfile": "b.pem",
                                    "unknown": 1})
    assert isinstance(from_dict, TlsConfig)
    assert from_dict.certfile == "b.pem"

    with pytest.raises(TypeError):
        _coerce_tls_config("not-a-config")


# ── start_all / stop_all ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_all_success_and_status():
    manager = _manager(
        _station("s1", 24001),
        _station("s2", 24002, simulation_enabled=True),
    )
    await manager.start_all()

    assert manager.is_running is True
    assert manager.station_count == 2
    assert manager.total_client_count == 0
    assert manager.uptime >= 0

    status = manager.get_station_status("s1")
    assert status is not None
    assert status.running is True
    assert status.yx_count == 10 and status.yc_count == 5
    assert status.tls_enabled is False

    assert manager.get_station_status("missing") is None
    assert len(manager.get_all_station_status()) == 2

    summary = manager.get_summary()
    assert summary["station_count"] == 2
    assert summary["total_yx"] == 20
    assert {s["id"] for s in summary["stations"]} == {"s1", "s2"}

    # simulation_enabled 的站启动时开启模拟
    simulated = [e for e in _FakeSlaveEngine.instances
                 if e.kwargs.get("port") == 24002][0]
    simulated.start_simulation.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_all_twice_is_noop():
    manager = _manager(_station("s1", 24001))
    await manager.start_all()
    await manager.start_all()          # 已在运行：仅告警返回
    assert manager.station_count == 1


@pytest.mark.asyncio
async def test_start_all_tls_error_skips_station(monkeypatch):
    def bad_tls(_cfg, _role):
        raise TlsConfigError("bad certificate")

    monkeypatch.setattr("core.engine.multi_station.build_context_from_config", bad_tls)

    manager = _manager(
        _station("tls-bad", 24001, tls=TlsConfig(enabled=True)),
        _station("ok", 24002),
    )
    await manager.start_all()

    assert manager.is_running is True
    assert manager.station_count == 1
    assert "tls-bad" in manager.start_errors
    assert "TLS 配置无效" in manager.start_errors["tls-bad"]
    # start_errors 返回副本
    snapshot = manager.start_errors
    snapshot.clear()
    assert manager.start_errors


@pytest.mark.asyncio
async def test_start_all_generic_error_rolls_back(monkeypatch):
    _FakeSlaveEngine.fail_ports = {24002}
    manager = _manager(_station("ok", 24001), _station("busy", 24002))

    with pytest.raises(RuntimeError, match="port busy"):
        await manager.start_all()

    assert manager.is_running is False
    assert manager.station_count == 0
    first = _FakeSlaveEngine.instances[0]
    assert first.stopped is True


@pytest.mark.asyncio
async def test_stop_all_reaps_engines_and_listener():
    manager = _manager(_station("s1", 24001))
    await manager.start_all()
    engine = manager.get_engine("s1")
    engine._server.is_running = True

    await manager.stop_all()

    assert engine.stopped is True
    engine.aclose_background_tasks.assert_awaited_once()
    engine._server.stop.assert_awaited_once()
    assert engine.event_callback is None
    assert manager.station_count == 0
    assert manager.is_running is False
    assert manager.get_station_status("s1") is None

    await manager.stop_all()           # 幂等：无引擎且未运行直接返回


@pytest.mark.asyncio
async def test_stop_all_swallows_stop_and_reap_errors():
    manager = _manager(_station("s1", 24001))
    await manager.start_all()
    engine = manager.get_engine("s1")
    _FakeSlaveEngine.fail_stop = True
    engine.aclose_background_tasks = AsyncMock(side_effect=RuntimeError("reap"))
    engine._server.is_running = True
    engine._server.stop = AsyncMock(side_effect=RuntimeError("close"))

    await manager.stop_all()           # 全部异常被吞掉

    assert manager.station_count == 0
    assert manager.is_running is False


@pytest.mark.asyncio
async def test_stop_all_when_only_running_flag():
    manager = _manager()
    manager._running = True            # 无引擎但标记运行中：也要走回收复位
    await manager.stop_all()
    assert manager.is_running is False


@pytest.mark.asyncio
async def test_close_station_listener_branches():
    await MultiStationManager._close_station_listener(types.SimpleNamespace())

    server = types.SimpleNamespace(is_running=False, stop=AsyncMock())
    await MultiStationManager._close_station_listener(
        types.SimpleNamespace(_server=server))
    server.stop.assert_not_awaited()

    server = types.SimpleNamespace(is_running=True, stop=AsyncMock(
        side_effect=RuntimeError("close")))
    await MultiStationManager._close_station_listener(
        types.SimpleNamespace(_server=server))


def test_detach_station_callback_branches():
    MultiStationManager._detach_station_callback(types.SimpleNamespace())

    def raising_setter(_callback):
        raise RuntimeError("setter")

    MultiStationManager._detach_station_callback(
        types.SimpleNamespace(set_event_callback=raising_setter))


# ── 模拟控制 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_and_stop_simulation_paths():
    manager = _manager(_station("s1", 24001), _station("s2", 24002))
    await manager.start_all()
    s1 = manager.get_engine("s1")

    await manager.start_simulation("s1")
    s1.start_simulation.assert_awaited_once()
    await manager.start_simulation("missing")      # 未知站：忽略
    await manager.start_simulation()               # 全部站
    s1.start_simulation.assert_awaited()

    await manager.stop_simulation("s1")
    s1.stop_simulation.assert_awaited_once()
    await manager.stop_simulation("missing")       # 未知站：忽略
    await manager.stop_simulation()                # 全部站

    # 配置缺失时跳过（模拟"引擎在但配置丢失"的异常态）
    manager._station_configs.clear()
    await manager.start_simulation()


# ── 事件聚合 ─────────────────────────────────────────────────────────────


def test_on_station_event_aggregates_and_swallows_errors():
    manager = _manager()
    received = []
    manager.set_event_callback(lambda event, data: received.append((event, dict(data))))

    manager._on_station_event("s1", "connected", {"x": 1})
    assert received == [("connected", {"x": 1, "station_id": "s1"})]

    def boom(_event, _data):
        raise RuntimeError("callback")

    manager.set_event_callback(boom)
    manager._on_station_event("s1", "connected", {})   # 异常被吞掉

    manager.set_event_callback(None)
    manager._on_station_event("s1", "connected", {})   # 无全局回调也不报错
