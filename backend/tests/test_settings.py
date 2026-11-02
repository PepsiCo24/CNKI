"""Settings storage and secret handling tests."""
from __future__ import annotations

from app.database.init_db import DEFAULT_SETTINGS
from app.models import AppSetting
from app.services.settings_service import SettingsService


def test_secret_is_encrypted_and_masked(db):
    service = SettingsService(db)
    service.set("ai.api_key", "sk-test-secret-123456")
    row = db.query(AppSetting).filter(AppSetting.key == "ai.api_key").one()
    assert "sk-test-secret-123456" not in row.value
    assert service.get("ai.api_key") == "sk-test-secret-123456"
    public = service.public_settings()
    assert "sk-test-secret-123456" not in str(public)
    assert public["ai.api_key_set"] is True
    assert "********" in public["ai.api_key"]


def test_masked_secret_is_not_overwritten(db):
    service = SettingsService(db)
    service.set("ai.api_key", "sk-original-secret")
    service.set("ai.api_key", "sk-********abcd")
    assert service.get("ai.api_key") == "sk-original-secret"


def test_unknown_setting_rejected(db):
    service = SettingsService(db)
    try:
        service.set("evil.key", "x")
    except ValueError as exc:
        assert "未知设置项" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown key should be rejected")


def test_defaults_and_theme_roundtrip(db):
    service = SettingsService(db)
    assert service.get("ai.provider") == DEFAULT_SETTINGS["ai.provider"]
    service.set("app.theme", "dark")
    assert service.get("app.theme") == "dark"
    service.set("review.shortcuts", {"include": "Alt+I", "exclude": "Alt+X", "defer": "Alt+D"})
    shortcuts = service.get("review.shortcuts")
    assert shortcuts["include"] == "Alt+I"
