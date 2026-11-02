"""Metadata file import, uploads and folder scan."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import clean_dir_input, save_upload
from app.api.envelope import ok
from app.core.config import get_settings
from app.core.constants import JobStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.database.session import get_db
from app.models import ImportJob, SearchTask
from app.schemas import ScanRequest
from app.services import serializers
from app.services.file_service import register_file
from app.services.import_service import import_metadata_bytes, queue_folder_scan
from app.services.log_service import log_event
from app.services.task_service import refresh_counters
from app.parsers.metadata import FORMAT_LABELS

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("/formats")
def formats():
    return ok(
        {
            "metadata": [{"id": key, "label": value} for key, value in FORMAT_LABELS.items()],
            "fulltext": [
                {"id": "pdf", "label": "PDF（可解析）"},
                {"id": "caj", "label": "CAJ（保留原文件，不解析）"},
            ],
        }
    )


@router.post("/metadata")
async def import_metadata(
    file: UploadFile = File(...),
    task_id: str | None = Form(None),
    format: str = Form("auto"),
):
    if not file.filename:
        raise ValidationAppError("缺少文件名")
    data = await file.read()
    await file.close()
    if len(data) > 20 * 1024 * 1024:
        raise ValidationAppError("题录文件不能超过 20MB")
    if len(data) == 0:
        raise ValidationAppError("题录文件为空")
    from app.database.session import SessionLocal

    db: Session = SessionLocal()
    try:
        result = import_metadata_bytes(
            db, filename=file.filename, data=data, task_id=task_id, forced_format=format
        )
    finally:
        db.close()
    return ok(result, message="题录导入完成")


@router.post("/files")
async def upload_files(
    files: list[UploadFile] = File(...),
    task_id: str | None = Form(None),
):
    from app.database.session import SessionLocal

    if len(files) > 50:
        raise ValidationAppError("单次最多上传 50 个文件")
    db: Session = SessionLocal()
    outcomes = []
    import_job: ImportJob | None = None
    try:
        task = db.get(SearchTask, task_id) if task_id else None
        if task_id and not task:
            raise NotFoundError("检索任务不存在")
        import_job = ImportJob(
            job_type="file_upload",
            status=JobStatus.RUNNING,
            source_path=f"上传 {len(files)} 个文件",
            task_id=task_id,
            total=len(files),
            started_at=utcnow(),
        )
        db.add(import_job)
        db.commit()
        db.refresh(import_job)
        for upload in files:
            if not upload.filename:
                continue
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in (".pdf", ".caj"):
                outcomes.append({"filename": upload.filename, "status": "failed", "message": "仅支持 PDF/CAJ"})
                await upload.close()
                continue
            temp_path = await save_upload(upload, prefix="upload_")
            try:
                outcome = register_file(db, source=temp_path, task=task, origin="upload", move_source=True)
                outcomes.append(
                    {
                        "filename": upload.filename,
                        "status": outcome.status,
                        "message": outcome.message,
                        "paper_id": outcome.paper.id if outcome.paper else None,
                        "duplicate_of_id": outcome.duplicate_of_id,
                    }
                )
            except Exception as exc:
                db.rollback()
                outcomes.append({"filename": upload.filename, "status": "failed", "message": str(exc)[:300]})
                temp_path.unlink(missing_ok=True)
            if import_job:
                import_job.processed = len(outcomes)
                import_job.imported = sum(1 for item in outcomes if item["status"] in ("imported", "suspected"))
                import_job.duplicates = sum(1 for item in outcomes if item["status"] == "duplicate")
                import_job.failed = sum(1 for item in outcomes if item["status"] == "failed")
                import_job.detail = {"rows": outcomes[-50:], "origin": "upload"}
                import_job.errors = [
                    {"file": item["filename"], "error": item["message"]}
                    for item in outcomes
                    if item["status"] == "failed"
                ]
                db.commit()
        if task:
            refresh_counters(db, task.id)
            task.status = "awaiting_import"
            db.commit()
        if import_job:
            import_job.status = JobStatus.COMPLETED
            import_job.finished_at = utcnow()
            db.commit()
    finally:
        db.close()
    imported = sum(1 for item in outcomes if item["status"] in ("imported", "suspected"))
    return ok({"outcomes": outcomes, "imported": imported, "import_job_id": import_job.id if import_job else None}, message=f"已导入 {imported} 个文件")


@router.post("/scan")
def scan(payload: ScanRequest, db: Session = Depends(get_db)):
    settings = get_settings()
    directory = clean_dir_input(payload.path)
    if directory:
        path = Path(directory)
        if not path.is_absolute():
            # Relative paths are interpreted against the configured import directory.
            path = (settings.imports_dir / directory).resolve()
        directory = str(path)
    else:
        directory = None
    job = queue_folder_scan(db, directory=directory, task_id=payload.task_id, origin="manual_scan")
    return ok(job, message="已加入扫描队列")


@router.get("")
def list_imports(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = "",
    task_id: str = "",
):
    query = db.query(ImportJob)
    if status:
        query = query.filter(ImportJob.status == status)
    if task_id:
        query = query.filter(ImportJob.task_id == task_id)
    total = query.count()
    jobs = (
        query.order_by(ImportJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "items": [serializers.import_job_out(job) for job in jobs],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{import_id}")
def get_import(import_id: str, db: Session = Depends(get_db)):
    job = db.get(ImportJob, import_id)
    if not job:
        raise NotFoundError("导入任务不存在")
    return ok(serializers.import_job_out(job))


@router.post("/{import_id}/retry")
def retry_import(import_id: str, db: Session = Depends(get_db)):
    job = db.get(ImportJob, import_id)
    if not job:
        raise NotFoundError("导入任务不存在")
    if job.job_type == "folder_scan":
        if not Path(job.source_path).exists():
            raise ValidationAppError(f"源目录不存在：{job.source_path}")
        new_job = queue_folder_scan(db, directory=job.source_path, task_id=job.task_id, origin="retry")
        return ok(new_job, message="已重新扫描目录")
    if job.job_type == "metadata_import":
        path = Path(job.source_path)
        if not path.exists():
            raise ValidationAppError("原始题录文件已不存在，请重新上传")
        result = import_metadata_bytes(
            db, filename=path.name, data=path.read_bytes(), task_id=job.task_id, forced_format="auto"
        )
        return ok(result, message="已重新导入题录")
    raise ValidationAppError("该导入任务不支持重试")


@router.delete("/{import_id}")
def delete_import(import_id: str, db: Session = Depends(get_db)):
    job = db.get(ImportJob, import_id)
    if not job:
        raise NotFoundError("导入任务不存在")
    if job.status == JobStatus.RUNNING:
        raise ValidationAppError("任务执行中不能删除")
    db.delete(job)
    db.commit()
    return ok({"id": import_id}, message="导入记录已删除")
