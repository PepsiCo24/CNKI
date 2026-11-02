"""Silent local-ingest capture sessions (no CNKI login or headless scrape)."""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import AiStatus, CaptureStage, JobStatus, JobType, TaskStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.models import BackgroundJob, CaptureSession, ImportJob, Paper, SearchTask, SearchTaskPaper
from app.services import serializers
from app.services.file_service import list_watchable_files
from app.services.import_service import scan_directory
from app.services.log_service import log_event
from app.services.settings_service import SettingsService
from app.services.task_service import refresh_counters
from app.tasks.queue import cancel_job, enqueue_job

ACTIVE_CAPTURE_STATUSES = {"running"}
DEFAULT_COUNTS = {
    "discovered": 0,
    "imported": 0,
    "skipped": 0,
    "duplicates": 0,
    "failed": 0,
    "ai_queued": 0,
    "ai_completed": 0,
}
TERMINAL_STAGES = {
    CaptureStage.READY_FOR_REVIEW,
    CaptureStage.TIMED_OUT,
    CaptureStage.CANCELLED,
    CaptureStage.FAILED,
}
STAGE_MESSAGES = {
    CaptureStage.WAITING_FILES: "等待导入目录中的题录或全文",
    CaptureStage.SCANNING: "正在扫描导入目录",
    CaptureStage.IMPORTING: "正在按来源与时间过滤并写入任务库",
    CaptureStage.AI_QUEUED: "已排队 AI 创新点分析",
    CaptureStage.READY_FOR_REVIEW: "本轮导入完成，可前往人工审核",
    CaptureStage.TIMED_OUT: "等待超时，已保留已导入数据",
    CaptureStage.CANCELLED: "已取消静默抓取",
    CaptureStage.FAILED: "静默抓取失败",
}


def resolve_import_dir(db: Session) -> Path:
    settings = get_settings()
    raw = SettingsService(db).get("data.import_dir") or ""
    path = Path(str(raw)).expanduser() if str(raw).strip() else Path(settings.imports_dir)
    return path


def validate_silent_capture_prerequisites(db: Session, task: SearchTask) -> Path:
    username = str(SettingsService(db).get("cnki.account_username") or "").strip()
    if not username:
        raise ValidationAppError("请先在设置 → 知网接入中填写账号标识")
    if not (task.journal or "").strip():
        raise ValidationAppError("请先设置文献来源（期刊名称）")
    if not task.start_date or not task.end_date:
        raise ValidationAppError("请先设置发表时间起止日期")
    if task.start_date > task.end_date:
        raise ValidationAppError("开始日期不能晚于结束日期")
    path = resolve_import_dir(db)
    if not path.exists() or not path.is_dir():
        raise ValidationAppError(f"导入目录不存在或不可用：{path}")
    return path


def get_active_session(db: Session, task_id: str) -> CaptureSession | None:
    rows = (
        db.query(CaptureSession)
        .filter(CaptureSession.task_id == task_id, CaptureSession.status == JobStatus.RUNNING)
        .order_by(CaptureSession.created_at.desc())
        .all()
    )
    for row in rows:
        if row.stage not in TERMINAL_STAGES:
            return row
    return None


def start_silent_capture(db: Session, task_id: str) -> dict:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    existing = get_active_session(db, task_id)
    if existing:
        return _present_session(db, existing)
    validate_silent_capture_prerequisites(db, task)
    timeout = int(SettingsService(db).get("cnki.capture_wait_timeout") or 1800)
    SettingsService(db).set("data.watch_enabled", True)
    session = CaptureSession(
        task_id=task.id,
        status=JobStatus.RUNNING,
        stage=CaptureStage.WAITING_FILES,
        progress=5.0,
        counts=dict(DEFAULT_COUNTS),
        wait_timeout_seconds=timeout,
        message=STAGE_MESSAGES[CaptureStage.WAITING_FILES],
        started_at=utcnow(),
    )
    db.add(session)
    db.flush()
    bg = enqueue_job(
        db,
        JobType.SILENT_CAPTURE,
        {"session_id": session.id, "task_id": task.id},
        dedupe_key=f"silent_capture:{task.id}",
        priority=3,
        commit=False,
    )
    db.flush()
    session.background_job_id = bg.id
    task.status = TaskStatus.RUNNING
    task.started_at = task.started_at or utcnow()
    task.last_run_at = utcnow()
    log_event(db, "启动静默抓取（本地导入目录）", task_id=task.id, detail={"session_id": session.id}, commit=False)
    db.commit()
    db.refresh(session)
    return serializers.capture_session_out(session)


def _present_session(db: Session, session: CaptureSession) -> dict:
    """Serialize a session, refreshing progress on every non-terminal read."""
    if session.stage not in TERMINAL_STAGES:
        refresh_session_progress(db, session)
        db.refresh(session)
    return serializers.capture_session_out(session)


def get_silent_capture(db: Session, task_id: str) -> dict:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    existing = get_active_session(db, task_id)
    if existing:
        return _present_session(db, existing)
    latest = (
        db.query(CaptureSession)
        .filter(CaptureSession.task_id == task_id)
        .order_by(CaptureSession.created_at.desc())
        .first()
    )
    if not latest:
        raise NotFoundError("没有静默抓取会话")
    return _present_session(db, latest)


