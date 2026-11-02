"""Durable job queue helpers (SQLite-backed)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.constants import JobStatus
from app.core.logging import get_logger
from app.models import BackgroundJob

logger = get_logger(__name__)


def enqueue_job(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    *,
    dedupe_key: str | None = None,
    priority: int = 5,
    task_id: str | None = None,
    max_attempts: int = 3,
    commit: bool = True,
) -> BackgroundJob:
    """Add a job, idempotently when dedupe_key is supplied.

    An existing pending/running job with the same dedupe key is returned instead of
    creating a duplicate (prevents double AI calls / double parsing).
    """
    if dedupe_key:
        existing = db.query(BackgroundJob).filter(BackgroundJob.dedupe_key == dedupe_key).first()
        if existing:
            if existing.status in (JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING):
                return existing
            # dedupe_key is globally unique (SQLite cannot express a partial unique
            # index here). Release the key from a finished job so the same work can be
            # re-run; the old job keeps its id and history.
            existing.dedupe_key = None
            db.flush()
    job = BackgroundJob(
        job_type=job_type,
        status=JobStatus.PENDING,
        payload=payload or {},
        priority=priority,
        max_attempts=max_attempts,
        dedupe_key=dedupe_key,
        task_id=task_id,
    )
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
        logger.info("Enqueued job %s (%s)", job.id, job_type)
    return job


def cancel_job(db: Session, job: BackgroundJob) -> None:
    if job.status == JobStatus.PENDING:
        job.status = JobStatus.CANCELLED
    elif job.status == JobStatus.RUNNING:
        job.status = JobStatus.CANCELLING
        job.cancel_requested = 1
    db.commit()
