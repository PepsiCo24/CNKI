"""Papers, files, extracted texts and innovation points."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    AiStatus,
    FulltextStatus,
    PaperType,
    ParseStatus,
    ReviewStatus,
)
from app.models.base import Base, IdMixin, TimestampMixin


class Paper(IdMixin, TimestampMixin, Base):
    __tablename__ = "papers"

    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    title_normalized: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    authors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    authors_text: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    journal: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    publication_date_precision: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    publication_date_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    online_first_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    update_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    paper_type: Mapped[str] = mapped_column(String(32), nullable=False, default=PaperType.JOURNAL)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    fulltext_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FulltextStatus.NOT_AVAILABLE, index=True
    )
    parse_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ParseStatus.NOT_PARSED, index=True
    )
    ai_status: Mapped[str] = mapped_column(String(32), nullable=False, default=AiStatus.NOT_ANALYZED, index=True)
    review_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ReviewStatus.PENDING_FULLTEXT, index=True
    )
    metadata_source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    raw_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("papers.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none", index=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    files: Mapped[list["PaperFile"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", lazy="selectin"
    )
    texts: Mapped[list["PaperText"]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", lazy="selectin"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary="paper_tags", back_populates="papers", lazy="selectin")

    __table_args__ = (
        Index("ix_papers_doi", "doi"),
        Index("ix_papers_journal_year", "journal", "year"),
        Index("ix_papers_title_norm", "title_normalized"),
        Index("ix_papers_review_updated", "review_status", "updated_at"),
    )


class PaperFile(IdMixin, TimestampMixin, Base):
    __tablename__ = "paper_files"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    relative_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    file_format: Mapped[str] = mapped_column(String(16), nullable=False, default="pdf")
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    origin: Mapped[str] = mapped_column(String(64), nullable=False, default="local_import")
    parse_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ParseStatus.NOT_PARSED, index=True
    )
    parse_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    paper: Mapped[Paper] = relationship(back_populates="files")


class PaperText(IdMixin, TimestampMixin, Base):
    __tablename__ = "paper_texts"

    paper_id: Mapped[str] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    file_id: Mapped[str | None] = mapped_column(ForeignKey("paper_files.id", ondelete="SET NULL"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_map: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extractor: Mapped[str] = mapped_column(String(64), nullable=False, default="pymupdf")
    quality: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    paper: Mapped[Paper] = relationship(back_populates="texts")


class InnovationItem(IdMixin, TimestampMixin, Base):
    """One row per extracted innovation point, powers the standalone innovation library."""

    __tablename__ = "innovation_items"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    result_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_results.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    core_technique: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (UniqueConstraint("result_id", "seq", name="uq_innovation_result_seq"),)


class Tag(IdMixin, TimestampMixin, Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="通用")
    color: Mapped[str] = mapped_column(String(32), nullable=False, default="#409EFF")

    papers: Mapped[list[Paper]] = relationship(secondary="paper_tags", back_populates="tags", lazy="selectin")


class PaperTag(Base):
    __tablename__ = "paper_tags"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Collection(IdMixin, TimestampMixin, Base):
    """User-created folder in the file tree (independent from physical journal folders)."""

    __tablename__ = "collections"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    color: Mapped[str] = mapped_column(String(32), nullable=False, default="#909399")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_collection_parent_name"),)


class CollectionPaper(Base):
    __tablename__ = "collection_papers"

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
