"""Deterministic redaction for snapshot data."""

from __future__ import annotations

import hashlib
import re
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PiiRedactor:
    def __init__(self) -> None:
        self.email_map: dict[str, str] = {}

    def _stable_suffix(self, value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]

    def redact_scalar(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        if EMAIL_RE.match(value):
            if value not in self.email_map:
                idx = len(self.email_map) + 1
                self.email_map[value] = f"user-{idx}@doubleagent.local"
            return self.email_map[value]

        lower = value.lower()
        if any(token in lower for token in ["token", "secret", "password", "apikey", "api_key"]):
            return f"redacted-{self._stable_suffix(value)}"

        return value

    def redact_obj(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.redact_obj(v) for v in obj]
        return self.redact_scalar(obj)

    def redact_resources(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.redact_obj(item) for item in items]

