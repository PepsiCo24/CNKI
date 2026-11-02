"""Settings, AI connection test, directory watch and maintenance."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.provider import LLMError, build_provider
from app.api.envelope import ok
from app.core.config import get_settings
from app.core.errors import ValidationAppError
from app.database.session import get_db
from app.schemas import AiTestRequest, SettingsUpdate
from app.services.settings_service import AI_PRESETS, SECRET_KEYS, SettingsService
from app.services.watch_service import get_watch_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_settings_api(db: Session = Depends(get_db)):
    service = SettingsService(db)
    public = service.public_settings()
    return ok(
        {
            "values": public,
            "providers": AI_PRESETS,
            "ai_configured": service.is_ai_configured(),
            "watcher": get_watch_service().status(),
        }
    )


@router.put("")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    service = SettingsService(db)
    values = dict(payload.values)
    # Ignore masked secrets sent back by the UI.
    for key in SECRET_KEYS:
        if key in values and isinstance(values[key], str) and "********" in values[key]:
            values.pop(key)
    if "data.import_dir" in values:
        raw = str(values["data.import_dir"]).strip()
        if raw:
            path = Path(raw).expanduser()
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValidationAppError(f"导入目录不可用：{exc}") from exc
            values["data.import_dir"] = str(path.resolve())
        else:
            values["data.import_dir"] = str(get_settings().imports_dir)
    watch_toggle = values.get("data.watch_enabled")
    try:
        service.set_many(values)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc
    watcher = get_watch_service()
    if watch_toggle is True:
        watcher.start(service.get("data.import_dir"))
    elif watch_toggle is False:
        watcher.stop()
    public = service.public_settings()
    return ok(
        {
            "values": public,
            "watcher": watcher.status(),
            "message": "设置已保存；并发数等后台参数会在数秒内生效",
        },
        message="设置已保存",
    )


@router.get("/providers")
def providers():
    return ok({"items": AI_PRESETS})


@router.post("/test-ai")
async def test_ai(payload: AiTestRequest, db: Session = Depends(get_db)):
    service = SettingsService(db)
    try:
        config = service.ai_config()
    except Exception as exc:
        if payload.provider == "mock":
            from app.services.settings_service import AiConfig

            config = AiConfig(
                provider="mock",
                base_url="",
                model="deterministic-mock-v1",
                api_key="",
                temperature=0.2,
                max_tokens=512,
                timeout=30,
                max_input_chars=6000,
                concurrency=1,
            )
        else:
            return ok({"ok": False, "error": str(exc)})
    if payload.provider:
        config.provider = payload.provider
    if payload.base_url is not None:
        config.base_url = payload.base_url
    if payload.model is not None:
        config.model = payload.model
    if config.provider != "mock" and not config.api_key and config.provider == "openai":
        return ok({"ok": False, "error": "缺少 API Key"})
    provider = build_provider(config)
    try:
        result = await provider.test_connection()
        return ok(result, message="连接成功")
    except LLMError as exc:
        return ok({"ok": False, "error": str(exc)})
    except Exception as exc:
        return ok({"ok": False, "error": f"连接失败：{exc}"})


@router.get("/storage")
def storage(db: Session = Depends(get_db)):
    settings = get_settings()
    usage = shutil.disk_usage(settings.data_dir)
    directories = {}
    for name, path in (
        ("papers", settings.papers_dir),
        ("imports", settings.imports_dir),
        ("metadata", settings.metadata_dir),
        ("ai_results", settings.ai_results_dir),
        ("exports", settings.exports_dir),
        ("backups", settings.backups_dir),
        ("logs", settings.logs_dir),
    ):
        total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        directories[name] = {"path": str(path), "bytes": total}
    return ok(
        {
            "data_dir": str(settings.data_dir),
            "database_bytes": settings.db_path.stat().st_size if settings.db_path.exists() else 0,
            "directories": directories,
            "disk_total": usage.total,
            "disk_free": usage.free,
        }
    )


@router.post("/watch/start")
def start_watch(db: Session = Depends(get_db)):
    service = SettingsService(db)
    directory = service.get("data.import_dir") or str(get_settings().imports_dir)
    result = get_watch_service().start(directory)
    service.set("data.watch_enabled", True)
    return ok(result, message="目录监听已启动")


@router.post("/watch/stop")
def stop_watch(db: Session = Depends(get_db)):
    result = get_watch_service().stop()
    SettingsService(db).set("data.watch_enabled", False)
    return ok(result, message="目录监听已停止")


@router.get("/watch/status")
def watch_status():
    return ok(get_watch_service().status())
