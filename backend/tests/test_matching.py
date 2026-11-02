"""Task condition matching: journal source is not a keyword."""
from __future__ import annotations

from datetime import date

from app.models import SearchTask
from app.services.matching import match_record


def _task(**kwargs) -> SearchTask:
    defaults = dict(
        name="测试任务",
        journal="岩土力学",
        keywords="",
        match_mode="fuzzy",
        start_date=date(2023, 1, 1),
        end_date=date(2025, 12, 31),
    )
    defaults.update(kwargs)
    return SearchTask(**defaults)


def _fields(**kwargs) -> dict:
    defaults = dict(
        title="某论文",
        journal="岩土力学",
        publication_date=date(2024, 5, 1),
        publication_date_precision="day",
        keywords=[],
        abstract="",
    )
    defaults.update(kwargs)
    return defaults


def test_journal_and_date_match():
    result = match_record(_task(), _fields())
    assert result.matched is True
    assert "期刊来源匹配" in result.reasons
    assert "发表日期匹配" in result.reasons


def test_other_journal_is_rejected_even_if_title_mentions_it():
    result = match_record(
        _task(),
        _fields(title="岩土力学领域研究", journal="岩石力学与工程学报"),
    )
    assert result.matched is False
    assert any("期刊来源不匹配" in item for item in result.mismatches)


def test_out_of_range_date_rejected():
    result = match_record(_task(), _fields(publication_date=date(2019, 5, 1)))
    assert result.matched is False
    assert any("超出检索范围" in item for item in result.mismatches)


def test_year_only_precision_compared_at_year_level():
    result = match_record(
        _task(),
        _fields(publication_date=date(2025, 1, 1), publication_date_precision="year"),
    )
    assert result.matched is True
    assert "年份范围匹配" in result.reasons


def test_topic_keyword_filter():
    task = _task(keywords="边坡 稳定性")
    result = match_record(task, _fields(title="边坡稳定性预测", keywords=["边坡", "稳定性"]))
    assert result.matched is True
    assert any("主题关键词命中" in reason for reason in result.reasons)
    missed = match_record(task, _fields(title="隧道开挖", abstract="隧道工程"))
    assert missed.matched is False
