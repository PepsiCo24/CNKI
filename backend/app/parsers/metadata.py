"""Metadata file parsers: RIS, BibTeX, EndNote ENW and CSV.

These work entirely offline on files the user exported from an official platform. No
network calls and no invented metadata: fields missing from the file remain empty and
date precision is preserved.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.utils import normalize_doi, parse_date_flexible, split_authors


@dataclass
class MetadataRecord:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    journal: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    doi: str | None = None
    source_id: str = ""
    url: str = ""
    publication_date_raw: str = ""
    year: int | None = None
    paper_type: str = "journal"
    language: str = "zh"
    raw: dict = field(default_factory=dict)
    source: str = "CNKI"

    def as_paper_fields(self) -> dict:
        from datetime import date

        parsed, precision, raw_date = parse_date_flexible(self.publication_date_raw or (str(self.year) if self.year else ""))
        return {
            "title": self.title.strip(),
            "authors": self.authors,
            "authors_text": "; ".join(self.authors),
            "journal": self.journal.strip(),
            "abstract": self.abstract.strip(),
            "keywords": self.keywords,
            "doi": normalize_doi(self.doi),
            "source_id": self.source_id or None,
            "source_url": self.url,
            "publication_date": parsed,
            "publication_date_precision": precision,
            "publication_date_raw": raw_date,
            "year": self.year or (parsed.year if parsed else None),
            "month": parsed.month if parsed and precision != "year" else None,
            "paper_type": self.paper_type,
            "language": self.language,
            "source": self.source,
            "raw_metadata": self.raw,
        }


FORMAT_LABELS = {"ris": "RIS", "bibtex": "BibTeX", "endnote": "EndNote", "csv": "CSV"}


def detect_format(filename: str, content: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in (".ris", ".nbib"):
        return "ris"
    if suffix in (".bib", ".bibtex"):
        return "bibtex"
    if suffix in (".enw", ".endnote"):
        return "endnote"
    if suffix == ".csv":
        return "csv"
    head = content.lstrip()[:4000]
    if head.startswith("@") or re.search(r"^@\w+\s*\{", head, re.M):
        return "bibtex"
    if re.search(r"^TY\s{0,2}-", head, re.M):
        return "ris"
    if re.search(r"^%0\s", head, re.M):
        return "endnote"
    if "," in head.splitlines()[0] if head.splitlines() else False:
        return "csv"
    return "ris"


def parse_metadata_file(filename: str, data: bytes, forced_format: str = "auto") -> tuple[list[MetadataRecord], str, list[dict]]:
    content = _decode(data)
    fmt = forced_format if forced_format != "auto" else detect_format(filename, content)
    errors: list[dict] = []
    try:
        if fmt == "ris":
            records = parse_ris(content)
        elif fmt == "bibtex":
            records = parse_bibtex(content)
        elif fmt == "endnote":
            records = parse_endnote(content)
        elif fmt == "csv":
            records = parse_csv(content)
        else:
            raise ValueError(f"不支持的题录格式：{fmt}")
    except Exception as exc:
        return [], fmt, [{"line": 0, "error": str(exc)}]
    valid: list[MetadataRecord] = []
    for index, record in enumerate(records, start=1):
        if not record.title.strip():
            errors.append({"line": index, "error": "缺少标题，已跳过"})
            continue
        if not record.authors:
            record.raw.setdefault("warning", "无作者信息")
        valid.append(record)
    return valid, fmt, errors


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# ------------------------------------------------------------------------------- RIS
RIS_TAG_MAP = {
    "TY": "type",
    "TI": "title",
    "T1": "title",
    "BT": "title",
    "AU": "author",
    "A1": "author",
    "AU ": "author",
    "JO": "journal",
    "JF": "journal",
    "T2": "journal",
    "J1": "journal",
    "JA": "journal",
    "PY": "year",
    "Y1": "date",
    "DA": "date",
    "AB": "abstract",
    "N2": "abstract",
    "KW": "keyword",
    "K1": "keyword",
    "DO": "doi",
    "UR": "url",
    "L1": "url",
    "ID": "source_id",
    "SN": "issn",
    "VL": "volume",
    "IS": "issue",
    "SP": "start_page",
    "EP": "end_page",
    "N1": "note",
}
RIS_TYPE_MAP = {
    "JOUR": "journal",
    "JFULL": "journal",
    "MGZN": "journal",
    "THES": "dissertation",
    "DISS": "dissertation",
    "CONF": "conference",
    "CPAPER": "conference",
}


def parse_ris(content: str) -> list[MetadataRecord]:
    records: list[MetadataRecord] = []
    current: dict[str, list[str]] = {}
    last_tag: str | None = None
    in_record = False

    def flush() -> None:
        nonlocal current, last_tag, in_record
        if not current:
            return
        record = MetadataRecord(
            title=_clean(_first(current, "title")),
            authors=[_clean(a) for a in current.get("author", []) if _clean(a)],
            journal=_clean(_first(current, "journal")),
            abstract=_clean(_first(current, "abstract")),
            keywords=[_clean(k) for k in current.get("keyword", []) if _clean(k)],
            doi=_first(current, "doi") or None,
            source_id=_clean(_first(current, "source_id")),
            url=_clean(_first(current, "url")),
            publication_date_raw=_clean(_first(current, "date") or _first(current, "year")),
            year=_int(_first(current, "year")),
            paper_type=RIS_TYPE_MAP.get(_first(current, "type").upper(), "journal"),
            raw={k: v for k, v in current.items()},
        )
        records.append(record)
        current = {}
        last_tag = None
        in_record = False

    for raw_line in content.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        match = re.match(r"^([A-Z][A-Z0-9])\s{0,2}-\s?(.*)$", line)
        if match:
            tag, value = match.group(1), match.group(2).strip()
            if tag == "TY":
                if current:
                    flush()
                in_record = True
            if not in_record and tag != "TY":
                in_record = True
            key = RIS_TAG_MAP.get(tag)
            if key:
                if key == "keyword":
                    # CNKI sometimes separates keywords with ; or ， inside one KW line.
                    for part in re.split(r"[;；]", value):
                        if part.strip():
                            current.setdefault("keyword", []).append(part.strip())
                else:
                    current.setdefault(key, []).append(value)
            last_tag = key
            if tag == "ER":
                flush()
        elif last_tag and line.startswith(" "):
            target = current.get(last_tag)
            if target:
                target[-1] = f"{target[-1]} {line.strip()}".strip()
    flush()
    return records


# ---------------------------------------------------------------------------- BibTeX
def parse_bibtex(content: str) -> list[MetadataRecord]:
    records: list[MetadataRecord] = []
    for entry_type, body in _iter_bibtex_entries(content):
        fields = _parse_bib_fields(body)
        authors = [a.strip() for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()]
        authors = [_bib_clean(a) for a in authors]
        date_raw = fields.get("date") or fields.get("year") or ""
        year = _int(fields.get("year"))
        title = _bib_clean(fields.get("title", ""))
        if not title:
            continue
        records.append(
            MetadataRecord(
                title=title,
                authors=authors,
                journal=_bib_clean(fields.get("journal") or fields.get("booktitle") or ""),
                abstract=_bib_clean(fields.get("abstract", "")),
                keywords=[k.strip() for k in re.split(r"[;,]", fields.get("keywords", "")) if k.strip()],
                doi=fields.get("doi"),
                url=fields.get("url", ""),
                source_id=fields.get("cnkiid", ""),
                publication_date_raw=date_raw,
                year=year,
                paper_type="journal"
                if entry_type.lower() in ("article", "journal")
                else ("conference" if entry_type.lower() in ("inproceedings", "conference") else "journal"),
                raw=fields,
            )
        )
    return records


def _iter_bibtex_entries(content: str):
    pattern = re.compile(r"@(\w+)\s*\{", re.I)
    for match in pattern.finditer(content):
        if match.group(1).lower() in ("string", "preamble", "comment"):
            continue
        start = match.end()
        depth = 1
        index = start
        while index < len(content) and depth > 0:
            char = content[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            index += 1
        body = content[start : index - 1]
        yield match.group(1), body


def _parse_bib_fields(body: str) -> dict[str, str]:
    # Drop the citation key before the first comma.
    comma = body.find(",")
    if comma >= 0:
        body = body[comma + 1 :]
    fields: dict[str, str] = {}
    for match in re.finditer(r"(\w+)\s*=\s*", body):
        key = match.group(1).lower()
        pos = match.end()
        if pos >= len(body):
            continue
        if body[pos] == "{":
            depth, index = 1, pos + 1
            while index < len(body) and depth > 0:
                if body[index] == "{":
                    depth += 1
                elif body[index] == "}":
                    depth -= 1
                index += 1
            value = body[pos + 1 : index - 1]
        elif body[pos] == '"':
            end = body.find('"', pos + 1)
            value = body[pos + 1 : end if end > 0 else len(body)]
        else:
            end = body.find(",", pos)
            value = body[pos : end if end > 0 else len(body)]
        fields.setdefault(key, value.strip())
    return fields


def _bib_clean(value: str) -> str:
    value = re.sub(r"\\[a-zA-Z]+\s*", "", value)
    value = value.replace("{", "").replace("}", "").replace("~", " ")
    return re.sub(r"\s+", " ", value).strip()


# --------------------------------------------------------------------------- EndNote
ENW_MAP = {
    "0": "type",
    "A": "author",
    "T": "title",
    "J": "journal",
    "B": "journal",
    "D": "year",
    "8": "date",
    "X": "abstract",
    "K": "keyword",
    "R": "doi",
    "U": "url",
    "M": "source_id",
    "N": "note",
    "V": "volume",
    "7": "edition",
}


def parse_endnote(content: str) -> list[MetadataRecord]:
    records: list[MetadataRecord] = []
    blocks: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    for line in content.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        match = re.match(r"^%([0-9A-Za-z@!#$&()*+])\s?(.*)$", line)
        if match:
            key = ENW_MAP.get(match.group(1))
            if key:
                current.setdefault(key, []).append(match.group(2).strip())
    if current:
        blocks.append(current)
    for block in blocks:
        title = _clean(_first(block, "title"))
        if not title:
            continue
        type_value = _first(block, "type").lower()
        records.append(
            MetadataRecord(
                title=title,
                authors=[_clean(a) for a in block.get("author", []) if _clean(a)],
                journal=_clean(_first(block, "journal")),
                abstract=_clean(_first(block, "abstract")),
                keywords=[k.strip() for k in re.split(r"[;,]", _first(block, "keyword")) if k.strip()],
                doi=_first(block, "doi") or None,
                url=_clean(_first(block, "url")),
                publication_date_raw=_clean(_first(block, "date") or _first(block, "year")),
                year=_int(_first(block, "year")),
                paper_type="dissertation" if "thesis" in type_value or "dissertation" in type_value else "journal",
                raw=block,
            )
        )
    return records


# -------------------------------------------------------------------------------- CSV
CSV_ALIASES = {
    "title": {"title", "题名", "篇名", "标题", "论文标题", "文献标题"},
    "authors": {"author", "authors", "作者", "全部作者"},
    "journal": {"journal", "source", "期刊", "来源", "文献来源", "刊名"},
    "abstract": {"abstract", "摘要"},
    "keywords": {"keywords", "keyword", "关键词"},
    "doi": {"doi", "do"},
    "date": {"date", "publication date", "发表时间", "发表日期", "出版日期", "年", "year"},
    "url": {"url", "链接", "文献详情url", "address"},
    "source_id": {"id", "cnki id", "文献标识", "来源id"},
    "type": {"type", "文献类型", "resource type"},
}


def parse_csv(content: str) -> list[MetadataRecord]:
    sample = content[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(content), dialect=dialect)
    if not reader.fieldnames:
        return []
    mapping: dict[str, str] = {}
    for fieldname in reader.fieldnames:
        normalized = (fieldname or "").strip().lower()
        for target, aliases in CSV_ALIASES.items():
            if normalized in aliases and target not in mapping:
                mapping[target] = fieldname
    records: list[MetadataRecord] = []
    for row in reader:
        title = (row.get(mapping.get("title", ""), "") or "").strip()
        if not title:
            continue
        authors_raw = row.get(mapping.get("authors", ""), "") or ""
        keywords_raw = row.get(mapping.get("keywords", ""), "") or ""
        date_raw = row.get(mapping.get("date", ""), "") or ""
        type_raw = (row.get(mapping.get("type", ""), "") or "").lower()
        paper_type = "dissertation" if "学位" in type_raw or "thesis" in type_raw else "journal"
        records.append(
            MetadataRecord(
                title=title,
                authors=split_authors(authors_raw),
                journal=(row.get(mapping.get("journal", ""), "") or "").strip(),
                abstract=(row.get(mapping.get("abstract", ""), "") or "").strip(),
                keywords=[k.strip() for k in re.split(r"[;；,，]", keywords_raw) if k.strip()],
                doi=(row.get(mapping.get("doi", ""), "") or "").strip() or None,
                source_id=(row.get(mapping.get("source_id", ""), "") or "").strip(),
                url=(row.get(mapping.get("url", ""), "") or "").strip(),
                publication_date_raw=date_raw,
                year=_int(date_raw),
                paper_type=paper_type,
                raw={k: v for k, v in row.items() if v},
            )
        )
    return records


def _first(mapping: dict[str, list[str]], key: str) -> str:
    values = mapping.get(key) or []
    return values[0] if values else ""


def _clean(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None
