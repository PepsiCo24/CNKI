"""Innovation point library: search, notes, filters."""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import AiAnalysisResult, InnovationItem, Paper, PaperTag, Tag
from app.services import serializers


def list_innovations(
    db: Session,
    *,
    q: str = "",
    paper_id: str = "",
    tag: str = "",
    page: int = 1,
    page_size: int = 20,
    sort: str = "created_at",
) -> dict[str, Any]:
    query = (
        db.query(InnovationItem)
        .join(AiAnalysisResult, AiAnalysisResult.id == InnovationItem.result_id)
        .join(Paper, Paper.id == InnovationItem.paper_id)
        .filter(AiAnalysisResult.is_current.is_(True), Paper.is_deleted.is_(False))
    )
    if paper_id:
        query = query.filter(InnovationItem.paper_id == paper_id)
    if tag:
        query = (
            query.join(PaperTag, PaperTag.paper_id == InnovationItem.paper_id)
            .join(Tag, Tag.id == PaperTag.tag_id)
            .filter(or_(Tag.name == tag, Tag.id == tag))
        )
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                InnovationItem.name.like(like),
                InnovationItem.core_technique.like(like),
                InnovationItem.description.like(like),
                InnovationItem.evidence.like(like),
                InnovationItem.note.like(like),
                Paper.title.like(like),
            )
        )
    total = query.distinct().count()
    if sort == "paper_year":
        query = query.order_by(Paper.year.desc(), InnovationItem.seq.asc())
    else:
        query = query.order_by(InnovationItem.created_at.desc())
    items = query.offset((max(1, page) - 1) * page_size).limit(page_size).all()
    paper_ids = list({item.paper_id for item in items})
    papers = {p.id: p for p in db.query(Paper).filter(Paper.id.in_(paper_ids)).all()} if paper_ids else {}
    result = [serializers.innovation_out(item, papers.get(item.paper_id)) for item in items]
    return {"items": result, "total": total, "page": page, "page_size": page_size}


def update_innovation(db: Session, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = db.get(InnovationItem, item_id)
    if not item:
        raise NotFoundError("创新点不存在")
    for key in ("note", "name", "tags_snapshot"):
        if payload.get(key) is not None:
            setattr(item, key, payload[key])
    db.commit()
    paper = db.get(Paper, item.paper_id)
    return serializers.innovation_out(item, paper)


def innovation_facets(db: Session) -> dict[str, Any]:
    rows = (
        db.query(InnovationItem.paper_id, Paper.title, Paper.journal)
        .join(AiAnalysisResult, AiAnalysisResult.id == InnovationItem.result_id)
        .join(Paper, Paper.id == InnovationItem.paper_id)
        .filter(AiAnalysisResult.is_current.is_(True), Paper.is_deleted.is_(False))
        .distinct()
        .all()
    )
    tags = (
        db.query(Tag.name, Tag.color, Tag.category)
        .join(PaperTag, PaperTag.tag_id == Tag.id)
        .join(InnovationItem, InnovationItem.paper_id == PaperTag.paper_id)
        .distinct()
        .all()
    )
    return {
        "papers": [{"id": pid, "title": title, "journal": journal} for pid, title, journal in rows],
        "tags": [{"name": name, "color": color, "category": category} for name, color, category in tags],
    }
