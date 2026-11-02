"""Local file intake, archive layout, PDF metadata inference and duplicate handling.

Archive layout (under the user-configurable data root):
    data/papers/{期刊}/ {年份}/ {规范化文件名}.pdf

The original filename and SHA-256 are retained in the database. Files are never
deleted automatically; suspected duplicates are flagged for human confirmation.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.constants import AiStatus, FulltextStatus, ParseStatus, ReviewStatus
from app.core.logging import get_logger
from app.core.utils import (
    ensure_within,
    extract_year,
    normalize_doi,
    normalize_title,
    safe_filename,
    sha256_file,
)
from app.models import Paper, PaperFile, SearchTask
from app.parsers.metadata import MetadataRecord
from app.services.dedup import find_duplicates
from app.services.settings_service import SettingsService
from app.services.task_service import link_paper, refresh_counters
from app.tasks.queue import enqueue_job

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".caj"}
METADATA_EXTENSIONS = {".ris", ".bib", ".bibtex", ".enw", ".csv"}
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")


@dataclass
class ImportOutcome:
    status: str  # imported | duplicate | suspected | failed
    message: str = ""
    paper: Paper | None = None
    file: PaperFile | None = None
    duplicate_of_id: str | None = None


def parse_pdf_hint(path: Path) -> dict:
    """Read only embedded metadata + first pages for DOI; never guesses content."""
    hint: dict = {
        "title": "",
        "authors": [],
        "doi": "",
        "year": None,
        "page_text": "",
        "note": "",
    }
    if path.suffix.lower() != ".pdf":
        return hint
    try:
        try:
            import pymupdf
        except ImportError:  # pragma: no cover
            import fitz as pymupdf  # type: ignore

        doc = pymupdf.open(path)
        meta = doc.metadata or {}
        hint["title"] = (meta.get("title") or "").strip()
        author = (meta.get("author") or "").strip()
        if author:
            hint["authors"] = [a.strip() for a in re.split(r"[;；,，]", author) if a.strip()]
        text = ""
        for index in range(min(2, doc.page_count)):
            text += doc[index].get_text("text") or ""
        hint["page_text"] = text
        match = DOI_PATTERN.search(text) or DOI_PATTERN.search(meta.get("subject", "") or "")
        if match:
            hint["doi"] = normalize_doi(match.group(0)) or ""
        created = meta.get("creationDate") or ""
        year_match = re.search(r"(19|20)\d{2}", created)
        if year_match:
            hint["year"] = int(year_match.group(0))
        doc.close()
    except Exception as exc:
        hint["note"] = f"无法读取 PDF 内嵌元数据：{exc}"
    return hint


def infer_record(path: Path) -> MetadataRecord:
    hint = parse_pdf_hint(path)
    stem = path.stem
    cleaned_stem = re.sub(r"^CNKI[_:：\-\s]*", "", stem, flags=re.I)
    cleaned_stem = re.sub(r"\s*\(\d+\)\s*$", "", cleaned_stem)
    cleaned_stem = re.sub(r"^\d{6,}[_\-\s]+", "", cleaned_stem)
    year = hint.get("year") or extract_year(stem) or extract_year(path.parent.name)
    title = hint["title"]
    if not title or len(title) < 4 or title.lower().endswith(".pdf"):
        title = cleaned_stem.replace("_", " ").strip()
    if not title:
        title = "未命名文献"
    language = "zh" if re.search(r"[\u4e00-\u9fff]", title) else "en"
    record = MetadataRecord(
        title=title,
        authors=hint["authors"],
        doi=hint["doi"] or None,
        publication_date_raw=str(year) if year else "",
        year=year,
        language=language,
        source="local",
        raw={
            "inference": "filename_or_pdf_metadata",
            "original_filename": path.name,
            "note": hint.get("note", ""),
        },
    )
    return record


def archive_file(
    db: Session,
    source: Path,
    *,
    journal: str = "",
    year: int | None = None,
    title: str = "",
    first_author: str = "",
) -> tuple[Path, str]:
    """Copy a file into the journal/year tree and return (absolute_path, relative_path)."""
    settings = get_settings()
    svc = SettingsService(db)
    sha = sha256_file(source)

    journal_dir = safe_filename(journal or "其他期刊", max_bytes=60)
    year_dir = str(year or "未知年份")
    target_dir = settings.papers_dir / journal_dir / year_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(svc.get("data.naming_pattern") or "{year}_{title}_{first_author}")
    title = (title or source.stem).replace("_", " ").strip()
    try:
        base = pattern.format(year=year or "未知年份", title=title, first_author=first_author)
    except (KeyError, ValueError):
        base = f"{year or '未知年份'}_{title}_{first_author}"
    base = safe_filename(base, max_bytes=120, fallback="paper") + source.suffix.lower()
    target = target_dir / base
    counter = 2
    while target.exists() and sha256_file(target) != sha:
        target = target_dir / f"{Path(base).stem}_{counter}{source.suffix.lower()}"
        counter += 1
    if not target.exists():
        shutil.copy2(source, target)
    ensure_within(settings.data_dir, target)
    relative = str(target.relative_to(settings.data_dir))
    return target, relative


def register_file(
    db: Session,
    *,
    source: Path,
    task: SearchTask | None = None,
    origin: str = "local_import",
    record: MetadataRecord | None = None,
    journal: str = "",
    move_source: bool = False,
    auto_parse: bool = True,
) -> ImportOutcome:
    settings = get_settings()
    source = source.resolve()
    if not source.exists() or not source.is_file():
        return ImportOutcome("failed", "文件不存在")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return ImportOutcome("failed", f"不支持的文件格式：{suffix}")
    if source.stat().st_size == 0:
        return ImportOutcome("failed", "空文件")
    sha = sha256_file(source)

    existing_file = db.query(PaperFile).filter(PaperFile.sha256 == sha).first()
    if existing_file:
        paper = db.get(Paper, existing_file.paper_id)
        if paper and not paper.is_deleted:
            if task:
                link_paper(db, task, paper, match_status="matched", score=100)
            db.commit()
            return ImportOutcome(
                "duplicate",
                "文件 SHA-256 已存在于文献库，已复用原记录",
                paper=paper,
                file=existing_file,
                duplicate_of_id=paper.id,
            )

    inferred = record or infer_record(source)
    if journal and not inferred.journal:
        inferred.journal = journal
    if not inferred.year:
        inferred.year = extract_year(source.stem)

    fields = inferred.as_paper_fields()
    duplicates = find_duplicates(
        db,
        doi=fields.get("doi"),
        title=fields["title"],
        authors=fields["authors"],
        year=fields.get("year"),
        sha256=None,
    )
    strong = next((hit for hit in duplicates if hit.reason in ("doi", "title") and hit.score >= 95), None)
    fuzzy = next((hit for hit in duplicates if hit.reason in ("title_fuzzy",)), None)

    paper: Paper | None = None
    duplicate_warning = ""
    suspected_target: Paper | None = None
    if strong:
        paper = strong.paper
        # Attach the fulltext when the metadata-only record has no usable file yet.
        has_primary = any(f.is_primary for f in paper.files)
        if has_primary:
            # Same metadata but a different file: never discard the new fulltext.
            # Keep it as a separate suspected duplicate for human confirmation.
            suspected_target = paper
            paper = None
            duplicate_warning = (
                f"已存在同标识/同标题文献（{strong.detail}），但全文文件不同；"
                "已保留新文件并标记疑似重复，请人工确认"
            )
        else:
            duplicate_warning = f"已与既有题录合并：{strong.detail}"
            _merge_missing_fields(paper, fields)

    if paper is None:
        paper = Paper(
            title=fields["title"],
            title_normalized=normalize_title(fields["title"]),
            authors=fields["authors"],
            authors_text="; ".join(fields["authors"]),
            journal=fields.get("journal", ""),
            abstract=fields.get("abstract", ""),
            keywords=fields.get("keywords", []),
            doi=fields.get("doi"),
            source_id=fields.get("source_id"),
            source_url=fields.get("source_url", ""),
            source="local",
            publication_date=fields.get("publication_date"),
            publication_date_precision=fields.get("publication_date_precision", "unknown"),
            publication_date_raw=fields.get("publication_date_raw", ""),
            year=fields.get("year"),
            month=fields.get("month"),
            paper_type=fields.get("paper_type", "journal"),
            language=fields.get("language", "zh"),
            metadata_source="pdf_inferred",
            raw_metadata=fields.get("raw_metadata", {}),
            imported_at=datetime.now(timezone.utc),
        )
        db.add(paper)
        db.flush()
        target_paper = suspected_target or (fuzzy.paper if fuzzy else None)
        if target_paper:
            paper.duplicate_of_id = target_paper.id
            paper.duplicate_status = "suspected"
            if not duplicate_warning:
                detail = fuzzy.detail if fuzzy else "标题高度相似"
                duplicate_warning = f"疑似重复：{detail}，已保留两份文件，请人工确认"
    else:
        paper.imported_at = paper.imported_at or datetime.now(timezone.utc)

    target, relative = archive_file(
        db,
        source,
        journal=paper.journal,
        year=paper.year,
        title=paper.title,
        first_author=(paper.authors[0] if paper.authors else ""),
    )
    file = PaperFile(
        paper_id=paper.id,
        original_filename=source.name,
        stored_filename=target.name,
        relative_path=relative,
        file_format=suffix.lstrip("."),
        mime_type="application/pdf" if suffix == ".pdf" else "application/octet-stream",
        size_bytes=target.stat().st_size,
        sha256=sha,
        is_primary=True,
        origin=origin,
        parse_status=ParseStatus.PENDING if suffix == ".pdf" else ParseStatus.UNSUPPORTED,
        parse_error="" if suffix == ".pdf" else "CAJ 格式需要官方阅读器，系统未内置解析器",
    )
    db.add(file)
    paper.fulltext_status = FulltextStatus.IMPORTED
    paper.parse_status = ParseStatus.PENDING if suffix == ".pdf" else ParseStatus.UNSUPPORTED
    paper.ai_status = AiStatus.NOT_ANALYZED
    if paper.review_status not in (ReviewStatus.INCLUDED, ReviewStatus.EXCLUDED, ReviewStatus.DEFERRED):
        paper.review_status = ReviewStatus.PENDING_AI
    db.flush()
    _write_metadata_sidecar(paper, file)
    from app.database.fts import index_paper

    index_paper(db, paper)
    if task:
        link_status = "suspected" if (paper.duplicate_status == "suspected" or (task.journal and not paper.journal)) else "matched"
        link_paper(db, task, paper, match_status=link_status)

    if auto_parse and suffix == ".pdf":
        job = enqueue_job(
            db,
            "parse_paper",
            {"paper_id": paper.id, "file_id": file.id},
            dedupe_key=f"parse:{paper.id}",
            priority=2,
            commit=False,
        )
        file.parse_status = ParseStatus.PENDING
        _ = job
    db.commit()
    if move_source:
        try:
            source.unlink()
        except OSError as exc:
            logger.warning("Could not remove staged upload %s: %s", source, exc)
    return ImportOutcome(
        "suspected" if paper.duplicate_status == "suspected" else ("imported" if not duplicate_warning else "imported"),
        duplicate_warning or "已归档并加入解析队列",
        paper=paper,
        file=file,
        duplicate_of_id=paper.duplicate_of_id,
    )


def register_metadata_record(
    db: Session,
    record: MetadataRecord,
    *,
    task: SearchTask | None = None,
    metadata_source: str = "RIS",
) -> tuple[Paper | None, str, str]:
    """Create or reuse a metadata-only paper. Returns (paper, status, message)."""
    from app.core.utils import normalize_doi, normalize_title

    fields = record.as_paper_fields()
    if not fields["title"]:
        return None, "failed", "缺少标题"
    duplicates = find_duplicates(
        db, doi=fields.get("doi"), title=fields["title"], authors=fields["authors"], year=fields.get("year")
    )
    strong = next((hit for hit in duplicates if hit.reason in ("doi", "title") and hit.score >= 95), None)
    if strong:
        paper = strong.paper
        _merge_missing_fields(paper, fields)
        if task:
            link_paper(db, task, paper, match_status="matched", score=strong.score)
        return paper, "duplicate", f"已存在：{strong.detail}"

    fuzzy = next((hit for hit in duplicates if hit.reason == "title_fuzzy"), None)
    paper = Paper(
        title=fields["title"],
        title_normalized=normalize_title(fields["title"]),
        authors=fields["authors"],
        authors_text="; ".join(fields["authors"]),
        journal=fields.get("journal", ""),
        abstract=fields.get("abstract", ""),
        keywords=fields.get("keywords", []),
        doi=normalize_doi(fields.get("doi")),
        source_id=fields.get("source_id"),
        source_url=fields.get("source_url", ""),
        source=record.source,
        publication_date=fields.get("publication_date"),
        publication_date_precision=fields.get("publication_date_precision", "unknown"),
        publication_date_raw=fields.get("publication_date_raw", ""),
        year=fields.get("year"),
        month=fields.get("month"),
        paper_type=fields.get("paper_type", "journal"),
        language=fields.get("language", "zh"),
        fulltext_status=FulltextStatus.NOT_AVAILABLE,
        parse_status=ParseStatus.NOT_PARSED,
        ai_status=AiStatus.NOT_ANALYZED,
        review_status=ReviewStatus.PENDING_FULLTEXT,
        metadata_source=metadata_source,
        raw_metadata=fields.get("raw_metadata", {}),
        duplicate_of_id=fuzzy.paper.id if fuzzy else None,
        duplicate_status="suspected" if fuzzy else "none",
    )
    db.add(paper)
    db.flush()
    _write_metadata_sidecar(paper, None)
    from app.database.fts import index_paper

    index_paper(db, paper)
    if task:
        link_paper(db, task, paper, match_status="suspected" if fuzzy else "matched")
    db.flush()
    message = "已导入题录（无全文，等待全文关联）"
    if fuzzy:
        message += f"；{fuzzy.detail}，请确认是否重复"
    return paper, "suspected" if fuzzy else "imported", message


def _merge_missing_fields(paper: Paper, fields: dict) -> None:
    """Fill blanks only. Existing/user-edited metadata is never overwritten."""
    simple = ["journal", "abstract", "source_url", "doi", "publication_date_raw", "metadata_source"]
    for key in simple:
        if not getattr(paper, key, None) and fields.get(key):
            setattr(paper, key, fields[key])
    if not paper.authors and fields.get("authors"):
        paper.authors = fields["authors"]
        paper.authors_text = "; ".join(fields["authors"])
    if not paper.keywords and fields.get("keywords"):
        paper.keywords = fields["keywords"]
    if not paper.publication_date and fields.get("publication_date"):
        paper.publication_date = fields["publication_date"]
        paper.publication_date_precision = fields.get("publication_date_precision", "unknown")
        paper.year = fields.get("year")
        paper.month = fields.get("month")
    if not paper.year and fields.get("year"):
        paper.year = fields["year"]


def _write_metadata_sidecar(paper: Paper, file: PaperFile | None) -> None:
    settings = get_settings()
    payload = {
        "paper_id": paper.id,
        "title": paper.title,
        "authors": paper.authors,
        "journal": paper.journal,
        "publication_date": paper.publication_date.isoformat() if paper.publication_date else None,
        "publication_date_precision": paper.publication_date_precision,
        "doi": paper.doi,
        "source": paper.source,
        "source_url": paper.source_url,
        "abstract": paper.abstract,
        "keywords": paper.keywords,
        "raw_metadata": paper.raw_metadata,
        "file": {
            "original_filename": file.original_filename,
            "stored_filename": file.stored_filename,
            "relative_path": file.relative_path,
            "sha256": file.sha256,
        }
        if file
        else None,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    target = settings.metadata_dir / f"{paper.id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def list_importable_files(directory: Path) -> list[Path]:
    """Fulltext files only (PDF/CAJ)."""
    files: list[Path] = []
    if not directory.exists():
        return files
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and not path.name.startswith("."):
            files.append(path)
    return sorted(files)


def list_watchable_files(directory: Path) -> list[Path]:
    """Files that the official-download takeover can import: fulltext or metadata."""
    files: list[Path] = []
    if not directory.exists():
        return files
    for path in directory.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_EXTENSIONS or suffix in METADATA_EXTENSIONS:
            files.append(path)
    return sorted(files)


def attach_fulltext_to_paper(
    db: Session, paper: Paper, source: Path, *, origin: str = "local_import"
) -> ImportOutcome:
    """Attach a user-provided fulltext to an existing metadata record."""
    if any(f.is_primary for f in paper.files):
        return ImportOutcome("duplicate", "该文献已有全文文件", paper=paper)
    sha = sha256_file(source)
    target, relative = archive_file(
        db,
        source,
        journal=paper.journal,
        year=paper.year,
        title=paper.title,
        first_author=(paper.authors[0] if paper.authors else ""),
    )
    file = PaperFile(
        paper_id=paper.id,
        original_filename=source.name,
        stored_filename=target.name,
        relative_path=relative,
        file_format=source.suffix.lstrip(".").lower(),
        mime_type="application/pdf" if source.suffix.lower() == ".pdf" else "application/octet-stream",
        size_bytes=target.stat().st_size,
        sha256=sha,
        is_primary=True,
        origin=origin,
        parse_status=ParseStatus.PENDING if source.suffix.lower() == ".pdf" else ParseStatus.UNSUPPORTED,
        parse_error="" if source.suffix.lower() == ".pdf" else "CAJ 格式未解析",
    )
    db.add(file)
    paper.fulltext_status = FulltextStatus.IMPORTED
    paper.parse_status = file.parse_status
    paper.review_status = ReviewStatus.PENDING_AI
    db.flush()
    _write_metadata_sidecar(paper, file)
    if source.suffix.lower() == ".pdf":
        enqueue_job(
            db,
            "parse_paper",
            {"paper_id": paper.id, "file_id": file.id},
            dedupe_key=f"parse:{paper.id}",
            priority=2,
            commit=False,
        )
    db.commit()
    refresh_counters_task(db, paper)
    return ImportOutcome("imported", "全文已关联", paper=paper, file=file)


def refresh_counters_task(db: Session, paper: Paper) -> None:
    from app.models import SearchTaskPaper

    task_ids = [
        row[0]
        for row in db.query(SearchTaskPaper.task_id).filter(SearchTaskPaper.paper_id == paper.id).all()
    ]
    for task_id in task_ids:
        refresh_counters(db, task_id)
    db.commit()
