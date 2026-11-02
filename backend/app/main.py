"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.envelope import install_exception_handlers, ok
from app.api.router import api_router
from app.core.config import PROJECT_ROOT, get_settings
from app.core.logging import get_logger, setup_logging
from app.database.init_db import init_db
from app.services.maintenance import auto_backup_loop, maybe_auto_backup
from app.services.watch_service import start_watcher_from_settings, stop_watcher
from app.tasks.runner import runner, runner_status

logger = get_logger(__name__)
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    await runner.start()
    start_watcher_from_settings()
    try:
        await asyncio.to_thread(maybe_auto_backup)
    except Exception:  # backup failure must never prevent startup
        logger.exception("Startup backup check failed")
    backup_stop = asyncio.Event()
    backup_task = asyncio.create_task(auto_backup_loop(backup_stop), name="auto-backup")
    logger.info("%s started at http://%s:%s", settings.app_name, settings.host, settings.port)
    try:
        yield
    finally:
        backup_stop.set()
        backup_task.cancel()
        try:
            await backup_task
        except (asyncio.CancelledError, Exception):
            pass
        stop_watcher()
        await runner.stop()
        logger.info("Application stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CNKI Scholar AI API",
        description=(
            "本地优先的科研文献管理与 AI 创新点筛选系统。"
            "所有数据保存在本地 SQLite 与文件目录中；不包含未授权的知网抓取。"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/api/health", include_in_schema=False)
    async def health_short():
        return ok({"status": "ok", "runner": runner_status()})

    frontend_dist = PROJECT_ROOT / "frontend" / "dist"
    if frontend_dist.exists():
        assets = frontend_dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/") or full_path in ("docs", "openapi.json"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (frontend_dist / full_path).resolve()
            if frontend_dist.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            index = frontend_dist / "index.html"
            if index.exists():
                return FileResponse(index)
            return JSONResponse({"detail": "frontend build not found"}, status_code=404)

    return app


app = create_app()
