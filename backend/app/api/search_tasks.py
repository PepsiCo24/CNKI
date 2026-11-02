"""Search task CRUD, execution controls and associated papers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.constants import TaskStatus
from app.core.errors import ConflictError, NotFoundError
from app.core.utils import utcnow
from app.database.session import get_db
from app.models import Paper, SearchTask, SearchTaskPaper, TaskLog
from app.schemas import AssociatePapersIn, SearchTaskCreate, SearchTaskUpdate, TaskRunRequest
from app.services import serializers
from app.services.log_service import log_event
from app.services.paper_service import list_papers
from app.services import capture_service
from app.services.search_task_service import (
    cancel_task,
    pause_task,
    resume_task,
    retry_task,
    retrieval_guide,
    run_task,
    update_task,
)
from app.services.task_service import build_conditions_snapshot, refresh_counters

router = APIRouter(prefix="/search-tasks", tags=["search-tasks"])


@router.get("")
def list_tasks(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str = "",
    q: str = "",
):
    query = db.query(SearchTask)
    if status:
        query = query.filter(SearchTask.status == status)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(SearchTask.name.like(like), SearchTask.journal.like(like)))
    total = query.count()
    tasks = (
        query.order_by(SearchTask.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ok(
        {
            "items": [serializers.task_out(task) for task in tasks],
            "total": total,
            "page": page,
            "page_size": page_size,
            "status_counts": dict(
                db.query(SearchTask.status, func.count(SearchTask.id)).group_by(SearchTask.status).all()
            ),
        }
    )


@router.post("")
def create_task(payload: SearchTaskCreate, db: Session = Depends(get_db)):
    task = SearchTask(
        name=payload.name.strip(),
        source=payload.source,
        paper_type=payload.paper_type,
        journal=payload.journal.strip(),
        keywords=payload.keywords.strip(),
        match_mode=payload.match_mode,
        start_date=payload.start_date,
        end_date=payload.end_date,
        sort_by=payload.sort_by,
        import_mode=payload.import_mode,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.flush()
    task.conditions_snapshot = build_conditions_snapshot(task)
    log_event(
        db,
        f"创建检索任务：{task.name}",
        task_id=task.id,
        detail=task.conditions_snapshot,
        commit=False,
    )
    db.commit()
    db.refresh(task)
    return ok(
        {"task": serializers.task_out(task), "guide": retrieval_guide(db, task)},
        message="检索任务已创建",
    )


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    logs = (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.desc())
        .limit(80)
        .all()
    )
    refresh_counters(db, task_id)
    db.commit()
    return ok(
        {
            "task": serializers.task_out(task),
            "guide": retrieval_guide(db, task),
            "logs": [serializers.log_out(item) for item in logs],
        }
    )


@router.put("/{task_id}")
def edit_task(task_id: str, payload: SearchTaskUpdate, db: Session = Depends(get_db)):
    task = update_task(db, task_id, payload.model_dump(exclude_none=True))
    return ok({"task": task, "guide": retrieval_guide(db, db.get(SearchTask, task_id))})


@router.delete("/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db)):
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status == TaskStatus.RUNNING:
        raise ConflictError("任务执行中不能删除，请先取消")
    db.delete(task)
    db.commit()
    return ok({"id": task_id}, message="检索任务已删除（文献记录保留）")


@router.post("/{task_id}/run")
def start_task(task_id: str, payload: TaskRunRequest | None = None, db: Session = Depends(get_db)):
    mode = payload.mode if payload else None
    result = run_task(db, task_id, mode)
    return ok(result, message="任务已启动")


@router.post("/{task_id}/pause")
def do_pause(task_id: str, db: Session = Depends(get_db)):
    return ok(pause_task(db, task_id), message="任务已暂停")


@router.post("/{task_id}/resume")
def do_resume(task_id: str, db: Session = Depends(get_db)):
    return ok(resume_task(db, task_id), message="任务已继续")


@router.post("/{task_id}/cancel")
def do_cancel(task_id: str, db: Session = Depends(get_db)):
    return ok(cancel_task(db, task_id), message="任务已取消")


@router.post("/{task_id}/retry")
def do_retry(task_id: str, db: Session = Depends(get_db)):
    return ok(retry_task(db, task_id), message="任务已重新执行")


@router.post("/{task_id}/silent-capture")
def start_silent_capture_endpoint(task_id: str, db: Session = Depends(get_db)):
    session = capture_service.start_silent_capture(db, task_id)
    return ok(session, message="已启动静默抓取")


@router.get("/{task_id}/silent-capture")
def get_silent_capture_endpoint(task_id: str, db: Session = Depends(get_db)):
    return ok(capture_service.get_silent_capture(db, task_id))


@router.post("/{task_id}/silent-capture/cancel")
def cancel_silent_capture_endpoint(task_id: str, db: Session = Depends(get_db)):
    return ok(capture_service.cancel_silent_capture(db, task_id), message="已取消")


@router.get("/{task_id}/guide")
def get_guide(task_id: str, db: Session = Depends(get_db)):
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    return ok(retrieval_guide(db, task))


@router.get("/{task_id}/papers")
def task_papers(
    task_id: str,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    review_status: str = "",
    q: str = "",
):
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    refresh_counters(db, task_id)
    db.commit()
    result = list_papers(
        db,
        task_id=task_id,
        review_status=review_status,
        q=q,
        page=page,
        page_size=page_size,
    )
    return ok(result)


@router.post("/{task_id}/papers")
def associate_papers(task_id: str, payload: AssociatePapersIn, db: Session = Depends(get_db)):
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    added = 0
    for paper_id in payload.paper_ids:
        paper = db.get(Paper, paper_id)
        if not paper or paper.is_deleted:
            continue
        exists = (
            db.query(SearchTaskPaper)
            .filter(SearchTaskPaper.task_id == task_id, SearchTaskPaper.paper_id == paper_id)
            .first()
        )
        if exists:
            continue
        db.add(
            SearchTaskPaper(
                task_id=task_id,
                paper_id=paper_id,
                match_status=payload.match_status,
                match_score=80.0 if payload.match_status == "suspected" else 100.0,
                added_at=utcnow(),
            )
        )
        added += 1
    db.commit()
    refresh_counters(db, task_id)
    db.commit()
    log_event(db, f"手动关联 {added} 篇文献", task_id=task_id, commit=True)
    return ok({"added": added}, message=f"已关联 {added} 篇文献")


@router.get("/{task_id}/logs")
def task_logs(
    task_id: str,
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
):
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    logs = (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return ok({"items": [serializers.log_out(item) for item in logs]})
