"""Custom SQLAlchemy column types."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Dialect
from sqlalchemy.types import Text, TypeDecorator

from app.core import crypto


class EncryptedJSON(TypeDecorator[dict[str, Any]]):
    """A dict column stored as Fernet-encrypted JSON text.

    Reads legacy rows transparently: plain JSON text (from the previous `JSON` column type) is
    decoded as-is and becomes encrypted the next time the row is written.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: dict[str, Any] | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return crypto.encrypt_json(dict(value))

    def process_result_value(self, value: str | None, dialect: Dialect) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        if crypto.is_encrypted(value):
            return crypto.decrypt_json(value)
        try:  # legacy plaintext JSON
            loaded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}
