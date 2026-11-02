"""Local encrypted secret store.

A Fernet key is generated once at ``data/keys/master.key`` with 0600 permissions.
Secrets (LLM API keys) are stored encrypted in the settings table and never returned
to the frontend in clear text; the API only exposes a masked hint. This avoids binding
credentials to a cloud service and works on Windows/macOS/Linux.
"""
from __future__ import annotations

import os
import stat
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
MASK = "********"


class SecretStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.key_path = self.settings.resolved_key_file
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            data = self.key_path.read_bytes().strip()
            if data:
                return data
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - best effort on exotic filesystems
            logger.warning("Could not tighten permissions on key file")
        return key

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            raise ValueError("无法解密本地密钥，密钥文件可能已更换") from None


@lru_cache
def get_secret_store() -> SecretStore:
    return SecretStore()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return MASK
    return f"{value[:3]}{MASK}{value[-4:]}"
