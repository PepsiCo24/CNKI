"""Deduplication tests: DOI, normalized title, SHA-256 and suspected duplicates."""
from __future__ import annotations

from app.core.utils import normalize_title, sha256_file
from app.models import Paper, PaperFile
from app.services.dedup import find_duplicates


def _paper(db, **kwargs) -> Paper:
    defaults = dict(
        title="默认标题",
        title_normalized=normalize_title(kwargs.get("title", "默认标题")),
        authors=["张三"],
        authors_text="张三",
        journal="岩土力学",
        year=2024,
    )
    defaults.update(kwargs)
    paper = Paper(**defaults)
    db.add(paper)
    db.commit()
    return paper


def test_doi_dedup(db):
    paper = _paper(db, title="某论文", doi="10.1234/abc")
    hits = find_duplicates(db, doi="https://doi.org/10.1234/ABC", title="完全不同")
    assert hits and hits[0].reason == "doi"
    assert hits[0].paper.id == paper.id


def test_title_author_year_dedup(db):
    paper = _paper(db, title="基于深度学习的边坡稳定性预测", authors=["李四"], year=2024)
    hits = find_duplicates(
        db,
        title="基于深度学习的边坡稳定性预测（正式版）",
        authors=["李四"],
        year=2024,
    )
    assert hits
    assert hits[0].paper.id == paper.id
    assert hits[0].reason in ("title", "title_fuzzy")
    assert hits[0].score >= 80


def test_sha256_file_dedup(db, sample_pdf):
    paper = _paper(db, title="带文件论文")
    digest = sha256_file(sample_pdf)
    db.add(
        PaperFile(
            paper_id=paper.id,
            original_filename=sample_pdf.name,
            stored_filename=sample_pdf.name,
            relative_path="papers/x.pdf",
            sha256=digest,
            size_bytes=sample_pdf.stat().st_size,
        )
    )
    db.commit()
    hits = find_duplicates(db, sha256=digest)
    assert hits and hits[0].reason == "sha256"
    assert hits[0].paper.id == paper.id


def test_fuzzy_title_is_suspected_but_retained(db):
    paper = _paper(db, title="改进随机森林边坡稳定性预测方法研究", authors=["张三"], year=2023)
    hits = find_duplicates(db, title="改进随机森林边坡稳定性预测方法", authors=["张三"], year=2023)
    assert hits
    assert hits[0].paper.id == paper.id
    # Nothing is deleted by dedup itself.
    assert db.get(Paper, paper.id) is not None


def test_normalize_title_strips_punctuation_and_spaces():
    assert normalize_title("  基于改进 随机森林的：边坡预测（研究） ") == normalize_title(
        "基于改进随机森林的边坡预测研究"
    )
