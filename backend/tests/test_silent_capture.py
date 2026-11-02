from datetime import date

import pytest

from app.core.constants import CaptureStage, JobType
from app.core.utils import utcnow
from app.models import CaptureSession, SearchTask


def test_capture_session_model_persists(client, db):
    assert JobType.SILENT_CAPTURE == "silent_capture"
    task = SearchTask(name="t", journal="岩土力学", keywords="", start_date=None, end_date=None)
    db.add(task)
    db.flush()
    session = CaptureSession(
        task_id=task.id,
        status="running",
        stage=CaptureStage.WAITING_FILES,
        progress=5.0,
        counts={"discovered": 0, "imported": 0, "skipped": 0, "duplicates": 0, "failed": 0, "ai_queued": 0, "ai_completed": 0},
        wait_timeout_seconds=1800,
        message="等待导入目录中的题录或全文",
        started_at=utcnow(),
    )
    db.add(session)
    db.commit()
    loaded = db.get(CaptureSession, session.id)
    assert loaded is not None
    assert loaded.stage == "waiting_files"


def _create_task(client, **overrides):
    payload = {
        "name": "边坡任务",
        "journal": "岩土力学",
        "keywords": "",
        "match_mode": "fuzzy",
        "start_date": "2023-01-01",
        "end_date": "2025-12-31",
        "sort_by": "publication_date",
        "import_mode": "folder_watch",
        "paper_type": "journal",
    }
    payload.update(overrides)
    res = client.post("/api/search-tasks", json=payload)
    assert res.status_code == 200
    return res.json()["data"]["task"]


def test_silent_capture_requires_account(client, db):
    task = _create_task(client)
    res = client.post(f"/api/search-tasks/{task['id']}/silent-capture")
    assert res.status_code in (400, 422)
    body = res.json()
    assert "账号" in body.get("message", "") or "账号" in str(body)


def test_silent_capture_starts_waiting_when_ready(client, db, tmp_path):
    from app.services.settings_service import SettingsService
    from app.core.config import get_settings

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "demo-user")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    task = _create_task(client)
    res = client.post(f"/api/search-tasks/{task['id']}/silent-capture")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["stage"] == "waiting_files"
    assert data["progress"] < 20


