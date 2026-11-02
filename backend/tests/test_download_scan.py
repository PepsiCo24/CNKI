"""Official-download takeover: metadata and fulltext files in the watched folder."""
from __future__ import annotations

from pathlib import Path

from app.models import ImportJob, Paper, PaperFile, SearchTask
from app.services.import_service import scan_directory
from app.services.task_service import refresh_counters


def test_scan_imports_ris_and_skips_out_of_scope(client, sample_ris: Path, tmp_path: Path):
    task = client.post(
        "/api/search-tasks",
        json={
            "name": "下载目录接管",
            "journal": "岩土力学",
            "start_date": "2023-01-01",
            "end_date": "2025-12-31",
        },
    ).json()["data"]["task"]
    incoming = tmp_path / "downloads"
    incoming.mkdir()
    (incoming / "export.ris").write_bytes(sample_ris.read_bytes())

    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        job = ImportJob(job_type="folder_scan", status="pending", source_path=str(incoming), task_id=task["id"])
        db.add(job)
        db.commit()
        scan_directory(db, job.id, str(incoming), task["id"])
        db.refresh(job)
        assert job.status == "completed"
        assert job.total == 1
        assert job.imported == 3
        assert job.detail["skipped"] == 2
        assert db.query(Paper).count() == 3
        assert db.query(PaperFile).count() == 0
        refresh_counters(db, task["id"])
        assert db.get(SearchTask, task["id"]).discovered_count == 3
    finally:
        db.close()


def test_scan_can_disable_metadata_import(client, sample_ris: Path, tmp_path: Path):
    from app.database.session import SessionLocal
    from app.services.settings_service import SettingsService

    incoming = tmp_path / "downloads2"
    incoming.mkdir()
    (incoming / "export.ris").write_bytes(sample_ris.read_bytes())
    db = SessionLocal()
    try:
        SettingsService(db).set("cnki.auto_import_downloads", False)
        job = ImportJob(job_type="folder_scan", status="pending", source_path=str(incoming))
        db.add(job)
        db.commit()
        scan_directory(db, job.id, str(incoming), None)
        db.refresh(job)
        assert job.total == 0
        assert db.query(Paper).count() == 0
    finally:
        db.close()
