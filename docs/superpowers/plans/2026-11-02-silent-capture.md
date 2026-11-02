# Silent Capture + Local One-Click Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本机实现合规的「静默抓取」会话（等待导入目录 → 按来源/时间过滤入库 → 排队 AI → 待人工审核），并强化 Windows/macOS 一键启动后推送到 `PepsiCo24/CNKI`。

**Architecture:** 新增 `CaptureSession` 编排实体与 `capture_service`；通过后台任务 `silent_capture` 等待本地导入目录出现文件后调用现有 `queue_folder_scan`/`scan_directory`，再用任务文献的 AI 状态聚合进度。前端任务详情以进度面板替换打断式交互。不登录知网、无头抓取或未授权接口。

**Tech Stack:** FastAPI、SQLAlchemy 2、SQLite、现有 BackgroundJob 队列、Vue 3 + Element Plus、bash/bat 启动脚本、pytest + TestClient。

**Spec:** `docs/superpowers/specs/2026-11-02-silent-capture-design.md`

## Global Constraints

- 合规：只处理本地导入目录中的官方导出题录/全文；禁止自动登录知网、无头抓取、私有接口
- 正式入库必须人工审核；静默抓取最高到 `ready_for_review`
- 绑定本机 `127.0.0.1`；不部署 GitHub Pages 业务站
- 密钥与 `.env` / `data/` 不进 Git
- 空导入目录必须停留在 `waiting_files`，不得立即以「完成 0 条」结束
- 同一 `task_id` 同时最多一个活跃会话（`waiting`/`running`）
- 默认等待超时 `1800` 秒
- 测试命令在仓库根目录：`.venv/bin/pytest backend/tests/<file>.py -v`（或已 activate 的 `pytest`）

---

## File Structure

| 路径 | 职责 |
| --- | --- |
| `backend/app/models/task.py` | 新增 `CaptureSession` 模型 |
| `backend/app/models/__init__.py` | 导出 `CaptureSession` |
| `backend/app/core/constants.py` | `JobType.SILENT_CAPTURE`、`CaptureStage` |
| `backend/app/services/capture_service.py` | 校验、启动/取消/刷新会话、阶段文案 |
| `backend/app/services/serializers.py` | `capture_session_out` |
| `backend/app/api/search_tasks.py` | `POST/GET .../silent-capture`、`POST .../cancel` |
| `backend/app/tasks/handlers.py` | `handle_silent_capture` |
| `backend/app/tasks/runner.py` | 分发 `silent_capture` |
| `backend/app/database/init_db.py` | 可选默认设置 `cnki.capture_wait_timeout` |
| `backend/alembic/versions/<rev>_capture_sessions.py` | 迁移（与 `create_all` 并存） |
| `backend/tests/test_silent_capture.py` | API/服务测试 |
| `frontend/src/types/index.ts` | `CaptureSession` 类型 |
| `frontend/src/api/index.ts` | `tasksApi.silentCapture*` |
| `frontend/src/pages/SearchTasksPage.vue` | 静默抓取 CTA + 进度面板 |
| `frontend/src/pages/SettingsPage.vue` | 账号配置状态提示（若需微调） |
| `scripts/start.sh` / `scripts/start.bat` | 一键启动强化 |
| `README.md` | 静默抓取与启动说明 |
| 远程 | 推送到 `https://github.com/PepsiCo24/CNKI` |

---

### Task 1: CaptureSession 模型与常量

**Files:**
- Modify: `backend/app/core/constants.py`
- Modify: `backend/app/models/task.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/b1c2d3e4f5a6_capture_sessions.py`
- Test: `backend/tests/test_silent_capture.py`

**Interfaces:**
- Produces: `CaptureStage` StrEnum；`JobType.SILENT_CAPTURE = "silent_capture"`；模型 `CaptureSession`（表 `capture_sessions`）
- Consumes: 现有 `IdMixin`、`TimestampMixin`、`JobStatus`、`SearchTask`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_silent_capture.py
from app.core.constants import CaptureStage, JobType
from app.models import CaptureSession


