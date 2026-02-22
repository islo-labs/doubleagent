"""
pytest fixtures for Todoist contract tests.

Uses the official todoist-api-python SDK to verify the fake works correctly.
Supports two modes:
  - Fake mode: tests run against the DoubleAgent fake (DOUBLEAGENT_TODOIST_URL is set)
  - Grounding mode: tests run against the real Todoist API (TODOIST_GROUNDING_TOKEN is set)

The SDK has no constructor parameter for base URL override, so we monkey-patch
the endpoints module to redirect requests to the fake server.
"""

import os
import time
from dataclasses import dataclass, field

import httpx
import pytest
from todoist_api_python.api import TodoistAPI

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

FAKE_URL = os.environ.get("DOUBLEAGENT_TODOIST_URL")
GROUNDING_TOKEN = os.environ.get("TODOIST_GROUNDING_TOKEN")

# Rate-limit delay (seconds) between API calls in grounding mode
GROUNDING_RATE_LIMIT_DELAY = 0.5


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
    """True when running against the real Todoist API (no fake URL set)."""
    return FAKE_URL is None


@pytest.fixture(scope="session")
def fake_url() -> str | None:
    """The URL of the fake server, or None in grounding mode."""
    return FAKE_URL


# ---------------------------------------------------------------------------
# Fixtures: SDK client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def todoist_client(grounding_mode: bool) -> TodoistAPI:
    """
    Provide an official TodoistAPI client.

    In fake mode, monkey-patches the SDK endpoint module so all requests
    go to the fake server instead of api.todoist.com.

    In grounding mode, uses the real API with the grounding token.
    """
    if grounding_mode:
        assert GROUNDING_TOKEN, (
            "TODOIST_GROUNDING_TOKEN must be set when running in grounding mode"
        )
        return TodoistAPI(GROUNDING_TOKEN)
    else:
        # Monkey-patch SDK base URL to point at the fake server
        import todoist_api_python._core.endpoints as endpoints
        endpoints.API_URL = f"{FAKE_URL}/api/v1"
        return TodoistAPI("fake-token")


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

    In grounding mode, tests create real resources on the Todoist API that must
    be deleted after the test to avoid polluting the account. Register each
    resource as it is created, and the fixture will delete them in reverse order.

    Usage in tests:
        def test_example(todoist_client, resource_tracker):
            project = todoist_client.add_project(name="Test")
            resource_tracker.project(project.id)
            # ... test logic ...
            # cleanup happens automatically after test
    """

    _client: TodoistAPI
    _tasks: list[str] = field(default_factory=list)
    _projects: list[str] = field(default_factory=list)
    _sections: list[str] = field(default_factory=list)
    _comments: list[str] = field(default_factory=list)
    _labels: list[str] = field(default_factory=list)

    def task(self, task_id: str) -> None:
        """Register a task for cleanup."""
        self._tasks.append(task_id)

    def project(self, project_id: str) -> None:
        """Register a project for cleanup."""
        self._projects.append(project_id)

    def section(self, section_id: str) -> None:
        """Register a section for cleanup."""
        self._sections.append(section_id)

    def comment(self, comment_id: str) -> None:
        """Register a comment for cleanup."""
        self._comments.append(comment_id)

    def label(self, label_id: str) -> None:
        """Register a label for cleanup."""
        self._labels.append(label_id)

    def cleanup(self) -> None:
        """
        Delete all tracked resources in reverse order.

        Order: comments -> tasks -> sections -> labels -> projects
        (children before parents to avoid cascade issues)
        """
        for comment_id in reversed(self._comments):
            try:
                self._client.delete_comment(comment_id)
            except Exception:
                pass

        for task_id in reversed(self._tasks):
            try:
                self._client.delete_task(task_id)
            except Exception:
                pass

        for section_id in reversed(self._sections):
            try:
                self._client.delete_section(section_id)
            except Exception:
                pass

        for label_id in reversed(self._labels):
            try:
                self._client.delete_label(label_id)
            except Exception:
                pass

        for project_id in reversed(self._projects):
            try:
                self._client.delete_project(project_id)
            except Exception:
                pass


@pytest.fixture
def resource_tracker(todoist_client: TodoistAPI, grounding_mode: bool) -> ResourceTracker:
    """
    Provide a ResourceTracker that cleans up after each test.

    In grounding mode: all tracked resources are deleted after the test.
    In fake mode: cleanup is skipped (the reset fixture handles it).
    """
    tracker = ResourceTracker(_client=todoist_client)
    yield tracker
    if grounding_mode:
        tracker.cleanup()
