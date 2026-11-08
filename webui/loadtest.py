"""压测编排（T76，both 模式）——子站按目标速率自发事件，主站侧差分统计.

编排层：不改引擎内核。驱动既有公开路径 ``slave_set_yx/yc``（自发 I 帧上行）
按目标速率循环触发，采样主站 ``ConnectionStats``（frames/i_frames/bytes
received）做差分，产出吞吐汇总（验收口径：每秒 N 条遥测稳定上送不断链）。

使用约束：主站与子站引擎都已运行（both 模式，或任何可注入双桥的场景）；
挂载为 ``master_bridge.loadtest`` 属性，路由层按属性存在性注册端点。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable

from .bridge import EngineBridge

logger = logging.getLogger("iec104.loadtest")

_TICK_S = 0.1          # 触发粒度（秒）：速率按 tick 均摊
_MAX_DURATION_S = 3600.0
_MAX_EPS = 10000.0


class LoadTestService:
    """单次压测会话（同时只允许一个实例在跑，幂等保护）."""

    def __init__(self, slave: EngineBridge, master: EngineBridge,
                 publish: Callable[[str, dict], None] | None = None):
        self._slave = slave
        self._master = master
        self._publish = publish or (lambda kind, data: None)
        self._task: asyncio.Task | None = None
        self._cfg: dict = {}
        self._base_stats: dict = {}
        self._events_sent = 0
        self._started_at = 0.0
        self._duration_s = 0.0
        self._summary: dict | None = None

    # ── 生命周期 ──────────────────────────────────────────────

    async def start(self, duration_s: float = 60.0, events_per_s: float = 100.0) -> dict:
        if self._task is not None and not self._task.done():
            return {"ok": False, "error": "压测已在运行"}
        duration_s = max(1.0, min(float(duration_s), _MAX_DURATION_S))
        events_per_s = max(1.0, min(float(events_per_s), _MAX_EPS))

        # 双端引擎都必须在运行
        sl_engine = self._slave.session.engine
        ma_engine = self._master.session.engine
        if sl_engine is None:
            return {"ok": False, "error": "子站引擎未启动（先在子站工作台启动监听）"}
        if ma_engine is None:
            return {"ok": False, "error": "主站引擎未连接（先在主站工作台连接）"}

        yc_ioas = [p.ioa for p in self._slave.points.table.get_all_yc()]
        yx_ioas = [p.ioa for p in self._slave.points.table.get_all_yx()]
        if not yc_ioas and not yx_ioas:
            return {"ok": False, "error": "子站点表为空，无可压测点位"}

        self._cfg = {"duration_s": duration_s, "events_per_s": events_per_s}
        self._events_sent = 0
        self._summary = None
        self._duration_s = duration_s
        self._started_at = time.monotonic()
        self._base_stats = self._master_stats()

        self._task = asyncio.create_task(self._run(duration_s, events_per_s,
                                                   yc_ioas, yx_ioas))
        self._publish("event", {"type": "ui", "data": {
            "msg": f"压测启动：{events_per_s:.0f} 事件/秒 × {duration_s:.0f}s"}})
        return {"ok": True}

    async def stop(self) -> dict:
        """提前停止并返回汇总（已自然结束时返回该次汇总）."""
        if self._task is None:
            return {"ok": False, "error": "压测未在运行"}
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        return {"ok": True, **self.summary()}

    def status(self) -> dict:
        running = self._task is not None and not self._task.done()
        cur = self._master_stats()
        elapsed = (time.monotonic() - self._started_at) if self._started_at else 0.0
        rx_frames = cur["frames_received"] - self._base_stats.get("frames_received", 0)
        return {
            "running": running,
            "elapsed_s": round(min(elapsed, self._duration_s), 2),
            "duration_s": self._duration_s,
            "target_eps": self._cfg.get("events_per_s", 0),
            "events_sent": self._events_sent,
            "rx_frames": rx_frames,
            "i_frames": cur["i_frames_received"] - self._base_stats.get("i_frames_received", 0),
            "bytes_received": cur["bytes_received"] - self._base_stats.get("bytes_received", 0),
            "fps": round(rx_frames / elapsed, 1) if elapsed > 0.2 else 0.0,
            "errors": cur["errors"] - self._base_stats.get("errors", 0),
            "summary": self._summary,
        }

    def last_summary(self) -> dict | None:
        """最近一次压测的汇总（从未运行过返回 None）——报告生成（T78）取用."""
        return self._summary

    def summary(self) -> dict:
        if self._summary is not None:
            return self._summary
        cur = self._master_stats()
        elapsed = max(time.monotonic() - self._started_at, 0.001)
        rx_frames = cur["frames_received"] - self._base_stats.get("frames_received", 0)
        return {
            "events_sent": self._events_sent,
            "rx_frames": rx_frames,
            "i_frames": cur["i_frames_received"] - self._base_stats.get("i_frames_received", 0),
            "bytes_received": cur["bytes_received"] - self._base_stats.get("bytes_received", 0),
            "avg_eps": round(self._events_sent / elapsed, 1),
            "avg_fps": round(rx_frames / elapsed, 1),
            "errors": cur["errors"] - self._base_stats.get("errors", 0),
        }

    # ── 内部 ──────────────────────────────────────────────────

    def _master_stats(self) -> dict:
        eng = self._master.session.engine
        st = getattr(eng, "connection_stats", None)
        if st is None:
            return {"frames_received": 0, "i_frames_received": 0,
                    "bytes_received": 0, "errors": 0}
        return {"frames_received": st.frames_received,
                "i_frames_received": st.i_frames_received,
                "bytes_received": st.bytes_received,
                "errors": st.errors}

    async def _run(self, duration_s: float, events_per_s: float,
                   yc_ioas: list[int], yx_ioas: list[int]) -> None:
        """触发循环：按速率均摊到 tick，交替发 YC/YX 自发事件."""
        deadline = time.monotonic() + duration_s
        per_tick = max(1, int(round(events_per_s * _TICK_S)))
        i = 0
        try:
            while time.monotonic() < deadline:
                t0 = time.monotonic()
                for _ in range(per_tick):
                    if i % 4 == 3 and yx_ioas:
                        ioa = yx_ioas[i % len(yx_ioas)]
                        eng = self._slave.session.engine
                        cur = eng.data_store.get_yx(ioa)
                        await self._slave.slave_set_yx(ioa, not (cur.value if cur else False))
                    elif yc_ioas:
                        ioa = yc_ioas[i % len(yc_ioas)]
                        eng = self._slave.session.engine
                        cur = eng.data_store.get_yc(ioa)
                        base = cur.value if cur else 0.0
                        await self._slave.slave_set_yc(
                            ioa, base + random.uniform(-1.0, 1.0))
                    else:
                        break
                    i += 1
                    self._events_sent += 1
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(_TICK_S - elapsed, 0.0))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 压测异常收敛为汇总，不崩 UI
            logger.warning("loadtest aborted: %s", e)
        finally:
            self._summary = self.summary()
            self._summary["target_eps"] = events_per_s
            self._summary["duration_s_actual"] = round(
                min(time.monotonic() - self._started_at, duration_s + 1.0), 2)
            self._publish("event", {"type": "ui", "data": {"msg": "压测结束"}})
