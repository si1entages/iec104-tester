"""PyInstaller 打包脚本 — Windows exe / Linux 可执行文件."""

import subprocess
import sys
import platform
from pathlib import Path


def build_windows():
    """打包为 Windows exe."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "IEC104Tester",
        "--windowed",                    # 无控制台窗口
        "--noconfirm",
        "--clean",
        "--add-data", "configs;configs",
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
        "app.py",
    ]

    if Path("resources/icon.ico").exists():
        cmd.insert(4, "--icon")
        cmd.insert(5, "resources/icon.ico")

    print(f"Building for Windows...")
    print(f"Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("\n✅ Build complete: dist/IEC104Tester/")


def build_linux():
    """打包为 Linux 可执行文件."""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "iec104-tester",
        "--onefile",                     # 单文件
        "--noconfirm",
        "--clean",
        "--add-data", "configs:configs",
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
        "app.py",
    ]

    print(f"Building for Linux...")
    print(f"Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print("\n✅ Build complete: dist/iec104-tester")


def main():
    system = platform.system()
    print(f"IEC 60870-5-104 Tester — Build Script")
    print(f"Platform: {system}")
    print(f"Python: {sys.version}")
    print()

    if system == "Windows":
        build_windows()
    elif system == "Linux":
        build_linux()
    else:
        print(f"Unsupported platform: {system}")
        print("Falling back to Linux build...")
        build_linux()


if __name__ == "__main__":
    main()
