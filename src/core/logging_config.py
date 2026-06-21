"""Logging initialisation — call setup_logging() once at startup."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from src.core.config import app_config


def setup_logging() -> None:
    log_dir: Path = app_config.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, app_config.log_level.upper(), logging.INFO))

    if not root.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

        fh = logging.handlers.RotatingFileHandler(
            log_dir / "automotoai.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
