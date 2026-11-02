"""Non-sensitive settings persisted in SQLite, secrets encrypted at rest."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotConfiguredError
from app.core.secrets import MASK, SecretStore, get_secret_store, mask_secret
from app.core.utils import utcnow
from app.database.init_db import DEFAULT_SETTINGS
from app.models import AppSetting

SECRET_KEYS = {
    "ai.api_key": "ai.api_key",
    "cnki.authorized_api_key": "cnki.authorized_api_key",
}

AI_PRESETS = [
    {
        "id": "mock",
        "label": "离线演示模型（Mock）",
        "kind": "mock",
        "base_url": "",
        "default_model": "deterministic-mock-v1",
        "note": "不联网，生成明确标注为模拟的分析，用于验收流程与断网演示。",
    },
    {
        "id": "openai",
        "label": "OpenAI / 兼容接口",
        "kind": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "note": "标准 /chat/completions 接口。",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "kind": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "note": "OpenAI 兼容接口，支持 deepseek-reasoner。",
    },
    {
        "id": "qwen",
        "label": "通义千问（DashScope 兼容模式）",
        "kind": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "note": "使用 DashScope 的 OpenAI 兼容端点。",
    },
    {
        "id": "ollama",
        "label": "Ollama 本地模型",
        "kind": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "default_model": "qwen2.5:7b",
        "note": "本机运行，无需 API Key，断网可用。",
    },
    {
        "id": "custom",
        "label": "自定义 OpenAI 兼容服务",
        "kind": "openai_compatible",
        "base_url": "",
        "default_model": "",
        "note": "填写自建或第三方兼容网关的 Base URL。",
    },
]

ALLOWED_KEYS = set(DEFAULT_SETTINGS) | {
    "ai.api_key",
    "cnki.authorized_api_key",
    "ai.prompt_template_id",
    "data.root_dir",
    "app.last_index_rebuild",
    "cnki.account_username",
    "cnki.account_institution",
    "cnki.account_note",
    "cnki.auto_import_downloads",
}


@dataclass
class AiConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    temperature: float
    max_tokens: int
    timeout: int
    max_input_chars: int
    concurrency: int
    reasoning_effort: str = ""
    cost_input_per_1k: float = 0.0
    cost_output_per_1k: float = 0.0


class SettingsService:
    def __init__(self, db: Session, secret_store: SecretStore | None = None):
        self.db = db
        self.secret_store = secret_store or get_secret_store()

    # ------------------------------------------------------------------ storage
    def _row(self, key: str) -> AppSetting | None:
        return self.db.query(AppSetting).filter(AppSetting.key == key).first()

    def get(self, key: str, default: Any = None) -> Any:
        row = self._row(key)
        if row is None:
            return DEFAULT_SETTINGS.get(key, default)
        if key in SECRET_KEYS:
            if not row.value:
                return ""
            try:
                return self.secret_store.decrypt(row.value)
            except ValueError:
                return ""
        try:
            return json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return row.value

    def set(self, key: str, value: Any, *, commit: bool = True) -> None:
        if key not in ALLOWED_KEYS:
            raise ValueError(f"未知设置项: {key}")
        row = self._row(key)
        is_secret = key in SECRET_KEYS
        if is_secret:
            if value in (None, "", MASK) or (isinstance(value, str) and "********" in value):
                return
            stored = self.secret_store.encrypt(str(value))
        else:
            stored = json.dumps(value, ensure_ascii=False)
        if row is None:
            row = AppSetting(key=key, value=stored, is_secret=is_secret, updated_at=utcnow())
            self.db.add(row)
        else:
            row.value = stored
            row.is_secret = is_secret
            row.updated_at = utcnow()
        if commit:
            self.db.commit()

    def set_many(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value, commit=False)
        self.db.commit()

    # ------------------------------------------------------------------ public view
    def public_settings(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, default in DEFAULT_SETTINGS.items():
            result[key] = self.get(key, default)
        for key in SECRET_KEYS:
            raw = self.get(key, "")
            result[key] = mask_secret(raw) if raw else ""
            result[f"{key}_set"] = bool(raw)
        prompt_id = self.get("ai.prompt_template_id", "")
        result["ai.prompt_template_id"] = prompt_id
        result["data.root_dir"] = str(get_settings().data_dir)
        if result.get("ai.provider") == "mock":
            result["ai.model"] = "deterministic-mock-v1"
            result["ai.base_url"] = ""
        return result

    # ------------------------------------------------------------------ AI config
    def ai_config(self) -> AiConfig:
        provider = str(self.get("ai.provider", "mock"))
        base_url = str(self.get("ai.base_url", "")).strip()
        model = str(self.get("ai.model", "")).strip()
        api_key = str(self.get("ai.api_key", "")).strip()
        if provider == "mock":
            base_url = ""
            model = "deterministic-mock-v1"
        elif provider == "ollama":
            base_url = base_url or "http://127.0.0.1:11434"
            model = model or "qwen2.5:7b"
        else:
            if not base_url or not model:
                raise NotConfiguredError("AI 未配置：请在设置中心填写 Base URL 与 Model ID")
            if not api_key:
                raise NotConfiguredError("AI 未配置：请填写 API Key（本地模型可切换 Ollama）")
        return AiConfig(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            temperature=float(self.get("ai.temperature", 0.2)),
            max_tokens=int(self.get("ai.max_tokens", 4096)),
            timeout=int(self.get("ai.timeout", 120)),
            max_input_chars=int(self.get("ai.max_input_chars", 60000)),
            concurrency=max(1, int(self.get("ai.concurrency", 1))),
            reasoning_effort=str(self.get("ai.reasoning_effort", "")),
            cost_input_per_1k=float(self.get("ai.cost_input_per_1k", 0.0)),
            cost_output_per_1k=float(self.get("ai.cost_output_per_1k", 0.0)),
        )

    def is_ai_configured(self) -> bool:
        try:
            self.ai_config()
            return True
        except NotConfiguredError:
            return False


def get_settings_service(db: Session) -> SettingsService:
    return SettingsService(db)
