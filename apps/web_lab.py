"""一键打开主站 + 子站两个 Web 窗口（联调）."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    py = sys.executable
    master = ROOT / "apps" / "web_master.py"
    slave = ROOT / "apps" / "web_slave.py"
    p1 = subprocess.Popen([py, str(master), "--http-port", "8765"])
    p2 = subprocess.Popen([py, str(slave), "--http-port", "8766"])
    try:
        p1.wait()
    finally:
        p2.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
