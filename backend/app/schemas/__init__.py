"""Pydantic input/output contracts (validation + API documentation)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import (
    AnalysisScope,
    PaperType,
    ReviewAction,
    ReviewStatus,
    TaskStatus,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str


# --------------------------------------------------------------------------- papers
class PaperBase(BaseModel):
    title: str = Field(min_length=1, max_length=1000)
    authors: list[str] = Field(default_factory=list)
    journal: str = ""
    abstract: str = ""
    doi: str | None = None
    keywords: list[str] = Field(default_factory=list)
    source_url: str = ""
    publication_date: date | None = None
    publication_date_precision: Literal["day", "month", "year", "unknown"] = "day"
    publication_date_raw: str = ""

    @field_validator("authors", "keywords", mode="before")
    @classmethod
    def _coerce_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.replace("；", ";").split(";") if part.strip()]
        return value


class PaperUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=1000)
    authors: list[str] | None = None
    journal: str | None = None
    abstract: str | None = None
    doi: str | None = None
    keywords: list[str] | None = None
    source_url: str | None = None
    publication_date: date | None = None
    publication_date_precision: Literal["day", "month", "year", "unknown"] | None = None
    publication_date_raw: str | None = None
    online_first_date: date | None = None
    update_date: date | None = None
    paper_type: PaperType | None = None
    language: str | None = None


# ----------------------------------------------------------------------- search task
class SearchTaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    source: Literal["CNKI"] = "CNKI"
    paper_type: PaperType = PaperType.JOURNAL
    journal: str = Field(default="", max_length=300)
    keywords: str = Field(default="", max_length=1000)
    match_mode: Literal["exact", "fuzzy"] = "fuzzy"
    start_date: date | None = None
    end_date: date | None = None
    sort_by: Literal["publication_date", "relevance"] = "publication_date"
    import_mode: Literal["metadata_import", "folder_watch", "authorized_api"] = "metadata_import"

    @model_validator(mode="after")
    def _validate_ranges(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("起始日期不得晚于结束日期")
        if self.import_mode == "authorized_api":
            # Explicitly gated; adapter must be configured with a permission reference.
            pass
        return self


class SearchTaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    journal: str | None = None
    keywords: str | None = None
    match_mode: Literal["exact", "fuzzy"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    sort_by: Literal["publication_date", "relevance"] | None = None
    import_mode: Literal["metadata_import", "folder_watch", "authorized_api"] | None = None
    paper_type: PaperType | None = None

    @model_validator(mode="after")
    def _validate_ranges(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("起始日期不得晚于结束日期")
        return self


# --------------------------------------------------------------------------- review
class ReviewActionIn(BaseModel):
    action: ReviewAction
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    expected_status: ReviewStatus | None = None
    confirm_duplicate: bool = False


class BatchReviewIn(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=200)
    action: ReviewAction
    note: str = ""
    tags: list[str] = Field(default_factory=list)


class ReviewUndoIn(BaseModel):
    review_id: str | None = None


# ----------------------------------------------------------------------------- tags
class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = "通用"
    color: str = "#409EFF"


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = None
    color: str | None = None


# ---------------------------------------------------------------------------- notes
class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
    note_type: Literal["general", "idea", "reading"] = "general"
    title: str = ""


class NoteUpdate(BaseModel):
    content: str | None = None
    title: str | None = None


class InnovationUpdate(BaseModel):
    note: str | None = None
    name: str | None = Field(default=None, max_length=300)
    tags_snapshot: list[str] | None = None


# ------------------------------------------------------------------------ ai results
class InnovationPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", max_length=300)
    problem: str = Field(default="", max_length=600)
    method: str = Field(default="", max_length=600)
    difference: str = Field(default="", max_length=600)
    evidence: str = Field(default="", max_length=1200)
    page: int | None = Field(default=None, ge=1)
    inferred: bool = False


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    section: str = ""
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(default="", max_length=2000)
    supports: str = ""


class LimitationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["claimed", "inferred", "作者明确披露", "分析推断"] = "inferred"
    text: str = Field(default="", max_length=1500)

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value):
        if value in ("claimed", "作者明确披露", "disclosed"):
            return "claimed"
        return "inferred"


class KeyResultItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metric: str = Field(default="", max_length=300)
    value: str = Field(default="", max_length=300)
    setting: str = Field(default="", max_length=800)
    conclusion: str = Field(default="", max_length=1000)


class AnalysisOutput(BaseModel):
    """Strict schema for LLM output. Validation failure triggers bounded repair."""

    model_config = ConfigDict(extra="ignore")

    one_sentence_summary: str = Field(min_length=5, max_length=160)
    research_problem: str = Field(default="未明确说明", max_length=2000)
    main_method: str = Field(default="未明确说明", max_length=3000)
    claimed_innovations: list[InnovationPoint] = Field(default_factory=list, max_length=3)
    inferred_contributions: list[InnovationPoint] = Field(default_factory=list, max_length=3)
    innovation_summary: str = Field(default="", max_length=800)
    key_results: list[KeyResultItem] = Field(default_factory=list, max_length=8)
    research_value: str = Field(default="", max_length=3000)
    limitations: list[LimitationItem] = Field(default_factory=list, max_length=8)
    screening_score: int = Field(ge=0, le=100)
    screening_reason: str = Field(default="", max_length=1500)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=15)
    analysis_scope: AnalysisScope = AnalysisScope.FULLTEXT
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    tags_suggestion: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("analysis_scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value):
        text = str(value or "").lower()
        if "摘要" in text or "abstract" in text:
            return "abstract"
        if "分块" in text or "chunk" in text:
            return "fulltext_chunked"
        if "题录" in text or "metadata" in text:
            return "metadata"
        if "全文" in text or "fulltext" in text:
            return "fulltext"
        return "fulltext"

    @field_validator("one_sentence_summary", "research_problem", "main_method", mode="before")
    @classmethod
    def _strip_text(cls, value):
        if isinstance(value, (int, float)):
            return str(value)
        return (value or "").strip()

    @field_validator(
        "claimed_innovations",
        "inferred_contributions",
        "key_results",
        "evidence",
        "limitations",
        "missing_information",
        "tags_suggestion",
        mode="before",
    )
    @classmethod
    def _none_to_list(cls, value):
        return value or []


class AnalysisEditIn(BaseModel):
    one_sentence_summary: str | None = None
    research_problem: str | None = None
    main_method: str | None = None
    claimed_innovations: list[InnovationPoint] | None = None
    inferred_contributions: list[InnovationPoint] | None = None
    innovation_summary: str | None = None
    key_results: list[KeyResultItem] | None = None
    research_value: str | None = None
    limitations: list[LimitationItem] | None = None
    screening_score: int | None = Field(default=None, ge=0, le=100)
    screening_reason: str | None = None
    evidence: list[EvidenceItem] | None = None
    missing_information: list[str] | None = None
    tags_suggestion: list[str] | None = None


class AnalyzeRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)
    force: bool = False
    prompt_template_id: str | None = None


# ------------------------------------------------------------------------- settings
class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class AiTestRequest(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None


class ExportRequest(BaseModel):
    format: Literal["csv", "xlsx", "json", "markdown", "ris", "bibtex", "notes_md"]
    paper_ids: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    include_notes: bool = True
    include_analysis: bool = True


class ScanRequest(BaseModel):
    path: str | None = None
    task_id: str | None = None


class MetadataImportRequest(BaseModel):
    task_id: str | None = None
    format: Literal["auto", "ris", "bibtex", "endnote", "csv"] = "auto"


class AssociatePapersIn(BaseModel):
    paper_ids: list[str]
    match_status: Literal["matched", "suspected"] = "matched"


class CreateSearchTaskResult(BaseModel):
    task_id: str


class FileTreeNode(BaseModel):
    key: str
    label: str
    count: int = 0
    icon: str | None = None
    children: list["FileTreeNode"] = Field(default_factory=list)


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    data_dir: str
    worker_running: bool
    watcher_running: bool
    ai_configured: bool
    timestamp: datetime


class BindFolderRequest(BaseModel):
    directory: str


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=20)
    description: str = ""
    is_default: bool = False
    is_active: bool = True


class PromptUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    description: str | None = None
    is_active: bool | None = None


class TaskRunRequest(BaseModel):
    mode: Literal["auto", "metadata_import", "folder_watch", "authorized_api"] | None = None


class AuthorizedAdapterConfig(BaseModel):
    enabled: bool = False
    base_url: str = ""
    api_key: str | None = None
    permission_reference: str = ""
    daily_limit: int = 200
