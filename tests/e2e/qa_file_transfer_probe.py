"""文件传输真机核实探针（只读，C4）.

对**已连接真机的主站**（默认 http://127.0.0.1:8765）执行文件传输读取流程，
把对端回帧中的 NOF/LOF/NOS/LSQ/CHS/FRQ/SRQ/SCQ/AFQ 等字段结构化打印出来，
用于填写 `docs/file_transfer_open_items.md` 的真机核实清单。

安全默认：
  - 默认只发「目录召唤」（F_SC SCQ=5），不 select / 不 request；
  - `--select` / `--request` 需显式开启（部分装置对文件操作敏感，联调前请确认）。

用法：
  python tests/e2e/qa_file_transfer_probe.py                 # 只读目录
  python tests/e2e/qa_file_transfer_probe.py --select 1      # 再选择 NOF=1
  python tests/e2e/qa_file_transfer_probe.py --request 1     # 再请求 NOF=1
  python tests/e2e/qa_file_transfer_probe.py --base http://127.0.0.1:8766 --ioa 0

注意：主站必须已经 `--mode master` 连接并处于 Running；脚本不建立 IEC 连接。
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_common import MASTER, get, post  # noqa: E402

from core.protocol.asdu import ASDU  # noqa: E402

# 文件传输类 TypeID → 简称
FILE_TYPES: dict[int, str] = {
    120: "F_FR", 121: "F_SR", 122: "F_SC", 123: "F_LS",
    124: "F_AF", 125: "F_SG", 126: "F_DR",
    128: "F_FR_NB", 129: "F_SR_NB",
}


def _file_frames(base: str, since: float) -> list[tuple[str, int, object]]:
    """取 since 之后收到的文件传输 I 帧（主站视角 rx），返回 (简称, COT, 数据对象)."""
    try:
        recent = get(base, "/api/recent")
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 读取 /api/recent 失败：{e}")
        return []

    out: list[tuple[str, int, object]] = []
    for item in recent.get("frames", []):
        data = item.get("data", item)
        if data.get("direction") != "rx":
            continue
        if float(item.get("ts", 0) or 0) < since:
            continue
        try:
            raw = bytes.fromhex(data.get("hex", ""))
        except ValueError:
            continue
        if len(raw) < 8 or (raw[2] & 0x01):      # 仅 I 帧
            continue
        try:
            asdu = ASDU.decode(raw[6:])
        except Exception:                        # noqa: BLE001 — 探针尽力解析
            continue
        tid = int(asdu.type_id)
        if tid not in FILE_TYPES:
            continue
        if tid == 126:  # F_DR_TA_1：目录条目天然多对象（SQ=1 连续编址），逐条目输出
            for entry in asdu.objects:
                out.append((FILE_TYPES[tid], int(asdu.cot), entry.data))
        else:
            obj = asdu.objects[0].data if asdu.objects else None
            out.append((FILE_TYPES[tid], int(asdu.cot), obj))
    return out


def _describe(name: str, cot: int, obj: object) -> str:
    """把数据对象字段展开为 `字段=值` 串（探针用，不依赖具体类名）."""
    if obj is None:
        return f"{name:7s} COT={cot:<2d} (无对象)"
    parts: list[str] = []
    if dataclasses.is_dataclass(obj):
        for field in dataclasses.fields(obj):
            if field.name in ("ioa", "quality", "time_tag", "time_short", "time_long"):
                continue
            value = getattr(obj, field.name)
            if isinstance(value, bytes):
                value = f"<{len(value)}B>"
            parts.append(f"{field.name}={value}")
    else:
        parts.append(repr(obj))
    return f"{name:7s} COT={cot:<2d} " + " ".join(parts)


def _observe(label: str, base: str, action: dict, wait: float) -> list[str]:
    """执行一次文件动作并打印观察到的回帧，返回原始描述行."""
    started = time.time()
    print(f"\n── {label} ──")
    try:
        result = post(base, "/api/master/file", action)
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 请求失败：{e}")
        return []
    if not result.get("ok", True):
        print(f"[错误] 主站返回：{result.get('error')}")
        return []

    time.sleep(wait)
    lines = [_describe(*frame) for frame in _file_frames(base, started)]
    if not lines:
        print("（未观察到文件传输回帧：确认主站已连接、装置支持文件传输，"
              "必要时增大 --wait）")
    for line in lines:
        print("  " + line)
    return lines


def _summary(lines: list[str]) -> None:
    """输出待核实记录要点（供人工粘贴到清单文档）."""
    joined = "\n".join(lines)
    print("\n===== 待核实记录要点 =====")
    print(f"  回帧条数: {len(lines)}")
    print(f"  出现的 NOF 集合: {_collect(joined, ('file_name',))}")
    print(f"  LSQ 取值: {_collect(joined, ('last_section', 'lsq'))}")
    print(f"  CHS 出现次数: {_count_fields(joined, ('checksum', 'chs'))}")
    print(f"  FRQ/SRQ 出现: {_collect(joined, ('status',))}")
    print("  对照 docs/file_transfer_open_items.md 逐项记录：")
    print("   ① NOF 语义（Ed.1 文件名 / Ed.2 文件类型）")
    print("   ② 目录请求的 SCQ/NOF 组合（本实现用 SCQ=5，项目约定）")
    print("   ③ LSQ=2/4 后是否需要去激活（WITH_DEACT 后续动作）")
    print("   ④ 多节流程（NOS/LSQ 序列、F_SR/F_SG 是否逐节出现）")
    print("   ⑤ FRQ/SRQ 否定标志（最高位 0x80 vs 取值 0/1）")


def _collect(text: str, fields: tuple[str, ...]) -> str:
    values = sorted({part.split("=", 1)[1] for part in text.split()
                     if any(part.startswith(f + "=") for f in fields)})
    return "{" + ", ".join(values) + "}" if values else "—"


def _count_fields(text: str, fields: tuple[str, ...]) -> int:
    return sum(1 for part in text.split()
               if any(part.startswith(f + "=") for f in fields))


def main() -> int:
    ap = argparse.ArgumentParser(description="文件传输真机核实探针（只读）")
    ap.add_argument("--base", default=MASTER, help=f"主站 Web API（默认 {MASTER}）")
    ap.add_argument("--ioa", type=int, default=0, help="文件传输信息对象地址（默认 0）")
    ap.add_argument("--select", type=int, default=None, metavar="NOF",
                    help="可选：对 NOF 发起文件选择（默认不做）")
    ap.add_argument("--request", type=int, default=None, metavar="NOF",
                    help="可选：对 NOF 发起文件请求（默认不做）")
    ap.add_argument("--wait", type=float, default=3.0, help="每次动作后等待回帧秒数")
    ap.add_argument("--dir-cot", type=int, default=13, choices=[5, 6, 13],
                    help="目录召唤 COT：13=FILE（项目约定默认）/ 5=REQ（Ed.2 第三方口径）/ 6=ACT")
    ap.add_argument("--dir-scq", type=int, default=5, choices=range(0, 8), metavar="0-7",
                    help="目录召唤 SCQ：5=项目约定默认 / 0=otfabric 实测口径")
    args = ap.parse_args()

    print(f"文件传输探针 | 主站 {args.base} | IOA={args.ioa} | 等待 {args.wait}s "
          f"| 目录 COT={args.dir_cot} SCQ={args.dir_scq}")
    try:
        status = get(args.base, "/api/status")
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 无法访问主站：{e}")
        return 2

    lines = _observe(
        f"① 目录召唤（F_SC COT={args.dir_cot} SCQ={args.dir_scq}）", args.base,
        {"action": "directory", "ioa": args.ioa,
         "cot": args.dir_cot, "qualifier": args.dir_scq}, args.wait)

    if args.select is not None:
        lines += _observe(
            f"② 文件选择 NOF={args.select}", args.base,
            {"action": "select", "ioa": args.ioa, "file_name": args.select}, args.wait)

    if args.request is not None:
        lines += _observe(
            f"③ 文件请求 NOF={args.request}", args.base,
            {"action": "request", "ioa": args.ioa, "file_name": args.request}, args.wait)

    _summary(lines)
    print(f"\n主站状态: state={status.get('state')} role={status.get('role')}")
    print("本脚本为只读探针：结论请人工写入 docs/file_transfer_open_items.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
