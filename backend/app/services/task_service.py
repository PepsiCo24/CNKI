"""Search task lifecycle, counters and condition snapshots."""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import ReviewStatus, TaskStatus
from app.core.errors import NotFoundError
from app.core.utils import utcnow
from app.models import Paper, SearchTask, SearchTaskPaper
from app.services.log_service import log_event


def get_task_or_404(db: Session, task_id: str) -> SearchTask:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    return task


def link_paper(
    db: Session,
    task: SearchTask,
    paper: Paper,
    *,
    match_status: str = "matched",
    score: float = 100.0,
) -> bool:
    existing = (
        db.query(SearchTaskPaper)
        .filter(SearchTaskPaper.task_id == task.id, SearchTaskPaper.paper_id == paper.id)
        .first()
    )
    if existing:
        return False
    db.add(
        SearchTaskPaper(
            task_id=task.id,
            paper_id=paper.id,
            match_status=match_status,
            match_score=score,
            added_at=utcnow(),
        )
    )
    db.flush()
    refresh_counters(db, task.id)
    return True


def refresh_counters(db: Session, task_id: str) -> None:
    # SessionLocal disables autoflush; flush pending status changes before aggregating.
    db.flush()
    task = db.get(SearchTask, task_id)
    if not task:
        return
    rows = (
        db.query(SearchTaskPaper.paper_id, Paper.review_status, Paper.fulltext_status, Paper.ai_status)
        .join(Paper, Paper.id == SearchTaskPaper.paper_id)
        .filter(SearchTaskPaper.task_id == task_id)
        .all()
    )
    task.discovered_count = len(rows)
    task.imported_count = sum(1 for r in rows if r.fulltext_status == "imported")
    task.analyzed_count = sum(1 for r in rows if r.ai_status in ("completed", "cached"))
    task.included_count = sum(1 for r in rows if r.review_status == ReviewStatus.INCLUDED)
    task.progress = round(task.imported_count / task.discovered_count * 100, 1) if task.discovered_count else 0.0


def build_conditions_snapshot(task: SearchTask) -> dict:
    return {
        "source": task.source,
        "paper_type": task.paper_type,
        "journal": task.journal,
        "keywords": task.keywords,
        "match_mode": task.match_mode,
        "start_date": task.start_date.isoformat() if task.start_date else None,
        "end_date": task.end_date.isoformat() if task.end_date else None,
        "sort_by": task.sort_by,
        "import_mode": task.import_mode,
        "generated_at": utcnow().isoformat(),
        "notes": (
            "来源条件为期刊名称时，应在知网官方检索页将“文献来源”限定为该期刊，"
            "而不是把期刊名当作主题关键词。"
        ),
    }


def set_status(db: Session, task: SearchTask, status: str, message: str = "", level: str = "info") -> None:
    task.status = status
    if status == TaskStatus.RUNNING:
        task.started_at = task.started_at or utcnow()
        task.last_run_at = utcnow()
    if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        task.finished_at = utcnow()
    if status == TaskStatus.FAILED:
        task.error_message = message
    db.commit()
    if message:
        log_event(db, message, task_id=task.id, level=level, commit=True)


def task_papers(db: Session, task_id: str) -> list[Paper]:
    return (
        db.query(Paper)
        .join(SearchTaskPaper, SearchTaskPaper.paper_id == Paper.id)
        .filter(SearchTaskPaper.task_id == task_id, Paper.is_deleted.is_(False))
        .order_by(Paper.created_at.desc())
        .all()
    )


def task_stats(db: Session) -> dict:
    total = db.query(func.count(SearchTask.id)).scalar() or 0
    running = db.query(func.count(SearchTask.id)).filter(SearchTask.status == TaskStatus.RUNNING).scalar() or 0
    awaiting = (
        db.query(func.count(SearchTask.id)).filter(SearchTask.status == TaskStatus.AWAITING_IMPORT).scalar() or 0
    )
    return {"total": total, "running": running, "awaiting_import": awaiting}