def test_capture_session_model_persists(db):
    assert JobType.SILENT_CAPTURE == "silent_capture"
    assert CaptureStage.WAITING_FILES == "waiting_files"
    row = CaptureSession(
        task_id="missing-will-fk-fail-or-use-real",
        status="running",
        stage=CaptureStage.WAITING_FILES,
        progress=0,
        counts={"discovered": 0, "imported": 0, "skipped": 0, "duplicates": 0, "failed": 0, "ai_queued": 0, "ai_completed": 0},
        wait_timeout_seconds=1800,
        message="等待导入目录中的题录或全文",
    )
    # Real test below creates a SearchTask first — this step only asserts enums exist.
    assert CaptureStage.READY_FOR_REVIEW == "ready_for_review"
```

先写完整可运行版（创建真实任务）：

```python
def test_capture_session_model_persists(client, db):
    from app.core.constants import CaptureStage, JobType
    from app.models import CaptureSession, SearchTask
    from app.core.utils import utcnow

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest backend/tests/test_silent_capture.py::test_capture_session_model_persists -v`  
Expected: FAIL（`CaptureSession` / `CaptureStage` / `SILENT_CAPTURE` 未定义）

- [ ] **Step 3: Add constants**

In `backend/app/core/constants.py`, append to `JobType`:

```python
SILENT_CAPTURE = "silent_capture"
```

Add:

```python
class CaptureStage(StrEnum):
    WAITING_FILES = "waiting_files"
    SCANNING = "scanning"
    IMPORTING = "importing"
    AI_QUEUED = "ai_queued"
    READY_FOR_REVIEW = "ready_for_review"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

- [ ] **Step 4: Add model**

Append to `backend/app/models/task.py`:

```python
class CaptureSession(IdMixin, TimestampMixin, Base):
    """Orchestrates silent local ingest for one search task (no CNKI login)."""

    __tablename__ = "capture_sessions"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("search_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.RUNNING, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting_files", index=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    import_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    background_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    wait_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_capture_task_status", "task_id", "status"),)
```

Export in `backend/app/models/__init__.py` (`CaptureSession` in import + `__all__`).

- [ ] **Step 5: Alembic migration**

Create `backend/alembic/versions/b1c2d3e4f5a6_capture_sessions.py` with `revises` = current head `de955d910552`，`upgrade` 创建 `capture_sessions` 表（列与模型一致），`downgrade` drop。

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/pytest backend/tests/test_silent_capture.py::test_capture_session_model_persists -v`  
Expected: PASS（`init_db`/`create_all` 会建表）

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/constants.py backend/app/models/task.py backend/app/models/__init__.py \
  backend/alembic/versions/b1c2d3e4f5a6_capture_sessions.py backend/tests/test_silent_capture.py
git commit -m "feat: add CaptureSession model for silent local ingest"
```

---

### Task 2: capture_service 前置校验与启动/取消

**Files:**
- Create: `backend/app/services/capture_service.py`
- Modify: `backend/app/services/serializers.py`
- Modify: `backend/app/database/init_db.py`（可选键 `cnki.capture_wait_timeout`: 1800）
- Test: `backend/tests/test_silent_capture.py`

**Interfaces:**
- Consumes: `CaptureSession`、`SettingsService`、`get_settings`、`enqueue_job`、`ValidationAppError`、`NotFoundError`
- Produces:
  - `ACTIVE_CAPTURE_STATUSES = {"running"}` 且 stage 非终态；终态 stage ∈ `{ready_for_review,timed_out,cancelled,failed}`
  - `validate_silent_capture_prerequisites(db, task) -> Path`（返回导入目录）
  - `start_silent_capture(db, task_id: str) -> dict`
  - `get_silent_capture(db, task_id: str) -> dict`
  - `cancel_silent_capture(db, task_id: str) -> dict`
  - `capture_session_out(session: CaptureSession) -> dict`
  - `DEFAULT_COUNTS` dict