def test_silent_capture_api_get_and_cancel(client, db, tmp_path):
    from app.services.settings_service import SettingsService

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    task = _create_task(client)
    started = client.post(f"/api/search-tasks/{task['id']}/silent-capture")
    assert started.status_code == 200
    got = client.get(f"/api/search-tasks/{task['id']}/silent-capture")
    assert got.status_code == 200
    assert got.json()["data"]["stage"] == "waiting_files"
    cancelled = client.post(f"/api/search-tasks/{task['id']}/silent-capture/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["stage"] == "cancelled"


def test_validate_and_start_service(client, db, tmp_path):
    from datetime import date
    from app.models import SearchTask
    from app.services.settings_service import SettingsService
    from app.services import capture_service
    from app.core.errors import ValidationAppError
    import pytest

    task = SearchTask(
        name="t",
        journal="岩土力学",
        keywords="",
        start_date=date(2023, 1, 1),
        end_date=date(2025, 12, 31),
        import_mode="folder_watch",
    )
    db.add(task)
    db.commit()
    with pytest.raises(ValidationAppError):
        capture_service.start_silent_capture(db, task.id)

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    out = capture_service.start_silent_capture(db, task.id)
    assert out["stage"] == "waiting_files"
    again = capture_service.start_silent_capture(db, task.id)
    assert again["id"] == out["id"]


def _ready_task(db, tmp_path, **overrides):
    from app.services.settings_service import SettingsService

    incoming = tmp_path / "imports"
    incoming.mkdir(exist_ok=True)
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    fields = {
        "name": "t",
        "journal": "岩土力学",
        "keywords": "",
        "start_date": date(2023, 1, 1),
        "end_date": date(2025, 12, 31),
        "import_mode": "folder_watch",
    }
    fields.update(overrides)
    task = SearchTask(**fields)
    db.add(task)
    db.commit()
    return task, incoming


def test_start_enqueues_silent_capture_job(db, tmp_path):
    from app.models import BackgroundJob
    from app.services import capture_service
    from app.services.settings_service import SettingsService

    task, _ = _ready_task(db, tmp_path)
    assert not SettingsService(db).get("data.watch_enabled")
    out = capture_service.start_silent_capture(db, task.id)
    assert not SettingsService(db).get("data.watch_enabled")
    assert out["stage"] == "waiting_files"
    assert out["progress"] < 20
    assert out["wait_timeout_seconds"] == 1800
    assert out["counts"]["imported"] == 0
    session = db.get(CaptureSession, out["id"])
    assert session is not None
    assert session.background_job_id
    job = db.get(BackgroundJob, session.background_job_id)
    assert job is not None
    assert job.job_type == JobType.SILENT_CAPTURE
    assert job.task_id == task.id
    assert job.payload["session_id"] == session.id
    assert job.payload["task_id"] == task.id


def test_validate_prerequisites_messages(db, tmp_path):
    from app.core.errors import ValidationAppError
    from app.services import capture_service
    from app.services.settings_service import SettingsService

    incoming = tmp_path / "imports"
    incoming.mkdir()
    task = SearchTask(
        name="t",
        journal="",
        keywords="",
        start_date=date(2023, 1, 1),
        end_date=date(2025, 12, 31),
    )
    db.add(task)
    db.commit()

    with pytest.raises(ValidationAppError) as missing_account:
        capture_service.validate_silent_capture_prerequisites(db, task)
    assert "账号" in str(missing_account.value)

    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    with pytest.raises(ValidationAppError) as missing_journal:
        capture_service.validate_silent_capture_prerequisites(db, task)
    assert "文献来源" in str(missing_journal.value)

    task.journal = "岩土力学"
    task.start_date = None
    with pytest.raises(ValidationAppError) as missing_dates:
        capture_service.validate_silent_capture_prerequisites(db, task)
    assert "发表时间" in str(missing_dates.value)

    task.start_date = date(2026, 1, 1)
    task.end_date = date(2025, 1, 1)
    with pytest.raises(ValidationAppError) as inverted:
        capture_service.validate_silent_capture_prerequisites(db, task)
    assert "开始日期" in str(inverted.value)

    task.start_date = date(2023, 1, 1)
    task.end_date = date(2025, 12, 31)
    SettingsService(db).set("data.import_dir", str(tmp_path / "missing-dir"))
    db.commit()
    with pytest.raises(ValidationAppError) as missing_dir:
        capture_service.validate_silent_capture_prerequisites(db, task)
    assert "导入目录" in str(missing_dir.value)


def test_get_and_cancel_silent_capture(db, tmp_path):
    from app.core.constants import JobStatus, TaskStatus
    from app.core.errors import NotFoundError
    from app.models import BackgroundJob
    from app.services import capture_service

    with pytest.raises(NotFoundError) as missing_task:
        capture_service.get_silent_capture(db, "missing-task")
    assert "检索任务不存在" in str(missing_task.value)

    task, _ = _ready_task(db, tmp_path)
    with pytest.raises(NotFoundError) as missing_session:
        capture_service.get_silent_capture(db, task.id)
    assert "没有静默抓取会话" in str(missing_session.value)

    started = capture_service.start_silent_capture(db, task.id)
    got = capture_service.get_silent_capture(db, task.id)
    assert got["id"] == started["id"]
    assert got["stage"] == "waiting_files"

    with pytest.raises(NotFoundError):
        capture_service.cancel_silent_capture(db, "missing-task")

    cancelled = capture_service.cancel_silent_capture(db, task.id)
    assert cancelled["id"] == started["id"]
    assert cancelled["stage"] == "cancelled"
    assert cancelled["status"] in ("cancelled", "completed")
    assert cancelled["finished_at"]
    db.refresh(task)
    assert task.status == TaskStatus.AWAITING_IMPORT
    session = db.get(CaptureSession, started["id"])
    job = db.get(BackgroundJob, session.background_job_id)
    assert job is not None
    assert job.status in (JobStatus.CANCELLED, JobStatus.CANCELLING)

    latest = capture_service.get_silent_capture(db, task.id)
    assert latest["id"] == started["id"]
    assert latest["stage"] == "cancelled"

    with pytest.raises(NotFoundError):
        capture_service.cancel_silent_capture(db, task.id)

    restarted = capture_service.start_silent_capture(db, task.id)
    assert restarted["id"] != started["id"]
    assert restarted["stage"] == "waiting_files"


def test_capture_session_out_and_default_timeout(db, tmp_path):
    from app.database.init_db import DEFAULT_SETTINGS
    from app.services import capture_service
    from app.services import serializers

    assert DEFAULT_SETTINGS["cnki.capture_wait_timeout"] == 1800
    task, _ = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    expected = {
        "id",
        "task_id",
        "status",
        "stage",
        "progress",
        "counts",
        "message",
        "error_message",
        "import_job_id",
        "wait_timeout_seconds",
        "started_at",
        "finished_at",
        "updated_at",
    }
    assert expected <= set(out)
    session = db.get(CaptureSession, out["id"])
    serialized = serializers.capture_session_out(session)
    assert serialized["id"] == session.id
    assert serialized["task_id"] == task.id
    assert serialized["message"] == "等待导入目录中的题录或全文"
    assert capture_service.DEFAULT_COUNTS == {
        "discovered": 0,
        "imported": 0,
        "skipped": 0,
        "duplicates": 0,
        "failed": 0,
        "ai_queued": 0,
        "ai_completed": 0,
    }
    assert capture_service.ACTIVE_CAPTURE_STATUSES == {"running"}


def test_silent_capture_waits_then_imports_ris(client, db, tmp_path, sample_ris):
    import shutil

    from app.models import BackgroundJob
    from app.services import capture_service
    from app.services.settings_service import SettingsService
    from app.tasks import handlers

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    SettingsService(db).set("cnki.capture_wait_timeout", 5)
    db.commit()
    task = _create_task(client)
    out = capture_service.start_silent_capture(db, task["id"])
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)

    handlers.handle_silent_capture_tick_for_tests(session.id, max_wait_loops=1, sleep_s=0)
    db.refresh(session)
    assert session.stage == "waiting_files"

    shutil.copy(sample_ris, incoming / sample_ris.name)
    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task["id"]})
    db.refresh(session)
    assert session.stage in ("ai_queued", "ready_for_review", "importing")
    assert session.counts.get("imported", 0) + session.counts.get("discovered", 0) >= 0
    assert session.stage in ("ready_for_review", "ai_queued")


