"""IEC104 子站入口 — 服务端（可独立供第三方主站连接，或与本工具主站联调）."""

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
    parser = argparse.ArgumentParser(description="IEC104 子站测试工具")
    parser.add_argument("--host", default="0.0.0.0")
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
    from gui.slave_app import SlaveMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("IEC104 Slave")
    app.setOrganizationName("IEC104Tester")
    apply_theme(app, args.theme)

    cfg = AppConfig()
    cfg.mode = "slave"
    cfg.connection.host = args.host
    cfg.connection.port = args.port
    cfg.connection.common_addr = args.common_addr
    cfg.display.theme = args.theme

    win = SlaveMainWindow(cfg)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
