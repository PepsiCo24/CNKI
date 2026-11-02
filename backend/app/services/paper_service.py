"""Paper queries, library listing, dashboard aggregates, tags, notes and collections."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.core.constants import AiStatus, FulltextStatus, ParseStatus, ReviewStatus
from app.core.errors import NotFoundError, ValidationAppError
from app.core.utils import utcnow
from app.database.fts import index_paper, remove_paper, search_ids
from app.models import (
    AiAnalysisJob,
    AiAnalysisResult,
    Collection,
    CollectionPaper,
    InnovationItem,
    Paper,
    PaperFile,
    PaperReview,
    PaperTag,
    ResearchNote,
    SearchTask,
    SearchTaskPaper,
    Tag,
)
from app.services import serializers
from app.services.file_service import _write_metadata_sidecar
from app.services.log_service import log_event

SORT_FIELDS = {
    "created_at": Paper.created_at,
    "updated_at": Paper.updated_at,
    "publication_date": Paper.publication_date,
    "year": Paper.year,
    "title": Paper.title,
    "journal": Paper.journal,
}


def current_analysis(db: Session, paper_id: str) -> AiAnalysisResult | None:
    return (
        db.query(AiAnalysisResult)
        .filter(AiAnalysisResult.paper_id == paper_id, AiAnalysisResult.is_current.is_(True))
        .order_by(AiAnalysisResult.created_at.desc())
        .first()
    )


def analysis_map(db: Session, paper_ids: list[str]) -> dict[str, AiAnalysisResult]:
    if not paper_ids:
        return {}
    rows = (
        db.query(AiAnalysisResult)
        .filter(AiAnalysisResult.paper_id.in_(paper_ids), AiAnalysisResult.is_current.is_(True))
        .order_by(AiAnalysisResult.created_at.desc())
        .all()
    )
    result: dict[str, AiAnalysisResult] = {}
    for row in rows:
        result.setdefault(row.paper_id, row)
    return result


def task_name_map(db: Session, paper_ids: list[str]) -> dict[str, list[str]]:
    if not paper_ids:
        return {}
    rows = (
        db.query(SearchTaskPaper.paper_id, SearchTask.name)
        .join(SearchTask, SearchTask.id == SearchTaskPaper.task_id)
        .filter(SearchTaskPaper.paper_id.in_(paper_ids))
        .all()
    )
    result: dict[str, list[str]] = {}
    for paper_id, name in rows:
        result.setdefault(paper_id, []).append(name)
    return result


def get_paper_or_404(db: Session, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if not paper or paper.is_deleted:
        raise NotFoundError("文献不存在")
    return paper


def paper_detail(db: Session, paper_id: str) -> dict[str, Any]:
    paper = get_paper_or_404(db, paper_id)
    analysis = current_analysis(db, paper_id)
    history = (
        db.query(AiAnalysisResult)
        .filter(AiAnalysisResult.paper_id == paper_id)
        .order_by(AiAnalysisResult.created_at.desc())
        .all()
    )
    notes = (
        db.query(ResearchNote)
        .filter(ResearchNote.paper_id == paper_id)
        .order_by(ResearchNote.created_at.desc())
        .all()
    )
    tasks = (
        db.query(SearchTask)
        .join(SearchTaskPaper, SearchTaskPaper.task_id == SearchTask.id)
        .filter(SearchTaskPaper.paper_id == paper_id)
        .all()
    )
    reviews = (
        db.query(PaperReview)
        .filter(PaperReview.paper_id == paper_id)
        .order_by(PaperReview.created_at.desc())
        .limit(30)
        .all()
    )
    return serializers.paper_detail(
        paper,
        analysis=analysis,
        history=history,
        notes=notes,
        tasks=tasks,
        reviews=reviews,
    )


def _apply_folder(query, folder: str):
    if not folder or folder == "all":
        return query
    if folder == "pending_analysis":
        return query.filter(
            Paper.fulltext_status == FulltextStatus.IMPORTED,
            Paper.ai_status.in_([AiStatus.NOT_ANALYZED, AiStatus.FAILED]),
        )
    if folder == "pending_review":
        return query.filter(Paper.review_status == ReviewStatus.PENDING_REVIEW)
    if folder == "included":
        return query.filter(Paper.review_status == ReviewStatus.INCLUDED)
    if folder == "excluded":
        return query.filter(Paper.review_status == ReviewStatus.EXCLUDED)
    if folder == "deferred":
        return query.filter(Paper.review_status == ReviewStatus.DEFERRED)
    if folder == "failed":
        return query.filter(
            or_(
                Paper.review_status == ReviewStatus.ANALYSIS_FAILED,
                Paper.parse_status == ParseStatus.FAILED,
                Paper.fulltext_status == FulltextStatus.FAILED,
            )
        )
    if folder == "duplicates":
        return query.filter(Paper.duplicate_status == "suspected")
    if folder == "no_fulltext":
        return query.filter(Paper.fulltext_status != FulltextStatus.IMPORTED)
    return query


def list_papers(
    db: Session,
    *,
    q: str = "",
    folder: str = "all",
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
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "created_at",
    order: str = "desc",
    include_deleted: bool = False,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    query = db.query(Paper)
    if not include_deleted:
        query = query.filter(Paper.is_deleted.is_(False))
    query = _apply_folder(query, folder)
    if review_status:
        query = query.filter(Paper.review_status == review_status)
    if ai_status:
        query = query.filter(Paper.ai_status == ai_status)
    if fulltext_status:
        query = query.filter(Paper.fulltext_status == fulltext_status)
    if journal:
        query = query.filter(Paper.journal == journal)
    if year:
        query = query.filter(Paper.year == year)
    if paper_type:
        query = query.filter(Paper.paper_type == paper_type)
    if author:
        query = query.filter(Paper.authors_text.like(f"%{author}%"))
    if task_id:
        query = query.join(SearchTaskPaper, SearchTaskPaper.paper_id == Paper.id).filter(
            SearchTaskPaper.task_id == task_id
        )
    if collection_id:
        query = query.join(CollectionPaper, CollectionPaper.paper_id == Paper.id).filter(
            CollectionPaper.collection_id == collection_id
        )
    if tag:
        query = (
            query.join(PaperTag, PaperTag.paper_id == Paper.id)
            .join(Tag, Tag.id == PaperTag.tag_id)
            .filter(or_(Tag.name == tag, Tag.id == tag))
        )
    if date_from:
        query = query.filter(Paper.publication_date >= date_from)
    if date_to:
        query = query.filter(Paper.publication_date <= date_to)

    fts_ids: list[str] = []
    if q.strip():
        fts_ids = search_ids(db, q.strip(), limit=1000)
        if not fts_ids:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        query = query.filter(Paper.id.in_(fts_ids))
        # Rank by FTS relevance while still honouring every other filter. Personal
        # libraries are small enough (bounded at 1000) to paginate in memory.
        candidates = query.all()
        order_index = {pid: idx for idx, pid in enumerate(fts_ids)}
        candidates.sort(key=lambda p: order_index.get(p.id, 999999))
        total = len(candidates)
        papers = candidates[(page - 1) * page_size : page * page_size]
    else:
        total = query.with_entities(func.count(func.distinct(Paper.id))).scalar() or 0
        if sort == "screening_score":
            current = (
                db.query(AiAnalysisResult.paper_id, AiAnalysisResult.screening_score)
                .filter(AiAnalysisResult.is_current.is_(True))
                .subquery()
            )
            query = query.outerjoin(current, current.c.paper_id == Paper.id)
            column = func.coalesce(current.c.screening_score, -1)
        else:
            column = SORT_FIELDS.get(sort, Paper.created_at)
        if order == "asc":
            query = query.order_by(column.asc(), Paper.id.asc())
        else:
            query = query.order_by(column.desc(), Paper.id.desc())
        papers = query.offset((page - 1) * page_size).limit(page_size).all()

    ids = [p.id for p in papers]
    analyses = analysis_map(db, ids)
    task_names = task_name_map(db, ids)
    items = [
        serializers.paper_summary(p, analysis=analyses.get(p.id), task_names=task_names.get(p.id, []))
        for p in papers
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def update_paper(db: Session, paper_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from app.core.utils import normalize_title

    paper = get_paper_or_404(db, paper_id)
    data = {k: v for k, v in payload.items() if v is not None}
    for key, value in data.items():
        if key == "authors":
            paper.authors = value
            paper.authors_text = "; ".join(value)
        elif key == "title":
            paper.title = value
            paper.title_normalized = normalize_title(value)
        else:
            setattr(paper, key, value)
    if "publication_date" in data:
        pub_date = data["publication_date"]
        if pub_date and paper.publication_date_precision == "unknown":
            paper.publication_date_precision = "day"
        if pub_date:
            paper.year = pub_date.year
            paper.month = pub_date.month
            paper.publication_date_raw = pub_date.isoformat()
    paper.updated_at = utcnow()
    db.flush()
    index_paper(db, paper)
    _write_metadata_sidecar(paper, next((f for f in paper.files if f.is_primary), None))
    log_event(db, f"文献元数据已更新：{paper.title[:60]}", detail={"paper_id": paper.id})
    db.commit()
    return paper_detail(db, paper_id)


def delete_paper(db: Session, paper_id: str) -> None:
    """Soft delete: keep original files and audit history on disk."""
    paper = get_paper_or_404(db, paper_id)
    paper.is_deleted = True
    paper.updated_at = utcnow()
    remove_paper(db, paper_id)
    db.commit()


def resolve_duplicate(db: Session, paper_id: str, action: str) -> dict[str, Any]:
    paper = get_paper_or_404(db, paper_id)
    if paper.duplicate_status != "suspected":
        raise ValidationAppError("该文献没有待确认的重复提示")
    if action == "keep_separate":
        paper.duplicate_status = "none"
        paper.duplicate_of_id = None
    elif action == "confirm_duplicate":
        paper.duplicate_status = "confirmed"
    else:
        raise ValidationAppError("未知的重复处理方式")
    db.commit()
    return paper_detail(db, paper_id)


def set_tags(db: Session, paper: Paper, tag_names: list[str], *, replace: bool = False) -> list[Tag]:
    from datetime import datetime as _dt

    if replace:
        db.query(PaperTag).filter(PaperTag.paper_id == paper.id).delete()
        db.flush()
    current = {tag.name for tag in paper.tags}
    added: list[Tag] = []
    for name in tag_names:
        name = (name or "").strip()
        if not name or name in current:
            continue
        tag = db.query(Tag).filter(Tag.name == name).first()
        if not tag:
            tag = Tag(name=name, category="自定义", color="#909399")
            db.add(tag)
            db.flush()
        db.add(PaperTag(paper_id=paper.id, tag_id=tag.id, created_at=utcnow()))
        current.add(name)
        added.append(tag)
    db.flush()
    db.refresh(paper)
    return added


def list_tags(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(Tag, func.count(PaperTag.paper_id))
        .outerjoin(PaperTag, PaperTag.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.category, Tag.name)
        .all()
    )
    return [
        {**serializers.tag_out(tag), "paper_count": count}
        for tag, count in rows
    ]


def create_tag(db: Session, name: str, category: str, color: str) -> dict[str, Any]:
    existing = db.query(Tag).filter(Tag.name == name).first()
    if existing:
        return serializers.tag_out(existing)
    tag = Tag(name=name.strip(), category=category or "通用", color=color or "#409EFF")
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return serializers.tag_out(tag)


def update_tag(db: Session, tag_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tag = db.get(Tag, tag_id)
    if not tag:
        raise NotFoundError("标签不存在")
    for key, value in payload.items():
        if value is not None:
            setattr(tag, key, value)
    db.commit()
    return serializers.tag_out(tag)


def delete_tag(db: Session, tag_id: str) -> None:
    tag = db.get(Tag, tag_id)
    if not tag:
        raise NotFoundError("标签不存在")
    db.delete(tag)
    db.commit()


def add_note(db: Session, paper_id: str, content: str, note_type: str, title: str = "") -> dict[str, Any]:
    paper = get_paper_or_404(db, paper_id)
    note = ResearchNote(paper_id=paper.id, content=content, note_type=note_type, title=title)
    db.add(note)
    db.flush()
    paper.notes_summary = " ".join(
        n.content for n in db.query(ResearchNote).filter(ResearchNote.paper_id == paper_id).limit(5)
    )[:2000]
    index_paper(db, paper)
    log_event(db, f"新增笔记：{paper.title[:40]}", detail={"paper_id": paper.id})
    db.commit()
    db.refresh(note)
    return serializers.note_out(note)


def update_note(db: Session, note_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    note = db.get(ResearchNote, note_id)
    if not note:
        raise NotFoundError("笔记不存在")
    for key, value in payload.items():
        if value is not None:
            setattr(note, key, value)
    db.commit()
    return serializers.note_out(note)


def delete_note(db: Session, note_id: str) -> None:
    note = db.get(ResearchNote, note_id)
    if not note:
        raise NotFoundError("笔记不存在")
    db.delete(note)
    db.commit()


# ------------------------------------------------------------------------- collections
def list_collections(db: Session) -> list[dict[str, Any]]:
    collections = db.query(Collection).order_by(Collection.sort_order, Collection.name).all()
    counts = dict(
        db.query(CollectionPaper.collection_id, func.count(CollectionPaper.paper_id))
        .group_by(CollectionPaper.collection_id)
        .all()
    )
    nodes = {
        c.id: {
            "id": c.id,
            "name": c.name,
            "parent_id": c.parent_id,
            "color": c.color,
            "count": counts.get(c.id, 0),
            "children": [],
        }
        for c in collections
    }
    roots: list[dict[str, Any]] = []
    for node in nodes.values():
        parent = nodes.get(node["parent_id"]) if node["parent_id"] else None
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


def create_collection(db: Session, name: str, parent_id: str | None = None, color: str = "#909399") -> dict[str, Any]:
    if not name.strip():
        raise ValidationAppError("文件夹名称不能为空")
    if parent_id and not db.get(Collection, parent_id):
        raise NotFoundError("父文件夹不存在")
    collection = Collection(name=name.strip(), parent_id=parent_id, color=color)
    db.add(collection)
    db.commit()
    return {"id": collection.id, "name": collection.name, "parent_id": collection.parent_id, "color": collection.color}


def update_collection(db: Session, collection_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise NotFoundError("文件夹不存在")
    for key in ("name", "color", "sort_order"):
        if payload.get(key) is not None:
            setattr(collection, key, payload[key])
    db.commit()
    return {"id": collection.id, "name": collection.name, "color": collection.color}


def delete_collection(db: Session, collection_id: str) -> None:
    collection = db.get(Collection, collection_id)
    if not collection:
        raise NotFoundError("文件夹不存在")
    db.delete(collection)
    db.commit()


def add_to_collection(db: Session, collection_id: str, paper_ids: list[str]) -> int:
    if not db.get(Collection, collection_id):
        raise NotFoundError("文件夹不存在")
    added = 0
    for paper_id in paper_ids:
        if not db.get(Paper, paper_id):
            continue
        exists = db.get(CollectionPaper, (collection_id, paper_id))
        if exists:
            continue
        db.add(CollectionPaper(collection_id=collection_id, paper_id=paper_id, created_at=utcnow()))
        added += 1
    db.commit()
    return added


def remove_from_collection(db: Session, collection_id: str, paper_ids: list[str]) -> None:
    if paper_ids:
        db.query(CollectionPaper).filter(
            CollectionPaper.collection_id == collection_id, CollectionPaper.paper_id.in_(paper_ids)
        ).delete(synchronize_session=False)
        db.commit()


# -------------------------------------------------------------------------------- tree
def file_tree(db: Session) -> list[dict[str, Any]]:
    base = db.query(Paper).filter(Paper.is_deleted.is_(False))
    total = base.count()
    journal_rows = (
        db.query(Paper.journal, func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.journal != "")
        .group_by(Paper.journal)
        .order_by(func.count(Paper.id).desc())
        .limit(40)
        .all()
    )
    year_rows = (
        db.query(Paper.year, func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.year.isnot(None))
        .group_by(Paper.year)
        .order_by(Paper.year.desc())
        .all()
    )
    tasks = db.query(SearchTask).order_by(SearchTask.created_at.desc()).all()
    task_counts = dict(
        db.query(SearchTaskPaper.task_id, func.count(SearchTaskPaper.paper_id))
        .group_by(SearchTaskPaper.task_id)
        .all()
    )
    status_counts = dict(
        db.query(Paper.review_status, func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False))
        .group_by(Paper.review_status)
        .all()
    )
    pending_analysis = (
        base.filter(
            Paper.fulltext_status == FulltextStatus.IMPORTED,
            Paper.ai_status.in_([AiStatus.NOT_ANALYZED, AiStatus.FAILED]),
        ).count()
    )
    failed = base.filter(
        or_(
            Paper.review_status == ReviewStatus.ANALYSIS_FAILED,
            Paper.parse_status == ParseStatus.FAILED,
            Paper.fulltext_status == FulltextStatus.FAILED,
        )
    ).count()
    suspected = base.filter(Paper.duplicate_status == "suspected").count()
    collection_children = list_collections(db)

    return [
        {"key": "all", "label": "全部文献", "count": total, "icon": "Files"},
        {
            "key": "tasks",
            "label": "检索任务",
            "count": len(tasks),
            "icon": "Search",
            "children": [
                {
                    "key": f"task:{task.id}",
                    "label": task.name,
                    "count": task_counts.get(task.id, 0),
                    "icon": "Document",
                }
                for task in tasks
            ],
        },
        {
            "key": "journals",
            "label": "按期刊",
            "count": len(journal_rows),
            "icon": "Collection",
            "children": [
                {
                    "key": f"journal:{journal}",
                    "label": journal,
                    "count": count,
                    "icon": "Notebook",
                }
                for journal, count in journal_rows
            ],
        },
        {
            "key": "years",
            "label": "按年份",
            "count": len(year_rows),
            "icon": "Calendar",
            "children": [
                {"key": f"year:{year}", "label": str(year), "count": count, "icon": "Calendar"}
                for year, count in year_rows
            ],
        },
        {
            "key": "status:pending_analysis",
            "label": "待分析",
            "count": pending_analysis,
            "icon": "MagicStick",
        },
        {
            "key": "status:pending_review",
            "label": "待审核",
            "count": status_counts.get(ReviewStatus.PENDING_REVIEW, 0),
            "icon": "View",
        },
        {
            "key": "status:included",
            "label": "已入库",
            "count": status_counts.get(ReviewStatus.INCLUDED, 0),
            "icon": "FolderChecked",
        },
        {
            "key": "status:excluded",
            "label": "暂不采用",
            "count": status_counts.get(ReviewStatus.EXCLUDED, 0),
            "icon": "FolderDelete",
        },
        {
            "key": "status:deferred",
            "label": "待定",
            "count": status_counts.get(ReviewStatus.DEFERRED, 0),
            "icon": "Clock",
        },
        {
            "key": "status:failed",
            "label": "下载/解析失败",
            "count": failed,
            "icon": "Warning",
        },
        {
            "key": "status:duplicates",
            "label": "疑似重复",
            "count": suspected,
            "icon": "CopyDocument",
        },
        {
            "key": "collections",
            "label": "自定义文件夹",
            "count": len(collection_children),
            "icon": "Folder",
            "children": _collection_nodes(collection_children),
        },
    ]


def _collection_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        result.append(
            {
                "key": f"collection:{node['id']}",
                "label": node["name"],
                "count": node["count"],
                "icon": "Folder",
                "children": _collection_nodes(node.get("children", [])),
            }
        )
    return result


def tree_filter(folder_key: str) -> dict[str, Any]:
    if folder_key.startswith("task:"):
        return {"task_id": folder_key.split(":", 1)[1]}
    if folder_key.startswith("journal:"):
        return {"journal": folder_key.split(":", 1)[1]}
    if folder_key.startswith("year:"):
        return {"year": int(folder_key.split(":", 1)[1])}
    if folder_key.startswith("status:"):
        return {"folder": folder_key.split(":", 1)[1]}
    if folder_key.startswith("collection:"):
        return {"collection_id": folder_key.split(":", 1)[1]}
    if folder_key == "tasks":
        return {"folder": "all"}
    if folder_key == "journals":
        return {"folder": "all"}
    if folder_key == "years":
        return {"folder": "all"}
    if folder_key == "collections":
        return {"folder": "all"}
    return {"folder": "all"}


# --------------------------------------------------------------------------- dashboard
def dashboard(db: Session) -> dict[str, Any]:
    base = db.query(func.count(Paper.id)).filter(Paper.is_deleted.is_(False))
    total = base.scalar() or 0
    fulltext = (
        db.query(func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.fulltext_status == FulltextStatus.IMPORTED)
        .scalar()
        or 0
    )
    analyzed = (
        db.query(func.count(AiAnalysisResult.id))
        .filter(AiAnalysisResult.is_current.is_(True))
        .scalar()
        or 0
    )
    pending_review = (
        db.query(func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.PENDING_REVIEW)
        .scalar()
        or 0
    )
    included = (
        db.query(func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.INCLUDED)
        .scalar()
        or 0
    )
    excluded = (
        db.query(func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.EXCLUDED)
        .scalar()
        or 0
    )
    pending_fulltext = (
        db.query(func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.fulltext_status != FulltextStatus.IMPORTED)
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.review_status == ReviewStatus.ANALYSIS_FAILED)
        .scalar()
        or 0
    )

    recent_tasks = db.query(SearchTask).order_by(SearchTask.updated_at.desc()).limit(6).all()
    recent_papers = (
        db.query(Paper).filter(Paper.is_deleted.is_(False)).order_by(Paper.created_at.desc()).limit(8).all()
    )
    ids = [p.id for p in recent_papers]
    analyses = analysis_map(db, ids)
    recent_paper_items = [
        serializers.paper_summary(p, analysis=analyses.get(p.id)) for p in recent_papers
    ]

    token_row = (
        db.query(
            func.coalesce(func.sum(AiAnalysisJob.tokens_prompt), 0),
            func.coalesce(func.sum(AiAnalysisJob.tokens_completion), 0),
            func.coalesce(func.sum(AiAnalysisJob.estimated_cost), 0.0),
            func.count(AiAnalysisJob.id),
        )
        .filter(AiAnalysisJob.status.in_(["completed", "running"]))
        .first()
    )
    avg_score = (
        db.query(func.avg(AiAnalysisResult.screening_score))
        .filter(AiAnalysisResult.is_current.is_(True))
        .scalar()
    )
    mock_count = (
        db.query(func.count(AiAnalysisResult.id))
        .filter(AiAnalysisResult.is_mock.is_(True), AiAnalysisResult.is_current.is_(True))
        .scalar()
        or 0
    )

    since = datetime.now(timezone.utc) - timedelta(days=6)
    activity_rows = (
        db.query(func.date(Paper.created_at), func.count(Paper.id))
        .filter(Paper.created_at >= since)
        .group_by(func.date(Paper.created_at))
        .all()
    )
    activity_map = {str(day): count for day, count in activity_rows}
    activity = []
    for offset in range(6, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).date()
        activity.append({"date": day.isoformat(), "count": activity_map.get(day.isoformat(), 0)})

    top_journals = (
        db.query(Paper.journal, func.count(Paper.id))
        .filter(Paper.is_deleted.is_(False), Paper.journal != "")
        .group_by(Paper.journal)
        .order_by(func.count(Paper.id).desc())
        .limit(5)
        .all()
    )
    storage = sum(
        row[0] or 0 for row in db.query(func.coalesce(func.sum(PaperFile.size_bytes), 0)).all()
    )
    innovations = (
        db.query(func.count(InnovationItem.id))
        .join(AiAnalysisResult, AiAnalysisResult.id == InnovationItem.result_id)
        .filter(AiAnalysisResult.is_current.is_(True))
        .scalar()
        or 0
    )
    return {
        "papers": {
            "total": total,
            "fulltext": fulltext,
            "analyzed": analyzed,
            "pending_review": pending_review,
            "included": included,
            "excluded": excluded,
            "pending_fulltext": pending_fulltext,
            "failed": failed,
            "innovations": innovations,
        },
        "recent_tasks": [serializers.task_out(t) for t in recent_tasks],
        "recent_papers": recent_paper_items,
        "ai": {
            "tokens_prompt": int(token_row[0] or 0),
            "tokens_completion": int(token_row[1] or 0),
            "estimated_cost": float(token_row[2] or 0),
            "job_count": int(token_row[3] or 0),
            "avg_score": round(float(avg_score), 1) if avg_score is not None else None,
            "mock_results": int(mock_count),
        },
        "activity": activity,
        "top_journals": [{"journal": journal, "count": count} for journal, count in top_journals],
        "storage_bytes": int(storage),
    }


# --------------------------------------------------------------------------- duplicates
def duplicates_list(db: Session) -> list[dict[str, Any]]:
    papers = (
        db.query(Paper)
        .filter(Paper.is_deleted.is_(False), Paper.duplicate_status == "suspected")
        .order_by(Paper.created_at.desc())
        .all()
    )
    result = []
    for paper in papers:
        target = db.get(Paper, paper.duplicate_of_id) if paper.duplicate_of_id else None
        result.append(
            {
                "paper": serializers.paper_summary(paper),
                "candidate": serializers.paper_summary(target) if target else None,
            }
        )
    return result
