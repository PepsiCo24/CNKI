"""Application configuration and filesystem layout.

All runtime data lives under a single user-configurable root (CNKI_DATA_DIR), so the
whole library can be moved or backed up as one folder.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CNKI_",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CNKI Scholar AI"
    api_prefix: str = "/api"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    database_url: str | None = None
    key_file: Path | None = None

    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    worker_concurrency: int = 2
    ai_concurrency: int = 1

    @field_validator("data_dir", "key_file", mode="before")
    @classmethod
    def _expand_path(cls, value):
        if value is None or value == "":
            return None
        return Path(os.path.expanduser(str(value))).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "database" / "cnki_scholar.db"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.db_path}"

    @property
    def resolved_key_file(self) -> Path:
        return self.key_file or (self.data_dir / "keys" / "master.key")

    @property
    def papers_dir(self) -> Path:
        return self.data_dir / "papers"

    @property
    def imports_dir(self) -> Path:
        return self.data_dir / "imports"

    @property
    def metadata_dir(self) -> Path:
        return self.data_dir / "metadata"

    @property
    def ai_results_dir(self) -> Path:
        return self.data_dir / "ai_results"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "temp"

    def ensure_dirs(self) -> None:
        for directory in (
            self.data_dir,
            self.data_dir / "database",
            self.papers_dir,
            self.imports_dir,
            self.metadata_dir,
            self.ai_results_dir,
            self.exports_dir,
            self.logs_dir,
            self.backups_dir,
            self.temp_dir,
            self.resolved_key_file.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
