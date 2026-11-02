"""Three-level deduplication.

1. DOI / platform identifier
2. normalized title + first author + year (fuzzy title similarity as a warning)
3. SHA-256 of the original file

A suspected duplicate is never deleted automatically: the caller receives it and the
API asks the user to confirm. Existing papers can gain a new file only when the file is
genuinely different (different SHA-256) and the user confirms.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.utils import normalize_doi, normalize_title
from app.models import Paper, PaperFile


@dataclass
class DuplicateHit:
    paper: Paper
    reason: str
    score: float
    detail: str = ""


def find_duplicates(
    db: Session,
    *,
    doi: str | None = None,
    title: str = "",
    authors: list[str] | None = None,
    year: int | None = None,
    sha256: str | None = None,
) -> list[DuplicateHit]:
    hits: list[DuplicateHit] = []
    seen: set[str] = set()

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        paper = (
            db.query(Paper)
            .filter(func.lower(Paper.doi) == normalized_doi, Paper.is_deleted.is_(False))
            .first()
        )
        if paper:
            hits.append(DuplicateHit(paper, "doi", 100.0, normalized_doi))
            seen.add(paper.id)

    if sha256:
        file = db.query(PaperFile).filter(PaperFile.sha256 == sha256).first()
        if file and file.paper_id not in seen:
            paper = db.get(Paper, file.paper_id)
            if paper and not paper.is_deleted:
                hits.append(DuplicateHit(paper, "sha256", 100.0, sha256[:12]))
                seen.add(paper.id)

    normalized = normalize_title(title)
    if normalized:
        candidates = db.query(Paper).filter(Paper.is_deleted.is_(False)).all()
        first_author = (authors or [""])[0] if authors else ""
        for paper in candidates:
            if paper.id in seen:
                continue
            candidate_title = paper.title_normalized or normalize_title(paper.title)
            if candidate_title == normalized:
                same_author = bool(first_author) and first_author in (paper.authors or [])
                same_year = year is not None and paper.year == year
                score = 95.0 + (3.0 if same_author else 0.0) + (2.0 if same_year else 0.0)
                detail = "标题完全一致" + ("，作者/年份一致" if same_author and same_year else "")
                hits.append(DuplicateHit(paper, "title", min(score, 100.0), detail))
                seen.add(paper.id)
                continue
            ratio = difflib.SequenceMatcher(None, normalized, candidate_title).ratio()
            same_author = bool(first_author) and first_author in (paper.authors or [])
            same_year = year is not None and paper.year == year
            # Author + year corroboration allows a slightly looser title threshold;
            # results are still marked "suspected" and require human confirmation.
            threshold = 0.88 if (same_author and same_year) else 0.94
            if ratio >= threshold and len(normalized) > 8:
                hits.append(
                    DuplicateHit(
                        paper,
                        "title_fuzzy",
                        round(ratio * 90, 1),
                        f"标题高度相似（{ratio:.0%}）"
                        + ("，作者一致" if same_author else "")
                        + ("，年份一致" if same_year else ""),
                    )
                )
                seen.add(paper.id)
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


def best_match(hits: list[DuplicateHit]) -> DuplicateHit | None:
    return hits[0] if hits else None