- [ ] **Step 1: Write failing tests**

```python
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
```

（此时 API 尚不存在 → FAIL。）

- [ ] **Step 2: Run tests — expect fail**

Run: `.venv/bin/pytest backend/tests/test_silent_capture.py -v`  
Expected: API 404 或 import 错误

- [ ] **Step 3: Implement serializer + service (without API yet — tests will still fail on API; add unit-style service tests if preferred)**

Add service tests that call service directly so Task 2 can pass before Task 3 API:

```python
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
```

`capture_service.py` 核心逻辑：

```python
DEFAULT_COUNTS = {
    "discovered": 0,
    "imported": 0,
    "skipped": 0,
    "duplicates": 0,
    "failed": 0,
    "ai_queued": 0,
    "ai_completed": 0,
}
TERMINAL_STAGES = {
    CaptureStage.READY_FOR_REVIEW,
    CaptureStage.TIMED_OUT,
    CaptureStage.CANCELLED,
    CaptureStage.FAILED,
}
STAGE_MESSAGES = {
    CaptureStage.WAITING_FILES: "等待导入目录中的题录或全文",
    CaptureStage.SCANNING: "正在扫描导入目录",
    CaptureStage.IMPORTING: "正在按来源与时间过滤并写入任务库",
    CaptureStage.AI_QUEUED: "已排队 AI 创新点分析",
    CaptureStage.READY_FOR_REVIEW: "本轮导入完成，可前往人工审核",
    CaptureStage.TIMED_OUT: "等待超时，已保留已导入数据",
    CaptureStage.CANCELLED: "已取消静默抓取",
    CaptureStage.FAILED: "静默抓取失败",
}

def resolve_import_dir(db) -> Path:
    settings = get_settings()
    raw = SettingsService(db).get("data.import_dir") or ""
    path = Path(str(raw)).expanduser() if str(raw).strip() else Path(settings.imports_dir)
    return path

def validate_silent_capture_prerequisites(db, task: SearchTask) -> Path:
    username = str(SettingsService(db).get("cnki.account_username") or "").strip()
    if not username:
        raise ValidationAppError("请先在设置 → 知网接入中填写账号标识")
    if not (task.journal or "").strip():
        raise ValidationAppError("请先设置文献来源（期刊名称）")
    if not task.start_date or not task.end_date:
        raise ValidationAppError("请先设置发表时间起止日期")
    if task.start_date > task.end_date:
        raise ValidationAppError("开始日期不能晚于结束日期")
    path = resolve_import_dir(db)
    if not path.exists() or not path.is_dir():
        raise ValidationAppError(f"导入目录不存在或不可用：{path}")
    return path

def get_active_session(db, task_id: str) -> CaptureSession | None:
    rows = (
        db.query(CaptureSession)
        .filter(CaptureSession.task_id == task_id, CaptureSession.status == JobStatus.RUNNING)
        .order_by(CaptureSession.created_at.desc())
        .all()
    )
    for row in rows:
        if row.stage not in TERMINAL_STAGES:
            return row
    return None

def start_silent_capture(db, task_id: str) -> dict:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    existing = get_active_session(db, task_id)
    if existing:
        return serializers.capture_session_out(existing)
    validate_silent_capture_prerequisites(db, task)
    timeout = int(SettingsService(db).get("cnki.capture_wait_timeout") or 1800)
    SettingsService(db).set("data.watch_enabled", True)
    session = CaptureSession(
        task_id=task.id,
        status=JobStatus.RUNNING,
        stage=CaptureStage.WAITING_FILES,
        progress=5.0,
        counts=dict(DEFAULT_COUNTS),
        wait_timeout_seconds=timeout,
        message=STAGE_MESSAGES[CaptureStage.WAITING_FILES],
        started_at=utcnow(),
    )
    db.add(session)
    db.flush()
    bg = enqueue_job(
        db,
        JobType.SILENT_CAPTURE,
        {"session_id": session.id, "task_id": task.id},
        dedupe_key=f"silent_capture:{task.id}",
        priority=3,
        commit=False,
    )
    session.background_job_id = bg.id
    task.status = TaskStatus.RUNNING
    task.started_at = task.started_at or utcnow()
    task.last_run_at = utcnow()
    log_event(db, "启动静默抓取（本地导入目录）", task_id=task.id, detail={"session_id": session.id}, commit=False)
    db.commit()
    db.refresh(session)
    return serializers.capture_session_out(session)
```