def test_import_progress_maps_processed_total_to_35_75():
    from app.services.capture_service import map_import_progress

    assert map_import_progress(0, 4) == 35.0
    assert map_import_progress(2, 4) == 55.0
    assert map_import_progress(4, 4) == 75.0
    assert map_import_progress(0, 0) == 75.0


def test_silent_capture_skips_out_of_range_and_refreshes_counters(client, db, tmp_path, sample_ris):
    import shutil

    from app.core.constants import ReviewStatus
    from app.models import BackgroundJob, ImportJob, Paper
    from app.services import capture_service
    from app.services.settings_service import SettingsService
    from app.tasks import handlers

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    SettingsService(db).set("cnki.capture_wait_timeout", 5)
    db.commit()
    task = _create_task(client)
    out = capture_service.start_silent_capture(db, task["id"])
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_ris, incoming / sample_ris.name)

    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task["id"]})
    db.refresh(session)
    task_row = db.get(SearchTask, task["id"])
    papers = db.query(Paper).all()

    assert session.stage == "ready_for_review"
    assert session.progress == 100
    assert session.counts["imported"] == 3
    assert session.counts["skipped"] == 2
    assert session.counts["discovered"] == 3
    assert session.counts["ai_queued"] == 0
    assert session.counts["failed"] == 0
    assert task_row.discovered_count == 3
    assert task_row.included_count == 0
    assert len(papers) == 3
    assert all(paper.review_status != ReviewStatus.INCLUDED for paper in papers)
    import_job = db.get(ImportJob, session.import_job_id)
    assert import_job is not None
    assert import_job.status == "completed"
    assert import_job.detail["skipped"] == 2
    scan_jobs = db.query(BackgroundJob).filter(BackgroundJob.job_type == JobType.SCAN_FOLDER).all()
    assert scan_jobs == []


