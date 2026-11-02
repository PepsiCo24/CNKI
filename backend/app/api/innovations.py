"""Innovation point library."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.errors import NotFoundError
from app.database.session import get_db
from app.models import InnovationItem, Paper
from app.schemas import InnovationUpdate
from app.services.innovation_service import innovation_facets, list_innovations, update_innovation
from app.services.serializers import innovation_out

router = APIRouter(prefix="/innovations", tags=["innovations"])


@router.get("")
def get_innovations(
    db: Session = Depends(get_db),
    q: str = "",
    paper_id: str = "",
    tag: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = "created_at",
):
    return ok(
        list_innovations(
            db,
            q=q,
            paper_id=paper_id,
            tag=tag,
            page=page,
            page_size=page_size,
            sort=sort,
        )
    )


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    return ok(innovation_facets(db))


@router.get("/{item_id}")
def get_innovation(item_id: str, db: Session = Depends(get_db)):
    item = db.get(InnovationItem, item_id)
    if not item:
        raise NotFoundError("创新点不存在")
    return ok(innovation_out(item, db.get(Paper, item.paper_id)))


@router.put("/{item_id}")
def edit_innovation(item_id: str, payload: InnovationUpdate, db: Session = Depends(get_db)):
    return ok(update_innovation(db, item_id, payload.model_dump(exclude_none=True)), message="创新点已更新")
