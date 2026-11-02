"""Shared API dependencies and upload helpers."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import ValidationAppError
from app.core.utils import safe_filename

MAX_UPLOAD_BYTES = 300 * 1024 * 1024


async def save_upload(upload: UploadFile, *, prefix: str = "") -> Path:
    settings = get_settings()
    original = safe_filename(upload.filename or "upload.bin", max_bytes=140)
    target = settings.temp_dir / f"{prefix}{uuid.uuid4().hex[:8]}_{original}"
    size = 0
    with target.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                handle.close()
                target.unlink(missing_ok=True)
                raise ValidationAppError("文件超过 300MB 上限")
            handle.write(chunk)
    if size == 0:
        target.unlink(missing_ok=True)
        raise ValidationAppError("上传文件为空")
    await upload.close()
    return target


def clean_dir_input(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip().strip('"').strip("'")
    if not value:
        return None
    if "\x00" in value:
        raise ValidationAppError("目录路径包含非法字符")
    return value
