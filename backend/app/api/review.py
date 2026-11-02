"""Review workbench endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.constants import ReviewAction
from app.database.session import get_db
from app.schemas import BatchReviewIn, ReviewActionIn, ReviewUndoIn
from app.services.analysis_service import request_analysis
from app.services.paper_service import paper_detail
from app.services.paper_service import get_paper_or_404
from app.services.review_service import (
    batch_review,
    perform_review,
    recent_reviews,
    review_history,
    review_queue,
    undo_review,
)

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/queue")
def queue(
    db: Session = Depends(get_db),
    status: str = "pending_review",
    sort: str = "score_desc",
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return ok(review_queue(db, status=status, sort=sort, q=q, page=page, page_size=page_size))


@router.get("/recent")
def recent(db: Session = Depends(get_db), limit: int = Query(50, ge=1, le=200)):
    return ok({"items": recent_reviews(db, limit)})


@router.get("/history/{paper_id}")
def history(paper_id: str, db: Session = Depends(get_db)):
    return ok({"items": review_history(db, paper_id)})


@router.get("/{paper_id}")
def review_detail(paper_id: str, db: Session = Depends(get_db)):
    return ok(paper_detail(db, paper_id))


@router.post("/{paper_id}/action")
def act(paper_id: str, payload: ReviewActionIn, db: Session = Depends(get_db)):
    if payload.action == ReviewAction.REANALYZE:
        result = request_analysis(db, [paper_id], force=True)
        return ok({"jobs": result}, message="已请求重新分析")
    result = perform_review(
        db,
        paper_id,
        action=payload.action,
        note=payload.note,
        tags=payload.tags,
        expected_status=payload.expected_status,
    )
    return ok(result, message="审核结果已保存")


@router.post("/{paper_id}/undo")
def undo(paper_id: str, payload: ReviewUndoIn | None = None, db: Session = Depends(get_db)):
    result = undo_review(db, paper_id, payload.review_id if payload else None)
    return ok(result, message="已撤销上一条审核记录")


@router.post("/batch")
def batch(payload: BatchReviewIn, db: Session = Depends(get_db)):
    if payload.action == ReviewAction.REANALYZE:
        jobs = request_analysis(db, payload.paper_ids, force=True)
        return ok({"jobs": jobs}, message=f"已请求重新分析 {len(jobs)} 篇")
    result = batch_review(
        db,
        payload.paper_ids,
        action=payload.action,
        note=payload.note,
        tags=payload.tags,
    )
    return ok(result, message=f"批量操作完成：成功 {result['count']} 篇")
