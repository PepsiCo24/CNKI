"""Analysis job creation, result editing (with originals) and AI usage statistics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.constants import AiStatus, ReviewStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.database.fts import index_paper
from app.models import AiAnalysisJob, AiAnalysisResult, InnovationItem, Paper, PromptTemplate
from app.services import serializers
from app.services.settings_service import SettingsService
from app.tasks.queue import enqueue_job

EDITABLE_FIELDS = [
    "one_sentence_summary",
    "research_problem",
    "main_method",
    "claimed_innovations",
    "inferred_contributions",
    "innovation_summary",
    "key_results",
    "research_value",
    "limitations",
    "screening_score",
    "screening_reason",
    "evidence",
    "missing_information",
    "tags_suggestion",
]


def request_analysis(
    db: Session,
    paper_ids: list[str],
    *,
    force: bool = False,
    prompt_template_id: str | None = None,
) -> list[dict[str, Any]]:
    settings = SettingsService(db)
    config = settings.ai_config()  # raises NotConfiguredError with actionable message
    prompt = _resolve_prompt(db, settings, prompt_template_id)
    created: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        paper = db.get(Paper, paper_id)
        if not paper or paper.is_deleted:
            raise NotFoundError(f"文献不存在：{paper_id}")
        active = (
            db.query(AiAnalysisJob)
            .filter(
                AiAnalysisJob.paper_id == paper_id,
                AiAnalysisJob.status.in_([AiStatus.QUEUED, AiStatus.RUNNING]),
            )
            .first()
        )
        if active and not force:
            created.append(serializers.ai_job_out(active))
            continue
        job = AiAnalysisJob(
            paper_id=paper_id,
            status=AiStatus.QUEUED,
            provider=config.provider,
            model=config.model,
            prompt_template_id=prompt.id if prompt else None,
            prompt_version=prompt.version if prompt else 1,
            analysis_scope="fulltext",
            max_attempts=2,
        )
        db.add(job)
        db.flush()
        dedupe_key = f"analyze:{paper_id}" if not force else f"analyze:{paper_id}:{uuid4().hex[:8]}"
        bg = enqueue_job(
            db,
            "analyze_paper",
            {
                "paper_id": paper_id,
                "ai_job_id": job.id,
                "force": force,
                "prompt_template_id": prompt_template_id,
            },
            dedupe_key=dedupe_key,
            priority=3,
            max_attempts=2,
            commit=False,
        )
        job.background_job_id = bg.id
        if paper.ai_status not in (AiStatus.COMPLETED, AiStatus.CACHED) or force:
            paper.ai_status = AiStatus.QUEUED
        if paper.review_status not in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED):
            paper.review_status = ReviewStatus.PENDING_AI
        db.commit()
        created.append(serializers.ai_job_out(job))
    return created


def _resolve_prompt(db: Session, settings: SettingsService, prompt_id: str | None) -> PromptTemplate | None:
    if prompt_id:
        prompt = db.get(PromptTemplate, prompt_id)
        if prompt:
            return prompt
    configured = settings.get("ai.prompt_template_id", "")
    if configured:
        prompt = db.get(PromptTemplate, configured)
        if prompt:
            return prompt
    return db.query(PromptTemplate).filter(PromptTemplate.is_default.is_(True)).first()


def edit_analysis(db: Session, result_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = db.get(AiAnalysisResult, result_id)
    if not result:
        raise NotFoundError("分析结果不存在")
    if not result.is_current:
        raise ValidationAppError("只能编辑当前版本的分析结果")
    if result.original_result is None:
        result.original_result = {
            field: getattr(result, field) for field in EDITABLE_FIELDS
        } | {
            "provider": result.provider,
            "model": result.model,
            "prompt_version": result.prompt_version,
            "saved_at": utcnow().isoformat(),
        }
    changed = False
    for key, value in payload.items():
        if value is not None and key in EDITABLE_FIELDS:
            setattr(result, key, value)
            changed = True
    if changed:
        result.is_edited = True
        result.edited_at = utcnow()
        result.updated_at = utcnow()
        db.query(InnovationItem).filter(InnovationItem.result_id == result.id).delete()
        for seq, item in enumerate((result.claimed_innovations or [])[:3], start=1):
            db.add(
                InnovationItem(
                    paper_id=result.paper_id,
                    result_id=result.id,
                    seq=seq,
                    name=(item.get("name") or f"创新点 {seq}")[:300],
                    core_technique=(item.get("method") or "")[:500],
                    description=(item.get("difference") or item.get("problem") or "")[:4000],
                    evidence=(item.get("evidence") or "")[:4000],
                    page=item.get("page"),
                    tags_snapshot=(result.tags_suggestion or [])[:8],
                )
            )
        paper = db.get(Paper, result.paper_id)
        if paper:
            index_paper(db, paper)
    db.commit()
    db.refresh(result)
    return serializers.analysis_out(result)


def analysis_stats(db: Session) -> dict[str, Any]:
    status_rows = dict(
        db.query(AiAnalysisJob.status, func.count(AiAnalysisJob.id)).group_by(AiAnalysisJob.status).all()
    )
    token_row = (
        db.query(
            func.coalesce(func.sum(AiAnalysisJob.tokens_prompt), 0),
            func.coalesce(func.sum(AiAnalysisJob.tokens_completion), 0),
            func.coalesce(func.sum(AiAnalysisJob.estimated_cost), 0.0),
        )
        .first()
    )
    model_rows = (
        db.query(AiAnalysisResult.model, func.count(AiAnalysisResult.id))
        .filter(AiAnalysisResult.is_current.is_(True))
        .group_by(AiAnalysisResult.model)
        .order_by(func.count(AiAnalysisResult.id).desc())
        .limit(8)
        .all()
    )
    recent_jobs = (
        db.query(AiAnalysisJob)
        .order_by(AiAnalysisJob.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "status_counts": status_rows,
        "tokens_prompt": int(token_row[0] or 0),
        "tokens_completion": int(token_row[1] or 0),
        "estimated_cost": float(token_row[2] or 0),
        "models": [{"model": model or "未记录", "count": count} for model, count in model_rows],
        "recent_jobs": [serializers.ai_job_out(job) for job in recent_jobs],
    }


def ai_jobs_list(db: Session, status: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
    query = db.query(AiAnalysisJob)
    if status:
        query = query.filter(AiAnalysisJob.status == status)
    total = query.count()
    jobs = (
        query.order_by(AiAnalysisJob.created_at.desc())
        .offset((max(1, page) - 1) * page_size)
        .limit(page_size)
        .all()
    )
    paper_ids = [job.paper_id for job in jobs]
    papers = {p.id: p for p in db.query(Paper).filter(Paper.id.in_(paper_ids)).all()} if paper_ids else {}
    bg_ids = [job.background_job_id for job in jobs if job.background_job_id]
    from app.models import BackgroundJob

    backgrounds = {
        bg.id: bg for bg in db.query(BackgroundJob).filter(BackgroundJob.id.in_(bg_ids)).all()
    } if bg_ids else {}
    items = []
    for job in jobs:
        item = serializers.ai_job_out(job)
        paper = papers.get(job.paper_id)
        item["paper"] = {"id": paper.id, "title": paper.title} if paper else None
        bg = backgrounds.get(job.background_job_id or "")
        item["progress"] = bg.progress if bg else (100 if job.status in ("completed", "cached") else 0)
        item["message"] = bg.message if bg else ""
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}
