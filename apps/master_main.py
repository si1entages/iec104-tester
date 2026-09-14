"""IEC104 主站入口 — 客户端（可独立连接第三方子站，或与本工具子站联调）."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _ensure_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def main(argv: list[str] | None = None) -> int:
    _ensure_path()
    parser = argparse.ArgumentParser(description="IEC104 主站测试工具")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2404)
    parser.add_argument("--common-addr", type=int, default=1)
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    from PySide6.QtWidgets import QApplication
    from core.config import AppConfig
    from gui.common import apply_theme
    from gui.master_app import MasterMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("IEC104 Master")
    app.setOrganizationName("IEC104Tester")
    apply_theme(app, args.theme)

    cfg = AppConfig()
    cfg.mode = "master"
    cfg.connection.host = args.host
    cfg.connection.port = args.port
    cfg.connection.common_addr = args.common_addr
    cfg.display.theme = args.theme

    win = MasterMainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
