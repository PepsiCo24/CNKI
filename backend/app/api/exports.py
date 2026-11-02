"""Export and backup endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import safe_filename
from app.database.session import get_db
from app.schemas import ExportRequest
from app.services.export_service import create_backup, export_papers, list_exports
from app.services.log_service import log_event
from app.tasks.queue import enqueue_job

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("")
def create_export(payload: ExportRequest, db: Session = Depends(get_db)):
    result = export_papers(
        db,
        fmt=payload.format,
        paper_ids=payload.paper_ids,
        filters=payload.filters,
        include_notes=payload.include_notes,
        include_analysis=payload.include_analysis,
    )
    log_event(
        db,
        f"导出 {result['paper_count']} 篇文献（{payload.format}）",
        detail={"filename": result["filename"]},
        commit=True,
    )
    return ok(result, message="导出完成")


@router.post("/async")
def create_export_async(payload: ExportRequest, db: Session = Depends(get_db)):
    job = enqueue_job(
        db,
        "export",
        {
            "format": payload.format,
            "paper_ids": payload.paper_ids,
            "filters": payload.filters,
            "include_notes": payload.include_notes,
            "include_analysis": payload.include_analysis,
        },
        priority=8,
        commit=True,
    )
    return ok({"job_id": job.id}, message="导出任务已排队")


@router.get("")
def exports_index():
    return ok({"items": list_exports()})


@router.post("/backup")
def backup_now(db: Session = Depends(get_db)):
    result = create_backup(db)
    log_event(db, f"创建本地备份：{result['filename']}", commit=True)
    return ok(result, message="备份完成（不包含 PDF 全文）")


@router.post("/backup/async")
def backup_async(db: Session = Depends(get_db)):
    job = enqueue_job(db, "backup", {}, priority=8, commit=True)
    return ok({"job_id": job.id}, message="备份任务已排队")


@router.get("/backups")
def list_backups():
    settings = get_settings()
    files = sorted(settings.backups_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return ok(
        {
            "items": [
                {
                    "filename": path.name,
                    "size_bytes": path.stat().st_size,
                    "created_at": path.stat().st_mtime,
                    "download_url": f"/api/exports/backups/{path.name}",
                }
                for path in files
            ]
        }
    )


@router.get("/backups/{filename}")
def download_backup(filename: str):
    settings = get_settings()
    path = (settings.backups_dir / safe_filename(filename)).resolve()
    if settings.backups_dir.resolve() not in path.parents or not path.exists():
        raise NotFoundError("备份文件不存在")
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.get("/files/{filename}")
def download_export(filename: str):
    settings = get_settings()
    safe = safe_filename(filename)
    for base in (settings.exports_dir, settings.backups_dir):
        path = (base / safe).resolve()
        if base.resolve() in path.parents and path.exists():
            return FileResponse(path, filename=path.name)
    raise NotFoundError("导出文件不存在")
