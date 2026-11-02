"""End-to-end API workflow: task -> RIS -> PDF -> parse -> AI -> review -> library."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.core.constants import AiStatus, FulltextStatus, ReviewStatus
from app.database.session import SessionLocal
from app.models import (
    AiAnalysisJob,
    AiAnalysisResult,
    BackgroundJob,
    InnovationItem,
    Paper,
    PaperReview,
    SearchTask,
    SearchTaskPaper,
)
from app.tasks import handlers


def _import_sample(client, task_id: str, ris_path: Path):
    with ris_path.open("rb") as handle:
        return client.post(
            "/api/imports/metadata",
            files={"file": ("sample_metadata.ris", handle, "application/x-research-info-systems")},
            data={"task_id": task_id, "format": "auto"},
        )


def test_full_workflow(client, sample_ris: Path, sample_pdf: Path):
    # 1. Create task with journal source and full date range.
    response = client.post(
        "/api/search-tasks",
        json={
            "name": "岩土力学期刊创新点调研",
            "journal": "岩土力学",
            "start_date": "2023-01-01",
            "end_date": "2025-12-31",
            "paper_type": "journal",
        },
    )
    assert response.status_code == 200
    task = response.json()["data"]["task"]
    task_id = task["id"]
    assert task["journal"] == "岩土力学"

    # 2. Invalid date range is rejected.
    bad = client.post(
        "/api/search-tasks",
        json={"name": "bad", "start_date": "2025-01-01", "end_date": "2024-01-01"},
    )
    assert bad.status_code == 422

    # 3. Import official RIS; only journal/date matching records are linked.
    imported = _import_sample(client, task_id, sample_ris)
    assert imported.status_code == 200
    data = imported.json()["data"]
    assert data["total"] == 5
    assert data["imported"] == 3
    assert data["detail"]["skipped"] == 2
    assert data["detail"]["format"] == "ris"

    linked = client.get(f"/api/search-tasks/{task_id}/papers").json()["data"]
    assert linked["total"] == 3
    target = next(item for item in linked["items"] if "改进随机森林" in item["title"])
    assert target["fulltext_status"] == FulltextStatus.NOT_AVAILABLE
    assert target["review_status"] == ReviewStatus.PENDING_FULLTEXT
    assert target["analysis_id"] is None

    # Metadata-only papers must be searchable too (FTS indexing on create).
    search_meta = client.get("/api/papers", params={"q": "深部岩体"}).json()["data"]
    assert search_meta["total"] == 1

    # 4. Upload the real (sample) PDF. It must merge into the existing metadata record.
    with sample_pdf.open("rb") as handle:
        upload = client.post(
            "/api/imports/files",
            files={"files": (sample_pdf.name, handle, "application/pdf")},
            data={"task_id": task_id},
        )
    assert upload.status_code == 200
    outcome = upload.json()["data"]["outcomes"][0]
    assert outcome["status"] == "imported"
    assert outcome["paper_id"] == target["id"]

    # 5. Run the parse handler synchronously (no lifespan runner in tests).
    parse_job = (
        SessionLocal()
        .query(BackgroundJob)
        .filter(BackgroundJob.job_type == "parse_paper")
        .order_by(BackgroundJob.created_at.desc())
        .first()
    )
    assert parse_job is not None
    handlers.handle_parse_paper(parse_job.payload)

    detail = client.get(f"/api/papers/{target['id']}").json()["data"]
    assert detail["parse_status"] == "parsed"
    assert detail["fulltext_status"] == FulltextStatus.IMPORTED
    assert detail["text_info"]["char_count"] > 1500
    assert "改进随机森林" in client.get(f"/api/papers/{target['id']}/text").json()["data"]["content"]

    # 6. Auto-analysis job was queued by the parse handler; execute it.
    session = SessionLocal()
    ai_bg = (
        session.query(BackgroundJob)
        .filter(BackgroundJob.job_type == "analyze_paper", BackgroundJob.status == "pending")
        .order_by(BackgroundJob.created_at.desc())
        .first()
    )
    assert ai_bg is not None, "parse should queue AI analysis when auto_analyze is on"
    payload = dict(ai_bg.payload)
    bg_id = ai_bg.id
    session.close()
    asyncio.run(handlers.handle_analyze_paper(bg_id, payload))

    detail = client.get(f"/api/papers/{target['id']}").json()["data"]
    assert detail["ai_status"] in (AiStatus.COMPLETED, AiStatus.CACHED)
    assert detail["review_status"] == ReviewStatus.PENDING_REVIEW
    analysis = detail["analysis"]
    assert analysis and analysis["is_mock"] is True
    assert analysis["one_sentence_summary"]
    assert analysis["analysis_scope"] == "fulltext"

    # 7. Review workbench sees the paper, then human includes it.
    queue = client.get("/api/review/queue").json()["data"]
    assert any(item["id"] == target["id"] for item in queue["items"])
    review = client.post(
        f"/api/review/{target['id']}/action",
        json={"action": "include", "note": "验收：方法有参考价值", "tags": ["岩土工程", "机器学习"]},
    )
    assert review.status_code == 200
    assert review.json()["data"]["review"]["to_status"] == ReviewStatus.INCLUDED

    # 8. Library search by innovation and abstract, not only title.
    library = client.get("/api/library/papers", params={"q": "随机森林"}).json()["data"]
    assert library["total"] == 1
    assert library["items"][0]["id"] == target["id"]
    assert library["items"][0]["screening_score"] == analysis["screening_score"]

    # 9. Innovation library.
    innovations = client.get("/api/innovations", params={"q": "模拟"}).json()["data"]
    assert innovations["total"] >= 1
    item = innovations["items"][0]
    assert item["paper"]["id"] == target["id"]
    updated = client.put(f"/api/innovations/{item['id']}", json={"note": "值得复现"})
    assert updated.json()["data"]["note"] == "值得复现"

    # 10. Task counters and review audit trail.
    task_detail = client.get(f"/api/search-tasks/{task_id}").json()["data"]
    counters = task_detail["task"]
    assert counters["discovered_count"] == 3
    assert counters["imported_count"] == 1
    assert counters["analyzed_count"] == 1
    assert counters["included_count"] == 1
    history = client.get(f"/api/review/history/{target['id']}").json()["data"]
    assert history["items"][0]["action"] == "include"
    assert history["items"][0]["note"]

    # 11. Restart persistence: data is in SQLite, independent from any process memory.
    session = SessionLocal()
    try:
        assert session.get(Paper, target["id"]).review_status == ReviewStatus.INCLUDED
        assert session.query(AiAnalysisResult).filter(AiAnalysisResult.paper_id == target["id"]).count() == 1
        assert session.query(InnovationItem).filter(InnovationItem.paper_id == target["id"]).count() >= 1
        assert session.query(PaperReview).filter(PaperReview.paper_id == target["id"]).count() == 1
        assert session.get(SearchTask, task_id).included_count == 1
    finally:
        session.close()


def test_review_undo_restores_previous_status(client, sample_ris: Path):
    response = client.post(
        "/api/search-tasks",
        json={"name": "撤销测试", "journal": "岩土力学", "start_date": "2023-01-01", "end_date": "2025-12-31"},
    )
    task_id = response.json()["data"]["task"]["id"]
    _import_sample(client, task_id, sample_ris)
    paper_id = client.get(f"/api/search-tasks/{task_id}/papers").json()["data"]["items"][0]["id"]

    client.post(f"/api/review/{paper_id}/action", json={"action": "defer", "note": "待复核"})
    assert client.get(f"/api/papers/{paper_id}").json()["data"]["review_status"] == "deferred"
    undo = client.post(f"/api/review/{paper_id}/undo")
    assert undo.status_code == 200
    restored = client.get(f"/api/papers/{paper_id}").json()["data"]["review_status"]
    assert restored in ("pending_fulltext", "pending_ai", "pending_review", "analyzing")


def test_pdf_stream_endpoint(client, sample_ris: Path, sample_pdf: Path):
    response = client.post("/api/search-tasks", json={"name": "pdf测试", "journal": "岩土力学"})
    task_id = response.json()["data"]["task"]["id"]
    _import_sample(client, task_id, sample_ris)
    target = next(
        item
        for item in client.get(f"/api/search-tasks/{task_id}/papers").json()["data"]["items"]
        if "改进随机森林" in item["title"]
    )
    with sample_pdf.open("rb") as handle:
        client.post(
            "/api/imports/files",
            files={"files": (sample_pdf.name, handle, "application/pdf")},
            data={"task_id": task_id},
        )
    stream = client.get(f"/api/papers/{target['id']}/file")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("application/pdf")
    assert len(stream.content) > 1000


def test_undo_refreshes_task_counters(client, sample_ris: Path):
    response = client.post(
        "/api/search-tasks",
        json={"name": "计数回归", "journal": "岩土力学", "start_date": "2023-01-01", "end_date": "2025-12-31"},
    )
    task_id = response.json()["data"]["task"]["id"]
    _import_sample(client, task_id, sample_ris)
    paper_id = client.get(f"/api/search-tasks/{task_id}/papers").json()["data"]["items"][0]["id"]
    client.post(f"/api/review/{paper_id}/action", json={"action": "include"})
    assert client.get(f"/api/search-tasks/{task_id}").json()["data"]["task"]["included_count"] == 1
    undo = client.post(f"/api/review/{paper_id}/undo", json={})
    assert undo.status_code == 200
    # Regression: SessionLocal has autoflush=False; counters must still see the new status.
    task = client.get(f"/api/search-tasks/{task_id}").json()["data"]["task"]
    assert task["included_count"] == 0