def test_silent_capture_empty_dir_times_out(db, tmp_path):
    from datetime import timedelta

    from app.core.constants import TaskStatus
    from app.core.utils import utcnow
    from app.models import BackgroundJob, Paper
    from app.services import capture_service
    from app.tasks import handlers

    task, _incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    session.started_at = utcnow() - timedelta(seconds=10)
    session.wait_timeout_seconds = 5
    db.commit()
    bg = db.get(BackgroundJob, session.background_job_id)

    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task.id})
    db.refresh(session)
    db.refresh(task)
    assert session.stage == "timed_out"
    assert session.finished_at is not None
    assert task.status == TaskStatus.AWAITING_IMPORT
    assert db.query(Paper).count() == 0


def test_silent_capture_cancel_skips_import(db, tmp_path, sample_ris):
    import shutil

    from app.models import BackgroundJob, Paper
    from app.services import capture_service
    from app.tasks import handlers

    task, incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_ris, incoming / sample_ris.name)
    bg.cancel_requested = 1
    db.commit()

    with pytest.raises(handlers.JobCancelled):
        handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task.id})
    db.refresh(session)
    assert session.stage == "cancelled"
    assert db.query(Paper).count() == 0


def test_silent_capture_ai_queued_does_not_include(client, db, tmp_path, sample_ris):
    import shutil

    from app.core.constants import AiStatus, ReviewStatus
    from app.core.utils import utcnow
    from app.models import BackgroundJob, Paper, SearchTaskPaper
    from app.services import capture_service
    from app.services.settings_service import SettingsService
    from app.tasks import handlers

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    task = _create_task(client)
    queued = Paper(title="已排队但未入库", ai_status=AiStatus.QUEUED, review_status=ReviewStatus.PENDING_AI)
    db.add(queued)
    db.flush()
    db.add(SearchTaskPaper(task_id=task["id"], paper_id=queued.id, added_at=utcnow()))
    db.commit()
    out = capture_service.start_silent_capture(db, task["id"])
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_ris, incoming / sample_ris.name)

    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task["id"]})
    db.refresh(session)
    papers = db.query(Paper).all()
    assert session.stage == "ai_queued"
    assert session.counts["ai_queued"] == 1
    assert session.counts["ai_completed"] == 0
    assert 75 <= session.progress < 100
    assert all(paper.review_status != ReviewStatus.INCLUDED for paper in papers)


@pytest.mark.asyncio
async def test_runner_dispatches_silent_capture(client, db, tmp_path, sample_ris):
    import shutil

    from app.models import BackgroundJob
    from app.services import capture_service
    from app.services.settings_service import SettingsService
    from app.tasks.runner import runner

    incoming = tmp_path / "imports"
    incoming.mkdir()
    SettingsService(db).set("cnki.account_username", "u1")
    SettingsService(db).set("data.import_dir", str(incoming))
    db.commit()
    task = _create_task(client)
    out = capture_service.start_silent_capture(db, task["id"])
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_ris, incoming / sample_ris.name)

    await runner._execute(bg.id)
    db.refresh(session)
    db.refresh(bg)
    assert session.stage == "ready_for_review"
    assert bg.status == "completed"


def test_get_silent_capture_maps_in_progress_scan(db, tmp_path):
    from app.core.constants import JobStatus
    from app.models import BackgroundJob, ImportJob
    from app.services import capture_service

    task, incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    job = ImportJob(
        job_type="folder_scan",
        status=JobStatus.RUNNING,
        source_path=str(incoming),
        task_id=task.id,
        total=4,
        processed=2,
        detail={"origin": "silent_capture", "skipped": 0},
    )
    db.add(job)
    db.flush()
    session.import_job_id = job.id
    session.stage = CaptureStage.IMPORTING
    session.progress = 35
    db.commit()

    got = capture_service.get_silent_capture(db, task.id)
    assert got["stage"] == "importing"
    assert got["status"] == "running"
    assert got["progress"] == 55.0
    assert got["finished_at"] is None

    again = capture_service.start_silent_capture(db, task.id)
    assert again["id"] == out["id"]
    assert again["stage"] == "importing"
    assert again["progress"] == 55.0
    assert db.query(BackgroundJob).filter(BackgroundJob.job_type == JobType.SCAN_FOLDER).count() == 0


