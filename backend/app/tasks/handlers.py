"""Background job handlers. Each handler is idempotent and records domain state."""
from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.analyzer import Analyzer, AnalysisError
from app.core.config import get_settings
from app.core.constants import AiStatus, FulltextStatus, JobStatus, ParseStatus, ReviewStatus
from app.core.errors import NotConfiguredError
from app.core.logging import get_logger
from app.core.utils import utcnow
from app.database.fts import index_paper, rebuild_all
from app.database.session import SessionLocal
from app.models import AiAnalysisJob, BackgroundJob, ImportJob, Paper, PaperFile, PaperText
from app.parsers.pdf_parser import extract_document
from app.services import capture_service
from app.services.analysis_service import request_analysis
from app.services.export_service import create_backup, export_papers
from app.services.file_service import _write_metadata_sidecar
from app.services.import_service import import_metadata_bytes, scan_directory
from app.services.log_service import log_event
from app.services.search_task_service import run_task
from app.services.task_service import refresh_counters
from app.tasks.queue import enqueue_job

logger = get_logger(__name__)


class JobCancelled(Exception):
    pass


def _project_path(relative: str) -> Path:
    settings = get_settings()
    candidate = (settings.data_dir / relative).resolve()
    if settings.data_dir.resolve() not in candidate.parents and candidate != settings.data_dir.resolve():
        raise ValueError("文件路径越界")
    return candidate


def handle_parse_paper(payload: dict[str, Any]) -> None:
    paper_id = payload.get("paper_id")
    file_id = payload.get("file_id")
    db: Session = SessionLocal()
    try:
        paper = db.get(Paper, paper_id)
        if not paper or paper.is_deleted:
            logger.warning("parse job skipped: paper missing %s", paper_id)
            return
        file = db.get(PaperFile, file_id) if file_id else None
        if not file:
            file = next((f for f in paper.files if f.is_primary), None) or (paper.files[0] if paper.files else None)
        if not file:
            paper.parse_status = ParseStatus.FAILED
            paper.review_status = (
                ReviewStatus.PENDING_FULLTEXT
                if paper.review_status not in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED)
                else paper.review_status
            )
            db.commit()
            return
        path = _project_path(file.relative_path)
        file.parse_status = ParseStatus.PENDING
        paper.parse_status = ParseStatus.PENDING
        db.commit()
        if not path.exists():
            raise FileNotFoundError(f"原始文件不存在：{file.relative_path}")
        document = extract_document(path)
        db.query(PaperText).filter(PaperText.paper_id == paper.id).delete()
        if document.content.strip():
            text_row = PaperText(
                paper_id=paper.id,
                file_id=file.id,
                content=document.content,
                page_map=[page.__dict__ for page in document.pages],
                sections=[section.__dict__ for section in document.sections],
                char_count=document.char_count,
                page_count=document.page_count,
                extractor=document.extractor,
                quality=document.quality,
                error=document.error,
            )
            db.add(text_row)
            file.page_count = document.page_count
            file.parse_status = ParseStatus.PARSED if document.quality in ("text", "sparse") else ParseStatus.PARTIAL
            file.parse_error = document.error
            paper.parse_status = file.parse_status
            paper.fulltext_status = FulltextStatus.IMPORTED
            if paper.review_status not in (
                ReviewStatus.INCLUDED,
                ReviewStatus.EXCLUDED,
                ReviewStatus.DEFERRED,
                ReviewStatus.PENDING_REVIEW,
            ):
                paper.review_status = ReviewStatus.PENDING_AI
        else:
            file.parse_status = (
                ParseStatus.UNSUPPORTED if document.quality == "unsupported" else ParseStatus.FAILED
            )
            file.parse_error = document.error or "未提取到文本"
            paper.parse_status = file.parse_status
            if paper.review_status not in (
                ReviewStatus.INCLUDED,
                ReviewStatus.EXCLUDED,
                ReviewStatus.DEFERRED,
                ReviewStatus.PENDING_REVIEW,
            ):
                paper.review_status = ReviewStatus.PENDING_AI
        paper.updated_at = utcnow()
        index_paper(db, paper)
        _write_metadata_sidecar(paper, file)
        log_event(
            db,
            f"全文解析{'成功' if document.content.strip() else '失败'}：{paper.title[:50]}",
            level="info" if document.content.strip() else "warning",
            detail={
                "paper_id": paper.id,
                "chars": document.char_count,
                "page_count": document.page_count,
                "quality": document.quality,
                "error": document.error,
            },
            commit=False,
        )
        db.commit()
        if document.content.strip():
            _maybe_auto_analyze(db, paper.id)
    finally:
        db.close()


def _maybe_auto_analyze(db: Session, paper_id: str) -> None:
    from app.services.settings_service import SettingsService

    settings = SettingsService(db)
    if not bool(settings.get("ai.auto_analyze", True)):
        return
    existing = (
        db.query(AiAnalysisJob)
        .filter(
            AiAnalysisJob.paper_id == paper_id,
            AiAnalysisJob.status.in_([AiStatus.COMPLETED, AiStatus.QUEUED, AiStatus.RUNNING]),
        )
        .first()
    )
    if existing:
        return
    try:
        request_analysis(db, [paper_id], force=False)
        log_event(db, "已自动创建 AI 分析任务", detail={"paper_id": paper_id}, commit=True)
    except NotConfiguredError as exc:
        log_event(db, f"未自动分析：{exc}", level="warning", detail={"paper_id": paper_id}, commit=True)
    except Exception as exc:  # pragma: no cover
        logger.exception("auto analysis enqueue failed")
        log_event(db, f"自动分析入队失败：{exc}", level="error", detail={"paper_id": paper_id}, commit=True)


