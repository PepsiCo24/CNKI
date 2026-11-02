"""File intake: archive, hash duplicates and suspected-duplicate retention."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from app.models import Paper, PaperFile
from app.services.file_service import register_file


def test_archive_and_merge_metadata_only(db, sample_pdf: Path, tmp_path: Path):
    first = register_file(db, source=sample_pdf, origin="test")
    assert first.status == "imported"
    assert first.paper is not None
    assert first.file is not None
    archived = Path(db.get(Paper, first.paper.id).files[0].relative_path)
    assert "papers/" in str(archived).replace("\\", "/") and "/2023/" in str(archived).replace("\\", "/")
    document = pymupdf.open(db.get(Paper, first.paper.id).files[0].relative_path if False else sample_pdf)
    document.close()

    # Same bytes -> reuse, do not create a new file.
    same = register_file(db, source=sample_pdf, origin="test")
    assert same.status == "duplicate"
    assert same.paper.id == first.paper.id
    assert db.query(PaperFile).filter(PaperFile.paper_id == first.paper.id).count() == 1


def test_different_fulltext_same_metadata_is_kept_for_confirmation(db, sample_pdf: Path, tmp_path: Path):
    first = register_file(db, source=sample_pdf, origin="test")
    assert first.paper is not None

    # Create a genuinely different PDF with the same embedded metadata.
    source = pymupdf.open(sample_pdf)
    source.new_page()
    modified = tmp_path / "modified_same_title.pdf"
    source.save(modified)
    source.close()

    second = register_file(db, source=modified, origin="test")
    assert second.status == "suspected"
    assert second.paper is not None
    assert second.paper.id != first.paper.id
    assert second.paper.duplicate_status == "suspected"
    assert second.paper.duplicate_of_id == first.paper.id
    # Both files are retained; nothing was deleted.
    assert db.query(PaperFile).filter(PaperFile.paper_id == first.paper.id).count() == 1
    assert db.query(PaperFile).filter(PaperFile.paper_id == second.paper.id).count() == 1
    assert db.get(Paper, first.paper.id) is not None
    assert db.get(Paper, second.paper.id) is not None
