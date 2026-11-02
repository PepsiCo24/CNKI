"""Watchdog-based import directory monitor with debounced rescans.

The watcher never processes a file twice: the import path is SHA-256 deduplicated in
``register_file``. Directory events are coalesced so a bulk download triggers one scan.
"""
from __future__ import annotations

import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import SessionLocal
from app.services.import_service import queue_folder_scan
from app.services.settings_service import SettingsService

logger = get_logger(__name__)

SUPPORTED = {".pdf", ".caj", ".ris", ".bib", ".bibtex", ".enw", ".csv"}


class _Handler(FileSystemEventHandler):
    def __init__(self, service: "WatchService"):
        self.service = service

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED or path.name.startswith("."):
            return
        self.service.schedule()


class WatchService:
    def __init__(self) -> None:
        self.observer: Observer | None = None
        self.path: Path | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.RLock()
        self._last_result: str = ""

    @property
    def running(self) -> bool:
        return self.observer is not None and self.observer.is_alive()

    def status(self) -> dict:
        return {
            "running": self.running,
            "path": str(self.path) if self.path else "",
            "last_result": self._last_result,
        }

    def start(self, directory: str | None = None) -> dict:
        settings = get_settings()
        target = Path(directory) if directory else settings.imports_dir
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
        if self.running and self.path == target:
            return {**self.status(), "message": "监听已在运行"}
        # Stop outside our own critical section: Observer.join() must not run while a
        # filesystem event handler is waiting for the same lock.
        self.stop()
        with self._lock:
            if self.running and self.path == target:  # pragma: no cover - the race is benign
                return {**self.status(), "message": "监听已在运行"}
            event_handler = _Handler(self)
            observer = Observer()
            observer.schedule(event_handler, str(target), recursive=True)
            observer.daemon = True
            observer.start()
            self.observer = observer
            self.path = target
            logger.info("Watching import directory: %s", target)
            return {**self.status(), "message": "目录监听已启动"}

    def stop(self) -> dict:
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            observer = self.observer
            self.observer = None
            self.path = None
        if observer:
            observer.stop()
            observer.join(timeout=3)
        return {"running": False, "message": "目录监听已停止"}

    def schedule(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(3.0, self._scan)
            self._timer.daemon = True
            self._timer.start()

    def _scan(self) -> None:
        try:
            with SessionLocal() as db:
                SettingsService(db).set("data.watch_enabled", True)
                job = queue_folder_scan(
                    db, directory=str(self.path) if self.path else None, origin="watcher"
                )
                self._last_result = f"已触发扫描（任务 {job['id'][:8]}）"
                logger.info("Watcher triggered scan: %s", job["id"])
        except Exception as exc:  # pragma: no cover - background thread
            self._last_result = f"扫描失败：{exc}"
            logger.exception("Watcher scan failed")


_watch_service: WatchService | None = None


def get_watch_service() -> WatchService:
    global _watch_service
    if _watch_service is None:
        _watch_service = WatchService()
    return _watch_service


def start_watcher_from_settings() -> None:
    with SessionLocal() as db:
        enabled = bool(SettingsService(db).get("data.watch_enabled", False))
        directory = SettingsService(db).get("data.import_dir") or str(get_settings().imports_dir)
    if enabled:
        try:
            get_watch_service().start(directory)
        except Exception as exc:
            logger.warning("Could not start watcher: %s", exc)


def stop_watcher() -> None:
    get_watch_service().stop()
