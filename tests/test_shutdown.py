"""关停路径与资源回收回归测试 (T07).

覆盖:
- ``EngineBase.aclose_background_tasks``：取消并回收残留后台任务（幂等）
- 引擎关停耗时可断言（历史缺陷：对端断开未关 transport → 3.13 下 stop() 固定阻塞 2s）
- 关停后无 pending task 告警、无任务泄漏（``asyncio.all_tasks``）
- ``MultiStationManager.stop_all()``：释放端口、回收引擎、幂等、回滚场景可回收
- Web 桥接 ``shutdown()``：清空订阅队列、断开日志桥接、回收已登记的多站管理器
"""

import asyncio
import gc
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.engine.base import EngineBase
from core.engine.multi_station import (
    MultiStationConfig,
    MultiStationManager,
    StationConfig,
)
from core.engine.slave import SlaveEngine

LOOP_TASK_NAME = "t07_idle_forever"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def idle_forever() -> None:
    """长驻空转协程，用于制造 pending 后台任务。"""
    await asyncio.sleep(60)


# ── EngineBase 后台任务回收 ──────────────────────────────────────

class _DummyEngine(EngineBase):
    pass


class TestBackgroundTaskReap:
    @pytest.mark.asyncio
    async def test_reap_cancels_all_pending(self):
        eng = _DummyEngine()
        eng._spawn(idle_forever())
        eng._spawn(idle_forever())
        assert len(eng._background_tasks) == 2

        n = await eng.aclose_background_tasks(timeout=1.0)
        assert n == 2
        assert eng._background_tasks == set()

    @pytest.mark.asyncio
    async def test_reap_is_idempotent(self):
        eng = _DummyEngine()
        eng._spawn(idle_forever())
        await eng.aclose_background_tasks(timeout=1.0)
        assert await eng.aclose_background_tasks(timeout=1.0) == 0
        assert eng._background_tasks == set()

    @pytest.mark.asyncio
    async def test_reap_ignores_finished_tasks(self):
        eng = _DummyEngine()

        async def quick():
            return 1

        eng._spawn(quick())
        await asyncio.sleep(0.05)
        # 完成的任务已被 done_callback 移除；回收应为 0
        assert await eng.aclose_background_tasks(timeout=1.0) == 0


# ── 引擎关停：耗时 + 无 pending 告警 ──────────────────────────────

class TestEngineShutdown:
    @pytest.mark.asyncio
    async def test_slave_stop_fast_with_active_client(self):
        """对端在线时子站 stop() 必须立即返回（< 1.0s）。"""
        port = _free_port()
        eng = SlaveEngine(host="127.0.0.1", port=port, common_addr=1)
        await eng.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            assert await _wait_until(lambda: eng.client_count > 0)

            start = asyncio.get_running_loop().time()
            await asyncio.wait_for(eng.stop(), timeout=10)
            elapsed = asyncio.get_running_loop().time() - start
            assert elapsed < 1.0, f"stop() took {elapsed:.3f}s"
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_no_pending_task_after_shutdown(self):
        """关停并回收后不得残留 pending 任务（无 "Task was destroyed" 告警）。"""
        loop = asyncio.get_running_loop()
        messages: list[str] = []
        prev = loop.get_exception_handler()
        loop.set_exception_handler(
            lambda _l, ctx: messages.append(str(ctx.get("message", ctx)))
        )
        try:
            port = _free_port()
            eng = SlaveEngine(host="127.0.0.1", port=port, common_addr=1)
            await eng.start()
            # 制造关停瞬间仍 pending 的短驻任务
            for _ in range(3):
                eng._spawn(idle_forever())

            await asyncio.wait_for(eng.stop(), timeout=10)
            await eng.aclose_background_tasks(timeout=1.0)

            assert eng._background_tasks == set()
            del eng
            gc.collect()
            await asyncio.sleep(0.05)

            pending = [
                t for t in asyncio.all_tasks()
                if t is not asyncio.current_task() and not t.done()
                and idle_forever.__name__ in getattr(t.get_coro(), "__qualname__", "")
            ]
            assert pending == [], f"leaked tasks: {pending}"
            assert not any("pending" in m.lower() for m in messages), messages
        finally:
            loop.set_exception_handler(prev)


# ── 多站显式回收 ─────────────────────────────────────────────────

def _two_station_config(ports: list[int]) -> MultiStationConfig:
    return MultiStationConfig(stations=[
        StationConfig(station_id="a", host="127.0.0.1", port=ports[0],
                      common_addr=1, auto_generate=True, yx_count=3, yc_count=2),
        StationConfig(station_id="b", host="127.0.0.1", port=ports[1],
                      common_addr=2, auto_generate=True, yx_count=3, yc_count=2),
    ])


