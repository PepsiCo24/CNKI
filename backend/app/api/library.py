"""Formal library: only human-approved papers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.constants import ReviewStatus
from app.database.session import get_db
from app.models import Paper, PaperTag, Tag
from app.services.paper_service import list_papers, paper_detail

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/papers")
def library_papers(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str = "",
    journal: str = "",
    year: int | None = None,
    tag: str = "",
    author: str = "",
    paper_type: str = "",
    sort: str = "updated_at",
    order: str = "desc",
):
    result = list_papers(
        db,
        review_status=ReviewStatus.INCLUDED,
        q=q,
        journal=journal,
        year=year,
        tag=tag,
        author=author,
        paper_type=paper_type,
        page=page,
        page_size=page_size,
        sort=sort,
        order=order,
    )
    return ok(result)


@router.get("/papers/{paper_id}")
def library_detail(paper_id: str, db: Session = Depends(get_db)):
    data = paper_detail(db, paper_id)
    if data["review_status"] != ReviewStatus.INCLUDED:
        # Detail remains readable for review links, but the client can show a badge.
        data["library_warning"] = "该文献尚未入库，当前为预审核详情"
    return ok(data)


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    base = db.query(Paper).filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.INCLUDED)
    journals = (
        db.query(Paper.journal, func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.INCLUDED, Paper.journal != "")
        .group_by(Paper.journal)
        .order_by(func.count(Paper.id).desc())
        .all()
    )
    years = (
        db.query(Paper.year, func.count(Paper.id))
        .filter(
            Paper.is_deleted.is_(False),
            Paper.review_status == ReviewStatus.INCLUDED,
            Paper.year.isnot(None),
        )
        .group_by(Paper.year)
        .order_by(Paper.year.desc())
        .all()
    )
    tags = (
        db.query(Tag.name, Tag.category, Tag.color, func.count(PaperTag.paper_id))
        .join(PaperTag, PaperTag.tag_id == Tag.id)
        .join(Paper, Paper.id == PaperTag.paper_id)
        .filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.INCLUDED)
        .group_by(Tag.id)
        .order_by(Tag.category, Tag.name)
        .all()
    )
    return ok(
        {
            "total": base.count(),
            "journals": [{"name": name, "count": count} for name, count in journals],
            "years": [{"year": year, "count": count} for year, count in years],
            "tags": [
                {"name": name, "category": category, "color": color, "count": count}
                for name, category, color, count in tags
            ],
        }
    )
