"""Launch the local server using .env / environment settings.

Usage:
    python scripts/run_server.py [--reload]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402

from app.core.config import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        reload_dirs=[str(ROOT / "backend")] if args.reload else None,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
