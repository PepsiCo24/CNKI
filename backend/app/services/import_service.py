"""Metadata-file import and directory import orchestration."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import JobStatus, TaskStatus
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.utils import safe_filename, utcnow
from app.models import ImportJob, SearchTask
from app.parsers.metadata import FORMAT_LABELS, parse_metadata_file
from app.services import serializers
from app.services.file_service import (
    METADATA_EXTENSIONS,
    list_watchable_files,
    register_file,
    register_metadata_record,
)
from app.services.log_service import log_event
from app.services.matching import match_record
from app.services.settings_service import SettingsService
from app.services.task_service import refresh_counters
from app.tasks.queue import enqueue_job

logger = get_logger(__name__)


def import_metadata_bytes(
    db: Session,
    *,
    filename: str,
    data: bytes,
    task_id: str | None = None,
    forced_format: str = "auto",
    create_job: bool = True,
    store_copy: bool = True,
) -> dict:
    settings = get_settings()
    stored: Path | None = None
    if store_copy:
        raw_dir = settings.metadata_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        stored = raw_dir / f"{stamp}_{safe_filename(filename, max_bytes=100)}"
        stored.write_bytes(data)

    records, fmt, parse_errors = parse_metadata_file(filename, data, forced_format)
    task = db.get(SearchTask, task_id) if task_id else None
    if task_id and not task:
        raise NotFoundError("检索任务不存在")

    job: ImportJob | None = None
    if create_job:
        job = ImportJob(
            job_type="metadata_import",
            status=JobStatus.RUNNING,
            source_path=str(stored or filename),
            task_id=task_id,
            total=len(records),
            started_at=utcnow(),
        )
        db.add(job)
        db.flush()

    imported = duplicates = skipped = suspected = 0
    errors = list(parse_errors)
    detail_rows: list[dict] = []
    for record in records:
        if task:
            match = match_record(task, record.as_paper_fields())
            if not match.matched:
                skipped += 1
                detail_rows.append(
                    {
                        "title": record.title[:120],
                        "status": "skipped",
                        "reasons": match.reasons,
                        "mismatches": match.mismatches,
                    }
                )
                continue
        else:
            match = None
        paper, status, message = register_metadata_record(
            db, record, task=task, metadata_source=FORMAT_LABELS.get(fmt, fmt.upper())
        )
        if status == "imported":
            imported += 1
        elif status == "duplicate":
            duplicates += 1
        elif status == "suspected":
            suspected += 1
            imported += 1
        else:
            errors.append({"title": record.title[:120], "error": message})
        detail_rows.append(
            {
                "title": record.title[:120],
                "paper_id": paper.id if paper else None,
                "status": status,
                "message": message,
                "match_score": match.score if match else None,
                "mismatches": match.mismatches if match else [],
            }
        )
    db.flush()

    if job is None:
        return {
            "imported": imported,
            "duplicates": duplicates,
            "suspected": suspected,
            "skipped": skipped,
            "failed": len(errors),
            "total": len(records),
            "format": fmt,
            "errors": errors[:100],
            "rows": detail_rows[:200],
        }

    job.imported = imported
    job.duplicates = duplicates
    job.processed = len(records)
    job.failed = len(errors)
    job.errors = errors[:100]
    job.detail = {
        "format": fmt,
        "suspected": suspected,
        "skipped": skipped,
        "rows": detail_rows[:200],
        "stored_file": str(stored) if stored else "",
    }
    job.status = JobStatus.COMPLETED
    job.finished_at = utcnow()
    if task:
        task.last_run_at = utcnow()
        task.status = "awaiting_import" if task.status in ("pending", "running", "failed") else task.status
        refresh_counters(db, task.id)
    db.commit()
    log_event(
        db,
        f"题录导入完成：{filename}（{FORMAT_LABELS.get(fmt, fmt)}，导入 {imported}，重复 {duplicates}，跳过 {skipped}）",
        task_id=task_id,
        job_id=job.background_job_id,
        detail={"job_id": job.id, "format": fmt, "errors": len(errors)},
        commit=True,
    )
    result = serializers.import_job_out(job)
    result["detail"]["suspected"] = suspected
    return result


def queue_folder_scan(
    db: Session, *, directory: str | None = None, task_id: str | None = None, origin: str = "folder_scan"
) -> dict:
    settings = get_settings()
    target = Path(directory) if directory else Path(str(settings.get("data.import_dir") or settings.imports_dir))
    if not target.exists() or not target.is_dir():
        raise NotFoundError(f"目录不存在：{target}")
    task = db.get(SearchTask, task_id) if task_id else None
    if task_id and not task:
        raise NotFoundError("检索任务不存在")
    import_job = ImportJob(
        job_type="folder_scan",
        status=JobStatus.PENDING,
        source_path=str(target),
        task_id=task_id,
        detail={"origin": origin},
    )
    db.add(import_job)
    db.flush()
    bg = enqueue_job(
        db,
        "scan_folder",
        {
            "directory": str(target),
            "import_job_id": import_job.id,
            "task_id": task_id,
            "origin": origin,
        },
        dedupe_key=f"scan:{target}:{task_id or 'all'}",
        priority=4,
        commit=False,
    )
    import_job.background_job_id = bg.id
    if task:
        task.status = "running"
        task.started_at = task.started_at or utcnow()
        task.last_run_at = utcnow()
    db.commit()
    return serializers.import_job_out(import_job)


def scan_directory(db: Session, import_job_id: str, directory: str, task_id: str | None = None) -> dict:
    """Executed by the background worker; updates ImportJob progressively."""
    job = db.get(ImportJob, import_job_id)
    if not job:
        raise NotFoundError("导入任务不存在")
    target = Path(directory)
    include_metadata = bool(SettingsService(db).get("cnki.auto_import_downloads", True))
    files = list_watchable_files(target)
    if not include_metadata:
        files = [path for path in files if path.suffix.lower() not in METADATA_EXTENSIONS]
    job.total = len(files)
    job.status = JobStatus.RUNNING
    job.started_at = utcnow()
    db.commit()
    task = db.get(SearchTask, task_id) if task_id else None
    imported = duplicates = suspected = failed = skipped = 0
    errors: list[dict] = []
    rows: list[dict] = []
    for index, path in enumerate(files, start=1):
        try:
            if path.suffix.lower() in METADATA_EXTENSIONS:
                result = import_metadata_bytes(
                    db,
                    filename=path.name,
                    data=path.read_bytes(),
                    task_id=task_id,
                    create_job=False,
                    store_copy=False,
                )
                imported += result["imported"]
                duplicates += result["duplicates"]
                suspected += result["suspected"]
                skipped += result["skipped"]
                failed += result["failed"]
                for error in result["errors"]:
                    errors.append({"file": path.name, "error": error.get("error", "题录解析失败")})
                rows.append(
                    {
                        "file": path.name,
                        "status": "metadata",
                        "message": f"题录 {result['total']} 条：导入 {result['imported']}，重复 {result['duplicates']}，跳过 {result['skipped']}",
                    }
                )
                job.detail = {
                    "origin": "folder_scan",
                    "suspected": suspected,
                    "skipped": skipped,
                    "rows": rows[-200:],
                }
            else:
                outcome = register_file(db, source=path, task=task, origin="folder_scan", auto_parse=True)
                if outcome.status == "failed":
                    failed += 1
                    errors.append({"file": path.name, "error": outcome.message})
                elif outcome.status == "duplicate":
                    duplicates += 1
                elif outcome.status == "suspected":
                    suspected += 1
                    imported += 1
                else:
                    imported += 1
                rows.append(
                    {
                        "file": path.name,
                        "status": outcome.status,
                        "paper_id": outcome.paper.id if outcome.paper else None,
                        "message": outcome.message,
                    }
                )
        except Exception as exc:  # one bad file must not abort the batch
            db.rollback()
            failed += 1
            errors.append({"file": path.name, "error": str(exc)[:300]})
            logger.exception("Import failed for %s", path)
        job.processed = index
        job.imported = imported
        job.duplicates = duplicates
        job.failed = failed
        job.errors = errors[:100]
        job.detail = {
            "origin": "folder_scan",
            "suspected": suspected,
            "skipped": skipped,
            "rows": rows[-200:],
        }
        db.commit()
    job.status = JobStatus.COMPLETED
    job.finished_at = utcnow()
    if task:
        committed = db.query(SearchTask.status).filter(SearchTask.id == task.id).scalar()
        if committed in (TaskStatus.CANCELLED, TaskStatus.PAUSED):
            task.status = committed
        elif task.status not in (TaskStatus.CANCELLED, TaskStatus.PAUSED):
            task.status = TaskStatus.AWAITING_IMPORT
        task.last_run_at = utcnow()
        refresh_counters(db, task.id)
    db.commit()
    log_event(
        db,
        f"目录导入完成：{directory}（发现 {len(files)}，导入 {imported}，重复 {duplicates}，跳过 {skipped}，失败 {failed}）",
        task_id=task_id,
        detail={"job_id": job.id},
        commit=True,
    )
    return serializers.import_job_out(job)
