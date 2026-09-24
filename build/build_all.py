"""构建 IEC104 主站 / 子站可执行文件.

用法:
  python build/build_all.py
  python build/build_all.py --onefile
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_one(entry: Path, name: str, onefile: bool) -> Path:
    dist = ROOT / "dist"
    work = ROOT / "build" / f"work_{name}"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", name,
        "--paths", str(ROOT),
        "--distpath", str(dist),
        "--workpath", str(work),
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.extend(["--onedir"])
    # 窗口应用，不弹控制台
    cmd.append("--windowed")
    icon = ROOT / "resources" / "icon.svg"
    # PyInstaller 不直接支持 svg，跳过
    cmd.append(str(entry))
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)
    out = dist / (name + (".exe" if sys.platform == "win32" else ""))
    if not onefile and sys.platform == "win32":
        out = dist / name / (name + ".exe")
    print("built:", out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onefile", action="store_true")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("请先安装: pip install pyinstaller")
        return 1

    results = []
    results.append(build_one(ROOT / "apps" / "web_master.py", "iec104-master", args.onefile))
    results.append(build_one(ROOT / "apps" / "web_slave.py", "iec104-slave", args.onefile))
    print("全部完成:")
    for r in results:
        print(" -", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
