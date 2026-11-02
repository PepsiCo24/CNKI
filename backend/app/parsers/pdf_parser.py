"""PDF/CAJ text extraction with page map and section detection.

PyMuPDF is primary; pdfplumber is a fallback for PDFs PyMuPDF cannot read. Scanned or
encrypted files are reported honestly (``quality``/``error``) rather than silently
pretending full text exists. CAJ is never parsed in-process.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

PAGE_MARKER = re.compile(r"^\[?第?\s*(\d+)\s*页\]?$")
HEADING_PATTERNS = [
    ("abstract", re.compile(r"^(摘\s*要|abstract)\s*[:：]?", re.I)),
    ("keywords", re.compile(r"^(关\s*键\s*词|key\s*words?)\s*[:：]?", re.I)),
    ("introduction", re.compile(r"^(引\s*言|前\s*言|绪\s*论|introduction)\s*[:：]?", re.I)),
    ("related_work", re.compile(r"^(相关研究|相关工作|研究现状|related work)\s*[:：]?", re.I)),
    ("methods", re.compile(r"^(研究方法|方法|方法与材料|试验方法|模型与方法|method(s|ology)?)\s*[:：]?", re.I)),
    ("experiments", re.compile(r"^(实\s*验|试验|数值模拟|案例分析|experiment(s)?)\s*[:：]?", re.I)),
    ("results", re.compile(r"^(结\s*果|结果与分析|results?)\s*[:：]?", re.I)),
    ("discussion", re.compile(r"^(讨\s*论|discussion)\s*[:：]?", re.I)),
    ("conclusion", re.compile(r"^(结\s*论|结论与展望|conclusions?)\s*[:：]?", re.I)),
    ("references", re.compile(r"^(参考文献|references)\s*[:：]?", re.I)),
]
NUMERIC_HEADING = re.compile(r"^\s*(\d{1,2}(\.\d{1,2})*)[\s、.．]+(\S.{0,40})$")
NUMERIC_SECTION_KEYWORDS = [
    ("introduction", ("引言", "前言", "绪论")),
    ("methods", ("方法", "模型", "理论", "技术路线")),
    ("experiments", ("实验", "试验", "数值模拟", "案例", "数据")),
    ("results", ("结果", "分析")),
    ("discussion", ("讨论",)),
    ("conclusion", ("结论", "总结", "展望")),
    ("references", ("参考文献",)),
]


def _map_numeric_heading(title: str) -> str | None:
    for name, keywords in NUMERIC_SECTION_KEYWORDS:
        if any(keyword in title for keyword in keywords):
            return name
    return None
NOISE_LINE = re.compile(
    r"^(第\s*\d+\s*卷\s*第?\s*\d+\s*期|vol\.?\s*\d+|no\.?\s*\d+|doi\s*[:：]|收稿日期|基金项目|作者简介|"
    r"通信作者|引用格式|中图分类号|文献标识码|文章编号|网络首发|cnki|https?://|www\.)",
    re.I,
)


@dataclass
class ParsedPage:
    page: int
    text: str
    char_start: int = 0
    char_end: int = 0


@dataclass
class Section:
    name: str
    label: str
    page: int
    char_start: int


@dataclass
class ParsedDocument:
    content: str
    pages: list[ParsedPage] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    page_count: int = 0
    quality: str = "text"
    extractor: str = "pymupdf"
    error: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.content)


SECTION_LABELS = {
    "abstract": "摘要",
    "keywords": "关键词",
    "introduction": "引言",
    "related_work": "相关工作",
    "methods": "研究方法",
    "experiments": "实验",
    "results": "结果",
    "discussion": "讨论",
    "conclusion": "结论",
    "references": "参考文献",
    "body": "正文",
}


def extract_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".caj":
        return ParsedDocument(
            content="",
            quality="unsupported",
            extractor="none",
            error="CAJ 为知网专有格式，系统未内置解析器。请使用官方阅读器打开，或导入你有权转换得到的 PDF。",
        )
    if suffix in (".pdf",):
        return _extract_pdf(path)
    return ParsedDocument(
        content="",
        quality="unsupported",
        extractor="none",
        error=f"不支持的全文格式：{suffix or '未知'}",
    )


def _extract_pdf(path: Path) -> ParsedDocument:
    try:
        import pymupdf  # noqa: F401
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore

    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        return ParsedDocument(content="", quality="failed", extractor="pymupdf", error=f"PDF 打开失败：{exc}")

    if doc.needs_pass:
        doc.close()
        return ParsedDocument(content="", quality="encrypted", extractor="pymupdf", error="PDF 已加密，无法提取正文")
    try:
        raw_pages = [page.get_text("text") or "" for page in doc]
        meta = doc.metadata or {}
        page_count = doc.page_count
    except Exception as exc:
        doc.close()
        return ParsedDocument(content="", quality="failed", extractor="pymupdf", error=f"PDF 解析失败：{exc}")
    finally:
        try:
            doc.close()
        except Exception:
            pass

    if sum(len(text.strip()) for text in raw_pages) < 40:
        fallback = _extract_with_pdfplumber(path, page_count)
        if fallback and fallback.content.strip():
            return fallback
        return ParsedDocument(
            content="",
            quality="scanned",
            extractor="pymupdf",
            page_count=page_count,
            metadata={
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "subject": meta.get("subject", ""),
                "keywords": meta.get("keywords", ""),
            },
            error="未提取到可阅读文本，可能是扫描版 PDF。请先进行 OCR，或仅基于摘要分析。",
        )

    cleaned_pages = _clean_pages(raw_pages)
    content, pages = _build_content(cleaned_pages)
    sections = detect_sections(content, pages)
    quality = "text"
    if len(content) < 500:
        quality = "sparse"
    return ParsedDocument(
        content=content,
        pages=pages,
        sections=sections,
        page_count=page_count,
        quality=quality,
        extractor="pymupdf",
        metadata={
            "title": (meta.get("title") or "").strip(),
            "author": (meta.get("author") or "").strip(),
            "subject": (meta.get("subject") or "").strip(),
            "keywords": (meta.get("keywords") or "").strip(),
        },
    )


def _extract_with_pdfplumber(path: Path, page_count: int) -> ParsedDocument | None:
    try:
        import pdfplumber

        texts: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                texts.append(page.extract_text() or "")
        if not any(t.strip() for t in texts):
            return None
        cleaned = _clean_pages(texts)
        content, pages = _build_content(cleaned)
        return ParsedDocument(
            content=content,
            pages=pages,
            sections=detect_sections(content, pages),
            page_count=len(texts),
            quality="text",
            extractor="pdfplumber",
        )
    except Exception as exc:
        logger.warning("pdfplumber fallback failed for %s: %s", path, exc)
        return None


def _clean_pages(raw_pages: list[str]) -> list[str]:
    # Remove repeated running headers/footers (appear on >= 60% of pages).
    line_counts: dict[str, int] = {}
    page_lines: list[list[str]] = []
    for text in raw_pages:
        lines = [line.strip() for line in text.splitlines()]
        page_lines.append(lines)
        for line in set(lines):
            if 0 < len(line) <= 60:
                line_counts[line] = line_counts.get(line, 0) + 1
    threshold = max(3, int(len(raw_pages) * 0.6))
    repeated = {line for line, count in line_counts.items() if count >= threshold}

    cleaned: list[str] = []
    for lines in page_lines:
        kept: list[str] = []
        for line in lines:
            if not line:
                if kept and kept[-1] != "":
                    kept.append("")
                continue
            if line in repeated and not re.search(r"\d{4}", line):
                continue
            if PAGE_MARKER.match(line) and len(line) <= 12:
                continue
            if NOISE_LINE.match(line) and len(line) < 120:
                continue
            kept.append(line)
        text = "\n".join(kept)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate English words
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        cleaned.append(text.strip())
    return cleaned


def _build_content(cleaned_pages: list[str]) -> tuple[str, list[ParsedPage]]:
    chunks: list[str] = []
    pages: list[ParsedPage] = []
    offset = 0
    for index, text in enumerate(cleaned_pages, start=1):
        marker = f"\n\n【第{index}页】\n" if index > 1 else f"【第{index}页】\n"
        chunk = marker + text
        start = offset
        chunks.append(chunk)
        offset += len(chunk)
        pages.append(ParsedPage(page=index, text=text, char_start=start, char_end=offset))
    return "".join(chunks).strip(), pages


def detect_sections(content: str, pages: list[ParsedPage]) -> list[Section]:
    sections: list[Section] = []
    seen: set[str] = set()
    for page in pages:
        for line in page.text.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 60:
                continue
            matched = None
            for name, pattern in HEADING_PATTERNS:
                if pattern.match(stripped):
                    matched = name
                    break
            if not matched:
                numeric = NUMERIC_HEADING.match(stripped)
                if numeric and not re.search(r"[。；;]$", stripped):
                    title = numeric.group(3)
                    matched = _map_numeric_heading(title)
            if matched and matched not in seen:
                seen.add(matched)
                char_start = page.char_start + max(0, content.find(stripped, page.char_start) - page.char_start)
                sections.append(
                    Section(name=matched, label=SECTION_LABELS.get(matched, matched), page=page.page, char_start=char_start)
                )
    if not sections:
        sections.append(Section(name="body", label="正文", page=pages[0].page if pages else 1, char_start=0))
    return sections


def render_with_page_markers(content: str, pages: list[dict], max_chars: int) -> str:
    """Build LLM input preserving page numbers, truncated on page boundaries."""
    if not pages:
        return content[:max_chars]
    parts: list[str] = []
    used = 0
    for page in pages:
        segment = page.get("text") or ""
        if not segment:
            continue
        block = f"\n【第{page['page']}页】\n{segment}"
        if used + len(block) > max_chars:
            remaining = max_chars - used
            if remaining > 200:
                parts.append(block[:remaining])
            break
        parts.append(block)
        used += len(block)
    return "".join(parts).strip()
