"""构建 IEC104 主站 / 子站可执行文件.

用法:
  python build/build_all.py
  python build/build_all.py --onefile
  python build/build_all.py --skip-frontend   # 跳过 npm 前端构建

产物为两个独立 exe（主站 iec104-master、子站 iec104-slave），双击即用。
纯 Web 形态：不打包桌面壳，保留控制台以便查看"服务已启动"提示与关闭服务。
静态页 / 配置 / 资源目录通过 --add-data 打入包内，分隔符用 os.pathsep 跨平台。

打包前默认先构建新前端（T10）：`webui/frontend` 经 vite build 输出到
`webui/static/app/`，随 `webui/static` 一并进包。若无 node/npm 则跳过并告警，
不阻断后端打包（旧原生页仍可用）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "webui" / "frontend"

# Windows CI/控制台的默认编码可能是 cp1252/cp936，中文提示会触发
# UnicodeEncodeError（GitHub Actions windows runner 实测）。仅统一**控制台输出**
# 为 UTF-8，不影响文件读写与 PyInstaller 产物。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 需要随包分发的数据目录：源目录(相对 ROOT) -> 包内目标路径
ADD_DATA = [
    ("webui/static", "webui/static"),
    ("configs", "configs"),
    ("resources", "resources"),
    # E1 Web 测试中心：随包分发 YAML 测试脚本，否则打包版“脚本列表”为空
    ("tests/scripts", "tests/scripts"),
]


def build_frontend() -> bool:
    """构建新前端（Vite 产物 → webui/static/app/）.

    返回 True 表示已执行构建；npm 缺失时返回 False（跳过，不阻断打包）。
    """
    npm = shutil.which("npm")
    if not npm:
        print("[frontend] 未找到 npm，跳过前端构建；"
              "将使用仓库内既有的 webui/static/app（若存在）")
        return False
    if (FRONTEND / "package-lock.json").is_file():
        install_cmd = [npm, "ci"]
    else:
        install_cmd = [npm, "install"]
    print("[frontend]", " ".join(install_cmd))
    subprocess.check_call(install_cmd, cwd=FRONTEND)
    print("[frontend]", npm, "run build")
    subprocess.check_call([npm, "run", "build"], cwd=FRONTEND)
    return True



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
    parser.add_argument("--skip-frontend", action="store_true",
                        help="跳过 npm 前端构建（复用 webui/static/app 现有产物）")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("请先安装: pip install pyinstaller")
        return 1

    if args.skip_frontend:
        print("[frontend] 已按 --skip-frontend 跳过前端构建")
    else:
        try:
            build_frontend()
        except subprocess.CalledProcessError as exc:
            print(f"[frontend] 前端构建失败（退出码 {exc.returncode}）；"
                  "如需仅打后端可用 --skip-frontend")
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