async def handle_analyze_paper(job_id: str, payload: dict[str, Any]) -> None:
    paper_id = payload.get("paper_id")
    ai_job_id = payload.get("ai_job_id")
    force = bool(payload.get("force"))
    prompt_id = payload.get("prompt_template_id")
    db: Session = SessionLocal()
    try:
        paper = db.get(Paper, paper_id)
        if not paper or paper.is_deleted:
            raise AnalysisError("文献不存在或已删除")
        job = db.get(BackgroundJob, job_id)
        ai_job = db.get(AiAnalysisJob, ai_job_id) if ai_job_id else None
        if ai_job:
            ai_job.attempts = (ai_job.attempts or 0) + 1
            db.commit()

        async def progress(percent: int, message: str) -> None:
            if job:
                refreshed = db.get(BackgroundJob, job_id)
                if refreshed:
                    if refreshed.cancel_requested:
                        raise JobCancelled("任务已请求取消")
                    refreshed.progress = max(0, min(100, percent))
                    refreshed.message = message[:500]
                    db.commit()

        analyzer = Analyzer(db, progress)
        result = await analyzer.run(
            paper_id,
            ai_job_id=ai_job_id,
            force=force,
            prompt_template_id=prompt_id,
        )
        if job:
            job.progress = 100
            job.message = f"分析完成：{result.one_sentence_summary[:120]}"
            db.commit()
        _refresh_paper_tasks(db, paper_id)
    finally:
        db.close()


async def handle_scan_folder(job_id: str, payload: dict[str, Any]) -> None:
    import_job_id = payload.get("import_job_id")
    directory = payload.get("directory")
    task_id = payload.get("task_id")
    await asyncio.to_thread(_run_scan, import_job_id, directory, task_id)


def _run_scan(import_job_id: str, directory: str, task_id: str | None) -> None:
    db: Session = SessionLocal()
    try:
        scan_directory(db, import_job_id, directory, task_id)
    finally:
        db.close()


def handle_import_metadata(payload: dict[str, Any]) -> None:
    path = Path(payload["path"])
    db: Session = SessionLocal()
    try:
        data = path.read_bytes()
        import_metadata_bytes(
            db,
            filename=payload.get("filename") or path.name,
            data=data,
            task_id=payload.get("task_id"),
            forced_format=payload.get("format", "auto"),
        )
    finally:
        db.close()


def handle_run_search_task(payload: dict[str, Any]) -> None:
    db: Session = SessionLocal()
    try:
        run_task(db, payload["task_id"], payload.get("mode"))
    finally:
        db.close()


def handle_export(job_id: str, payload: dict[str, Any]) -> None:
    db: Session = SessionLocal()
    try:
        result = export_papers(
            db,
            fmt=payload["format"],
            paper_ids=payload.get("paper_ids") or [],
            filters=payload.get("filters") or {},
            include_notes=payload.get("include_notes", True),
            include_analysis=payload.get("include_analysis", True),
        )
        job = db.get(BackgroundJob, job_id)
        if job:
            job.message = result["filename"]
            job.payload = {**(job.payload or {}), "result": result}
            job.progress = 100
            db.commit()
    finally:
        db.close()


def handle_rebuild_index(payload: dict[str, Any]) -> None:
    db: Session = SessionLocal()
    try:
        count = rebuild_all(db)
        job = db.get(BackgroundJob, payload.get("job_id", ""))
        log_event(db, f"全文索引重建完成：{count} 篇", commit=True)
        if job:
            job.message = f"索引已重建（{count} 篇）"
            db.commit()
    finally:
        db.close()


def handle_silent_capture(job_id: str, payload: dict[str, Any]) -> None:
    session_id = str((payload or {}).get("session_id") or "")
    if not session_id:
        logger.warning("silent capture skipped: missing session_id on job %s", job_id)
        return
    db: Session = SessionLocal()
    try:
        capture_service.run_silent_capture_session(db, session_id)
    finally:
        db.close()


def handle_silent_capture_tick_for_tests(session_id: str, max_wait_loops: int = 1, sleep_s: float = 0) -> None:
    """Stop an empty-directory wait early so tests can assert ``waiting_files``."""
    import time

    db: Session = SessionLocal()
    try:
        capture_service.run_silent_capture_session(
            db,
            session_id,
            sleep_fn=lambda _seconds: time.sleep(sleep_s),
            max_wait_loops=max_wait_loops,
        )
    finally:
        db.close()


def handle_backup(payload: dict[str, Any]) -> None:
    db: Session = SessionLocal()
    try:
        result = create_backup(db)
        job = db.get(BackgroundJob, payload.get("job_id", ""))
        if job:
            job.message = result["filename"]
            job.payload = {**(job.payload or {}), "result": result}
            db.commit()
        log_event(db, f"备份完成：{result['filename']}", commit=True)
    finally:
        db.close()


def _refresh_paper_tasks(db: Session, paper_id: str) -> None:
    from app.models import SearchTaskPaper

    task_ids = [
        row[0] for row in db.query(SearchTaskPaper.task_id).filter(SearchTaskPaper.paper_id == paper_id).all()
    ]
    for task_id in task_ids:
        refresh_counters(db, task_id)
    db.commit()


SYNC_HANDLERS = {
    "scan_folder": handle_scan_folder.__name__,
}
