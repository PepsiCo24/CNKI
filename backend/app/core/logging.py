"""Logging setup: rotating file log under data/logs plus console output.

Secrets are never logged; callers must pass only metadata. The log formatter is
deliberately simple so local users can inspect it with any text editor.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.logs_dir / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s [%(filename)s:%(lineno)d] %(message)s")
    )
    root.addHandler(file_handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("watchdog").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
