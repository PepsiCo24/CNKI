"""PDF extraction tests using the labeled sample paper."""
from __future__ import annotations

from pathlib import Path

from app.parsers.pdf_parser import extract_document, render_with_page_markers


def test_extract_sample_pdf(sample_pdf: Path):
    document = extract_document(sample_pdf)
    assert document.quality == "text"
    assert document.page_count == 2
    assert len(document.pages) == 2
    assert document.char_count > 1500
    assert "改进随机森林" in document.content
    assert "MAE=0.021" in document.content
    assert document.extractor in ("pymupdf", "pdfplumber")
    labels = [section.label for section in document.sections]
    assert "摘要" in labels
    assert "研究方法" in labels or "实验" in labels
    assert "参考文献" in labels
    assert document.error == ""


def test_page_map_offsets_are_consistent(sample_pdf: Path):
    document = extract_document(sample_pdf)
    for page in document.pages:
        assert page.char_start < page.char_end
        assert page.page >= 1
    assert document.pages[0].char_start == 0


def test_render_with_page_markers_respects_limit(sample_pdf: Path):
    document = extract_document(sample_pdf)
    rendered = render_with_page_markers(
        document.content, [page.__dict__ for page in document.pages], 500
    )
    assert "【第1页】" in rendered
    assert len(rendered) <= 560


def test_caj_is_marked_unsupported(tmp_path: Path):
    path = tmp_path / "paper.caj"
    path.write_bytes(b"fake caj")
    document = extract_document(path)
    assert document.content == ""
    assert document.quality == "unsupported"
    assert "CAJ" in document.error


def test_missing_pdf_returns_error(tmp_path: Path):
    document = extract_document(tmp_path / "missing.pdf")
    assert document.quality == "failed"
    assert document.error
