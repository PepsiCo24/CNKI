"""Durable queue recovery, dedupe and export tests."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from app.core.constants import JobStatus
from app.database.session import SessionLocal
from app.models import (
    AiAnalysisJob,
    BackgroundJob,
    ImportJob,
    Paper,
    PaperReview,
)
from app.services.dedup import find_duplicates
from app.services.export_service import create_backup, export_papers
from app.tasks.queue import enqueue_job
from app.tasks.runner import runner


def test_recover_requeues_interrupted_jobs(db):
    paper = Paper(title="恢复测试", title_normalized="恢复测试", authors=["张三"], authors_text="张三")
    db.add(paper)
    db.flush()
    bg = BackgroundJob(job_type="parse_paper", status=JobStatus.RUNNING, payload={"paper_id": paper.id})
    ai = AiAnalysisJob(paper_id=paper.id, status="running", provider="mock", model="m")
    imp = ImportJob(job_type="folder_scan", status=JobStatus.RUNNING)
    cancelling = BackgroundJob(job_type="scan_folder", status=JobStatus.CANCELLING, cancel_requested=1)
    db.add_all([bg, ai, imp, cancelling])
    db.commit()

    result = runner.recover()
    db.expire_all()
    assert result["requeued"] >= 1
    assert db.get(BackgroundJob, bg.id).status == JobStatus.PENDING
    assert db.get(BackgroundJob, cancelling.id).status == JobStatus.CANCELLED
    assert db.get(AiAnalysisJob, ai.id).status == "queued"
    assert db.get(ImportJob, imp.id).status == JobStatus.PENDING


def test_recover_keeps_completed_results(db):
    paper = Paper(title="已完成", title_normalized="已完成", authors=[], authors_text="")
    db.add(paper)
    db.flush()
    done = BackgroundJob(job_type="export", status=JobStatus.COMPLETED, payload={})
    db.add(done)
    db.commit()
    runner.recover()
    db.expire_all()
    assert db.get(BackgroundJob, done.id).status == JobStatus.COMPLETED
    assert db.get(Paper, paper.id) is not None


def test_enqueue_deduplicates_active_jobs(db):
    first = enqueue_job(db, "analyze_paper", {"paper_id": "p1"}, dedupe_key="analyze:p1")
    second = enqueue_job(db, "analyze_paper", {"paper_id": "p1"}, dedupe_key="analyze:p1")
    assert first.id == second.id
    assert db.query(BackgroundJob).filter(BackgroundJob.dedupe_key == "analyze:p1").count() == 1


def test_export_csv_json_xlsx_ris(db, tmp_path: Path):
    paper = Paper(
        title="导出测试论文",
        title_normalized="导出测试论文",
        authors=["张三", "李四"],
        authors_text="张三; 李四",
        journal="岩土力学",
        year=2024,
        doi="10.1/export",
        abstract="摘要内容",
        keywords=["边坡", "试验"],
        review_status="included",
    )
    db.add(paper)
    db.commit()

    csv_result = export_papers(db, fmt="csv", paper_ids=[paper.id], filters={})
    csv_text = Path(csv_result["path"]).read_text(encoding="utf-8-sig")
    assert "导出测试论文" in csv_text and "标题" in csv_text

    json_result = export_papers(db, fmt="json", paper_ids=[paper.id], filters={})
    payload = json.loads(Path(json_result["path"]).read_text(encoding="utf-8"))
    assert payload["paper_count"] == 1
    assert payload["papers"][0]["doi"] == "10.1/export"

    xlsx_result = export_papers(db, fmt="xlsx", paper_ids=[paper.id], filters={})
    from openpyxl import load_workbook

    workbook = load_workbook(xlsx_result["path"])
    assert workbook.active["B2"].value == "导出测试论文"

    ris_result = export_papers(db, fmt="ris", paper_ids=[paper.id], filters={})
    ris_text = Path(ris_result["path"]).read_text(encoding="utf-8")
    assert "TI  - 导出测试论文" in ris_text
    assert "AU  - 张三" in ris_text


def test_backup_contains_database_and_manifest(db):
    result = create_backup(db)
    path = Path(result["path"])
    assert path.exists()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert any(name.endswith("cnki_scholar.db") for name in names)
        assert "manifest.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert "PDF files are not included" in manifest["contents"]


def test_duplicate_warning_requires_confirmation(db):
    paper = Paper(
        title="相同标题论文",
        title_normalized="相同标题论文",
        authors=["张三"],
        authors_text="张三",
        duplicate_status="suspected",
    )
    db.add(paper)
    db.commit()
    hits = find_duplicates(db, title="相同标题论文", authors=["张三"])
    assert hits


def test_dedupe_key_can_be_reused_after_completion(db):
    first = enqueue_job(db, "parse_paper", {"paper_id": "p1"}, dedupe_key="parse:p1")
    first.status = JobStatus.COMPLETED
    db.commit()
    second = enqueue_job(db, "parse_paper", {"paper_id": "p1"}, dedupe_key="parse:p1")
    assert second.id != first.id
    db.refresh(first)
    assert first.dedupe_key is None
    assert second.status == JobStatus.PENDING
    assert db.query(BackgroundJob).filter(BackgroundJob.dedupe_key == "parse:p1").count() == 1


def test_export_accepts_tree_key_and_searches(db):
    paper = Paper(
        title="树筛选导出论文",
        title_normalized="树筛选导出论文",
        authors=["张三"],
        authors_text="张三",
        journal="岩土力学",
        year=2024,
        review_status="included",
    )
    db.add(paper)
    db.commit()
    from app.database.fts import index_paper

    index_paper(db, paper)
    db.commit()
    result = export_papers(db, fmt="json", paper_ids=[], filters={"tree_key": "status:included", "q": "树筛选"})
    payload = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert payload["paper_count"] == 1
    assert payload["papers"][0]["title"] == "树筛选导出论文"
