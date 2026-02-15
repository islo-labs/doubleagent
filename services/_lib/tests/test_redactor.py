"""Unit tests for PII redactor."""

from doubleagent_sdk.redactor import PiiRedactor, RedactionPolicy


def test_email_anonymization():
    redactor = PiiRedactor()
    resources = [{"email": "alice@example.com", "id": 1}]
    result = redactor.redact_resources(resources)
    assert result[0]["email"] == "user-1@doubleagent.local"


def test_email_deterministic():
    """Same email maps to same anonymized value."""
    redactor = PiiRedactor()
    resources = [
        {"email": "alice@example.com"},
        {"email": "bob@example.com"},
        {"email": "alice@example.com"},  # repeat
    ]
    redactor.redact_resources(resources)
    assert resources[0]["email"] == resources[2]["email"]
    assert resources[0]["email"] != resources[1]["email"]


def test_name_anonymization():
    redactor = PiiRedactor()
    resources = [{"name": "Alice Smith", "id": 1}]
    redactor.redact_resources(resources)
    assert resources[0]["name"].startswith("User ")


def test_avatar_placeholder():
    redactor = PiiRedactor()
    resources = [{"avatar_url": "https://avatars.github.com/u/123"}]
    redactor.redact_resources(resources)
    assert "doubleagent.local" in resources[0]["avatar_url"]


def test_phone_removed():
    redactor = PiiRedactor()
    resources = [{"phone": "+1-555-0100"}]
    redactor.redact_resources(resources)
    assert resources[0]["phone"] == ""


def test_nested_dict_redacted():
    redactor = PiiRedactor()
    resources = [{"owner": {"email": "admin@corp.com", "login": "admin"}}]
    redactor.redact_resources(resources)
    assert resources[0]["owner"]["email"].endswith("@doubleagent.local")


def test_custom_pattern():
    policy = RedactionPolicy(custom_patterns=[(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED-SSN]")])
    redactor = PiiRedactor(policy=policy)
    resources = [{"bio": "SSN is 123-45-6789"}]
    redactor.redact_resources(resources)
    assert "123-45-6789" not in resources[0]["bio"]
    assert "[REDACTED-SSN]" in resources[0]["bio"]


def test_non_pii_fields_untouched():
    redactor = PiiRedactor()
    resources = [{"id": 42, "description": "A cool project", "language": "Python"}]
    redactor.redact_resources(resources)
    assert resources[0]["description"] == "A cool project"
    assert resources[0]["language"] == "Python"
