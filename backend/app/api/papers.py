"""Literature records, files, extracted text, notes and tags."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import save_upload
from app.api.envelope import ok
from app.core.config import get_settings
from app.core.constants import ParseStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.database.session import get_db
from app.models import PaperFile, PaperText, ResearchNote, Tag
from app.schemas import NoteCreate, NoteUpdate, PaperUpdate
from app.services import serializers
from app.services.analysis_service import request_analysis
from app.services.file_service import attach_fulltext_to_paper
from app.services.log_service import log_event
from app.services.paper_service import (
    add_note,
    analysis_map,
    delete_note,
    delete_paper,
    file_tree,
    get_paper_or_404,
    list_papers,
    paper_detail,
    resolve_duplicate,
    set_tags,
    tree_filter,
    update_note,
    update_paper,
)
from app.tasks.queue import enqueue_job

router = APIRouter(tags=["papers"])


@router.get("/papers/tree")
def get_tree(db: Session = Depends(get_db)):
    return ok({"nodes": file_tree(db)})


@router.get("/papers")
def get_papers(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str = "",
    folder: str = "all",
    tree_key: str = "",
    journal: str = "",
    year: int | None = None,
    tag: str = "",
    review_status: str = "",
    ai_status: str = "",
    fulltext_status: str = "",
    author: str = "",
    task_id: str = "",
    collection_id: str = "",
    paper_type: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "created_at",
    order: str = "desc",
):
    filters = {
        "q": q,
        "folder": folder,
        "journal": journal,
        "year": year,
        "tag": tag,
        "review_status": review_status,
        "ai_status": ai_status,
        "fulltext_status": fulltext_status,
        "author": author,
        "task_id": task_id,
        "collection_id": collection_id,
        "paper_type": paper_type,
        "sort": sort,
        "order": order,
    }
    if tree_key:
        for key, value in tree_filter(tree_key).items():
            if value and not filters.get(key):
                filters[key] = value
    if date_from:
        from datetime import date

        filters["date_from"] = date.fromisoformat(date_from)
    if date_to:
        from datetime import date

        filters["date_to"] = date.fromisoformat(date_to)
    filters["page"] = page
    filters["page_size"] = page_size
    return ok(list_papers(db, **filters))


@router.get("/papers/{paper_id}")
def get_paper(paper_id: str, db: Session = Depends(get_db)):
    return ok(paper_detail(db, paper_id))


@router.put("/papers/{paper_id}")
def edit_paper(paper_id: str, payload: PaperUpdate, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise ValidationAppError("没有需要更新的字段")
    return ok(update_paper(db, paper_id, data), message="文献信息已更新")


@router.delete("/papers/{paper_id}")
def remove_paper(paper_id: str, db: Session = Depends(get_db)):
    delete_paper(db, paper_id)
    return ok({"id": paper_id, "deleted": True}, message="文献已移入回收状态（原始文件保留在磁盘）")


@router.get("/papers/{paper_id}/file")
def get_paper_file(paper_id: str, db: Session = Depends(get_db), file_id: str = ""):
    settings = get_settings()
    paper = get_paper_or_404(db, paper_id)
    file = None
    if file_id:
        file = db.get(PaperFile, file_id)
        if file and file.paper_id != paper_id:
            file = None
    if not file:
        file = next((f for f in paper.files if f.is_primary), None) or (paper.files[0] if paper.files else None)
    if not file:
        raise NotFoundError("该文献尚未关联全文文件")
    path = (settings.data_dir / file.relative_path).resolve()
    if settings.data_dir.resolve() not in path.parents or not path.exists():
        raise NotFoundError("原始文件不存在，可能已被移动或删除")
    media = "application/pdf" if file.file_format == "pdf" else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media,
        filename=file.original_filename or path.name,
        content_disposition_type="inline",
    )


@router.get("/papers/{paper_id}/text")
def get_paper_text(paper_id: str, db: Session = Depends(get_db)):
    get_paper_or_404(db, paper_id)
    text = db.query(PaperText).filter(PaperText.paper_id == paper_id).first()
    if not text:
        return ok({"content": "", "page_map": [], "sections": [], "page_count": 0, "available": False})
    return ok(
        {
            "content": text.content,
            "page_map": text.page_map or [],
            "sections": text.sections or [],
            "page_count": text.page_count,
            "char_count": text.char_count,
            "quality": text.quality,
            "extractor": text.extractor,
            "error": text.error,
            "available": True,
        }
    )


@router.post("/papers/{paper_id}/parse")
def parse_paper(paper_id: str, db: Session = Depends(get_db)):
    paper = get_paper_or_404(db, paper_id)
    file = next((f for f in paper.files if f.is_primary), None) or (paper.files[0] if paper.files else None)
    if not file:
        raise ValidationAppError("该文献尚未关联全文文件")
    if file.file_format != "pdf":
        raise ValidationAppError("CAJ 等格式暂不支持解析，请导入你有权转换得到的 PDF")
    file.parse_status = ParseStatus.PENDING
    paper.parse_status = ParseStatus.PENDING
    db.commit()
    job = enqueue_job(
        db,
        "parse_paper",
        {"paper_id": paper.id, "file_id": file.id},
        dedupe_key=f"parse:{paper.id}",
        priority=2,
        commit=True,
    )
    log_event(db, "已请求解析全文", detail={"paper_id": paper.id}, commit=True)
    return ok(serializers.job_out(job), message="解析任务已排队")


@router.post("/papers/{paper_id}/analyze")
def analyze_paper(paper_id: str, db: Session = Depends(get_db), force: bool = Query(False)):
    paper = get_paper_or_404(db, paper_id)
    if not paper.abstract and not paper.texts:
        raise ValidationAppError("缺少摘要和全文，无法分析")
    jobs = request_analysis(db, [paper_id], force=force)
    return ok({"jobs": jobs}, message="AI 分析任务已排队")


@router.post("/papers/{paper_id}/attach-file")
async def attach_file(paper_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    paper = get_paper_or_404(db, paper_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".caj"):
        await file.close()
        raise ValidationAppError("仅支持 PDF/CAJ")
    temp_path = await save_upload(file, prefix="attach_")
    outcome = attach_fulltext_to_paper(db, paper, temp_path, origin="manual_attach")
    temp_path.unlink(missing_ok=True)
    return ok(
        {"status": outcome.status, "message": outcome.message, "paper_id": paper_id},
        message=outcome.message,
    )


@router.get("/papers/{paper_id}/notes")
def get_notes(paper_id: str, db: Session = Depends(get_db)):
    get_paper_or_404(db, paper_id)
    notes = (
        db.query(ResearchNote)
        .filter(ResearchNote.paper_id == paper_id)
        .order_by(ResearchNote.created_at.desc())
        .all()
    )
    return ok({"items": [serializers.note_out(note) for note in notes]})


@router.post("/papers/{paper_id}/notes")
def create_note(paper_id: str, payload: NoteCreate, db: Session = Depends(get_db)):
    note = add_note(db, paper_id, payload.content, payload.note_type, payload.title)
    return ok(note, message="笔记已保存")


@router.put("/notes/{note_id}")
def edit_note(note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)):
    note = update_note(db, note_id, payload.model_dump(exclude_unset=True))
    return ok(note, message="笔记已更新")


@router.delete("/notes/{note_id}")
def remove_note(note_id: str, db: Session = Depends(get_db)):
    delete_note(db, note_id)
    return ok({"id": note_id}, message="笔记已删除")


@router.post("/papers/{paper_id}/tags")
def add_tags(
    paper_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    paper = get_paper_or_404(db, paper_id)
    names = payload.get("tags") or []
    replace = bool(payload.get("replace", False))
    if not isinstance(names, list):
        raise ValidationAppError("tags 必须是数组")
    added = set_tags(db, paper, [str(name) for name in names], replace=replace)
    db.commit()
    db.refresh(paper)
    return ok({"tags": [serializers.tag_out(tag) for tag in paper.tags], "added": len(added)})


@router.delete("/papers/{paper_id}/tags/{tag_id}")
def remove_tag(paper_id: str, tag_id: str, db: Session = Depends(get_db)):
    from app.models import PaperTag

    link = db.get(PaperTag, (paper_id, tag_id))
    if not link:
        raise NotFoundError("该文献没有此标签")
    db.delete(link)
    db.commit()
    return ok({"paper_id": paper_id, "tag_id": tag_id})


@router.post("/papers/{paper_id}/duplicate")
def duplicate_action(paper_id: str, payload: dict, db: Session = Depends(get_db)):
    action = payload.get("action", "")
    return ok(resolve_duplicate(db, paper_id, action), message="重复状态已更新")


@router.get("/papers/{paper_id}/reviews")
def paper_reviews(paper_id: str, db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500)):
    get_paper_or_404(db, paper_id)
    from app.models import PaperReview

    reviews = (
        db.query(PaperReview)
        .filter(PaperReview.paper_id == paper_id)
        .order_by(PaperReview.created_at.desc())
        .limit(limit)
        .all()
    )
    return ok({"items": [serializers.review_out(r) for r in reviews]})
