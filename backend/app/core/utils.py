"""Small shared helpers: IDs, hashes, safe filenames, dates, title normalization."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WHITESPACE = re.compile(r"\s+")
CJK = re.compile(r"[\u4e00-\u9fff]")

MAX_FILENAME_BYTES = 180


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_filename(name: str, max_bytes: int = MAX_FILENAME_BYTES, fallback: str = "untitled") -> str:
    """Make a filename safe for Windows/macOS while preserving Chinese characters.

    Length is limited by UTF-8 byte length (common Windows/path constraint), keeping the
    extension intact.
    """
    name = unicodedata.normalize("NFC", name or "").strip()
    name = ILLEGAL_FILENAME_CHARS.sub("_", name)
    name = name.replace("\r", " ").replace("\n", " ")
    name = WHITESPACE.sub(" ", name).strip(" .")
    if not name:
        name = fallback
    path = Path(name)
    stem, suffix = path.stem, path.suffix
    if len(stem.encode("utf-8")) > max_bytes:
        while stem and len((stem + suffix).encode("utf-8")) > max_bytes:
            stem = stem[:-1]
        stem = stem.rstrip() or fallback
    result = f"{stem}{suffix}"
    if result.startswith("."):
        result = "_" + result
    return result


def normalize_title(title: str) -> str:
    if not title:
        return ""
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[\s\-—–_·,，.。;；:：'\"“”‘’()（）\[\]【】]", "", text)
    return text.strip()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    value = doi.strip().lower()
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value)
    value = value.rstrip(". ")
    return value or None


def parse_date_flexible(raw: str | None) -> tuple[date | None, str, str]:
    """Return (date, precision, raw). Never fabricates missing month/day.

    precision: day | month | year | unknown
    """
    raw = (raw or "").strip()
    if not raw:
        return None, "unknown", ""
    text = raw.replace("年", "-").replace("月", "-").replace("日", "")
    text = re.sub(r"[./]", "-", text).strip()
    match = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", text)
    if not match:
        return None, "unknown", raw
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    if year < 1800 or year > 2200:
        return None, "unknown", raw
    if month is not None and not (1 <= month <= 12):
        return None, "unknown", raw
    try:
        if day is not None and month is not None:
            return date(year, month, day), "day", raw
        if month is not None:
            return date(year, month, 1), "month", raw
        return date(year, 1, 1), "year", raw
    except ValueError:
        return None, "unknown", raw


def parse_date_strict(raw: str | date | None) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def as_iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def first_author(authors: Any) -> str:
    if isinstance(authors, list) and authors:
        return str(authors[0])
    if isinstance(authors, str) and authors:
        return re.split(r"[;；,，]", authors)[0].strip()
    return ""


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def split_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[;；,，、]|\band\b", raw)
    return dedupe_keep_order([p.strip() for p in parts if p and p.strip()])


def extract_year(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    return int(match.group(0)) if match else None


def human_filesize(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def ensure_within(base: Path, target: Path) -> Path:
    """Resolve target and guard against path traversal outside base."""
    base_resolved = base.resolve()
    target_resolved = target.resolve()
    if base_resolved != target_resolved and base_resolved not in target_resolved.parents:
        raise ValueError(f"path escapes data root: {target}")
    return target_resolved
