"""PyInstaller Windows 打包脚本.

用法:
    python build/build_windows.py
    python build/build_windows.py --icon resources/icon.ico
"""

import subprocess
import sys
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="IEC104 Tester Windows 打包")
    parser.add_argument("--icon", default="resources/icon.ico", help="图标文件路径")
    parser.add_argument("--name", default="IEC104Tester", help="输出名称")
    parser.add_argument("--console", action="store_true", help="显示控制台窗口")
    parser.add_argument("--onefile", action="store_true", help="打包为单文件")
    args = parser.parse_args()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", args.name,
        "--noconfirm",
        "--clean",
        "--add-data", "configs;configs",
        "--add-data", "resources;resources",
        "--hidden-import", "PySide6.QtSvg",
        "--hidden-import", "PySide6.QtWidgets",
        "--hidden-import", "PySide6.QtCore",
        "--hidden-import", "PySide6.QtGui",
        "--collect-all", "PySide6",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        "--exclude-module", "PIL",
    ]

    if not args.console:
        cmd.append("--windowed")

    if args.onefile:
        cmd.append("--onefile")

    icon_path = Path(args.icon)
    if icon_path.exists():
        cmd.extend(["--icon", str(icon_path)])
        print(f"Using icon: {icon_path}")
    else:
        print(f"Warning: Icon not found at {icon_path}, using default")

    cmd.append("app.py")

    print(f"IEC 60870-5-104 Tester — Windows Build")
    print(f"Python: {sys.version}")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"\n✅ Build complete: dist/{args.name}/")
    else:
        print(f"\n❌ Build failed (exit code {result.returncode})")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
