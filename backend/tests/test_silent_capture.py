from app.core.constants import CaptureStage, JobType
from app.models import CaptureSession, SearchTask
from app.core.utils import utcnow


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
