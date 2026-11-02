"""Silent local-ingest capture sessions (no CNKI login or headless scrape)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import CaptureStage, JobStatus, JobType, TaskStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.models import BackgroundJob, CaptureSession, SearchTask
from app.services import serializers
from app.services.log_service import log_event
from app.services.settings_service import SettingsService
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
        return serializers.capture_session_out(existing)
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


def get_silent_capture(db: Session, task_id: str) -> dict:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    existing = get_active_session(db, task_id)
    if existing:
        return serializers.capture_session_out(existing)
    latest = (
        db.query(CaptureSession)
        .filter(CaptureSession.task_id == task_id)
        .order_by(CaptureSession.created_at.desc())
        .first()
    )
    if not latest:
        raise NotFoundError("没有静默抓取会话")
    return serializers.capture_session_out(latest)


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
