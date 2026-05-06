"""PyInstaller Linux 打包脚本.

用法:
    python build/build_linux.py
    python build/build_linux.py --onefile
    python build/build_linux.py --appimage
"""

import subprocess
import sys
import argparse
import shutil
from pathlib import Path


def build_pyinstaller(args):
    """使用 PyInstaller 打包."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", args.name,
        "--noconfirm",
        "--clean",
        "--add-data", "configs:configs",
        "--add-data", "resources:resources",
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

    if args.onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    icon_path = Path(args.icon)
    if icon_path.exists():
        print(f"Using icon: {icon_path}")

    cmd.append("app.py")

    print(f"IEC 60870-5-104 Tester — Linux Build")
    print(f"Python: {sys.version}")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)
    if result.returncode == 0:
        output = f"dist/{args.name}" if not args.onefile else f"dist/{args.name}"
        print(f"\n✅ Build complete: {output}")
    else:
        print(f"\n❌ Build failed (exit code {result.returncode})")
        sys.exit(result.returncode)


def build_deb(args):
    """打包为 .deb 包."""
    build_dir = Path("build/deb")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # 创建目录结构
    pkg_dir = build_dir / f"{args.name}_1.0.0_amd64"
    bin_dir = pkg_dir / "usr" / "local" / "bin"
    share_dir = pkg_dir / "usr" / "share" / args.name
    desktop_dir = pkg_dir / "usr" / "share" / "applications"
    deb_dir = pkg_dir / "DEBIAN"

    for d in [bin_dir, share_dir, desktop_dir, deb_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # DEBIAN/control
    control = f"""Package: {args.name.lower()}
Version: 1.0.0
Section: utils
Priority: optional
Architecture: amd64
Maintainer: IEC104 Tester Team
Description: IEC 60870-5-104 Protocol Test Tool
 A comprehensive testing tool for IEC 60870-5-104 protocol
 with master/slave simulation, data monitoring, and more.
"""
    (deb_dir / "control").write_text(control)

    # .desktop 文件
    desktop = f"""[Desktop Entry]
Name=IEC 104 Tester
Comment=IEC 60870-5-104 Protocol Test Tool
Exec=/usr/local/bin/{args.name.lower()}
Icon=/usr/share/{args.name}/icon.png
Terminal=false
Type=Application
Categories=Development;Network;
"""
    (desktop_dir / f"{args.name.lower()}.desktop").write_text(desktop)

    print(f"Debian package structure created at: {pkg_dir}")
    print("Run 'dpkg-deb --build' to create the .deb file")


def main():
    parser = argparse.ArgumentParser(description="IEC104 Tester Linux 打包")
    parser.add_argument("--name", default="iec104-tester", help="输出名称")
    parser.add_argument("--icon", default="resources/icon.svg", help="图标文件路径")
    parser.add_argument("--onefile", action="store_true", help="打包为单文件")
    parser.add_argument("--deb", action="store_true", help="创建 Debian 包结构")
    args = parser.parse_args()

    if args.deb:
        build_deb(args)
    else:
        build_pyinstaller(args)


if __name__ == "__main__":
    main()
