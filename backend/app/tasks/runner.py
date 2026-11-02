"""Persistent in-process job runner.

SQLite is the queue: a job is claimed by an atomic status transition, so a crash mid-run
leaves a ``running`` row that is reset to ``pending`` on the next startup. Domain results
are committed as they are produced, so completed work is never lost.
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.constants import AiStatus, JobStatus, JobType
from app.core.logging import get_logger
from app.core.utils import utcnow
from app.database.session import SessionLocal
from app.models import AiAnalysisJob, BackgroundJob, ImportJob
from app.tasks import handlers

logger = get_logger(__name__)


class JobRunner:
    def __init__(self) -> None:
        self.starting = False
        self.stopping = False
        self._loop_task: asyncio.Task | None = None
        self._active: dict[str, asyncio.Task] = {}
        self._ai_active = 0
        self._settings = get_settings()
        self._ai_limit_cache = max(1, self._settings.ai_concurrency)
        self._ai_limit_at = 0.0

    # ----------------------------------------------------------------- lifecycle
    def recover(self) -> dict:
        db = SessionLocal()
        try:
            running = db.query(BackgroundJob).filter(BackgroundJob.status == JobStatus.RUNNING).all()
            for job in running:
                job.status = JobStatus.PENDING
                job.started_at = None
                job.message = "进程重启后重新排队"
                job.error = (job.error + "\n" if job.error else "") + "检测到进程中断，任务已安全重新排队"
            cancelling = db.query(BackgroundJob).filter(BackgroundJob.status == JobStatus.CANCELLING).all()
            for job in cancelling:
                job.status = JobStatus.CANCELLED
                job.finished_at = utcnow()
            ai_running = db.query(AiAnalysisJob).filter(AiAnalysisJob.status == AiStatus.RUNNING).all()
            for job in ai_running:
                job.status = AiStatus.QUEUED
            imports = db.query(ImportJob).filter(ImportJob.status == JobStatus.RUNNING).all()
            for job in imports:
                job.status = JobStatus.PENDING
            db.commit()
            return {"requeued": len(running), "cancelled": len(cancelling), "ai_reset": len(ai_running)}
        finally:
            db.close()

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self.recover()
        self.stopping = False
        self._loop_task = asyncio.create_task(self._loop(), name="job-runner")
        logger.info(
            "Job runner started (workers=%s, ai_concurrency=%s)",
            self._settings.worker_concurrency,
            self._settings.ai_concurrency,
        )

    async def stop(self) -> None:
        self.stopping = True
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in list(self._active.values()):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active.values(), return_exceptions=True)
        self._active.clear()
        db = SessionLocal()
        try:
            for job in db.query(BackgroundJob).filter(BackgroundJob.status == JobStatus.RUNNING).all():
                job.status = JobStatus.PENDING
                job.started_at = None
                job.message = "服务停止，任务已重新排队"
            db.commit()
        finally:
            db.close()
        logger.info("Job runner stopped")

    @property
    def is_running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    # --------------------------------------------------------------------- loop
    async def _loop(self) -> None:
        while not self.stopping:
            try:
                await self._process_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover
                logger.exception("Job runner loop error")
            await asyncio.sleep(0.6)

    async def _process_once(self) -> None:
        settings = self._settings
        if len(self._active) >= max(1, settings.worker_concurrency):
            return
        job = self._claim_next(allow_ai=self._ai_active < self._current_ai_limit())
        if not job:
            return
        task = asyncio.create_task(self._execute(job.id), name=f"job-{job.id}")
        self._active[job.id] = task
        if job.job_type == JobType.ANALYZE_PAPER:
            self._ai_active += 1

        def _done(_task: asyncio.Task, job_id: str = job.id, is_ai: bool = job.job_type == JobType.ANALYZE_PAPER):
            self._active.pop(job_id, None)
            if is_ai:
                self._ai_active = max(0, self._ai_active - 1)

        task.add_done_callback(_done)

    def _current_ai_limit(self) -> int:
        """Read the UI-configurable AI concurrency with a short cache."""
        import time

        now = time.monotonic()
        if now - self._ai_limit_at > 5:
            self._ai_limit_at = now
            db = SessionLocal()
            try:
                from app.services.settings_service import SettingsService

                self._ai_limit_cache = max(1, int(SettingsService(db).get("ai.concurrency", 1)))
            except Exception:
                pass
            finally:
                db.close()
        return self._ai_limit_cache

    def _claim_next(self, *, allow_ai: bool) -> BackgroundJob | None:
        db = SessionLocal()
        try:
            query = db.query(BackgroundJob).filter(BackgroundJob.status == JobStatus.PENDING)
            if not allow_ai:
                query = query.filter(BackgroundJob.job_type != JobType.ANALYZE_PAPER)
            job = query.order_by(BackgroundJob.priority.asc(), BackgroundJob.created_at.asc()).first()
            if not job:
                return None
            job.status = JobStatus.RUNNING
            job.attempts = (job.attempts or 0) + 1
            job.started_at = utcnow()
            job.message = "执行中"
            db.commit()
            db.refresh(job)
            db.expunge(job)
            return job
        finally:
            db.close()

    async def _execute(self, job_id: str) -> None:
        db = SessionLocal()
        try:
            job = db.get(BackgroundJob, job_id)
            if not job:
                return
            payload = dict(job.payload or {})
            job_type = job.job_type
            cancel_requested = bool(job.cancel_requested)
        finally:
            db.close()
        if cancel_requested:
            self._finish(job_id, JobStatus.CANCELLED, "任务在开始前被取消")
            return
        try:
            if job_type == JobType.PARSE_PAPER:
                await asyncio.to_thread(handlers.handle_parse_paper, payload)
            elif job_type == JobType.ANALYZE_PAPER:
                await handlers.handle_analyze_paper(job_id, payload)
            elif job_type == JobType.SCAN_FOLDER:
                await handlers.handle_scan_folder(job_id, payload)
            elif job_type == JobType.IMPORT_METADATA:
                await asyncio.to_thread(handlers.handle_import_metadata, payload)
            elif job_type == JobType.RUN_SEARCH_TASK:
                await asyncio.to_thread(handlers.handle_run_search_task, payload)
            elif job_type == JobType.EXPORT:
                await asyncio.to_thread(handlers.handle_export, job_id, payload)
            elif job_type == JobType.REBUILD_INDEX:
                payload["job_id"] = job_id
                await asyncio.to_thread(handlers.handle_rebuild_index, payload)
            elif job_type == JobType.BACKUP:
                payload["job_id"] = job_id
                await asyncio.to_thread(handlers.handle_backup, payload)
            elif job_type == JobType.SILENT_CAPTURE:
                await asyncio.to_thread(handlers.handle_silent_capture, job_id, payload)
            else:
                raise ValueError(f"未知任务类型：{job_type}")
            self._finish(job_id, JobStatus.COMPLETED, "执行完成")
        except handlers.JobCancelled:
            self._finish(job_id, JobStatus.CANCELLED, "任务已取消")
        except Exception as exc:
            await self._handle_failure(job_id, exc)

    def _finish(self, job_id: str, status: str, message: str) -> None:
        db = SessionLocal()
        try:
            job = db.get(BackgroundJob, job_id)
            if not job:
                return
            job.status = status
            job.finished_at = utcnow()
            job.progress = 100
            # Handlers may have written a more useful completion message (filename,
            # analysis summary, …); only replace the generic "running" placeholder.
            if not (status == JobStatus.COMPLETED and job.message and job.message != "执行中"):
                job.message = message
            if status == JobStatus.COMPLETED:
                job.error = ""
            if status == JobStatus.CANCELLED and job.job_type == JobType.SILENT_CAPTURE:
                from app.services.capture_service import ensure_session_cancelled

                session_id = str((job.payload or {}).get("session_id") or "")
                if session_id:
                    ensure_session_cancelled(db, session_id)
            db.commit()
            if status == JobStatus.COMPLETED:
                logger.info("Job %s completed", job_id)
            else:
                logger.warning("Job %s finished: %s", job_id, message)
        finally:
            db.close()

    async def _handle_failure(self, job_id: str, exc: Exception) -> None:
        error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-6000:]
        logger.error("Job %s failed: %s", job_id, exc)
        await asyncio.sleep(0.5)
        db = SessionLocal()
        try:
            job = db.get(BackgroundJob, job_id)
            if not job:
                return
            if job.cancel_requested:
                job.status = JobStatus.CANCELLED
                job.finished_at = utcnow()
                db.commit()
                return
            job.error = error_text
            job.message = str(exc)[:500]
            if job.attempts < job.max_attempts:
                job.status = JobStatus.PENDING
                job.started_at = None
                db.commit()
                logger.warning("Job %s requeued (%s/%s)", job_id, job.attempts, job.max_attempts)
            else:
                job.status = JobStatus.FAILED
                job.finished_at = utcnow()
                db.commit()
                logger.error("Job %s permanently failed", job_id)
        finally:
            db.close()


runner = JobRunner()


def runner_status() -> dict:
    return {
        "running": runner.is_running,
        "active": len(runner._active),
        "worker_concurrency": get_settings().worker_concurrency,
        "ai_concurrency": get_settings().ai_concurrency,
    }


def cancel_background_job(db, job: BackgroundJob) -> None:
    if job.status == JobStatus.PENDING:
        job.status = JobStatus.CANCELLED
        job.finished_at = utcnow()
    elif job.status == JobStatus.RUNNING:
        job.status = JobStatus.CANCELLING
        job.cancel_requested = 1
    db.commit()