class TestMultiStationReclaim:
    @pytest.mark.asyncio
    async def test_stop_all_releases_ports_and_engines(self):
        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        await mgr.start_all()
        assert mgr.station_count == 2
        assert mgr.is_running is True

        await mgr.stop_all()
        assert mgr.station_count == 0
        assert mgr.is_running is False

        # 端口已释放：可重新绑定
        for p in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", p))
            finally:
                s.close()

    @pytest.mark.asyncio
    async def test_stop_all_idempotent(self):
        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        await mgr.start_all()
        await mgr.stop_all()
        await mgr.stop_all()  # 二次调用不应抛错
        assert mgr.station_count == 0
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_stop_all_reclaims_partial_start(self):
        """模拟 start_all 回滚：_running 仍为 False 但已有引擎，也必须回收。"""
        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        # 只手动启动一个站，不置 _running（等价于 start_all 中途失败）
        await mgr._start_station(mgr._config.stations[0])
        assert mgr.station_count == 1
        assert mgr.is_running is False

        await mgr.stop_all()
        assert mgr.station_count == 0
        # 端口释放
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", ports[0]))
        finally:
            s.close()

    @pytest.mark.asyncio
    async def test_stop_all_releases_listener_when_engine_stop_raises(self):
        """单站 stop() 抛错时，其余站仍回收，失败站监听端口也不泄漏。"""
        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        await mgr.start_all()
        bad = mgr.get_engine("a")
        assert bad is not None

        async def boom():
            raise RuntimeError("engine stop failed")

        bad.stop = boom  # type: ignore[method-assign]
        await mgr.stop_all()

        assert mgr.station_count == 0
        assert mgr.is_running is False
        for p in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", p))
            finally:
                s.close()

    @pytest.mark.asyncio
    async def test_stop_all_concurrent_calls_stop_engine_once(self):
        """并发 stop_all（Web 关停 + /api/multi/stop）只回收同一引擎一次。"""
        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        await mgr.start_all()
        engine = mgr.get_engine("a")
        assert engine is not None
        calls = 0
        original_stop = engine.stop

        async def counting_stop():
            nonlocal calls
            calls += 1
            await original_stop()

        engine.stop = counting_stop  # type: ignore[method-assign]
        await asyncio.gather(mgr.stop_all(), mgr.stop_all())

        assert calls == 1
        assert mgr.station_count == 0
        assert mgr.is_running is False


# ── Web 桥接关停 ─────────────────────────────────────────────────

class TestBridgeShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_clears_subscribers_and_reclaims_multistation(self):
        from webui.bridge import EngineBridge

        bridge = EngineBridge(role="slave")
        q = bridge.subscribe()
        assert q in bridge.bus._subscribers

        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        await mgr.start_all()
        bridge.session.attach_multi_station(mgr)

        await bridge.shutdown()

        assert bridge.bus._subscribers == set()
        assert mgr.station_count == 0
        assert mgr.is_running is False
        # 二次关停幂等
        await bridge.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_reclaims_multistation_started_via_web_api(self):
        """走真实 Web 注册路径（multi_start）后关停，管理器与端口均被回收。"""
        from webui.bridge import EngineBridge

        bridge = EngineBridge(role="slave")
        ports = [_free_port(), _free_port()]
        result = await bridge.multi_start([
            {"station_id": "a", "host": "127.0.0.1", "port": ports[0],
             "common_addr": 1, "auto_generate": True, "yx_count": 3, "yc_count": 2},
            {"station_id": "b", "host": "127.0.0.1", "port": ports[1],
             "common_addr": 2, "auto_generate": True, "yx_count": 3, "yc_count": 2},
        ])
        assert result["ok"] is True
        mgr = bridge.session.multi_station
        assert mgr is not None
        assert mgr.station_count == 2

        await bridge.shutdown()

        assert bridge.session.multi_station is None
        assert mgr.station_count == 0
        assert mgr.is_running is False
        for p in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", p))
            finally:
                s.close()

    @pytest.mark.asyncio
    async def test_shutdown_reclaims_multistation_when_engine_stop_raises(self):
        """单站引擎关停抛错时，finally 兜底仍回收多站管理器。"""
        from webui.bridge import EngineBridge

        bridge = EngineBridge(role="slave")
        ports = [_free_port(), _free_port()]
        mgr = MultiStationManager(_two_station_config(ports))
        await mgr.start_all()
        bridge.session.attach_multi_station(mgr)

        async def boom():
            raise RuntimeError("engine stop failed")

        bridge.session.stop_slave = boom  # type: ignore[method-assign]
        await bridge.shutdown()

        assert bridge.session.multi_station is None
        assert mgr.station_count == 0
        assert mgr.is_running is False
        for p in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", p))
            finally:
                s.close()

    @pytest.mark.asyncio
    async def test_shutdown_clears_subscribers_when_session_shutdown_raises(self):
        """会话关停意外抛错时，桥接仍清空订阅者队列（finally 兜底）。"""
        from webui.bridge import EngineBridge

        bridge = EngineBridge(role="slave")
        q = bridge.subscribe()
        assert q in bridge.bus._subscribers

        async def boom():
            raise RuntimeError("session shutdown failed")

        bridge.session.shutdown = boom  # type: ignore[method-assign]
        await bridge.shutdown()

        assert bridge.bus._subscribers == set()
