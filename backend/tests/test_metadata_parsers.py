"""Metadata parser unit tests (RIS / BibTeX / EndNote / CSV, date precision)."""
from __future__ import annotations

from pathlib import Path

from app.core.utils import parse_date_flexible
from app.parsers.metadata import parse_bibtex, parse_csv, parse_endnote, parse_metadata_file, parse_ris


def test_ris_parsing_preserves_fields_and_dates():
    content = """TY  - JOUR
TI  - 岩石力学示例研究
AU  - 张三
AU  - 李四
JO  - 岩土力学
PY  - 2024
DA  - 2024-05-12
AB  - 这是一个摘要。
KW  - 岩石
KW  - 试验
DO  - 10.1234/ABC.001
UR  - https://example.invalid/1
ER  - 
"""
    records = parse_ris(content)
    assert len(records) == 1
    record = records[0]
    assert record.title == "岩石力学示例研究"
    assert record.authors == ["张三", "李四"]
    assert record.journal == "岩土力学"
    fields = record.as_paper_fields()
    assert fields["publication_date"].isoformat() == "2024-05-12"
    assert fields["publication_date_precision"] == "day"
    assert fields["doi"] == "10.1234/abc.001"


def test_ris_year_only_precision_does_not_invent_month_day():
    content = """TY  - JOUR
T1  - 仅年份文献
AU  - 王五
JO  - 岩土力学
PY  - 2024
ER  - 
"""
    records = parse_ris(content)
    fields = records[0].as_paper_fields()
    assert fields["publication_date_precision"] == "year"
    assert fields["publication_date_raw"] == "2024"


def test_bibtex_parsing():
    content = """
@article{zhang2023,
  title = {A {Study} of Slopes},
  author = {Zhang, San and Li, Si},
  journal = {Rock Mechanics},
  year = {2023},
  doi = {10.1000/test},
  keywords = {slope; stability},
  abstract = {An abstract.}
}
"""
    records = parse_bibtex(content)
    assert len(records) == 1
    assert "A Study of Slopes" in records[0].title
    assert len(records[0].authors) == 2
    assert records[0].year == 2023


def test_endnote_parsing():
    content = """%0 Journal Article
%A 张三
%T 一个标题
%J 岩土力学
%D 2023
%R 10.1000/enw
%X 摘要内容
%K 关键词1
%K 关键词2

"""
    records = parse_endnote(content)
    assert len(records) == 1
    assert records[0].title == "一个标题"
    assert records[0].journal == "岩土力学"


def test_csv_chinese_headers():
    content = "标题,作者,期刊,发表时间,摘要,关键词,DOI\n中文标题,张三;李四,岩土力学,2024-01-02,摘要,岩土;边坡,10.1/x\n"
    records = parse_csv(content)
    assert records and records[0].title == "中文标题"
    assert records[0].authors == ["张三", "李四"]


def test_file_detection_and_errors(tmp_path: Path):
    path = tmp_path / "x.ris"
    content = "TY  - JOUR\nTI  - 无作者标题\nPY  - 2023\nER  - \n"
    records, fmt, errors = parse_metadata_file(path.name, content.encode("utf-8"))
    assert fmt == "ris"
    assert len(records) == 1
    assert records[0].authors == []
    # Missing title records are skipped and reported.
    bad, _, bad_errors = parse_metadata_file("bad.ris", b"TY  - JOUR\nAU  - A\nER  - \n")
    assert bad == [] and bad_errors


def test_parse_date_flexible():
    assert parse_date_flexible("2024-03-05")[1:] == ("day", "2024-03-05")
    assert parse_date_flexible("2024-03")[:2] == (__import__("datetime").date(2024, 3, 1), "month")
    assert parse_date_flexible("2024")[1] == "year"
    assert parse_date_flexible("not-a-date")[1] == "unknown"
    assert parse_date_flexible("2024-13-01")[1] == "unknown"
