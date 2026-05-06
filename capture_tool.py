#!/usr/bin/env python3
"""报文录制/回放 CLI 工具.

用法:
    # 录制
    python capture_tool.py record --mode master --host 127.0.0.1 --port 2404 -o session.i104
    python capture_tool.py record --mode slave --port 2404 -o slave_session.i104

    # 回放
    python capture_tool.py play session.i104
    python capture_tool.py play session.i104 --speed 2.0
    python capture_tool.py play session.i104 --step

    # 分析
    python capture_tool.py analyze session.i104
    python capture_tool.py analyze session.i104 --format json

    # 格式转换
    python capture_tool.py convert session.i104 -o session.json
    python capture_tool.py convert session.json -o session.i104

    # 查看
    python capture_tool.py show session.i104
    python capture_tool.py show session.i104 --filter "frame_type=I direction=RX"
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


# ═══════════════════════════════════════════════════════════════════
#  录制
# ═══════════════════════════════════════════════════════════════════

async def cmd_record(args):
    """录制报文."""
    from core.capture import PacketRecorder
    from core.config import AppConfig

    recorder = PacketRecorder()

    # 构建配置
    config = AppConfig()
    config.mode = args.mode
    config.connection.host = args.host
    config.connection.port = args.port

    # 创建引擎
    if args.mode == "master":
        from core.engine.master import MasterEngine
        engine = MasterEngine(
            host=args.host,
            port=args.port,
            common_addr=args.common_addr,
            auto_start=True,
            auto_gi=args.auto_gi,
            reconnect=True,
        )
    else:
        from core.engine.slave import SlaveEngine
        from core.data.point_table import PointTable
        pt = PointTable()
        pt.generate_demo_points(yx_count=100, yc_count=50)
        engine = SlaveEngine(
            port=args.port,
            common_addr=args.common_addr,
            point_table=pt,
        )

    # 连接录制器
    engine.set_packet_recorder(recorder)

    # 事件回调
    def on_event(event, data):
        print(f"  [{event.value}] {data}")

    engine.set_event_callback(on_event)

    # 输出路径
    output = args.output or f"capture_{args.mode}_{time.strftime('%Y%m%d_%H%M%S')}.i104"
    format = "json" if output.endswith(".json") else "binary"

    print(f"🔴 Recording: {output}")
    print(f"   Mode: {args.mode} | Host: {args.host}:{args.port}")
    print(f"   Press Ctrl+C to stop\n")

    recorder.start(output, description=f"{args.mode} session", format=format)

    await engine.start()

    try:
        while True:
            await asyncio.sleep(1)
            stats = recorder.get_stats()
            print(
                f"\r  📊 Frames: {stats['total_frames']} "
                f"(RX={stats['rx_frames']}, TX={stats['tx_frames']}) "
                f"| Elapsed: {stats['elapsed_s']:.0f}s",
                end="", flush=True,
            )
    except KeyboardInterrupt:
        print("\n")
    finally:
        total = recorder.stop()
        await engine.stop()
        print(f"✅ Saved {total} frames to {output}")


# ═══════════════════════════════════════════════════════════════════
#  回放
# ═══════════════════════════════════════════════════════════════════

async def cmd_play(args):
    """回放报文."""
    from core.capture import PacketPlayer, FrameFilter

    player = PacketPlayer()
    count = player.load(args.file)
    print(f"📂 Loaded {count} frames from {args.file}")
    print(f"   Duration: {player.duration:.2f}s")

    # 设置速度
    player.set_speed(args.speed)
    print(f"   Speed: {args.speed}x")

    # 过滤器
    if args.filter:
        f = _parse_filter(args.filter)
        player.set_filter(f)
        print(f"   Filter: {f.describe()}")

    # 单步模式
    if args.step:
        print("\n▶ Step mode (Enter=next, b=back, q=quit)\n")
        while True:
            frame = player.current_frame
            if frame:
                _print_frame(frame, player.current_index)

            cmd = input("  > ").strip().lower()
            if cmd == "q":
                break
            elif cmd == "b":
                player.step_backward()
            else:
                player.step_forward()
        return

    # 异步回放
    print(f"\n▶ Playing...\n")

    def on_frame(frame, index):
        _print_frame(frame, index)

    def on_complete():
        print(f"\n✅ Playback complete")

    await player.play(on_frame=on_frame, on_complete=on_complete)


# ═══════════════════════════════════════════════════════════════════
#  分析
# ═══════════════════════════════════════════════════════════════════

def cmd_analyze(args):
    """分析报文."""
    import json
    from core.capture import CaptureFile, CaptureAnalyzer

    header, frames = CaptureFile.load(args.file)
    analyzer = CaptureAnalyzer()
    result = analyzer.analyze(frames)

    if args.format == "json":
        output = {
            "file": args.file,
            "header": {
                "created": header.created,
                "description": header.description,
            },
            "stats": {
                "total_frames": result.stats.total_frames,
                "rx_frames": result.stats.rx_frames,
                "tx_frames": result.stats.tx_frames,
                "i_frames": result.stats.i_frames,
                "s_frames": result.stats.s_frames,
                "u_frames": result.stats.u_frames,
                "total_bytes": result.stats.total_bytes,
                "duration_s": result.stats.duration_s,
                "avg_bps": result.stats.avg_bps,
                "asdu_types": result.stats.asdu_type_counts,
                "cot_distribution": result.stats.cot_counts,
            },
            "anomalies": [
                {
                    "timestamp": a.timestamp,
                    "type": a.anomaly_type,
                    "severity": a.severity,
                    "description": a.description,
                }
                for a in result.anomalies
            ],
            "u_frames": result.u_frame_details,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(result.session_summary)

        if result.anomalies:
            print(f"\n⚠️  Anomalies:")
            for a in result.anomalies[:20]:
                icon = "❌" if a.severity == "error" else "⚠️"
                print(f"  {icon} [{a.timestamp:.3f}s] {a.description}")
            if len(result.anomalies) > 20:
                print(f"  ... and {len(result.anomalies) - 20} more")

        if result.u_frame_details:
            print(f"\n🔄 U-Frame Timeline:")
            for u in result.u_frame_details[:20]:
                print(f"  {u['direction']} {u['function']} @ {u['timestamp']:.3f}s")


# ═══════════════════════════════════════════════════════════════════
#  显示
# ═══════════════════════════════════════════════════════════════════

def cmd_show(args):
    """显示录制内容."""
    from core.capture import CaptureFile, FrameFilter

    header, frames = CaptureFile.load(args.file)
    print(f"📂 File: {args.file}")
    print(f"   Created: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(header.created))}")
    print(f"   Description: {header.description or '(none)'}")
    print(f"   Frames: {len(frames)}")

    # 过滤
    if args.filter:
        f = _parse_filter(args.filter)
        frames = f.apply(frames)
        print(f"   Filtered: {len(frames)} frames ({f.describe()})")

    # 显示
    limit = args.limit or 50
    print(f"\n{'#':>6} {'Time':>10} {'Dir':>3} {'Type':>3} {'Len':>5} {'Hex'}")
    print("-" * 70)

    for i, frame in enumerate(frames[:limit]):
        _print_frame_line(i, frame)

    if len(frames) > limit:
        print(f"\n  ... {len(frames) - limit} more frames (use --limit to show more)")


# ═══════════════════════════════════════════════════════════════════
#  转换
# ═══════════════════════════════════════════════════════════════════

def cmd_convert(args):
    """格式转换."""
    from core.capture import CaptureFile

    header, frames = CaptureFile.load(args.file)

    output = args.output
    if not output:
        # 自动切换扩展名
        if args.file.endswith(".json"):
            output = args.file.replace(".json", ".i104")
        else:
            output = args.file.replace(".i104", ".json")

    CaptureFile.save(output, frames, description=header.description, created=header.created)
    print(f"✅ Converted {len(frames)} frames: {args.file} → {output}")


# ═══════════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════════

def _parse_filter(filter_str: str) -> FrameFilter:
    """解析过滤器字符串. 格式: "key=value key=value ..."."""
    from core.capture import FrameFilter

    f = FrameFilter()
    for part in filter_str.split():
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower()
        value = value.strip()

        if key == "direction":
            f.direction = value
        elif key == "frame_type" or key == "type":
            f.frame_type = value
        elif key == "asdu_type" or key == "asdu":
            f.asdu_type = int(value)
        elif key == "cot":
            f.cot = int(value)
        elif key == "ioa":
            f.ioa = int(value)
        elif key == "addr" or key == "common_addr":
            f.common_addr = int(value)
        elif key == "min_len":
            f.min_length = int(value)
        elif key == "max_len":
            f.max_length = int(value)

    return f


def _print_frame(frame, index: int):
    """打印单帧详情."""
    hex_str = " ".join(f"{b:02X}" for b in frame.frame_data[:32])
    if len(frame.frame_data) > 32:
        hex_str += "..."
    print(
        f"  [{index:6d}] {frame.timestamp:10.3f}s "
        f"{frame.direction_str:>3} {frame.frame_type:>3} "
        f"{frame.frame_length:5d}B  {hex_str}"
    )


def _print_frame_line(index: int, frame):
    """打印单帧行."""
    hex_str = " ".join(f"{b:02X}" for b in frame.frame_data[:20])
    if len(frame.frame_data) > 20:
        hex_str += "..."
    print(
        f"{index:6d} {frame.timestamp:10.3f}s "
        f"{frame.direction_str:>3} {frame.frame_type:>3} "
        f"{frame.frame_length:5d}B  {hex_str}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 报文录制/回放工具",
    )
    subparsers = parser.add_subparsers(dest="command")

    # record
    p_record = subparsers.add_parser("record", help="录制报文")
    p_record.add_argument("--mode", choices=["master", "slave"], default="master")
    p_record.add_argument("--host", default="127.0.0.1")
    p_record.add_argument("--port", type=int, default=2404)
    p_record.add_argument("--common-addr", type=int, default=1)
    p_record.add_argument("--auto-gi", action="store_true", help="自动总召")
    p_record.add_argument("-o", "--output", help="输出文件路径")
    p_record.add_argument("--log-level", default="INFO")

    # play
    p_play = subparsers.add_parser("play", help="回放报文")
    p_play.add_argument("file", help="录制文件路径")
    p_play.add_argument("--speed", type=float, default=1.0, help="回放速度倍数")
    p_play.add_argument("--step", action="store_true", help="单步模式")
    p_play.add_argument("--filter", help='过滤器 "frame_type=I direction=RX"')
    p_play.add_argument("--log-level", default="INFO")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="分析报文")
    p_analyze.add_argument("file", help="录制文件路径")
    p_analyze.add_argument("--format", choices=["text", "json"], default="text")
    p_analyze.add_argument("--log-level", default="INFO")

    # show
    p_show = subparsers.add_parser("show", help="显示录制内容")
    p_show.add_argument("file", help="录制文件路径")
    p_show.add_argument("--limit", type=int, default=50, help="显示帧数上限")
    p_show.add_argument("--filter", help='过滤器 "frame_type=I direction=RX"')
    p_show.add_argument("--log-level", default="INFO")

    # convert
    p_convert = subparsers.add_parser("convert", help="格式转换")
    p_convert.add_argument("file", help="输入文件")
    p_convert.add_argument("-o", "--output", help="输出文件")
    p_convert.add_argument("--log-level", default="INFO")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    setup_logging(getattr(args, "log_level", "INFO"))

    if args.command == "record":
        asyncio.run(cmd_record(args))
    elif args.command == "play":
        asyncio.run(cmd_play(args))
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "show":
        cmd_show(args)
    elif args.command == "convert":
        cmd_convert(args)


if __name__ == "__main__":
    main()
