"""20 客户端并发性能用例（子站单实例 ↔ 20 个主站连接）.

验证多客户端场景下的连接建立、总召响应与聚合吞吐；默认 5s，可用
``IEC104_PERF_CLIENTS_SECONDS`` 拉长。属于 ``perf`` 标记，默认不参与全量测试。
"""

from __future__ import annotations

import asyncio
import os
import socket

import pytest

from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from core.engine.slave import SlaveEngine

pytestmark = pytest.mark.perf

CLIENTS = 20
MIN_FRAME_RATE = 1_000  # 帧/秒（聚合，含 GI 响应与确认帧）
DEFAULT_SECONDS = 5.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_point_table() -> PointTable:
    pt = PointTable()
    pt.generate_demo_points(yx_count=100, yc_count=20, yk_count=5, ym_count=5)
    pt.common_addr = 1
    pt.station_name = "PERF-20"
    return pt


async def _wait_until(predicate, timeout: float = 15.0, interval: float = 0.05) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def _rx_frames(master: MasterEngine) -> int:
    stats = master.connection_stats
    return int(stats.frames_received) if stats else 0


async def test_twenty_clients_concurrent_gi() -> None:
    duration = float(os.environ.get("IEC104_PERF_CLIENTS_SECONDS", DEFAULT_SECONDS))
    assert duration > 0

    port = _free_port()
    points = _demo_point_table()
    slave = SlaveEngine(
        host="127.0.0.1", port=port, common_addr=1,
        max_connections=CLIENTS + 8, point_table=points,
    )
    slave.data_store.init_from_point_table(points)
    masters = [
        MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                     auto_start=True, auto_gi=False, reconnect=False)
        for _ in range(CLIENTS)
    ]

    await slave.start()
    try:
        await asyncio.gather(*(m.start() for m in masters))
        assert await _wait_until(lambda: slave.client_count == CLIENTS), (
            f"only {slave.client_count}/{CLIENTS} clients connected"
        )
        assert await _wait_until(lambda: all(m.is_running for m in masters)), (
            "not all masters reached running state"
        )

        start_counts = [_rx_frames(m) for m in masters]
        yx_ioas = [p.ioa for p in points.get_all_yx()]
        loop = asyncio.get_running_loop()
        began = loop.time()
        deadline = began + duration
        rounds = 0

        # 先做一轮总召，确认 20 条链路都能完成请求/响应
        await asyncio.gather(*(m.general_interrogation() for m in masters))

        # 持续自发上送：每轮 100 个 YX × 20 个客户端 = 2000 帧广播
        while loop.time() < deadline:
            for index, ioa in enumerate(yx_ioas):
                await slave.send_spontaneous_yx(ioa, bool((rounds + index) % 2))
            rounds += 1
            await asyncio.sleep(0.5)

        # 等最后一轮广播与 S 帧确认完成
        await asyncio.sleep(1.0)
        elapsed = loop.time() - began
        end_counts = [_rx_frames(m) for m in masters]
        total_frames = sum(end - start for start, end in zip(
            start_counts, end_counts, strict=True,
        ))
        rate = total_frames / elapsed

        print(
            f"\n[perf] {CLIENTS} clients, {rounds} spontaneous rounds, "
            f"{total_frames} frames received in {elapsed:.2f}s "
            f"= {rate:,.0f} frames/s (aggregate)"
        )
        assert all(m.is_running for m in masters), "a master dropped during the run"
        assert total_frames > 0, "no frames received"
        assert rate >= MIN_FRAME_RATE, (
            f"aggregate throughput {rate:,.0f} frames/s < {MIN_FRAME_RATE:,} frames/s"
        )
    finally:
        await asyncio.gather(*(m.stop() for m in masters), return_exceptions=True)
        await slave.stop()

    assert slave.client_count == 0, "slave still reports clients after stop"
