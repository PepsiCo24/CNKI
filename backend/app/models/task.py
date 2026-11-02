"""Search tasks, persistent background jobs, import jobs and logs."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import JobStatus, JobType, TaskStatus
from app.models.base import Base, IdMixin, TimestampMixin


class SearchTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "search_tasks"

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="CNKI")
    paper_type: Mapped[str] = mapped_column(String(32), nullable=False, default="journal")
    journal: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    keywords: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    match_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fuzzy")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_by: Mapped[str] = mapped_column(String(32), nullable=False, default="publication_date")
    import_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="metadata_import")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TaskStatus.PENDING, index=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    included_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    links: Mapped[list["SearchTaskPaper"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )


class SearchTaskPaper(Base):
    __tablename__ = "search_task_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False, default="matched")
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    task: Mapped[SearchTask] = relationship(back_populates="links")

    __table_args__ = (UniqueConstraint("task_id", "paper_id", name="uq_task_paper"),)


class BackgroundJob(IdMixin, TimestampMixin, Base):
    """Durable queue. Every long-running unit of work is one row here."""

    __tablename__ = "background_jobs"

    job_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    cancel_requested: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    __table_args__ = (Index("ix_jobs_status_priority", "status", "priority", "created_at"),)


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"

    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="file_import")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING, index=True)
    source_path: Mapped[str] = mapped_column(String(1500), nullable=False, default="")
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    background_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskLog(IdMixin, Base):
    __tablename__ = "task_logs"

    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_task_logs_created", "created_at"),)


class AppSetting(IdMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_secret: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptTemplate(IdMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_default: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class CaptureSession(IdMixin, TimestampMixin, Base):
    """Orchestrates silent local ingest for one search task (no CNKI login)."""

    __tablename__ = "capture_sessions"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.RUNNING, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting_files", index=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    import_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    background_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    wait_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_capture_task_status", "task_id", "status"),)
