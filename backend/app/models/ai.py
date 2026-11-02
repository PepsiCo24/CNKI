"""AI analysis jobs/results, human reviews and research notes."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import AiStatus, ReviewAction
from app.models.base import Base, IdMixin, TimestampMixin


class AiAnalysisJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_analysis_jobs"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    background_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AiStatus.QUEUED, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prompt_template_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="fulltext")
    tokens_prompt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiAnalysisResult(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_analysis_results"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_analysis_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prompt_template_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    analysis_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="fulltext")
    input_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    one_sentence_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    research_problem: Mapped[str] = mapped_column(Text, nullable=False, default="")
    main_method: Mapped[str] = mapped_column(Text, nullable=False, default="")
    claimed_innovations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    inferred_contributions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    innovation_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    research_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    limitations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    screening_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    screening_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    missing_information: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tags_suggestion: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False, default="")

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (Index("ix_analysis_paper_current", "paper_id", "is_current"),)


class PaperReview(IdMixin, Base):
    __tablename__ = "paper_reviews"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default=ReviewAction.INCLUDE)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    to_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewer: Mapped[str] = mapped_column(String(64), nullable=False, default="local_user")
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_undo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_reviews_paper_created", "paper_id", "created_at"),)


class ResearchNote(IdMixin, TimestampMixin, Base):
    __tablename__ = "research_notes"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note_type: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
