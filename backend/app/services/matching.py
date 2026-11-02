"""Match imported metadata against search-task conditions.

The journal field is treated as the *source/journal name* (hard filter), never as a
topic keyword. Date matching respects the stored precision: a year-only record is
matched at year granularity rather than inventing a month/day.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.models import SearchTask


def _norm(value: str) -> str:
    return re.sub(r"[\s\-—–_·,，.。;；:：'\"“”‘’()（）\[\]【】]", "", (value or "").lower())


@dataclass
class TaskMatch:
    matched: bool
    score: float = 100.0
    reasons: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)


def match_record(task: SearchTask, fields: dict) -> TaskMatch:
    reasons: list[str] = []
    mismatches: list[str] = []
    score = 100.0

    if task.journal.strip():
        expected = _norm(task.journal)
        actual = _norm(fields.get("journal") or "")
        if not actual:
            mismatches.append("题录缺少期刊来源")
            score -= 35
        elif expected != actual and expected not in actual and actual not in expected:
            mismatches.append(f"期刊来源不匹配（期望“{task.journal}”，实际“{fields.get('journal')}”）")
            score -= 60
        else:
            reasons.append("期刊来源匹配")

    if task.start_date or task.end_date:
        pub_date: date | None = fields.get("publication_date")
        precision = fields.get("publication_date_precision", "unknown")
        if not pub_date:
            mismatches.append("缺少发表日期，无法核对日期范围")
            score -= 25
        else:
            start = task.start_date
            end = task.end_date
            if precision == "year":
                year = pub_date.year
                if (start and year < start.year) or (end and year > end.year):
                    mismatches.append(f"年份 {year} 超出检索范围")
                    score -= 60
                else:
                    reasons.append("年份范围匹配")
            else:
                if (start and pub_date < start) or (end and pub_date > end):
                    mismatches.append(f"发表日期 {pub_date.isoformat()} 超出检索范围")
                    score -= 60
                else:
                    reasons.append("发表日期匹配")

    keywords = [k.strip() for k in re.split(r"[\s;,，；]+", task.keywords or "") if k.strip()]
    if keywords:
        haystack = " ".join(
            [
                fields.get("title") or "",
                fields.get("abstract") or "",
                " ".join(fields.get("keywords") or []),
            ]
        )
        haystack_norm = haystack.lower()
        if task.match_mode == "exact":
            found = [k for k in keywords if k.lower() in haystack_norm]
        else:
            found = [k for k in keywords if k.lower() in haystack_norm]
        if found:
            reasons.append("主题关键词命中：" + "、".join(found))
        else:
            mismatches.append("主题关键词未命中")
            score -= 45

    hard_mismatch = any(
        token in " ".join(mismatches)
        for token in ("期刊来源不匹配", "超出检索范围", "主题关键词未命中")
    )
    matched = not hard_mismatch and (not task.journal.strip() or "期刊来源匹配" in reasons)
    return TaskMatch(matched=matched, score=max(0.0, score), reasons=reasons, mismatches=mismatches)
