"""Sidecar entrypoint for PyInstaller / Electron packaging.

Set CNKI_DATA_DIR before importing app.main: configuration and the SQLAlchemy engine
are created at import time.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CNKI Scholar AI FastAPI sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        os.environ["CNKI_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("CNKI_LOG_LEVEL", args.log_level)

    import uvicorn

    from app.main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower(), access_log=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - packaging diagnostics
        print(f"sidecar failed: {exc}", file=sys.stderr)
        raise
