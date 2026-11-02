"""System information, logs, maintenance endpoints."""
from __future__ import annotations

import platform
import sqlite3
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.config import get_settings
from app.database.fts import rebuild_all
from app.database.session import get_db
from app.models import BackgroundJob, Paper, PaperFile
from app.services.paper_service import duplicates_list
from app.services.settings_service import SettingsService
from app.services.watch_service import get_watch_service
from app.tasks.queue import enqueue_job
from app.tasks.runner import runner, runner_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/info")
def system_info(db: Session = Depends(get_db)):
    settings = get_settings()
    service = SettingsService(db)
    total_size = 0
    count = 0
    for paper in db.query(Paper).filter(Paper.is_deleted.is_(False)).all():
        for file in paper.files:
            if file.relative_path:
                path = settings.data_dir / file.relative_path
                if path.exists():
                    total_size += path.stat().st_size
                    count += 1
    db_bytes = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    return ok(
        {
            "app": settings.app_name,
            "version": "0.1.0",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "data_dir": str(settings.data_dir),
            "database": str(settings.db_path),
            "database_bytes": db_bytes,
            "papers": db.query(func.count(Paper.id)).filter(Paper.is_deleted.is_(False)).scalar() or 0,
            "files": count,
            "fulltext_bytes": total_size,
            "runner": runner_status(),
            "watcher": get_watch_service().status(),
            "ai": {
                "configured": service.is_ai_configured(),
                "provider": service.get("ai.provider", "mock"),
                "model": service.get("ai.model", ""),
            },
            "paths": {
                "papers": str(settings.papers_dir),
                "imports": str(settings.imports_dir),
                "exports": str(settings.exports_dir),
                "logs": str(settings.logs_dir),
                "backups": str(settings.backups_dir),
            },
            "permissions": {
                "cnki_programmatic_download": False,
                "note": "未启用任何未经确认的知网自动化下载能力。",
            },
        }
    )


@router.get("/logs")
def system_logs(lines: int = Query(200, ge=10, le=2000)):
    settings = get_settings()
    log_path = settings.logs_dir / "app.log"
    if not log_path.exists():
        return ok({"lines": [], "path": str(log_path)})
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        content = handle.readlines()[-lines:]
    return ok({"lines": [line.rstrip("\n") for line in content], "path": str(log_path)})


@router.post("/reindex")
def reindex(db: Session = Depends(get_db)):
    count = rebuild_all(db)
    return ok({"indexed": count, "message": "全文索引已重建"})


@router.post("/backup")
def backup_now(db: Session = Depends(get_db)):
    from app.services.export_service import create_backup

    result = create_backup(db)
    return ok(result, message="备份完成")


@router.get("/duplicates")
def duplicates(db: Session = Depends(get_db)):
    return ok({"items": duplicates_list(db)})


@router.get("/jobs")
def list_jobs(
    db: Session = Depends(get_db),
    status: str = "",
    job_type: str = "",
    page: int = 1,
    page_size: int = 30,
):
    from app.services.serializers import job_out

    query = db.query(BackgroundJob)
    if status:
        query = query.filter(BackgroundJob.status == status)
    if job_type:
        query = query.filter(BackgroundJob.job_type == job_type)
    total = query.count()
    jobs = (
        query.order_by(BackgroundJob.created_at.desc())
        .offset((max(1, page) - 1) * max(1, page_size))
        .limit(min(page_size, 100))
        .all()
    )
    return ok(
        {
            "items": [job_out(job) for job in jobs],
            "total": total,
            "page": page,
            "page_size": page_size,
            "runner": runner_status(),
        }
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    from app.core.errors import NotFoundError
    from app.services.serializers import job_out

    job = db.get(BackgroundJob, job_id)
    if not job:
        raise NotFoundError("任务不存在")
    return ok(job_out(job))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    from app.core.errors import NotFoundError
    from app.services.serializers import job_out
    from app.tasks.runner import cancel_background_job

    job = db.get(BackgroundJob, job_id)
    if not job:
        raise NotFoundError("任务不存在")
    cancel_background_job(db, job)
    return ok(job_out(job), message="已请求取消任务")


@router.post("/jobs/retry-failed")
def retry_failed_jobs(db: Session = Depends(get_db)):
    from app.core.utils import utcnow
    from app.core.constants import JobStatus

    jobs = db.query(BackgroundJob).filter(BackgroundJob.status == JobStatus.FAILED).all()
    for job in jobs:
        job.status = JobStatus.PENDING
        job.attempts = 0
        job.error = ""
        job.started_at = None
        job.finished_at = None
    db.commit()
    return ok({"count": len(jobs), "message": "失败任务已重新排队"})
