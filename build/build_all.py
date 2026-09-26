"""构建 IEC104 主站 / 子站可执行文件.

用法:
  python build/build_all.py
  python build/build_all.py --onefile

产物为两个独立 exe（主站 iec104-master、子站 iec104-slave），双击即用。
纯 Web 形态：不打包桌面壳，保留控制台以便查看"服务已启动"提示与关闭服务。
静态页 / 配置 / 资源目录通过 --add-data 打入包内，分隔符用 os.pathsep 跨平台。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 需要随包分发的数据目录：源目录(相对 ROOT) -> 包内目标路径
ADD_DATA = [
    ("webui/static", "webui/static"),
    ("configs", "configs"),
    ("resources", "resources"),
]


def _add_data_arg(src: str, dest: str) -> str:
    """拼接 PyInstaller --add-data 值，使用 os.pathsep 保证跨平台.

    Windows 分隔符为 ';'，POSIX 为 ':'；硬编码会导致另一端解析失败。
    """
    return f"{src}{os.pathsep}{dest}"


def build_one(entry: Path, name: str, onefile: bool) -> Path:
    dist = ROOT / "dist"
    work = ROOT / "build" / f"work_{name}"
    # --specpath 目录必须已存在，且要与 --workpath 一致，
    # 避免 PyInstaller 把 *.spec 写到仓库根目录污染工作区。
    os.makedirs(work, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", name,
        "--paths", str(ROOT),
        "--distpath", str(dist),
        "--workpath", str(work),
        "--specpath", str(work),
    ]
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.extend(["--onedir"])
    # 纯 Web 形态：保留控制台（不加 --windowed），用户可见启动提示并能 Ctrl+C/关闭窗口停止服务
    for src_rel, dest in ADD_DATA:
        cmd.extend(["--add-data", _add_data_arg(str(ROOT / src_rel), dest)])
    # 图标：PyInstaller 不直接支持 svg，跳过（保持现状）
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
