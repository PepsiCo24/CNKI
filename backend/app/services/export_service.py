"""Export literature metadata, notes and AI analysis to local files.

Full copyrighted PDFs are never bundled into exports; only metadata, notes and
AI-generated analysis (plus source paths) are included.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ValidationAppError
from app.core.logging import get_logger
from app.core.utils import safe_filename, utcnow
from app.models import AiAnalysisResult, Paper, PaperFile, ResearchNote, SearchTaskPaper, Tag
from app.services.paper_service import current_analysis, list_papers, paper_detail
from app.services.serializers import analysis_out

logger = get_logger(__name__)

HEADER_LABELS = {
    "id": "ID",
    "title": "标题",
    "authors": "作者",
    "journal": "期刊",
    "year": "年份",
    "publication_date": "发表日期",
    "date_precision": "日期精度",
    "doi": "DOI",
    "keywords": "关键词",
    "abstract": "摘要",
    "source": "来源",
    "source_url": "详情链接",
    "review_status": "审核状态",
    "ai_status": "AI 状态",
    "tags": "标签",
    "score": "筛选参考分",
    "one_sentence_summary": "一句话总结",
    "innovation_summary": "创新点总结",
    "research_problem": "研究问题",
    "main_method": "研究方法",
    "claimed_innovations": "核心创新点",
    "research_value": "研究价值",
    "limitations": "研究局限",
    "analysis_scope": "分析范围",
    "analysis_model": "分析模型",
    "analysis_is_mock": "模拟分析",
    "notes": "个人笔记",
    "file_path": "文件路径",
    "file_sha256": "SHA-256",
}

EXPORT_FORMATS = {
    "csv": ("文献清单.csv", "text/csv"),
    "xlsx": ("文献清单.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "json": ("文献数据.json", "application/json"),
    "markdown": ("文献综述素材.md", "text/markdown"),
    "ris": ("文献题录.ris", "application/x-research-info-systems"),
    "bibtex": ("文献题录.bib", "application/x-bibtex"),
    "notes_md": ("科研笔记.md", "text/markdown"),
}


ALLOWED_FILTERS = {
    "q",
    "folder",
    "journal",
    "year",
    "tag",
    "review_status",
    "ai_status",
    "fulltext_status",
    "author",
    "task_id",
    "collection_id",
    "paper_type",
    "date_from",
    "date_to",
    "sort",
    "order",
}


def _collect(db: Session, paper_ids: list[str], filters: dict[str, Any]) -> list[Paper]:
    if paper_ids:
        papers = db.query(Paper).filter(Paper.id.in_(paper_ids), Paper.is_deleted.is_(False)).all()
        order = {pid: index for index, pid in enumerate(paper_ids)}
        papers.sort(key=lambda p: order.get(p.id, 9999))
        return papers
    from app.services.paper_service import tree_filter

    clean = dict(filters or {})
    tree_key = str(clean.pop("tree_key", "") or "")
    if tree_key:
        for key, value in tree_filter(tree_key).items():
            clean.setdefault(key, value)
    clean = {key: value for key, value in clean.items() if key in ALLOWED_FILTERS and value not in (None, "")}
    for key in ("date_from", "date_to"):
        if isinstance(clean.get(key), str) and clean[key]:
            from datetime import date

            clean[key] = date.fromisoformat(clean[key])

    items: list[Paper] = []
    page = 1
    while page <= 20:
        result = list_papers(db, page=page, page_size=200, include_deleted=False, **clean)
        ids = [item["id"] for item in result["items"]]
        if not ids:
            break
        items.extend(db.query(Paper).filter(Paper.id.in_(ids)).all())
        if len(items) >= result["total"]:
            break
        page += 1
    return items


def _rows(db: Session, papers: list[Paper], *, include_notes: bool, include_analysis: bool) -> list[dict]:
    rows = []
    for paper in papers:
        analysis = current_analysis(db, paper.id) if include_analysis else None
        notes = []
        if include_notes:
            notes = [
                n.content
                for n in db.query(ResearchNote)
                .filter(ResearchNote.paper_id == paper.id)
                .order_by(ResearchNote.created_at.asc())
                .all()
            ]
        primary = next((f for f in paper.files if f.is_primary), None)
        rows.append(
            {
                "id": paper.id,
                "title": paper.title,
                "authors": "; ".join(paper.authors or []),
                "journal": paper.journal,
                "year": paper.year,
                "publication_date": paper.publication_date.isoformat() if paper.publication_date else "",
                "date_precision": paper.publication_date_precision,
                "doi": paper.doi or "",
                "keywords": "; ".join(paper.keywords or []),
                "abstract": paper.abstract,
                "source": paper.source,
                "source_url": paper.source_url,
                "review_status": paper.review_status,
                "ai_status": paper.ai_status,
                "tags": "; ".join(tag.name for tag in paper.tags),
                "score": analysis.screening_score if analysis else "",
                "one_sentence_summary": analysis.one_sentence_summary if analysis else "",
                "innovation_summary": analysis.innovation_summary if analysis else "",
                "research_problem": analysis.research_problem if analysis else "",
                "main_method": analysis.main_method if analysis else "",
                "claimed_innovations": analysis.claimed_innovations if analysis else [],
                "research_value": analysis.research_value if analysis else "",
                "limitations": analysis.limitations if analysis else [],
                "analysis_scope": analysis.analysis_scope if analysis else "",
                "analysis_model": analysis.model if analysis else "",
                "analysis_is_mock": analysis.is_mock if analysis else False,
                "notes": "\n".join(notes),
                "file_path": str(get_settings().data_dir / primary.relative_path) if primary else "",
                "file_sha256": primary.sha256 if primary else "",
            }
        )
    return rows


def export_papers(
    db: Session,
    *,
    fmt: str,
    paper_ids: list[str],
    filters: dict[str, Any],
    include_notes: bool = True,
    include_analysis: bool = True,
) -> dict[str, Any]:
    if fmt not in EXPORT_FORMATS:
        raise ValidationAppError(f"不支持的导出格式：{fmt}")
    papers = _collect(db, paper_ids, filters)
    if not papers:
        raise ValidationAppError("没有可导出的文献")
    rows = _rows(db, papers, include_notes=include_notes, include_analysis=include_analysis)
    settings = get_settings()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name, _mime = EXPORT_FORMATS[fmt]
    filename = f"{stamp}_{safe_filename(base_name, max_bytes=120)}"
    target = settings.exports_dir / filename

    if fmt == "csv":
        _write_csv(target, rows)
    elif fmt == "xlsx":
        _write_xlsx(target, rows)
    elif fmt == "json":
        _write_json(db, target, papers, rows, include_notes, include_analysis)
    elif fmt == "markdown":
        _write_markdown(db, target, papers, include_notes, include_analysis)
    elif fmt == "notes_md":
        _write_notes_markdown(db, target, papers)
    elif fmt == "ris":
        _write_ris(target, papers)
    elif fmt == "bibtex":
        _write_bibtex(target, papers)
    return {
        "filename": filename,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "paper_count": len(papers),
        "format": fmt,
        "download_url": f"/api/exports/files/{filename}",
        "created_at": utcnow().isoformat(),
    }


def list_exports() -> list[dict[str, Any]]:
    settings = get_settings()
    files = sorted(settings.exports_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "download_url": f"/api/exports/files/{path.name}",
        }
        for path in files
        if path.is_file() and not path.name.startswith(".")
    ]


def export_file_path(filename: str) -> Path:
    settings = get_settings()
    candidate = (settings.exports_dir / safe_filename(filename)).resolve()
    if settings.exports_dir.resolve() not in candidate.parents:
        raise ValidationAppError("非法文件名")
    if not candidate.exists():
        raise ValidationAppError("导出文件不存在")
    return candidate


def _write_csv(target: Path, rows: list[dict]) -> None:
    columns = list(rows[0].keys())
    labels = [HEADER_LABELS.get(column, column) for column in columns]
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=labels)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {HEADER_LABELS.get(column, column): _flat(row.get(column)) for column in columns}
            )


def _write_xlsx(target: Path, rows: list[dict]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "文献清单"
    columns = list(rows[0].keys())
    headers = HEADER_LABELS
    header_fill = PatternFill("solid", fgColor="1F2937")
    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index, value=headers.get(column, column))
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.column_dimensions[get_column_letter(index)].width = 22 if column not in ("title", "abstract", "notes") else 45
    for row_index, row in enumerate(rows, start=2):
        for column_index, column in enumerate(columns, start=1):
            value = _flat(row.get(column))
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=column in ("title", "abstract", "notes", "claimed_innovations"))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(target)


def _write_json(
    db: Session,
    target: Path,
    papers: list[Paper],
    rows: list[dict],
    include_notes: bool,
    include_analysis: bool,
) -> None:
    payload = {
        "app": "CNKI Scholar AI",
        "export_version": 1,
        "exported_at": utcnow().isoformat(),
        "paper_count": len(papers),
        "papers": rows,
        "note": "不包含受版权保护的全文文件；file_path 为本地路径引用。",
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_markdown(db: Session, target: Path, papers: list[Paper], include_notes: bool, include_analysis: bool) -> None:
    lines = [
        "# 文献综述素材",
        "",
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"文献数量：{len(papers)}",
        "",
        "> 本文件由 CNKI Scholar AI 生成。AI 分析结论仅作筛选参考，不代表学术质量评价。",
        "",
        "---",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        analysis = current_analysis(db, paper.id) if include_analysis else None
        lines.append(f"## {index}. {paper.title}")
        lines.append("")
        lines.append(f"- 作者：{'、'.join(paper.authors or []) or '未明确说明'}")
        lines.append(f"- 期刊：{paper.journal or '未明确说明'}")
        lines.append(f"- 发表时间：{paper.publication_date_raw or paper.year or '未明确说明'}")
        lines.append(f"- DOI：{paper.doi or '未明确说明'}")
        lines.append(f"- 标签：{'、'.join(t.name for t in paper.tags) or '无'}")
        if analysis:
            lines.append(f"- 筛选参考分：{analysis.screening_score}（AI 辅助指标）")
            lines.append(f"- 分析范围：{analysis.analysis_scope} / 模型：{analysis.model}")
        lines.append("")
        if paper.abstract:
            lines.extend(["### 摘要", "", paper.abstract, ""])
        if analysis:
            lines.extend(["### 一句话总结", "", analysis.one_sentence_summary, ""])
            lines.extend(["### 创新点总结", "", analysis.innovation_summary or "未明确说明", ""])
            if analysis.claimed_innovations:
                lines.extend(["### 核心创新点", ""])
                for item in analysis.claimed_innovations:
                    if isinstance(item, dict):
                        lines.append(f"- **{item.get('name', '')}**：{item.get('difference') or item.get('method', '')}")
                        if item.get("evidence"):
                            lines.append(f"  - 证据：{item['evidence']}")
                lines.append("")
            lines.extend(["### 研究方法", "", analysis.main_method or "未明确说明", ""])
            lines.extend(["### 研究价值", "", analysis.research_value or "未明确说明", ""])
        if include_notes:
            notes = db.query(ResearchNote).filter(ResearchNote.paper_id == paper.id).all()
            if notes:
                lines.extend(["### 个人笔记", ""])
                lines.extend([f"- {n.content}" for n in notes])
                lines.append("")
        lines.extend(["---", ""])
    target.write_text("\n".join(lines), encoding="utf-8")


def _write_notes_markdown(db: Session, target: Path, papers: list[Paper]) -> None:
    lines = ["# 科研笔记", ""]
    for paper in papers:
        notes = db.query(ResearchNote).filter(ResearchNote.paper_id == paper.id).all()
        if not notes:
            continue
        lines.append(f"## {paper.title}")
        lines.append("")
        for note in notes:
            lines.append(f"- **{note.note_type}**：{note.content}")
        lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")


def _write_ris(target: Path, papers: list[Paper]) -> None:
    blocks = []
    for paper in papers:
        lines = ["TY  - JOUR"]
        if paper.title:
            lines.append(f"TI  - {paper.title}")
        for author in paper.authors or []:
            lines.append(f"AU  - {author}")
        if paper.journal:
            lines.append(f"JO  - {paper.journal}")
        if paper.year:
            lines.append(f"PY  - {paper.year}")
        if paper.publication_date:
            lines.append(f"DA  - {paper.publication_date.isoformat()}")
        if paper.abstract:
            lines.append(f"AB  - {paper.abstract}")
        for keyword in paper.keywords or []:
            lines.append(f"KW  - {keyword}")
        if paper.doi:
            lines.append(f"DO  - {paper.doi}")
        if paper.source_url:
            lines.append(f"UR  - {paper.source_url}")
        lines.append("ER  -")
        blocks.append("\n".join(lines))
    target.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _write_bibtex(target: Path, papers: list[Paper]) -> None:
    entries = []
    for index, paper in enumerate(papers, start=1):
        key = f"paper{index}_{(paper.year or 'nd')}"
        authors = " and ".join(paper.authors or [])
        fields = [
            ("title", paper.title),
            ("author", authors),
            ("journal", paper.journal),
            ("year", str(paper.year) if paper.year else ""),
            ("doi", paper.doi or ""),
            ("url", paper.source_url),
            ("keywords", ", ".join(paper.keywords or [])),
        ]
        body = ",\n".join(
            f"  {name} = {{{_escape_bib(value)}}}" for name, value in fields if value
        )
        entries.append(f"@article{{{key},\n{body}\n}}")
    target.write_text("\n\n".join(entries) + "\n", encoding="utf-8")


def _escape_bib(value: str) -> str:
    return (value or "").replace("{", "").replace("}", "")


def _flat(value: Any) -> str:
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(
                    "；".join(
                        str(item.get(k) or "")
                        for k in ("name", "text", "value")
                        if item.get(k)
                    )
                )
            else:
                parts.append(str(item))
        return " | ".join(part for part in parts if part)
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def create_backup(db: Session) -> dict[str, Any]:
    """SQLite online backup + metadata/AI artifacts as a single zip (no paper PDFs)."""
    settings = get_settings()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = settings.backups_dir / f"cnki_backup_{stamp}.zip"
    with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmp:
        tmp_path = Path(tmp)
        db_snapshot = tmp_path / "cnki_scholar.db"
        source = sqlite3.connect(str(settings.db_path))
        dest = sqlite3.connect(str(db_snapshot))
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_snapshot, "database/cnki_scholar.db")
            for directory, prefix in (
                (settings.metadata_dir, "metadata"),
                (settings.ai_results_dir, "ai_results"),
            ):
                for path in directory.rglob("*.json"):
                    archive.write(path, f"{prefix}/{path.relative_to(directory)}")
            manifest = {
                "created_at": utcnow().isoformat(),
                "app": "CNKI Scholar AI",
                "contents": "database + metadata + ai_results (PDF files are not included)",
                "data_root": str(settings.data_dir),
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "filename": target.name,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "download_url": f"/api/exports/files/{target.name}",
        "created_at": utcnow().isoformat(),
    }