`cancel_silent_capture`：找到活跃会话 → `stage=cancelled`、`status=completed` 或 `cancelled`、`finished_at`；若有 `background_job_id` 按现有方式请求取消；任务状态回到 `awaiting_import`。

`serializers.capture_session_out`：返回 `id, task_id, status, stage, progress, counts, message, error_message, import_job_id, wait_timeout_seconds, started_at, finished_at, updated_at`。

Seed `cnki.capture_wait_timeout: 1800` in `DEFAULT_SETTINGS`.

- [ ] **Step 4: Run service tests**

Run: `.venv/bin/pytest backend/tests/test_silent_capture.py::test_validate_and_start_service -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/capture_service.py backend/app/services/serializers.py \
  backend/app/database/init_db.py backend/tests/test_silent_capture.py
git commit -m "feat: add silent capture service with prerequisite checks"
```

---

### Task 3: silent_capture 后台处理与进度聚合

**Files:**
- Modify: `backend/app/tasks/handlers.py`
- Modify: `backend/app/tasks/runner.py`
- Modify: `backend/app/services/capture_service.py`（`refresh_session_progress`、`tick_wait_or_scan`）
- Test: `backend/tests/test_silent_capture.py`

**Interfaces:**
- Consumes: `queue_folder_scan`、`scan_directory`、`list_watchable_files`、`ImportJob`、`Paper`/`SearchTaskPaper`/`AiStatus`
- Produces: `handlers.handle_silent_capture(job_id, payload)`；会话在无文件时轮询等待，有文件则 `queue_folder_scan` 并轮询 ImportJob，完成后聚合 AI 计数并进入 `ready_for_review`

- [ ] **Step 1: Write failing test — empty dir stays waiting; file triggers import**

```python
def test_silent_capture_waits_then_imports_ris(client, db, tmp_path, sample_ris):
    import shutil
    import time
    from app.services.settings_service import SettingsService
    from app.services import capture_service
    from app.tasks import handlers
    from app.models import CaptureSession, BackgroundJob

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

    # Simulate one wait tick with empty dir: still waiting
    handlers.handle_silent_capture_tick_for_tests(session.id, max_wait_loops=1, sleep_s=0)
    db.refresh(session)
    assert session.stage == "waiting_files"

    shutil.copy(sample_ris, incoming / sample_ris.name)
    handlers.handle_silent_capture(bg.id, {"session_id": session.id, "task_id": task["id"]})
    db.refresh(session)
    assert session.stage in ("ai_queued", "ready_for_review", "importing")
    assert session.counts.get("imported", 0) + session.counts.get("discovered", 0) >= 0
    # After full handler with file present, imported or skipped should reflect RIS rows
    assert session.stage in ("ready_for_review", "ai_queued")
```

为实现可测性，handler 内 wait 循环使用短 sleep，并检查 `cancel_requested` 与超时；测试可直接调用 `run_silent_capture_session(db, session_id)` 同步函数（handler 包一层）。

推荐同步核心：

