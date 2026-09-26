"""IEC104 子站 Web 入口 — 启动本地 Web 服务并自动打开浏览器.

用法:
  python apps/web_slave.py
  python apps/web_slave.py --http-port 9000 --no-browser
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli(default_role="slave"))
