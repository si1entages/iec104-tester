#!/usr/bin/env python3
"""网络异常模拟 CLI 工具.

用法:
    # 使用预设
    python sim_tool.py --preset poor_wifi --mode master --host 127.0.0.1

    # 自定义条件
    python sim_tool.py --loss 0.1 --delay 50 --mode master --host 127.0.0.1

    # 压力测试
    python sim_tool.py --preset stress --mode master --host 127.0.0.1

    # 查看预设列表
    python sim_tool.py --list-presets
"""

import sys
import os
import asyncio
import argparse
import logging
import time
from pathlib import Path

project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


PRESETS = {
    "clean": "正常网络 (无异常)",
    "poor_wifi": "差WiFi (延迟30ms±20ms, 丢包5%)",
    "congested": "网络拥塞 (延迟100ms±50ms, 丢包10%)",
    "satellite": "卫星链路 (延迟500ms±100ms, 丢包2%)",
    "unreliable": "高丢包 (丢包30%, 损坏5%)",
    "intermittent": "间歇断线 (5%概率断线5秒)",
    "slow_link": "低带宽 (1KB/s, 延迟50ms)",
    "stress": "综合压力 (全部异常叠加)",
}


async def main():
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 网络异常模拟",
    )
    parser.add_argument("--mode", choices=["master", "slave"], default="master")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2404)
    parser.add_argument("--common-addr", type=int, default=1)
    parser.add_argument("--auto-gi", action="store_true")

    # 预设
    parser.add_argument("--preset", choices=list(PRESETS.keys()), help="使用预设条件")
    parser.add_argument("--list-presets", action="store_true", help="列出所有预设")

    # 自定义条件
    parser.add_argument("--loss", type=float, default=0, help="丢包率 (0.0~1.0)")
    parser.add_argument("--delay", type=float, default=0, help="延迟 (ms)")
    parser.add_argument("--delay-var", type=float, default=0, help="延迟抖动 (ms)")
    parser.add_argument("--duplicate", type=float, default=0, help="重复率 (0.0~1.0)")
    parser.add_argument("--corrupt", type=float, default=0, help="损坏率 (0.0~1.0)")
    parser.add_argument("--corrupt-bits", type=int, default=1, help="翻转位数")
    parser.add_argument("--reorder", type=float, default=0, help="乱序率 (0.0~1.0)")
    parser.add_argument("--disconnect-rate", type=float, default=0, help="断线触发率")
    parser.add_argument("--disconnect-dur", type=float, default=3.0, help="断线持续时间(s)")
    parser.add_argument("--bandwidth", type=int, default=0, help="带宽限制 (B/s)")
    parser.add_argument("--direction", choices=["rx", "tx", "both"], default="both")

    # 控制
    parser.add_argument("--duration", type=int, default=0, help="运行时长(秒), 0=无限")
    parser.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    if args.list_presets:
        print("可用预设:")
        for name, desc in PRESETS.items():
            print(f"  {name:15s} — {desc}")
        return

    setup_logging(args.log_level)

    from core.simulation import SimulationManager, ConditionPreset
    from core.config import AppConfig

    # 构建条件
    sim = SimulationManager()
    if args.preset:
        sim.apply_preset(args.preset)
    else:
        sim.apply_condition(
            loss_rate=args.loss,
            delay_ms=args.delay,
            delay_variance_ms=args.delay_var,
            duplicate_rate=args.duplicate,
            corrupt_rate=args.corrupt,
            corrupt_bits=args.corrupt_bits,
            reorder_rate=args.reorder,
            disconnect_rate=args.disconnect_rate,
            disconnect_duration_s=args.disconnect_dur,
            bandwidth_bps=args.bandwidth,
            direction=args.direction,
        )

    # 创建引擎
    if args.mode == "master":
        from core.engine.master import MasterEngine
        engine = MasterEngine(
            host=args.host, port=args.port,
            common_addr=args.common_addr,
            auto_start=True, auto_gi=args.auto_gi,
        )
    else:
        from core.engine.slave import SlaveEngine
        from core.data.point_table import PointTable
        pt = PointTable()
        pt.generate_demo_points(yx_count=100, yc_count=50)
        engine = SlaveEngine(port=args.port, point_table=pt)

    # 安装模拟
    sim.install(engine)

    # 事件回调
    def on_event(event, data):
        print(f"  [{event.value}]")

    engine.set_event_callback(on_event)

    print(f"🔧 Network Simulation Active")
    print(f"   {sim.condition.describe()}")
    print(f"   Mode: {args.mode} | {args.host}:{args.port}")
    if args.duration > 0:
        print(f"   Duration: {args.duration}s")
    print(f"   Press Ctrl+C to stop\n")

    await engine.start()

    start_time = time.monotonic()
    try:
        while True:
            await asyncio.sleep(2)
            elapsed = time.monotonic() - start_time
            print(f"\r  {sim.stats_summary()}", end="", flush=True)

            if args.duration > 0 and elapsed >= args.duration:
                print(f"\n⏱ Duration reached ({args.duration}s)")
                break
    except KeyboardInterrupt:
        print("\n")
    finally:
        print(f"\n{sim.stats_summary()}")
        sim.remove()
        await engine.stop()
        print("✅ Simulation stopped")


if __name__ == "__main__":
    asyncio.run(main())