```python
def run_silent_capture_session(db, session_id: str, *, sleep_fn=time.sleep) -> None:
    session = db.get(CaptureSession, session_id)
    ...
    deadline = session.started_at.timestamp() + session.wait_timeout_seconds
    import_dir = resolve_import_dir(db)
    while True:
        db.refresh(session)
        if session.stage == CaptureStage.CANCELLED:
            return
        bg = db.get(BackgroundJob, session.background_job_id) if session.background_job_id else None
        if bg and bg.cancel_requested:
            _finish(session, CaptureStage.CANCELLED); db.commit(); raise JobCancelled()
        files = list_watchable_files(import_dir)
        if files:
            break
        if time.time() > deadline:
            _finish(session, CaptureStage.TIMED_OUT); db.commit(); return
        session.progress = min(14.0, session.progress + 0.5)
        session.message = STAGE_MESSAGES[CaptureStage.WAITING_FILES]
        db.commit()
        sleep_fn(2)

    session.stage = CaptureStage.SCANNING
    session.progress = 20
    db.commit()
    job = queue_folder_scan(db, directory=str(import_dir), task_id=session.task_id, origin="silent_capture")
    session.import_job_id = job["id"]
    session.stage = CaptureStage.IMPORTING
    session.progress = 35
    db.commit()
    # Poll ImportJob until terminal
    ...
    # Aggregate AI counts for task papers; if any queued/running -> ai_queued else ready_for_review
```

注意：`queue_folder_scan` 会再 enqueue `scan_folder`；在无 worker 的测试中需**直接** `scan_directory(db, import_job_id, directory, task_id)`，或在 `run_silent_capture_session` 检测环境/参数 `inline_scan=True`。

测试友好签名：

```python
def run_silent_capture_session(db, session_id: str, *, sleep_fn=time.sleep, inline_scan=False) -> None:
```

当 `inline_scan=True`（测试默认 True）：创建 ImportJob 后直接 `scan_directory(...)`，不依赖 worker。  
生产 handler：`inline_scan=False`，enqueue 后轮询 ImportJob；若长时间 pending，可 fallback inline 一次——**YAGNI：生产依赖 worker，测试用 inline_scan=True**。

- [ ] **Step 2: Run test — expect fail**

- [ ] **Step 3: Implement handler + runner branch**

In `runner.py` `_execute`:

```python
elif job_type == JobType.SILENT_CAPTURE:
    await asyncio.to_thread(handlers.handle_silent_capture, job_id, payload)
```

`handle_silent_capture(job_id, payload)` 打开 Session，调用 `run_silent_capture_session(..., inline_scan=False)`；轮询 ImportJob 时若 status 仍 pending 超过 N 秒，可在同线程调用 `scan_directory`（因测试客户端无 worker）。为让本机无单独触发也稳健：**生产也在 silent_capture handler 内直接 `scan_directory`**（仍写入 ImportJob 行以复用进度字段），不再二次 enqueue。这样与现有 `queue_folder_scan` 二选一：

最终选定（写进实现）：`run_silent_capture_session` **创建 ImportJob 行后直接调用 `scan_directory`**，不调用 `queue_folder_scan`（避免双重任务）。进度从 ImportJob.processed/total 映射到 35–75%。

- [ ] **Step 4: Filter / AI aggregation assertions**

Add test that out-of-range RIS entries are skipped (reuse sample or craft minimal RIS). After scan, `ready_for_review` and task counters refresh via existing `refresh_counters`.

- [ ] **Step 5: Tests pass + commit**

```bash
git add backend/app/services/capture_service.py backend/app/tasks/handlers.py backend/app/tasks/runner.py \
  backend/tests/test_silent_capture.py
git commit -m "feat: run silent capture wait-scan-import pipeline in worker"
```

---

### Task 4: HTTP API 端点

**Files:**
- Modify: `backend/app/api/search_tasks.py`
- Test: `backend/tests/test_silent_capture.py`（启用 Task 2 中的 client 测试）

