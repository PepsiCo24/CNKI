"""Response serializers. API contracts are explicit and independent from ORM internals."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from app.core.constants import REVIEW_LABELS
from app.models import (
    AiAnalysisJob,
    AiAnalysisResult,
    BackgroundJob,
    ImportJob,
    InnovationItem,
    Paper,
    PaperFile,
    PaperReview,
    PromptTemplate,
    ResearchNote,
    SearchTask,
    Tag,
    TaskLog,
)


def iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        # SQLite drops tzinfo; stored timestamps are UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value.isoformat()


def tag_out(tag: Tag) -> dict[str, Any]:
    return {"id": tag.id, "name": tag.name, "category": tag.category, "color": tag.color}


def file_out(file: PaperFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "original_filename": file.original_filename,
        "stored_filename": file.stored_filename,
        "relative_path": file.relative_path,
        "file_format": file.file_format,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "sha256": file.sha256,
        "is_primary": file.is_primary,
        "origin": file.origin,
        "parse_status": file.parse_status,
        "parse_error": file.parse_error,
        "page_count": file.page_count,
        "created_at": iso(file.created_at),
    }


def analysis_out(result: AiAnalysisResult, *, include_raw: bool = False) -> dict[str, Any]:
    data = {
        "id": result.id,
        "paper_id": result.paper_id,
        "job_id": result.job_id,
        "provider": result.provider,
        "model": result.model,
        "is_mock": result.is_mock,
        "prompt_version": result.prompt_version,
        "parameters": result.parameters or {},
        "analysis_scope": result.analysis_scope,
        "input_chars": result.input_chars,
        "one_sentence_summary": result.one_sentence_summary,
        "research_problem": result.research_problem,
        "main_method": result.main_method,
        "claimed_innovations": result.claimed_innovations or [],
        "inferred_contributions": result.inferred_contributions or [],
        "innovation_summary": result.innovation_summary,
        "key_results": result.key_results or [],
        "research_value": result.research_value,
        "limitations": result.limitations or [],
        "screening_score": result.screening_score,
        "screening_reason": result.screening_reason,
        "evidence": result.evidence or [],
        "missing_information": result.missing_information or [],
        "tags_suggestion": result.tags_suggestion or [],
        "is_current": result.is_current,
        "is_edited": result.is_edited,
        "edited_at": iso(result.edited_at),
        "original_result": result.original_result,
        "cache_key": result.cache_key,
        "created_at": iso(result.created_at),
        "updated_at": iso(result.updated_at),
    }
    if include_raw:
        data["raw_response"] = result.raw_response
    return data


def paper_summary(
    paper: Paper,
    *,
    analysis: AiAnalysisResult | None = None,
    task_names: list[str] | None = None,
) -> dict[str, Any]:
    primary = next((f for f in paper.files if f.is_primary), None) or (paper.files[0] if paper.files else None)
    return {
        "id": paper.id,
        "title": paper.title,
        "authors": paper.authors or [],
        "authors_text": paper.authors_text,
        "journal": paper.journal,
        "year": paper.year,
        "publication_date": iso(paper.publication_date),
        "publication_date_precision": paper.publication_date_precision,
        "publication_date_raw": paper.publication_date_raw,
        "doi": paper.doi,
        "source": paper.source,
        "source_id": paper.source_id,
        "source_url": paper.source_url,
        "abstract": paper.abstract,
        "keywords": paper.keywords or [],
        "paper_type": paper.paper_type,
        "language": paper.language,
        "fulltext_status": paper.fulltext_status,
        "parse_status": paper.parse_status,
        "ai_status": paper.ai_status,
        "review_status": paper.review_status,
        "review_label": REVIEW_LABELS.get(paper.review_status, paper.review_status),
        "duplicate_status": paper.duplicate_status,
        "duplicate_of_id": paper.duplicate_of_id,
        "metadata_source": paper.metadata_source,
        "file_count": len(paper.files),
        "has_fulltext": paper.fulltext_status == "imported",
        "primary_file": file_out(primary) if primary else None,
        "tags": [tag_out(t) for t in paper.tags],
        "created_at": iso(paper.created_at),
        "updated_at": iso(paper.updated_at),
        "imported_at": iso(paper.imported_at),
        "one_sentence_summary": analysis.one_sentence_summary if analysis else "",
        "innovation_summary": analysis.innovation_summary if analysis else "",
        "screening_score": analysis.screening_score if analysis else None,
        "analysis_id": analysis.id if analysis else None,
        "is_mock": bool(analysis.is_mock) if analysis else False,
        "task_names": task_names or [],
    }


def paper_detail(
    paper: Paper,
    *,
    analysis: AiAnalysisResult | None = None,
    history: list[AiAnalysisResult] | None = None,
    notes: list[ResearchNote] | None = None,
    tasks: list[SearchTask] | None = None,
    reviews: list[PaperReview] | None = None,
) -> dict[str, Any]:
    data = paper_summary(paper, analysis=analysis, task_names=[t.name for t in (tasks or [])])
    text = paper.texts[0] if paper.texts else None
    data.update(
        {
            "files": [file_out(f) for f in paper.files],
            "text_info": {
                "char_count": text.char_count if text else 0,
                "page_count": text.page_count if text else 0,
                "quality": text.quality if text else "",
                "extractor": text.extractor if text else "",
                "error": text.error if text else "",
                "sections": text.sections if text else [],
            }
            if text
            else None,
            "analysis": analysis_out(analysis) if analysis else None,
            "analysis_history": [analysis_out(item) for item in (history or [])],
            "notes": [note_out(n) for n in (notes or [])],
            "reviews": [review_out(r) for r in (reviews or [])],
            "task_ids": [t.id for t in (tasks or [])],
            "raw_metadata": paper.raw_metadata or {},
            "online_first_date": iso(paper.online_first_date),
            "update_date": iso(paper.update_date),
        }
    )
    return data


def note_out(note: ResearchNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "paper_id": note.paper_id,
        "title": note.title,
        "content": note.content,
        "note_type": note.note_type,
        "created_at": iso(note.created_at),
        "updated_at": iso(note.updated_at),
    }


def review_out(review: PaperReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "paper_id": review.paper_id,
        "action": review.action,
        "from_status": review.from_status,
        "to_status": review.to_status,
        "note": review.note,
        "reviewer": review.reviewer,
        "snapshot": review.snapshot or {},
        "previous_status": review.previous_status,
        "is_undo": review.is_undo,
        "created_at": iso(review.created_at),
    }


def task_out(task: SearchTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "source": task.source,
        "paper_type": task.paper_type,
        "journal": task.journal,
        "keywords": task.keywords,
        "match_mode": task.match_mode,
        "start_date": iso(task.start_date),
        "end_date": iso(task.end_date),
        "sort_by": task.sort_by,
        "import_mode": task.import_mode,
        "status": task.status,
        "progress": task.progress,
        "discovered_count": task.discovered_count,
        "imported_count": task.imported_count,
        "analyzed_count": task.analyzed_count,
        "included_count": task.included_count,
        "error_message": task.error_message,
        "conditions_snapshot": task.conditions_snapshot or {},
        "extra": task.extra or {},
        "started_at": iso(task.started_at),
        "finished_at": iso(task.finished_at),
        "last_run_at": iso(task.last_run_at),
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
    }


def job_out(job: BackgroundJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "payload": job.payload or {},
        "priority": job.priority,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "cancel_requested": bool(job.cancel_requested),
        "task_id": job.task_id,
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
    }


def import_job_out(job: ImportJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "source_path": job.source_path,
        "task_id": job.task_id,
        "background_job_id": job.background_job_id,
        "total": job.total,
        "processed": job.processed,
        "imported": job.imported,
        "duplicates": job.duplicates,
        "failed": job.failed,
        "errors": job.errors or [],
        "detail": job.detail or {},
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
    }


def ai_job_out(job: AiAnalysisJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "paper_id": job.paper_id,
        "background_job_id": job.background_job_id,
        "status": job.status,
        "provider": job.provider,
        "model": job.model,
        "prompt_version": job.prompt_version,
        "input_chars": job.input_chars,
        "chunk_count": job.chunk_count,
        "analysis_scope": job.analysis_scope,
        "tokens_prompt": job.tokens_prompt,
        "tokens_completion": job.tokens_completion,
        "estimated_cost": job.estimated_cost,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "result_id": job.result_id,
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
    }


def prompt_out(prompt: PromptTemplate) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "name": prompt.name,
        "content": prompt.content,
        "version": prompt.version,
        "is_default": bool(prompt.is_default),
        "is_active": bool(prompt.is_active),
        "description": prompt.description,
        "created_at": iso(prompt.created_at),
        "updated_at": iso(prompt.updated_at),
    }


def innovation_out(item: InnovationItem, paper: Paper | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "paper_id": item.paper_id,
        "result_id": item.result_id,
        "seq": item.seq,
        "name": item.name,
        "core_technique": item.core_technique,
        "description": item.description,
        "evidence": item.evidence,
        "page": item.page,
        "note": item.note,
        "tags_snapshot": item.tags_snapshot or [],
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
        "paper": {
            "id": paper.id,
            "title": paper.title,
            "authors": paper.authors or [],
            "journal": paper.journal,
            "year": paper.year,
            "doi": paper.doi,
        }
        if paper
        else None,
    }


def log_out(log: TaskLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "task_id": log.task_id,
        "job_id": log.job_id,
        "level": log.level,
        "message": log.message,
        "detail": log.detail or {},
        "created_at": iso(log.created_at),
    }
