"""Maintenance helpers: automatic local backups and index housekeeping."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import SessionLocal
from app.services.export_service import create_backup
from app.services.log_service import log_event
from app.services.settings_service import SettingsService

logger = get_logger(__name__)


def maybe_auto_backup() -> dict | None:
    settings = get_settings()
    with SessionLocal() as db:
        enabled = bool(SettingsService(db).get("data.auto_backup", False))
        if not enabled:
            return None
        existing = sorted(
            settings.backups_dir.glob("cnki_backup_*.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if existing:
            newest = datetime.fromtimestamp(existing[0].stat().st_mtime, tz=timezone.utc)
            if datetime.now(timezone.utc) - newest < timedelta(hours=24):
                return None
        try:
            result = create_backup(db)
            log_event(db, f"自动备份完成：{result['filename']}", commit=True)
            return result
        except Exception as exc:  # pragma: no cover - depends on disk state
            logger.exception("Automatic backup failed")
            log_event(db, f"自动备份失败：{exc}", level="error", commit=True)
            return None


async def auto_backup_loop(stop_event: asyncio.Event) -> None:
    """Check hourly; never blocks startup and never raises out of the loop."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3600)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            await asyncio.to_thread(maybe_auto_backup)
        except Exception:  # pragma: no cover
            logger.exception("auto backup loop error")