**Interfaces:**
- Produces:
  - `POST /api/search-tasks/{task_id}/silent-capture` → `{ session: capture_session_out }`
  - `GET /api/search-tasks/{task_id}/silent-capture` → 活跃或最近一次会话；无则 404
  - `POST /api/search-tasks/{task_id}/silent-capture/cancel`

- [ ] **Step 1: Keep/enable API tests from Task 2; add get/cancel**

```python
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
```

- [ ] **Step 2: Run — fail on missing routes**

- [ ] **Step 3: Wire routes**

```python
@router.post("/{task_id}/silent-capture")
def start_silent_capture_endpoint(task_id: str, db: Session = Depends(get_db)):
    session = capture_service.start_silent_capture(db, task_id)
    return ok(session, message="已启动静默抓取")

@router.get("/{task_id}/silent-capture")
def get_silent_capture_endpoint(task_id: str, db: Session = Depends(get_db)):
    return ok(capture_service.get_silent_capture(db, task_id))

@router.post("/{task_id}/silent-capture/cancel")
def cancel_silent_capture_endpoint(task_id: str, db: Session = Depends(get_db)):
    return ok(capture_service.cancel_silent_capture(db, task_id), message="已取消")
```

`get_silent_capture`：优先活跃会话，否则最近一条，都没有则 `NotFoundError("没有静默抓取会话")`。

- [ ] **Step 4: Tests pass + commit**

```bash
git add backend/app/api/search_tasks.py backend/tests/test_silent_capture.py
git commit -m "feat: expose silent-capture HTTP API on search tasks"
```

---

### Task 5: 前端静默抓取进度 UI

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/pages/SearchTasksPage.vue`
- Modify: `frontend/src/pages/SettingsPage.vue`（账号未配置时提示文案，轻量）

**Interfaces:**
- Consumes: 上述三个 API
- Produces: 主按钮「静默抓取」；进度面板绑定 `stage/progress/counts/message`；1.5s 轮询直至终态

- [ ] **Step 1: Types + API client**

```ts
export interface CaptureCounts {
  discovered: number
  imported: number
  skipped: number
  duplicates: number
  failed: number
  ai_queued: number
  ai_completed: number
}

export interface CaptureSession {
  id: string
  task_id: string
  status: string
  stage: string
  progress: number
  counts: CaptureCounts
  message: string
  error_message: string
  wait_timeout_seconds: number
  started_at?: string | null
  finished_at?: string | null
}
```

```ts
// tasksApi 增加
silentCaptureStart: (id: string) => http.post<never, CaptureSession>(`/search-tasks/${id}/silent-capture`),
silentCaptureGet: (id: string) => http.get<never, CaptureSession>(`/search-tasks/${id}/silent-capture`),
silentCaptureCancel: (id: string) => http.post<never, CaptureSession>(`/search-tasks/${id}/silent-capture/cancel`),
```

注意：若 `http` 客户端已解包 `data`，类型为 `CaptureSession`；若返回整包，按现有 `tasksApi.get` 风格对齐。

- [ ] **Step 2: SearchTasksPage 行为**

- 将原「抓取入库（下载目录）」主路径改为「静默抓取」`type="primary"`
- `captureSession` ref + `capturePolling`；点击后 `silentCaptureStart`，开始 `setInterval` 1.5s `silentCaptureGet`
- 面板：`el-progress` + stage 文案 + counts 微标；取消按钮调用 cancel
- 终态 `ready_for_review`：`ElMessage.success` + 可选 `router.push` 审核页
- 保留「导入官方题录」为次要；条件单区保留「打开知网」链接（非必经弹窗）
- 前置：若设置里无账号，按钮 click 时提示去设置（可用 `settingsApi` 读 `cnki.account_username`）

- [ ] **Step 3: Manual smoke（dev）**

Run: `./scripts/dev.sh` 或已有后端 + `cd frontend && npm run dev`  
Expected: 创建任务 → 设置账号与导入目录 → 静默抓取见等待 → 拷贝 `examples/sample_metadata.ris` 到导入目录 → 进度前进

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/index.ts \
  frontend/src/pages/SearchTasksPage.vue frontend/src/pages/SettingsPage.vue
git commit -m "feat: add silent capture progress UI on search tasks"
```