def cancel_silent_capture(db: Session, task_id: str) -> dict:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    session = get_active_session(db, task_id)
    if not session:
        raise NotFoundError("没有进行中的静默抓取会话")
    session.stage = CaptureStage.CANCELLED
    session.status = JobStatus.CANCELLED
    session.finished_at = utcnow()
    session.message = STAGE_MESSAGES[CaptureStage.CANCELLED]
    if session.background_job_id:
        job = db.get(BackgroundJob, session.background_job_id)
        if job:
            cancel_job(db, job)
    task.status = TaskStatus.AWAITING_IMPORT
    log_event(db, "已取消静默抓取", task_id=task.id, detail={"session_id": session.id}, commit=False)
    db.commit()
    db.refresh(session)
    return serializers.capture_session_out(session)


def map_import_progress(processed: int, total: int) -> float:
    """Map ImportJob.processed/total onto the importing band, 35–75%."""
    if total <= 0:
        return 75.0
    ratio = max(0.0, min(1.0, float(processed) / float(total)))
    return round(35.0 + 40.0 * ratio, 1)


def _wait_deadline(session: CaptureSession) -> float:
    started = session.started_at or utcnow()
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started.timestamp() + int(session.wait_timeout_seconds or 0)


def _count_ai(db: Session, task_id: str) -> tuple[int, int]:
    rows = (
        db.query(Paper.ai_status)
        .join(SearchTaskPaper, SearchTaskPaper.paper_id == Paper.id)
        .filter(SearchTaskPaper.task_id == task_id, Paper.is_deleted.is_(False))
        .all()
    )
    queued = sum(1 for (status,) in rows if status in (AiStatus.QUEUED, AiStatus.RUNNING))
    completed = sum(1 for (status,) in rows if status in (AiStatus.COMPLETED, AiStatus.CACHED))
    return queued, completed


def _pending_parse_count(db: Session, task_id: str) -> int:
    """Parse jobs still pending or running for papers linked to this task."""
    paper_ids = {
        paper_id
        for (paper_id,) in db.query(SearchTaskPaper.paper_id).filter(SearchTaskPaper.task_id == task_id).all()
    }
    if not paper_ids:
        return 0
    payloads = (
        db.query(BackgroundJob.payload)
        .filter(
            BackgroundJob.job_type == JobType.PARSE_PAPER,
            BackgroundJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)),
        )
        .all()
    )
    pending = 0
    for (payload,) in payloads:
        paper_id = str((payload or {}).get("paper_id") or "")
        if paper_id in paper_ids:
            pending += 1
    return pending


def _finish_session(db: Session, session: CaptureSession, stage: str, *, error: str = "") -> None:
    session.stage = stage
    session.message = STAGE_MESSAGES[stage]
    session.finished_at = utcnow()
    if error:
        session.error_message = error[:4000]
    if stage == CaptureStage.CANCELLED:
        session.status = JobStatus.CANCELLED
    elif stage == CaptureStage.FAILED:
        session.status = JobStatus.FAILED
    else:
        session.status = JobStatus.COMPLETED
    task = db.get(SearchTask, session.task_id)
    if task and task.status == TaskStatus.RUNNING and stage in (
        CaptureStage.CANCELLED,
        CaptureStage.TIMED_OUT,
        CaptureStage.FAILED,
        CaptureStage.READY_FOR_REVIEW,
    ):
        task.status = TaskStatus.AWAITING_IMPORT
    if stage == CaptureStage.TIMED_OUT:
        log_event(db, "静默抓取等待超时", task_id=session.task_id, detail={"session_id": session.id}, commit=False)
    elif stage == CaptureStage.CANCELLED:
        log_event(db, "静默抓取已取消", task_id=session.task_id, detail={"session_id": session.id}, commit=False)
    db.commit()


def tick_wait_or_scan(db: Session, session: CaptureSession, *, now: float | None = None) -> str:
    """One wait check. Returns waiting, scan, timed_out, or cancelled.

    An empty import directory stays in waiting_files until timeout or cancel.
    """
    db.refresh(session)
    if session.stage == CaptureStage.CANCELLED:
        return "cancelled"
    bg = db.get(BackgroundJob, session.background_job_id) if session.background_job_id else None
    if bg and bg.cancel_requested:
        _finish_session(db, session, CaptureStage.CANCELLED)
        return "cancelled"
    files = list_watchable_files(resolve_import_dir(db))
    if files:
        return "scan"
    moment = time.time() if now is None else now
    if moment > _wait_deadline(session):
        _finish_session(db, session, CaptureStage.TIMED_OUT)
        return "timed_out"
    session.stage = CaptureStage.WAITING_FILES
    session.progress = min(14.0, float(session.progress or 0) + 0.5)
    session.message = STAGE_MESSAGES[CaptureStage.WAITING_FILES]
    db.commit()
    return "waiting"


