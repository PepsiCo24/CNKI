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


@pytest.mark.skip(reason="HTTP routes are added in Task 4")
def test_silent_capture_requires_account(client, db):
    task = _create_task(client)
    res = client.post(f"/api/search-tasks/{task['id']}/silent-capture")
    assert res.status_code in (400, 422)
    body = res.json()
    assert "账号" in body.get("message", "") or "账号" in str(body)


@pytest.mark.skip(reason="HTTP routes are added in Task 4")
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

    task, _ = _ready_task(db, tmp_path)
    out = capture_service.start_silent_capture(db, task.id)
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