---

### Task 6: 一键启动脚本与 README

**Files:**
- Modify: `scripts/start.sh`
- Modify: `scripts/start.bat`
- Create: `start.command`（可选，调用 `scripts/start.sh` 并 `OPEN_BROWSER=1`）
- Modify: `README.md`

- [ ] **Step 1: Strengthen start.sh**

- 默认 `OPEN_BROWSER="${OPEN_BROWSER:-1}"`（或文档明确需手动设 1；为实现「一键」建议默认打开浏览器）
- 打印：数据目录、导入目录提示、Ctrl+C 停止
- 若 `setup` 失败给出 Python/Node 检查提示

- [ ] **Step 2: Align start.bat**

- 与 sh 相同端口/提示
- 失败 `pause` 保留
- 确保 `cd` 到仓库根

- [ ] **Step 3: README 小节**

在「快速开始」与「知网接入」增加：

1. 设置 → 知网接入：账号标识 + 导入目录  
2. 检索任务：来源 + 时间段 → 静默抓取  
3. 将官网导出文件放入导入目录  
4. 进度完成后人工审核入库  
5. Windows: `scripts\start.bat`；macOS: `./scripts/start.sh`

- [ ] **Step 4: Commit**

```bash
git add scripts/start.sh scripts/start.bat start.command README.md
git commit -m "docs: clarify one-click local launch and silent capture usage"
```

---

### Task 7: 全量回归、首次完整提交与推送 GitHub

**Files:**
- 仓库根：纳入此前未跟踪的应用代码（设计 commit 后仍大量 untracked）
- Remote: `https://github.com/PepsiCo24/CNKI.git`

- [ ] **Step 1: Run full backend tests**

Run: `.venv/bin/pytest backend/tests -q`  
Expected: 全部 PASS

- [ ] **Step 2: Ensure .gitignore 排除密钥与 data**

确认 `.env`、`data/`、`.venv`、`node_modules`、`frontend/dist` 被忽略。

- [ ] **Step 3: Stage project (exclude secrets) and commit if needed**

```bash
git add .env.example .gitignore README.md backend docs examples frontend pyproject.toml scripts start.command
git status
git commit -m "chore: add CNKI Scholar AI codebase with silent capture"
```

若文件已在先前 task commits 中，本步仅补漏。

- [ ] **Step 4: Push**

```bash
git remote add origin https://github.com/PepsiCo24/CNKI.git
git push -u origin main
```

若远程已有 README，先 `git pull --rebase origin main` 再 push。需要用户 GitHub 认证（`gh auth` / credential）。失败则停下报告，不强制 `--force`。

- [ ] **Step 5: Verify remote**

Run: `gh repo view PepsiCo24/CNKI` 或打开仓库 URL  
Expected: 最新 commit 可见；README 含一键启动说明

---

## Self-Review (plan vs spec)

| Spec 要求 | Task |
| --- | --- |
| 账号标识 + 来源 + 时间段前置校验 | Task 2 |
| 静默等待空目录 / 超时 / 取消 | Task 3–4 |
| 扫描过滤写入任务库 | Task 3（`scan_directory` + task_id） |
| AI 排队不自动正式入库 | Task 3 阶段 `ready_for_review` |
| 进度 API + 前端进度条 | Task 4–5 |
| start.sh / start.bat | Task 6 |
| 推送 PepsiCo24/CNKI；非 Pages | Task 7 |
| 禁止无头/自动登录 | Global Constraints + 无相关代码任务 |

无 TBD 占位；`CaptureSession` / API / `inline_scan` 命名在任务间一致。
