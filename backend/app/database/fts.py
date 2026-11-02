"""FTS5 index for literature/innovation search.

Uses the trigram tokenizer (good for Chinese substring search). For queries shorter
than 3 characters the search service falls back to LIKE. The index is maintained by
``index_paper`` after any mutation; ``rebuild_index`` can always reconstruct it.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import AiAnalysisResult, Paper, PaperText, ResearchNote

logger = get_logger(__name__)

CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(
  paper_id UNINDEXED,
  title,
  authors,
  journal,
  abstract,
  innovations,
  notes,
  tokenize = 'trigram'
)
"""


def ensure_fts(db: Session) -> bool:
    try:
        db.execute(text(CREATE_FTS))
        db.commit()
        return True
    except Exception as exc:  # pragma: no cover - depends on sqlite build
        logger.warning("FTS5 unavailable, falling back to LIKE search: %s", exc)
        db.rollback()
        return False


def _collect(db: Session, paper: Paper) -> tuple[str, str, str]:
    analyses = (
        db.query(AiAnalysisResult)
        .filter(AiAnalysisResult.paper_id == paper.id, AiAnalysisResult.is_current.is_(True))
        .all()
    )
    innovations: list[str] = []
    for analysis in analyses:
        innovations.append(analysis.innovation_summary or "")
        for item in (analysis.claimed_innovations or []) + (analysis.inferred_contributions or []):
            if isinstance(item, dict):
                innovations.extend(
                    str(item.get(key) or "")
                    for key in ("name", "problem", "method", "difference")
                )
    notes = (
        db.query(ResearchNote)
        .filter(ResearchNote.paper_id == paper.id)
        .all()
    )
    note_text = " ".join(f"{n.title} {n.content}" for n in notes)
    fulltext = ""
    paper_text = db.query(PaperText).filter(PaperText.paper_id == paper.id).first()
    if paper_text:
        fulltext = paper_text.content[:20000]
    return " ".join(innovations), f"{note_text} {paper.notes_summary} {fulltext}"


def index_paper(db: Session, paper: Paper) -> None:
    try:
        innovations, notes = _collect(db, paper)
        db.execute(text("DELETE FROM paper_fts WHERE paper_id = :pid"), {"pid": paper.id})
        db.execute(
            text(
                "INSERT INTO paper_fts (paper_id, title, authors, journal, abstract, innovations, notes) "
                "VALUES (:pid, :title, :authors, :journal, :abstract, :innovations, :notes)"
            ),
            {
                "pid": paper.id,
                "title": paper.title or "",
                "authors": paper.authors_text or "",
                "journal": paper.journal or "",
                "abstract": paper.abstract or "",
                "innovations": innovations,
                "notes": notes,
            },
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to index paper %s: %s", paper.id, exc)


def remove_paper(db: Session, paper_id: str) -> None:
    try:
        db.execute(text("DELETE FROM paper_fts WHERE paper_id = :pid"), {"pid": paper_id})
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to remove FTS row %s: %s", paper_id, exc)


def rebuild_all(db: Session) -> int:
    ensure_fts(db)
    db.execute(text("DELETE FROM paper_fts"))
    papers = db.query(Paper).filter(Paper.is_deleted.is_(False)).all()
    for paper in papers:
        index_paper(db, paper)
    db.commit()
    return len(papers)


def search_ids(db: Session, query: str, limit: int = 200) -> list[str]:
    """Return paper ids matching the query, ordered by FTS rank (or LIKE fallback)."""
    q = (query or "").strip()
    if not q:
        return []
    if len(q) >= 3:
        try:
            rows = db.execute(
                text(
                    "SELECT paper_id FROM paper_fts WHERE paper_fts MATCH :q "
                    "ORDER BY bm25(paper_fts) LIMIT :limit"
                ),
                {"q": _fts_query(q), "limit": limit},
            ).fetchall()
            if rows:
                return [row[0] for row in rows]
        except Exception as exc:  # pragma: no cover
            logger.warning("FTS query failed, falling back to LIKE: %s", exc)
    like = f"%{q}%"
    rows = db.execute(
        text(
            "SELECT paper_id FROM paper_fts WHERE title LIKE :like OR authors LIKE :like "
            "OR journal LIKE :like OR abstract LIKE :like OR innovations LIKE :like OR notes LIKE :like "
            "LIMIT :limit"
        ),
        {"like": like, "limit": limit},
    ).fetchall()
    return [row[0] for row in rows]


def _fts_query(raw: str) -> str:
    # Quote the whole phrase so punctuation in user input cannot break FTS syntax.
    return '"' + raw.replace('"', '""') + '"'
