"""
pytest fixtures for Resend contract tests.

Uses the official resend Python SDK to verify the fake works correctly.
Supports two modes:
  - Fake mode: tests run against the DoubleAgent fake (DOUBLEAGENT_RESEND_URL is set)
  - Grounding mode: tests run against the real Resend API (RESEND_GROUNDING_TOKEN is set)

The SDK uses module-level variables for configuration:
  resend.api_key = "re_..."
  resend.api_url = "http://localhost:8080"
"""

import os
import time
from dataclasses import dataclass, field

import httpx
import pytest
import resend

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

FAKE_URL = os.environ.get("DOUBLEAGENT_RESEND_URL")
GROUNDING_TOKEN = os.environ.get("RESEND_GROUNDING_TOKEN")

# Rate-limit delay (seconds) between API calls in grounding mode.
# Resend allows 2 requests/second; 1s delay keeps us safely within limits.
GROUNDING_RATE_LIMIT_DELAY = 1.0


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "fake_only: mark test to run only against the fake (skip in grounding mode)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip fake_only tests when running in grounding mode."""
    if FAKE_URL is None:
        skip_fake_only = pytest.mark.skip(reason="Test only runs against the fake server")
        for item in items:
            if "fake_only" in item.keywords:
                item.add_marker(skip_fake_only)


# ---------------------------------------------------------------------------
# Fixtures: mode detection
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def grounding_mode() -> bool:
    """True when running against the real Resend API (no fake URL set)."""
    return FAKE_URL is None


@pytest.fixture(scope="session")
def fake_url() -> str | None:
    """The URL of the fake server, or None in grounding mode."""
    return FAKE_URL


# ---------------------------------------------------------------------------
# Fixtures: SDK client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def configure_resend_sdk(grounding_mode: bool) -> None:
    """
    Configure the resend SDK module-level variables.

    In fake mode, points the SDK at the fake server with a dummy API key.
    In grounding mode, uses the real API with the grounding token.

    The resend SDK uses module-level singletons (resend.api_key, resend.api_url)
    rather than a client class, so we set them once at session scope.
    """
    if grounding_mode:
        assert GROUNDING_TOKEN, (
            "RESEND_GROUNDING_TOKEN must be set when running in grounding mode"
        )
        resend.api_key = GROUNDING_TOKEN
        # api_url defaults to https://api.resend.com — no override needed
    else:
        resend.api_key = "re_fake_test_key_1234567890"
        resend.api_url = FAKE_URL


# ---------------------------------------------------------------------------
# Fixtures: reset (fake mode only)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_fake(grounding_mode: bool) -> None:
    """Reset fake state before each test. No-op in grounding mode."""
    if not grounding_mode:
        httpx.post(f"{FAKE_URL}/_doubleagent/reset")
    yield


# ---------------------------------------------------------------------------
# Fixtures: rate limiting
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def rate_limit_delay(grounding_mode: bool) -> None:
    """Add a small delay between tests in grounding mode to avoid rate limits."""
    yield
    if grounding_mode:
        time.sleep(GROUNDING_RATE_LIMIT_DELAY)


# ---------------------------------------------------------------------------
# ResourceTracker: cleanup for grounding mode
# ---------------------------------------------------------------------------

@dataclass
class ResourceTracker:
    """
    Tracks resources created during a test so they can be cleaned up afterward.

    In grounding mode, tests create real resources on the Resend API that must
    be deleted after the test to avoid polluting the account. Register each
    resource as it is created, and the fixture will delete them in reverse order.

    Usage in tests:
        def test_example(resource_tracker):
            result = resend.Domains.create({"name": "test.example.com"})
            resource_tracker.domain(result["id"])
            # ... test logic ...
            # cleanup happens automatically after test
    """

    _emails: list[str] = field(default_factory=list)
    _domains: list[str] = field(default_factory=list)
    _contacts: list[str] = field(default_factory=list)
    _templates: list[str] = field(default_factory=list)
    _api_keys: list[str] = field(default_factory=list)
    _webhooks: list[str] = field(default_factory=list)

    def email(self, email_id: str) -> None:
        """Register an email for tracking (emails cannot be deleted, but tracked for reference)."""
        self._emails.append(email_id)

    def domain(self, domain_id: str) -> None:
        """Register a domain for cleanup."""
        self._domains.append(domain_id)

    def contact(self, contact_id: str) -> None:
        """Register a contact for cleanup."""
        self._contacts.append(contact_id)

    def template(self, template_id: str) -> None:
        """Register a template for cleanup."""
        self._templates.append(template_id)

    def api_key(self, api_key_id: str) -> None:
        """Register an API key for cleanup."""
        self._api_keys.append(api_key_id)

    def webhook(self, webhook_id: str) -> None:
        """Register a webhook for cleanup."""
        self._webhooks.append(webhook_id)

    def cleanup(self) -> None:
        """
        Delete all tracked resources in reverse order.

        Order: webhooks -> api_keys -> templates -> contacts -> domains
        (emails are not deletable via the API, so they are skipped)
        """
        for webhook_id in reversed(self._webhooks):
            try:
                resend.Webhooks.remove(webhook_id)
            except Exception:
                pass

        for api_key_id in reversed(self._api_keys):
            try:
                resend.ApiKeys.remove(api_key_id)
            except Exception:
                pass

        for template_id in reversed(self._templates):
            try:
                resend.Templates.remove(template_id)
            except Exception:
                pass

        for contact_id in reversed(self._contacts):
            try:
                resend.Contacts.remove(id=contact_id)
            except Exception:
                pass

        for domain_id in reversed(self._domains):
            try:
                resend.Domains.remove(domain_id)
            except Exception:
                pass


@pytest.fixture
def resource_tracker(grounding_mode: bool) -> ResourceTracker:
    """
    Provide a ResourceTracker that cleans up after each test.

    In grounding mode: all tracked resources are deleted after the test.
    In fake mode: cleanup is skipped (the reset fixture handles it).
    """
    tracker = ResourceTracker()
    yield tracker
    if grounding_mode:
        tracker.cleanup()
