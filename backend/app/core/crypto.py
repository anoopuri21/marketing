"""Encryption at rest for integration credentials (OAuth tokens, service-account JSON, webhook secrets).

* Fernet (AES-128-CBC + HMAC-SHA256) via `cryptography`, which python-jose already pulls in.
* The key is derived from `SECRET_KEY` with scrypt unless an explicit `ENCRYPTION_KEY` (urlsafe base64,
  32 bytes) is configured – so a fresh install is encrypted out of the box and rotating `SECRET_KEY`
  without `ENCRYPTION_KEY` invalidates stored credentials (documented in .env.example).
* Values are prefixed with `enc:v1:` so plaintext rows written before this feature keep working and
  are transparently upgraded the next time they are saved.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
_SALT = b"rankpilot-integration-secrets"


def _derive_key(secret: str) -> bytes:
    raw = hashlib.scrypt(secret.encode("utf-8"), salt=_SALT, n=2**14, r=8, p=1, dklen=32)
    return base64.urlsafe_b64encode(raw)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode("utf-8"))
    return Fernet(_derive_key(settings.secret_key))


def encrypt_text(plain: str) -> str:
    return PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    """Decrypt a `PREFIX`ed value; plaintext (legacy) values are returned unchanged."""
    if not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:  # key rotated without ENCRYPTION_KEY, or tampered row
        raise ValueError("Stored credentials cannot be decrypted with the current SECRET_KEY/ENCRYPTION_KEY") from exc


def encrypt_json(data: dict[str, Any] | None) -> str | None:
    if data is None:
        return None
    return encrypt_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))


def decrypt_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):  # legacy plain JSON column value
        return value
    try:
        text = decrypt_text(value)
    except ValueError:
        log.error("integration credentials undecryptable – returning empty config")
        return {}
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)
