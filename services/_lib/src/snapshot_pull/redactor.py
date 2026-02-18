"""PII redaction engine for snapshot data.

Runs during ``snapshot pull`` *before* writing to disk, so no real PII
is ever persisted.  Provides deterministic replacement (same input →
same output) so referential integrity is preserved across resources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RedactionPolicy:
    email: str = "anonymize"
    name: str = "anonymize"
    avatar_url: str = "placeholder"
    phone: str = "remove"
    custom_patterns: list[tuple[str, str]] = field(default_factory=list)


_PLACEHOLDER_AVATAR = "https://doubleagent.local/avatar/placeholder.png"

_EMAIL_FIELDS = {"email", "user_email", "author_email", "committer_email", "notification_email"}
_NAME_FIELDS = {"name", "real_name", "display_name", "full_name", "author_name", "committer_name"}
_AVATAR_FIELDS = {"avatar_url", "image_url", "icon_url", "profile_image"}
_PHONE_FIELDS = {"phone", "phone_number", "mobile"}


class PiiRedactor:
    def __init__(self, policy: RedactionPolicy | None = None) -> None:
        self.policy = policy or RedactionPolicy()
        self._email_counter: dict[str, int] = {}
        self._name_counter: dict[str, int] = {}
        self._next_user_id = 0

    def redact_resources(self, resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for resource in resources:
            self._redact_dict(resource)
        return resources

    def _redact_dict(self, d: dict[str, Any]) -> None:
        for key, value in list(d.items()):
            if isinstance(value, dict):
                self._redact_dict(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._redact_dict(item)
            elif isinstance(value, str):
                d[key] = self._redact_field(key.lower(), value)

    def _redact_field(self, field_name: str, value: str) -> str:
        if field_name in _EMAIL_FIELDS or "@" in value:
            if self.policy.email == "remove":
                return ""
            return self._anonymize_email(value)

        if field_name in _NAME_FIELDS:
            if self.policy.name == "remove":
                return ""
            return self._anonymize_name(value)

        if field_name in _AVATAR_FIELDS:
            if self.policy.avatar_url == "remove":
                return ""
            return _PLACEHOLDER_AVATAR

        if field_name in _PHONE_FIELDS:
            return ""

        for pattern, replacement in self.policy.custom_patterns:
            value = re.sub(pattern, replacement, value)

        return value

    def _anonymize_email(self, email: str) -> str:
        if email not in self._email_counter:
            self._next_user_id += 1
            self._email_counter[email] = self._next_user_id
        uid = self._email_counter[email]
        return f"user-{uid}@doubleagent.local"

    def _anonymize_name(self, name: str) -> str:
        if not name or name.strip() == "":
            return name
        if name not in self._name_counter:
            self._next_user_id += 1
            self._name_counter[name] = self._next_user_id
        uid = self._name_counter[name]
        return f"User {uid}"
