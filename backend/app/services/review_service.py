"""Human review workflow: include / exclude / defer / undo with full audit trail."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.constants import ReviewAction, ReviewStatus
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.models import AiAnalysisResult, Paper, PaperReview, SearchTaskPaper
from app.services import serializers
from app.services.paper_service import current_analysis, get_paper_or_404, set_tags
from app.services.log_service import log_event
from app.services.task_service import refresh_counters

ACTION_TO_STATUS = {
    ReviewAction.INCLUDE: ReviewStatus.INCLUDED,
    ReviewAction.EXCLUDE: ReviewStatus.EXCLUDED,
    ReviewAction.DEFER: ReviewStatus.DEFERRED,
}
ACTION_LABELS = {
    ReviewAction.INCLUDE: "入库",
    ReviewAction.EXCLUDE: "暂不采用",
    ReviewAction.DEFER: "待定",
}


def review_queue(
    db: Session,
    *,
    status: str = "pending_review",
    page: int = 1,
    page_size: int = 20,
    sort: str = "score_desc",
    q: str = "",
) -> dict[str, Any]:
    from app.database.fts import search_ids

    query = db.query(Paper).filter(Paper.is_deleted.is_(False))
    statuses = [s.strip() for s in status.split(",") if s.strip()]
    if statuses:
        query = query.filter(Paper.review_status.in_(statuses))
    if q.strip():
        ids = search_ids(db, q.strip(), limit=300)
        if not ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        query = query.filter(Paper.id.in_(ids))
    total = query.count()
    if sort in ("score_desc", "score_asc"):
        current = (
            db.query(AiAnalysisResult.paper_id, AiAnalysisResult.screening_score)
            .filter(AiAnalysisResult.is_current.is_(True))
            .subquery()
        )
        query = query.outerjoin(current, current.c.paper_id == Paper.id)
        column = func.coalesce(current.c.screening_score, -1)
        query = query.order_by(column.desc() if sort == "score_desc" else column.asc())
    elif sort == "updated_asc":
        query = query.order_by(Paper.updated_at.asc())
    else:
        query = query.order_by(Paper.updated_at.desc())
    papers = query.offset((max(1, page) - 1) * page_size).limit(page_size).all()
    items = []
    for paper in papers:
        analysis = current_analysis(db, paper.id)
        item = serializers.paper_summary(paper, analysis=analysis)
        item["analysis"] = serializers.analysis_out(analysis) if analysis else None
        item["evidence"] = (analysis.evidence if analysis else []) or []
        item["review_history"] = [
            serializers.review_out(r)
            for r in db.query(PaperReview)
            .filter(PaperReview.paper_id == paper.id)
            .order_by(PaperReview.created_at.desc())
            .limit(5)
            .all()
        ]
        items.append(item)
    counts = dict(
        db.query(Paper.review_status, func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False))
        .group_by(Paper.review_status)
        .all()
    )
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "counts": counts,
    }


def perform_review(
    db: Session,
    paper_id: str,
    *,
    action: str,
    note: str = "",
    tags: list[str] | None = None,
    expected_status: str | None = None,
) -> dict[str, Any]:
    paper = get_paper_or_404(db, paper_id)
    if action == ReviewAction.REANALYZE:
        raise ValidationAppError("重新分析请调用 AI 分析接口")
    target = ACTION_TO_STATUS.get(action)
    if not target:
        raise ValidationAppError(f"不支持的审核操作：{action}")
    if expected_status and paper.review_status != expected_status:
        raise ConflictError(
            "文献状态已发生变化，请刷新后重试",
            detail={"current": paper.review_status, "expected": expected_status},
        )
    analysis = current_analysis(db, paper.id)
    from_status = paper.review_status
    paper.review_status = target
    paper.updated_at = utcnow()
    added_tags = set_tags(db, paper, tags or [])
    review = PaperReview(
        paper_id=paper.id,
        action=action,
        from_status=from_status,
        to_status=target,
        note=note or "",
        previous_status=from_status,
        snapshot={
            "analysis_id": analysis.id if analysis else None,
            "screening_score": analysis.screening_score if analysis else None,
            "one_sentence_summary": analysis.one_sentence_summary if analysis else "",
            "innovation_summary": analysis.innovation_summary if analysis else "",
            "tags": [tag.name for tag in added_tags],
            "title": paper.title,
        },
        created_at=utcnow(),
    )
    db.add(review)
    db.flush()
    _refresh_tasks(db, paper.id)
    log_event(
        db,
        f"审核操作：{ACTION_LABELS[action]} - {paper.title[:60]}",
        detail={"paper_id": paper.id, "from": from_status, "to": target, "review_id": review.id},
        commit=False,
    )
    db.commit()
    return {"review": serializers.review_out(review), "paper": serializers.paper_summary(paper, analysis=analysis)}


def undo_review(db: Session, paper_id: str, review_id: str | None = None) -> dict[str, Any]:
    paper = get_paper_or_404(db, paper_id)
    query = db.query(PaperReview).filter(
        PaperReview.paper_id == paper_id,
        PaperReview.is_undo.is_(False),
        PaperReview.action.in_([ReviewAction.INCLUDE, ReviewAction.EXCLUDE, ReviewAction.DEFER]),
    )
    if review_id:
        query = query.filter(PaperReview.id == review_id)
    review = query.order_by(PaperReview.created_at.desc()).first()
    if not review:
        raise NotFoundError("没有可撤销的审核记录")
    current = paper.review_status
    target = review.from_status or ReviewStatus.PENDING_REVIEW
    paper.review_status = target
    paper.updated_at = utcnow()
    undo = PaperReview(
        paper_id=paper.id,
        action=ReviewAction.UNDO,
        from_status=current,
        to_status=target,
        note=f"撤销审核记录 {review.id}",
        previous_status=current,
        is_undo=True,
        snapshot={"undone_review_id": review.id, "title": paper.title},
        created_at=utcnow(),
    )
    db.add(undo)
    _refresh_tasks(db, paper.id)
    log_event(db, f"撤销审核：{paper.title[:60]}", detail={"paper_id": paper.id, "review_id": review.id})
    db.commit()
    return {
        "review": serializers.review_out(undo),
        "paper": serializers.paper_summary(paper, analysis=current_analysis(db, paper.id)),
    }


def batch_review(
    db: Session,
    paper_ids: list[str],
    *,
    action: str,
    note: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    succeeded, failed = [], []
    for paper_id in paper_ids:
        try:
            perform_review(db, paper_id, action=action, note=note, tags=tags)
            succeeded.append(paper_id)
        except Exception as exc:
            db.rollback()
            failed.append({"paper_id": paper_id, "error": str(exc)})
    return {"succeeded": succeeded, "failed": failed, "count": len(succeeded)}


def review_history(db: Session, paper_id: str, limit: int = 100) -> list[dict[str, Any]]:
    get_paper_or_404(db, paper_id)
    reviews = (
        db.query(PaperReview)
        .filter(PaperReview.paper_id == paper_id)
        .order_by(PaperReview.created_at.desc())
        .limit(limit)
        .all()
    )
    return [serializers.review_out(r) for r in reviews]


def recent_reviews(db: Session, limit: int = 50) -> list[dict[str, Any]]:
    reviews = db.query(PaperReview).order_by(PaperReview.created_at.desc()).limit(limit).all()
    paper_ids = list({r.paper_id for r in reviews})
    papers = {p.id: p for p in db.query(Paper).filter(Paper.id.in_(paper_ids)).all()} if paper_ids else {}
    result = []
    for review in reviews:
        item = serializers.review_out(review)
        paper = papers.get(review.paper_id)
        item["paper_title"] = paper.title if paper else "（已删除）"
        result.append(item)
    return result


def _refresh_tasks(db: Session, paper_id: str) -> None:
    task_ids = [
        row[0] for row in db.query(SearchTaskPaper.task_id).filter(SearchTaskPaper.paper_id == paper_id).all()
    ]
    for task_id in task_ids:
        refresh_counters(db, task_id)
