"""Domain constants shared by models, services and API schemas."""
from __future__ import annotations

from enum import StrEnum


class PaperType(StrEnum):
    JOURNAL = "journal"
    DISSERTATION = "dissertation"
    CONFERENCE = "conference"


class FulltextStatus(StrEnum):
    NOT_AVAILABLE = "not_available"
    IMPORTED = "imported"
    DOWNLOADING = "downloading"
    FAILED = "failed"


class ParseStatus(StrEnum):
    NOT_PARSED = "not_parsed"
    PENDING = "pending"
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class AiStatus(StrEnum):
    NOT_ANALYZED = "not_analyzed"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CACHED = "cached"


class ReviewStatus(StrEnum):
    PENDING_FULLTEXT = "pending_fulltext"
    PENDING_AI = "pending_ai"
    ANALYZING = "analyzing"
    PENDING_REVIEW = "pending_review"
    INCLUDED = "included"
    EXCLUDED = "excluded"
    DEFERRED = "deferred"
    ANALYSIS_FAILED = "analysis_failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING_IMPORT = "awaiting_import"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CANCELLING = "cancelling"


class JobType(StrEnum):
    PARSE_PAPER = "parse_paper"
    ANALYZE_PAPER = "analyze_paper"
    SCAN_FOLDER = "scan_folder"
    IMPORT_METADATA = "import_metadata"
    RUN_SEARCH_TASK = "run_search_task"
    EXPORT = "export"
    REBUILD_INDEX = "rebuild_index"
    BACKUP = "backup"
    SILENT_CAPTURE = "silent_capture"


class CaptureStage(StrEnum):
    WAITING_FILES = "waiting_files"
    SCANNING = "scanning"
    IMPORTING = "importing"
    AI_QUEUED = "ai_queued"
    READY_FOR_REVIEW = "ready_for_review"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ReviewAction(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    DEFER = "defer"
    UNDO = "undo"
    REANALYZE = "reanalyze"


class AnalysisScope(StrEnum):
    ABSTRACT = "abstract"
    FULLTEXT = "fulltext"
    FULLTEXT_CHUNKED = "fulltext_chunked"
    METADATA = "metadata"


AI_STATUS_TO_REVIEW = {
    AiStatus.NOT_ANALYZED: ReviewStatus.PENDING_AI,
    AiStatus.QUEUED: ReviewStatus.PENDING_AI,
    AiStatus.RUNNING: ReviewStatus.ANALYZING,
    AiStatus.COMPLETED: ReviewStatus.PENDING_REVIEW,
    AiStatus.CACHED: ReviewStatus.PENDING_REVIEW,
    AiStatus.FAILED: ReviewStatus.ANALYSIS_FAILED,
}

REVIEW_LABELS = {
    ReviewStatus.PENDING_FULLTEXT: "待获取全文",
    ReviewStatus.PENDING_AI: "待 AI 分析",
    ReviewStatus.ANALYZING: "AI 分析中",
    ReviewStatus.PENDING_REVIEW: "待人工审核",
    ReviewStatus.INCLUDED: "已入库",
    ReviewStatus.EXCLUDED: "暂不采用",
    ReviewStatus.DEFERRED: "待定",
    ReviewStatus.ANALYSIS_FAILED: "分析失败",
}


def derive_review_status(
    *,
    fulltext_status: str,
    ai_status: str,
    current: str,
) -> str:
    """Status reconciliation that never auto-includes a paper.

    Once a human decision exists (included/excluded/deferred) the paper stays in that
    business state; only workflow states are recalculated here.
    """
    if current in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED):
        return current
    if ai_status == AiStatus.COMPLETED:
        return ReviewStatus.PENDING_REVIEW
    if ai_status == AiStatus.FAILED:
        return ReviewStatus.ANALYSIS_FAILED
    if ai_status == AiStatus.RUNNING:
        return ReviewStatus.ANALYZING
    if fulltext_status in (FulltextStatus.NOT_AVAILABLE, FulltextStatus.FAILED):
        return ReviewStatus.PENDING_FULLTEXT
    return ReviewStatus.PENDING_AI
