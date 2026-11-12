"""协议层变异冒烟（mutation smoke）.

不是完整的变异测试分数，而是一组**快速、可重复的测试灵敏度检查**：对
``core/protocol`` 的编解码逻辑注入少量典型变异（边界条件取反、位掩码错误、
序列号位移错误等），在隔离的临时副本里跑协议测试。变异必须被测试杀死
（测试失败）；若变异存活，说明对应行为没有断言覆盖。

用法::

    python tools/mutation_smoke.py

退出码 0 = 全部变异被杀死；1 = 存在存活变异或基线失败。

为什么不用 mutmut 全量跑？完整变异测试对每个变异都要跑一遍测试套件，协议模块
会产生数百个变异、耗时以小时计，不适合每次 CI。本冒烟只选高价值变异，控制在
十几秒内，作为 CI 的固定防线；发布前可再手动跑更大范围的变异工具。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_FILES = [
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/test_apci.py",
    "tests/test_apci_s_frame.py",
    "tests/test_asdu.py",
    "tests/test_protocol.py",
    "tests/test_protocol_io.py",
    "tests/test_protocol_type_coverage.py",
    "tests/test_frame_corpus_replay.py",
    "tests/test_commands.py",
    "tests/test_integration.py",
    "tests/test_sequence.py",
    "tests/test_state_machine.py",
    "tests/test_types.py",
]


@dataclass(frozen=True)
class Mutation:
    label: str
    path: str
    old: str
    new: str


MUTATIONS = [
    Mutation("APCI 起始字节校验取反", "core/protocol/apci.py",
             "if data[0] != START_BYTE:", "if data[0] == START_BYTE:"),
    Mutation("APCI 最小长度边界放宽", "core/protocol/apci.py",
             "if length < 4:", "if length < 0:"),
    Mutation("I/S/U 帧判别取反", "core/protocol/apci.py",
             "if (cf[0] & 0x01) == 0:", "if (cf[0] & 0x01) == 1:"),
    Mutation("I 帧发送序列号位移错误", "core/protocol/apci.py",
             "apci.tx_seq = (cf[0] >> 1) | (cf[1] << 7)",
             "apci.tx_seq = (cf[0] >> 1) | (cf[1] << 8)"),
    Mutation("S 帧保留位约束取反", "core/protocol/apci.py",
             "elif (cf[0] & 0x03) == 0x01 and cf[1] == 0x00:",
             "elif (cf[0] & 0x03) == 0x01 and cf[1] != 0x00:"),
    Mutation("U 帧功能码取错字节", "core/protocol/apci.py",
             "apci.u_func = cf[0]", "apci.u_func = cf[1]"),
    Mutation("ASDU VSQ 数量最低位被置 1", "core/protocol/asdu.py",
             "vsq = self.num & VSQ_NUM_MASK", "vsq = (self.num & VSQ_NUM_MASK) | 0x01"),
    Mutation("ASDU COT 编码混入 P/N/T 位", "core/protocol/asdu.py",
             "cot_byte = (self.cot & 0x3F) | (0x40 if self.pn else 0) | (0x80 if self.test else 0)",
             "cot_byte = self.cot & 0x7F"),
    Mutation("ASDU 解码 SQ 位识别错误", "core/protocol/asdu.py",
             "sq = bool(vsq & VSQ_SQ_BIT)", "sq = bool(vsq & 0x40)"),
    Mutation("ASDU 解码 COT 掩码错误", "core/protocol/asdu.py",
             "cot = cot_byte & 0x3F", "cot = cot_byte & 0x7F"),
    Mutation("SQ=1 后续对象 IOA 不递增", "core/protocol/asdu.py",
             "ioa = base_ioa + i if sq else base_ioa", "ioa = base_ioa"),
    # WP1 起 CA 长度可配，解码改为按 ca_length 逐字节累加（见 asdu.py
    # ASDU.decode / decode_header 两处）。锚点随之更新；replace(..., 1) 只改
    # 第一处（decode），等价于改动前「公共地址字节序错误」变异的覆盖面。
    Mutation("公共地址字节序错误", "core/protocol/asdu.py",
             "common_addr |= data[pos + i] << (8 * i)",
             "common_addr |= data[pos + i] << (7 * i)"),
]


def _prepare_workspace(base: Path) -> None:
    shutil.copytree(
        ROOT / "core", base / "core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (base / "tests").mkdir()
    for rel in TEST_FILES:
        shutil.copy2(ROOT / rel, base / rel)
    shutil.copytree(
        ROOT / "tests" / "fixtures", base / "tests" / "fixtures",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    # 临时目录不在仓库内：显式给 pytest-asyncio 配置，避免回落到仓库 pyproject
    (base / "pytest.ini").write_text(
        "[pytest]\nasyncio_mode = auto\ntestpaths = tests\n", encoding="utf-8",
    )


def _run_tests(base: Path) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PYTHONPATH": str(base),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
         "--basetemp", str(base / ".pytest-tmp"),
         *[str(base / rel) for rel in TEST_FILES if (base / rel).exists()]],
        cwd=base, env=env, capture_output=True, text=True, timeout=180,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="协议层变异冒烟")
    parser.add_argument("--keep", action="store_true", help="保留临时目录以便排查")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="iec104-mutation-") as tmp:
        base = Path(tmp)
        _prepare_workspace(base)

        baseline = _run_tests(base)
        if baseline.returncode != 0:
            print("基线测试失败，无法判定变异：")
            print(baseline.stdout[-4000:])
            print(baseline.stderr[-2000:])
            return 1
        print(f"基线通过；开始 {len(MUTATIONS)} 个变异 ...")

        originals: dict[Path, str] = {}
        killed = 0
        survived: list[str] = []
        skipped: list[str] = []
        try:
            for mutation in MUTATIONS:
                target = base / mutation.path
                if target not in originals:
                    originals[target] = target.read_text(encoding="utf-8")
                text = originals[target]
                if mutation.old not in text:
                    skipped.append(mutation.label)
                    print(f"  SKIP  {mutation.label}（源码片段已变化，需更新工具）")
                    continue
                target.write_text(text.replace(mutation.old, mutation.new, 1),
                                  encoding="utf-8")
                result = _run_tests(base)
                target.write_text(text, encoding="utf-8")

                if result.returncode == 0:
                    survived.append(mutation.label)
                    print(f"  SURVIVED  {mutation.label}")
                else:
                    killed += 1
                    print(f"  killed    {mutation.label}")
        finally:
            for target, text in originals.items():
                target.write_text(text, encoding="utf-8")
            if args.keep:
                keep_dir = ROOT / "build" / "mutation-smoke"
                if keep_dir.exists():
                    shutil.rmtree(keep_dir)
                shutil.copytree(base, keep_dir)
                print(f"临时副本保留在：{keep_dir}")

    total = killed + len(survived)
    print(f"\n结果：{killed}/{total} 个变异被杀死")
    if skipped:
        print("跳过的变异（源码片段已变化，请更新：")
        for label in skipped:
            print(f"  - {label}")
        print("）")
        return 1
    if survived:
        print("存活变异（需补断言或调整变异）：")
        for label in survived:
            print(f"  - {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
