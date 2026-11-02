"""Dashboard aggregates."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.database.session import get_db
from app.services.paper_service import dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(db: Session = Depends(get_db)):
    return ok(dashboard(db))
