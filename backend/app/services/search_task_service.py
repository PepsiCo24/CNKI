"""Search task execution, pause/resume/cancel and retrieval-condition helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.adapters.cnki import get_adapter
from app.core.constants import JobStatus, TaskStatus
from app.core.errors import ConflictError, NotFoundError, PermissionRequiredError, ValidationAppError
from app.core.utils import utcnow
from app.models import BackgroundJob, SearchTask
from app.services import serializers
from app.services.import_service import queue_folder_scan
from app.services.log_service import log_event
from app.services.settings_service import SettingsService
from app.services.task_service import build_conditions_snapshot, refresh_counters, set_status

RUNNING_STATES = (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.AWAITING_IMPORT)


def retrieval_guide(db: Session, task: SearchTask) -> dict[str, Any]:
    settings = SettingsService(db)
    authorized_config = {
        "enabled": bool(settings.get("cnki.authorized_enabled", False)),
        "base_url": settings.get("cnki.authorized_base_url", ""),
        "permission_reference": settings.get("cnki.authorized_permission_reference", ""),
        "daily_limit": settings.get("cnki.authorized_daily_limit", 200),
    }
    adapter = get_adapter("CNKI", authorized_config)
    guide = adapter.retrieval_guide(task)
    guide["task_id"] = task.id
    guide["task_name"] = task.name
    guide["conditions"] = task.conditions_snapshot or build_conditions_snapshot(task)
    guide["import_modes"] = [
        {
            "id": "metadata_import",
            "label": "导入官方题录",
            "available": True,
            "description": "使用知网官方导出的 RIS/BibTeX/EndNote/CSV 文件。",
        },
        {
            "id": "folder_watch",
            "label": "本地全文接管",
            "available": True,
            "description": "监听导入目录，自动发现 PDF/CAJ 并归档。",
        },
        {
            "id": "authorized_api",
            "label": "授权数据接口",
            "available": bool(authorized_config["enabled"] and authorized_config["base_url"]),
            "description": "仅在取得明确许可并配置官方文档端点后可用；当前版本不内置未确认端点。",
        },
    ]
    guide["authorized_config"] = {
        "enabled": authorized_config["enabled"],
        "configured": bool(authorized_config["base_url"] and authorized_config["permission_reference"]),
    }
    return guide


def run_task(db: Session, task_id: str, mode: str | None = None) -> dict[str, Any]:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status == TaskStatus.RUNNING:
        raise ConflictError("任务正在执行中")
    chosen_mode = mode or task.import_mode
    task.conditions_snapshot = build_conditions_snapshot(task)
    task.status = TaskStatus.RUNNING
    task.started_at = utcnow()
    task.last_run_at = utcnow()
    task.error_message = ""
    db.commit()
    log_event(
        db,
        f"启动检索任务：{task.name}（模式：{chosen_mode}）",
        task_id=task.id,
        detail={"conditions": task.conditions_snapshot},
        commit=True,
    )
    try:
        if chosen_mode == "folder_watch":
            settings = SettingsService(db)
            directory = task.extra.get("directory") or settings.get("data.import_dir") or ""
            job = queue_folder_scan(db, directory=directory, task_id=task.id, origin="search_task")
            return {"task": serializers.task_out(task), "job": job, "guide": retrieval_guide(db, task)}
        if chosen_mode == "authorized_api":
            adapter = get_adapter("CNKI_AUTHORIZED", _authorized_config(db))
            adapter.search(task)
        task.status = TaskStatus.AWAITING_IMPORT
        db.commit()
        log_event(
            db,
            "已生成官方检索条件单，等待题录导入或本地全文接管",
            task_id=task.id,
            detail={"mode": chosen_mode},
            commit=True,
        )
        return {"task": serializers.task_out(task), "guide": retrieval_guide(db, task), "job": None}
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.error_message = str(exc)[:1000]
        db.commit()
        log_event(db, f"任务启动失败：{exc}", task_id=task.id, level="error", commit=True)
        raise


def pause_task(db: Session, task_id: str) -> dict[str, Any]:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING, TaskStatus.AWAITING_IMPORT):
        raise ValidationAppError("当前状态不能暂停")
    task.status = TaskStatus.PAUSED
    jobs = (
        db.query(BackgroundJob)
        .filter(BackgroundJob.task_id == task.id, BackgroundJob.status == JobStatus.PENDING)
        .all()
    )
    for job in jobs:
        job.status = JobStatus.CANCELLED
        job.finished_at = utcnow()
    db.commit()
    log_event(db, "任务已暂停", task_id=task.id, commit=True)
    return serializers.task_out(task)


def resume_task(db: Session, task_id: str) -> dict[str, Any]:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status != TaskStatus.PAUSED:
        raise ValidationAppError("只有已暂停的任务可以继续")
    return run_task(db, task_id)


def cancel_task(db: Session, task_id: str) -> dict[str, Any]:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status == TaskStatus.COMPLETED:
        raise ValidationAppError("已完成任务不能取消")
    task.status = TaskStatus.CANCELLED
    task.finished_at = utcnow()
    jobs = (
        db.query(BackgroundJob)
        .filter(
            BackgroundJob.task_id == task.id,
            BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .all()
    )
    for job in jobs:
        job.status = JobStatus.CANCELLED if job.status == JobStatus.PENDING else JobStatus.CANCELLING
        job.cancel_requested = 1
        job.finished_at = utcnow() if job.status == JobStatus.CANCELLED else None
    db.commit()
    log_event(db, "任务已取消", task_id=task.id, level="warning", commit=True)
    return serializers.task_out(task)


def retry_task(db: Session, task_id: str) -> dict[str, Any]:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.AWAITING_IMPORT):
        raise ValidationAppError("只有失败、取消或等待导入的任务可以重新执行")
    refresh_counters(db, task.id)
    db.commit()
    return run_task(db, task.id)


def update_task(db: Session, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = db.get(SearchTask, task_id)
    if not task:
        raise NotFoundError("检索任务不存在")
    if task.status == TaskStatus.RUNNING:
        raise ConflictError("任务执行中不能修改条件，请先暂停")
    for key, value in payload.items():
        if value is not None:
            setattr(task, key, value)
    task.conditions_snapshot = build_conditions_snapshot(task)
    db.commit()
    log_event(db, "任务条件已更新", task_id=task.id, detail=task.conditions_snapshot, commit=True)
    return serializers.task_out(task)


def _authorized_config(db: Session) -> dict:
    settings = SettingsService(db)
    return {
        "enabled": bool(settings.get("cnki.authorized_enabled", False)),
        "base_url": settings.get("cnki.authorized_base_url", ""),
        "permission_reference": settings.get("cnki.authorized_permission_reference", ""),
        "daily_limit": settings.get("cnki.authorized_daily_limit", 200),
        "api_key": settings.get("cnki.authorized_api_key", ""),
    }