def test_silent_capture_pdf_stays_ai_queued_until_parse_drains(db, tmp_path, sample_pdf):
    import shutil

    from app.core.constants import JobStatus, ReviewStatus
    from app.models import BackgroundJob, Paper
    from app.services import capture_service
    from app.tasks import handlers

    task, incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_pdf, incoming / sample_pdf.name)

    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task.id})
    db.refresh(session)
    papers = db.query(Paper).filter(Paper.is_deleted.is_(False)).all()
    parse_jobs = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.job_type == JobType.PARSE_PAPER, BackgroundJob.status == JobStatus.PENDING)
        .all()
    )

    assert papers
    assert session.stage == "ai_queued"
    assert session.status == "running"
    assert session.finished_at is None
    assert session.stage != "ready_for_review"
    assert parse_jobs
    assert all(paper.review_status != ReviewStatus.INCLUDED for paper in papers)
    assert db.query(BackgroundJob).filter(BackgroundJob.job_type == JobType.SCAN_FOLDER).count() == 0

    mid = capture_service.get_silent_capture(db, task.id)
    assert mid["stage"] == "ai_queued"
    assert mid["status"] == "running"
    assert mid["finished_at"] is None

    for job in parse_jobs:
        job.status = JobStatus.COMPLETED
    db.commit()
    drained = capture_service.get_silent_capture(db, task.id)
    assert drained["stage"] == "ready_for_review"
    assert drained["status"] == "completed"
    assert drained["finished_at"]
    papers = db.query(Paper).filter(Paper.is_deleted.is_(False)).all()
    assert all(paper.review_status != ReviewStatus.INCLUDED for paper in papers)


def test_silent_capture_cancel_during_scan_sticks(db, tmp_path, sample_ris, monkeypatch):
    import shutil

    from app.models import BackgroundJob
    from app.services import capture_service, import_service
    from app.tasks import handlers

    task, incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_ris, incoming / sample_ris.name)

    def scan_then_cancel(scan_db, import_job_id, directory, task_id):
        capture_service.cancel_silent_capture(scan_db, task_id)
        return import_service.scan_directory(scan_db, import_job_id, directory, task_id)

    monkeypatch.setattr(capture_service, "scan_directory", scan_then_cancel)
    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task.id})
    db.refresh(session)
    assert session.stage == "cancelled"
    assert session.status == "cancelled"
    assert session.finished_at is not None
    assert session.message == "已取消静默抓取"
    assert session.progress != 100

    latest = capture_service.get_silent_capture(db, task.id)
    assert latest["stage"] == "cancelled"
    assert latest["status"] == "cancelled"
    assert latest["finished_at"]


def test_task_cancel_stops_silent_capture(db, tmp_path, sample_ris):
    import shutil

    from app.core.constants import JobStatus, TaskStatus
    from app.models import BackgroundJob, Paper
    from app.services import capture_service
    from app.services.search_task_service import cancel_task
    from app.services.settings_service import SettingsService
    from app.tasks import handlers

    task, incoming = _ready_task(db, tmp_path)
    assert not SettingsService(db).get("data.watch_enabled")
    out = capture_service.start_silent_capture(db, task.id)
    assert not SettingsService(db).get("data.watch_enabled")
    session = db.get(CaptureSession, out["id"])
    job = db.get(BackgroundJob, session.background_job_id)
    assert job is not None
    assert job.task_id == task.id
    shutil.copy(sample_ris, incoming / sample_ris.name)

    cancel_task(db, task.id)
    db.refresh(session)
    db.refresh(job)
    db.refresh(task)
    assert task.status == TaskStatus.CANCELLED
    assert session.stage == "cancelled"
    assert session.status == "cancelled"
    assert job.cancel_requested
    assert job.status in (JobStatus.CANCELLED, JobStatus.CANCELLING)

    with pytest.raises(handlers.JobCancelled):
        handlers.handle_silent_capture(job.id, {"session_id": session.id, "task_id": task.id})
    db.refresh(task)
    db.refresh(session)
    assert task.status == TaskStatus.CANCELLED
    assert session.stage == "cancelled"
    assert db.query(Paper).count() == 0


