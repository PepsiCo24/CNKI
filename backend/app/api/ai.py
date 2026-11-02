"""AI analysis job endpoints and result editing."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.envelope import ok
from app.core.constants import AiStatus, FulltextStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.database.session import get_db
from app.models import AiAnalysisJob, AiAnalysisResult, BackgroundJob, Paper
from app.schemas import AnalysisEditIn, AnalyzeRequest
from app.services import serializers
from app.services.analysis_service import ai_jobs_list, analysis_stats, edit_analysis, request_analysis
from app.services.log_service import log_event
from app.tasks.runner import cancel_background_job

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze")
def analyze(payload: AnalyzeRequest, db: Session = Depends(get_db)):
    if not payload.paper_ids:
        raise ValidationAppError("请至少选择一篇文献")
    jobs = request_analysis(
        db,
        payload.paper_ids[:100],
        force=payload.force,
        prompt_template_id=payload.prompt_template_id,
    )
    return ok({"jobs": jobs}, message=f"已排队 {len(jobs)} 个分析任务")


@router.post("/analyze-pending")
def analyze_pending(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
    force: bool = False,
):
    query = (
        db.query(Paper)
        .filter(
            Paper.is_deleted.is_(False),
            Paper.fulltext_status == FulltextStatus.IMPORTED,
            Paper.ai_status.in_([AiStatus.NOT_ANALYZED, AiStatus.FAILED]),
        )
        .order_by(Paper.updated_at.asc())
        .limit(limit)
    )
    paper_ids = [paper.id for paper in query.all()]
    if not paper_ids:
        return ok({"jobs": [], "message": "没有待分析文献"})
    jobs = request_analysis(db, paper_ids, force=force)
    return ok({"jobs": jobs}, message=f"已排队 {len(jobs)} 个分析任务")


@router.get("/jobs")
def list_ai_jobs(
    db: Session = Depends(get_db),
    status: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return ok(ai_jobs_list(db, status=status, page=page, page_size=page_size))


@router.get("/jobs/{job_id}")
def get_ai_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(AiAnalysisJob, job_id)
    if not job:
        raise NotFoundError("AI 任务不存在")
    data = serializers.ai_job_out(job)
    paper = db.get(Paper, job.paper_id)
    data["paper"] = {"id": paper.id, "title": paper.title} if paper else None
    if job.result_id:
        result = db.get(AiAnalysisResult, job.result_id)
        data["result"] = serializers.analysis_out(result) if result else None
    return ok(data)


@router.post("/jobs/{job_id}/cancel")
def cancel_ai_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(AiAnalysisJob, job_id)
    if not job:
        raise NotFoundError("AI 任务不存在")
    if job.status in (AiStatus.QUEUED, AiStatus.RUNNING):
        job.status = AiStatus.FAILED
        job.error = "用户取消"
        job.finished_at = utcnow()
        if job.background_job_id:
            bg = db.get(BackgroundJob, job.background_job_id)
            if bg:
                cancel_background_job(db, bg)
        paper = db.get(Paper, job.paper_id)
        if paper and paper.ai_status == AiStatus.RUNNING:
            paper.ai_status = AiStatus.FAILED
        db.commit()
        log_event(db, "AI 任务已取消", detail={"ai_job_id": job.id}, commit=True)
    return ok(serializers.ai_job_out(job), message="已请求取消")


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return ok(analysis_stats(db))


@router.get("/results/{result_id}")
def get_result(result_id: str, db: Session = Depends(get_db)):
    result = db.get(AiAnalysisResult, result_id)
    if not result:
        raise NotFoundError("分析结果不存在")
    return ok(serializers.analysis_out(result, include_raw=True))


@router.put("/results/{result_id}")
def update_result(result_id: str, payload: AnalysisEditIn, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise ValidationAppError("没有需要更新的字段")
    result = edit_analysis(db, result_id, data)
    return ok(result, message="分析结果已人工编辑（原始版本已保留）")


@router.get("/papers/{paper_id}/analysis")
def paper_analysis(paper_id: str, db: Session = Depends(get_db)):
    paper = db.get(Paper, paper_id)
    if not paper or paper.is_deleted:
        raise NotFoundError("文献不存在")
    results = (
        db.query(AiAnalysisResult)
        .filter(AiAnalysisResult.paper_id == paper_id)
        .order_by(AiAnalysisResult.created_at.desc())
        .all()
    )
    return ok(
        {
            "current": serializers.analysis_out(results[0]) if results and results[0].is_current else None,
            "history": [serializers.analysis_out(item) for item in results],
            "ai_status": paper.ai_status,
        }
    )
