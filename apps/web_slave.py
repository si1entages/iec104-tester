"""IEC104 子站 — Web 桌面壳（pywebview）.

用法:
  python apps/web_slave.py
  python apps/web_slave.py --http-port 8766 --no-shell
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IEC104 子站 Web UI")
    parser.add_argument("--http-port", type=int, default=8766)
    parser.add_argument("--title", default="IEC104 子站测试工具")
    parser.add_argument("--no-shell", action="store_true", help="不启动窗口，仅 HTTP 服务")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=840)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    from webui.server import run_server

    t = threading.Thread(
        target=run_server, args=("slave", "127.0.0.1", args.http_port),
        daemon=True,
    )
    t.start()

    url = f"http://127.0.0.1:{args.http_port}/"
    if args.no_shell:
        print(f"Slave Web UI: {url}")
        try:
            t.join()
        except KeyboardInterrupt:
            pass
        return 0

    try:
        import webview
    except ImportError:
        print(f"未安装 pywebview，请用浏览器打开: {url}")
        try:
            t.join()
        except KeyboardInterrupt:
            pass
        return 0

    webview.create_window(
        args.title, url, width=args.width, height=args.height,
        background_color="#0f1419",
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