def test_task_pause_stops_silent_capture(db, tmp_path):
    from app.core.constants import TaskStatus
    from app.models import BackgroundJob
    from app.services import capture_service
    from app.services.search_task_service import pause_task

    task, _incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    job = db.get(BackgroundJob, session.background_job_id)
    pause_task(db, task.id)
    db.refresh(session)
    db.refresh(job)
    db.refresh(task)
    assert task.status == TaskStatus.PAUSED
    assert session.stage == "cancelled"
    assert session.status == "cancelled"
    assert job is not None
    assert job.task_id == task.id
    assert job.status == "cancelled"
    assert job.cancel_requested


def test_wait_loop_stops_when_task_paused(db, tmp_path, sample_ris):
    import shutil

    from app.core.constants import TaskStatus
    from app.models import BackgroundJob, Paper
    from app.services import capture_service
    from app.tasks import handlers

    task, incoming = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    bg = db.get(BackgroundJob, session.background_job_id)
    shutil.copy(sample_ris, incoming / sample_ris.name)
    task.status = TaskStatus.PAUSED
    db.commit()

    with pytest.raises(handlers.JobCancelled):
        handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task.id})
    db.refresh(session)
    db.refresh(task)
    assert session.stage == "cancelled"
    assert session.status == "cancelled"
    assert task.status == TaskStatus.PAUSED
    assert db.query(Paper).count() == 0


def test_scan_and_post_scan_keep_cancelled_and_paused(db, tmp_path, sample_ris):
    import shutil

    from app.core.constants import JobStatus, TaskStatus
    from app.models import ImportJob
    from app.services import capture_service
    from app.services.import_service import scan_directory

    task, incoming = _ready_task(db, tmp_path)
    shutil.copy(sample_ris, incoming / sample_ris.name)
    task.status = TaskStatus.CANCELLED
    db.commit()
    cancelled_job = ImportJob(
        job_type="folder_scan",
        status=JobStatus.PENDING,
        source_path=str(incoming),
        task_id=task.id,
    )
    db.add(cancelled_job)
    db.commit()
    scan_directory(db, cancelled_job.id, str(incoming), task.id)
    db.refresh(task)
    assert task.status == TaskStatus.CANCELLED

    task.status = TaskStatus.PAUSED
    db.commit()
    paused_job = ImportJob(
        job_type="folder_scan",
        status=JobStatus.PENDING,
        source_path=str(incoming),
        task_id=task.id,
    )
    db.add(paused_job)
    db.commit()
    scan_directory(db, paused_job.id, str(incoming), task.id)
    db.refresh(task)
    assert task.status == TaskStatus.PAUSED

    out = capture_service.start_silent_capture(db, task.id)
    session = db.get(CaptureSession, out["id"])
    task.status = TaskStatus.PAUSED
    done = ImportJob(
        job_type="folder_scan",
        status=JobStatus.COMPLETED,
        source_path=str(incoming),
        task_id=task.id,
        total=1,
        processed=1,
        imported=1,
        detail={"skipped": 0},
    )
    db.add(done)
    db.flush()
    session.import_job_id = done.id
    session.stage = CaptureStage.IMPORTING
    db.commit()
    capture_service.refresh_session_progress(db, session)
    db.refresh(task)
    db.refresh(session)
    assert task.status == TaskStatus.PAUSED
    assert session.stage == "cancelled"
    assert session.status == "cancelled"


def test_start_does_not_enable_global_watch(db, tmp_path, monkeypatch):
    from app.services import capture_service, watch_service
    from app.services.settings_service import SettingsService

    def fail_start(self, directory=None):
        raise AssertionError("silent capture must not start the folder watcher")

    monkeypatch.setattr(watch_service.WatchService, "start", fail_start)
    task, _incoming = _ready_task(db, tmp_path)
    assert not SettingsService(db).get("data.watch_enabled")
    capture_service.start_silent_capture(db, task.id)
    assert SettingsService(db).get("data.watch_enabled") is False
