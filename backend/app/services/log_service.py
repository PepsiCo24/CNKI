"""Chronological task/job log helper."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.utils import utcnow
from app.models import TaskLog


def log_event(
    db: Session,
    message: str,
    *,
    task_id: str | None = None,
    job_id: str | None = None,
    level: str = "info",
    detail: dict | None = None,
    commit: bool = False,
) -> TaskLog:
    entry = TaskLog(
        task_id=task_id,
        job_id=job_id,
        level=level,
        message=message[:2000],
        detail=detail or {},
        created_at=utcnow(),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
