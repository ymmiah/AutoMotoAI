"""
AutoMoto AI  —  entry point.

Usage:
  python main.py                # desktop GUI (default)
  python main.py --mode web     # web server only
  python main.py --mode both    # desktop GUI + web server
  python main.py --mode web --port 8080
"""
from __future__ import annotations

import argparse
import sys
import threading

from src.core.config import app_config, server_config
from src.core.logging_config import setup_logging


def _run_desktop():
    from src.ui.desktop.app import DesktopApp
    DesktopApp().run()


def _run_web():
    from src.ui.web.server import start_server
    start_server()


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description=f"{app_config.name} v{app_config.version}",
    )
    parser.add_argument(
        "--mode",
        choices=["desktop", "web", "both"],
        default="desktop",
        help="Launch mode (default: desktop)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Web server port (overrides WEB_PORT in .env)",
    )
    args = parser.parse_args()

    if args.port is not None:
        server_config.port = args.port

    if args.mode == "desktop":
        _run_desktop()
    elif args.mode == "web":
        _run_web()
    elif args.mode == "both":
        # Web server runs in a daemon thread; desktop owns the main thread
        web_thread = threading.Thread(target=_run_web, daemon=True, name="web-server")
        web_thread.start()
        _run_desktop()


if __name__ == "__main__":
    main()