def refresh_session_progress(db: Session, session: CaptureSession, import_job: ImportJob | None = None) -> None:
    """Copy import totals and task parse/AI queue state onto the session.

    While the import job is open, processed/total maps onto 35–75%.
    After it completes, pending parse jobs or queued/running AI stay in
    ai_queued (status running, finished_at cleared) so their workers can
    finish. A later read advances to ready_for_review once those queues
    drain. Terminal stages keep their stage and status; only counts update.
    Papers are never auto-included, and parse/AI are not run inline.
    """
    db.refresh(session)
    if import_job is None and session.import_job_id:
        import_job = db.get(ImportJob, session.import_job_id)
    elif import_job is not None:
        db.refresh(import_job)
    counts = {**DEFAULT_COUNTS, **dict(session.counts or {})}
    if import_job is not None:
        detail = import_job.detail or {}
        counts["imported"] = int(import_job.imported or 0)
        counts["duplicates"] = int(import_job.duplicates or 0)
        counts["failed"] = int(import_job.failed or 0)
        counts["skipped"] = int(detail.get("skipped") or 0)
    refresh_counters(db, session.task_id)
    task = db.get(SearchTask, session.task_id)
    if task is not None:
        counts["discovered"] = int(task.discovered_count or 0)
    ai_queued, ai_completed = _count_ai(db, session.task_id)
    counts["ai_queued"] = ai_queued
    counts["ai_completed"] = ai_completed
    session.counts = counts
    if session.stage in TERMINAL_STAGES:
        db.commit()
        return
    if import_job is not None and import_job.status == JobStatus.FAILED:
        session.progress = map_import_progress(int(import_job.processed or 0), int(import_job.total or 0))
        session.stage = CaptureStage.FAILED
        session.status = JobStatus.FAILED
        session.error_message = session.error_message or "导入失败"
        session.message = STAGE_MESSAGES[CaptureStage.FAILED]
        session.finished_at = utcnow()
    elif import_job is not None and import_job.status != JobStatus.COMPLETED:
        session.progress = map_import_progress(int(import_job.processed or 0), int(import_job.total or 0))
    elif import_job is not None and import_job.status == JobStatus.COMPLETED:
        if _pending_parse_count(db, session.task_id) or ai_queued > 0:
            total = ai_queued + ai_completed
            session.stage = CaptureStage.AI_QUEUED
            session.status = JobStatus.RUNNING
            session.finished_at = None
            session.progress = round(75.0 + 20.0 * (ai_completed / total), 1) if total else 75.0
            session.message = STAGE_MESSAGES[CaptureStage.AI_QUEUED]
        else:
            session.stage = CaptureStage.READY_FOR_REVIEW
            session.status = JobStatus.COMPLETED
            session.progress = 100.0
            session.finished_at = utcnow()
            session.message = STAGE_MESSAGES[CaptureStage.READY_FOR_REVIEW]
            if task and task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.AWAITING_IMPORT
            log_event(
                db,
                "静默抓取完成，可前往人工审核",
                task_id=session.task_id,
                detail={"session_id": session.id},
                commit=False,
            )
    db.commit()


def _run_inline_scan(db: Session, session: CaptureSession) -> None:
    """Persist an ImportJob and scan in-process. Does not enqueue scan_folder."""
    session_id = session.id
    import_dir = resolve_import_dir(db)
    session.stage = CaptureStage.SCANNING
    session.progress = 20
    session.message = STAGE_MESSAGES[CaptureStage.SCANNING]
    db.commit()

    job = ImportJob(
        job_type="folder_scan",
        status=JobStatus.PENDING,
        source_path=str(import_dir),
        task_id=session.task_id,
        detail={"origin": "silent_capture"},
    )
    db.add(job)
    db.flush()
    session.import_job_id = job.id
    session.stage = CaptureStage.IMPORTING
    session.progress = 35
    session.message = STAGE_MESSAGES[CaptureStage.IMPORTING]
    db.commit()
    try:
        scan_directory(db, job.id, str(import_dir), session.task_id)
    except Exception as exc:
        db.rollback()
        failed = db.get(CaptureSession, session_id)
        if failed and failed.stage not in TERMINAL_STAGES:
            _finish_session(db, failed, CaptureStage.FAILED, error=str(exc))
        raise
    db.refresh(session)
    db.refresh(job)
    refresh_session_progress(db, session, job)


def run_silent_capture_session(
    db: Session,
    session_id: str,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_wait_loops: int | None = None,
) -> None:
    """Wait for import files, scan them inline, then aggregate parse/AI progress.

    Pending parse and AI jobs stay queued for their own workers.
    """
    from app.tasks.handlers import JobCancelled

    session = db.get(CaptureSession, session_id)
    if session is None:
        raise NotFoundError("没有静默抓取会话")
    loops = 0
    while True:
        action = tick_wait_or_scan(db, session)
        if action == "cancelled":
            raise JobCancelled()
        if action == "timed_out":
            return
        if action == "scan":
            break
        loops += 1
        if max_wait_loops is not None and loops >= max_wait_loops:
            return
        sleep_fn(2)
    _run_inline_scan(db, session)
