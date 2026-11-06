"""性能基准（默认排除，``pytest -m perf`` 显式运行）."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("psutil")  # soak 用它统计句柄；同时确保 dev 依赖完整

from core.data.point_table import PointTable  # noqa: E402
from core.protocol.apci import APCICodec  # noqa: E402
from core.protocol.asdu import ASDU, ASDUBuilder  # noqa: E402
from core.protocol.types import COT  # noqa: E402
from webui.points import PointService  # noqa: E402

pytestmark = pytest.mark.perf

DECODE_FRAMES = 20_000
DECODE_MIN_RATE = 2_000  # 帧/秒

SNAPSHOT_POINTS = 100_000
SNAPSHOT_MAX_SECONDS = 5.0

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sample_frame() -> bytes:
    payload = ASDUBuilder.build_single_point_sequence(
        1, [(i, i % 2 == 0, 0) for i in range(1, 101)], cot=COT.INTROGEN,
    )
    return APCICodec.encode_i(0, 0, payload)


def test_apci_asdu_decode_throughput() -> None:
    """2 万帧 APCI+ASDU 解码吞吐（真实总召数据帧）."""
    frame = _sample_frame()
    asdu_body = frame[6:]
    assert ASDU.decode(asdu_body).num == 100

    start = time.perf_counter()
    for _ in range(DECODE_FRAMES):
        apci, _ = APCICodec.decode(frame)
        ASDU.decode(frame[6:6 + apci.asdu_length])
    elapsed = time.perf_counter() - start

    rate = DECODE_FRAMES / elapsed
    print(f"\n[perf] decode: {DECODE_FRAMES} frames in {elapsed:.3f}s "
          f"= {rate:,.0f} frames/s")
    assert rate >= DECODE_MIN_RATE, (
        f"decode throughput {rate:,.0f} frames/s < {DECODE_MIN_RATE:,} frames/s"
    )


def test_point_snapshot_100k() -> None:
    """10 万点定义表快照（Web UI 首次加载/刷新路径）."""
    table = PointTable()
    table.generate_demo_points(
        yx_count=50_000, yc_count=50_000, yk_count=0, ym_count=0, step_count=0,
    )
    service = PointService(table)
    assert service.count == SNAPSHOT_POINTS

    start = time.perf_counter()
    snapshot = service.snapshot()
    elapsed = time.perf_counter() - start

    print(f"\n[perf] snapshot: {len(snapshot)} points in {elapsed:.3f}s")
    assert len(snapshot) == SNAPSHOT_POINTS
    assert elapsed < SNAPSHOT_MAX_SECONDS, (
        f"snapshot took {elapsed:.3f}s >= {SNAPSHOT_MAX_SECONDS}s"
    )
