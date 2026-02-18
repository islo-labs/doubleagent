import os
import time
import functools

import pytest
import requests
from todoist_api_python.api import TodoistAPI


def is_grounding_mode() -> bool:
    """Check if we're running in grounding mode (against real Todoist API)."""
    return bool(os.environ.get("TODOIST_GROUNDING_TOKEN"))


@pytest.fixture(scope="session")
def is_grounding():
    """Session fixture indicating whether we're in grounding mode."""
    return is_grounding_mode()


def get_fake_url() -> str:
    """Get the fake service URL from environment variable"""
    url = os.environ.get("DOUBLEAGENT_TODOIST_URL")
    if not url:
        raise ValueError(
            "DOUBLEAGENT_TODOIST_URL environment variable is required"
        )
    return url.rstrip("/")


@pytest.fixture(scope="session")
def fake_url(is_grounding) -> str | None:
    """Provide the fake service URL, or None in grounding mode."""
    if is_grounding:
        return None
    return get_fake_url()


@pytest.fixture
def reset_state(fake_url):
    """Reset the fake service state before each test. No-op in grounding mode."""
    if fake_url is None:
        return
    response = requests.post(f"{fake_url}/_doubleagent/reset")
    response.raise_for_status()
    assert response.json() == {"status": "ok"}


class ResourceTracker:
    """Tracks resources created during a test for cleanup in grounding mode."""

    def __init__(self):
        self.task_ids: list[str] = []
        self.project_ids: list[str] = []
        self.section_ids: list[str] = []
        self.label_ids: list[str] = []
        self.comment_ids: list[str] = []


@pytest.fixture
def todoist_client(fake_url, reset_state, is_grounding, monkeypatch) -> TodoistAPI:
    """
    Provide a configured Todoist SDK client.

    In fake mode: monkey-patches the SDK URL to point at the fake service.
    In grounding mode: uses the real token and real API, tracks resources for cleanup.
    """
    tracker = ResourceTracker()

    if is_grounding:
        token = os.environ["TODOIST_GROUNDING_TOKEN"]
        client = TodoistAPI(token)
    else:
        import todoist_api_python._core.endpoints as endpoints

        monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")
        client = TodoistAPI("fake-token")

    # Wrap add_* methods to track created resources
    original_add_task = client.add_task
    original_add_task_quick = client.add_task_quick
    original_add_project = client.add_project
    original_add_section = client.add_section
    original_add_label = client.add_label
    original_add_comment = client.add_comment

    @functools.wraps(original_add_task)
    def tracked_add_task(*args, **kwargs):
        result = original_add_task(*args, **kwargs)
        tracker.task_ids.append(result.id)
        return result

    @functools.wraps(original_add_task_quick)
    def tracked_add_task_quick(*args, **kwargs):
        result = original_add_task_quick(*args, **kwargs)
        tracker.task_ids.append(result.id)
        return result

    @functools.wraps(original_add_project)
    def tracked_add_project(*args, **kwargs):
        result = original_add_project(*args, **kwargs)
        tracker.project_ids.append(result.id)
        return result

    @functools.wraps(original_add_section)
    def tracked_add_section(*args, **kwargs):
        result = original_add_section(*args, **kwargs)
        tracker.section_ids.append(result.id)
        return result

    @functools.wraps(original_add_label)
    def tracked_add_label(*args, **kwargs):
        result = original_add_label(*args, **kwargs)
        tracker.label_ids.append(result.id)
        return result

    @functools.wraps(original_add_comment)
    def tracked_add_comment(*args, **kwargs):
        result = original_add_comment(*args, **kwargs)
        tracker.comment_ids.append(result.id)
        return result

    client.add_task = tracked_add_task
    client.add_task_quick = tracked_add_task_quick
    client.add_project = tracked_add_project
    client.add_section = tracked_add_section
    client.add_label = tracked_add_label
    client.add_comment = tracked_add_comment

    yield client

    # Teardown: delete tracked resources in dependency order (best-effort)
    if is_grounding:
        for comment_id in reversed(tracker.comment_ids):
            try:
                client.delete_comment(comment_id=comment_id)
            except Exception:
                pass
        for task_id in reversed(tracker.task_ids):
            try:
                client.delete_task(task_id=task_id)
            except Exception:
                pass
        for section_id in reversed(tracker.section_ids):
            try:
                client.delete_section(section_id=section_id)
            except Exception:
                pass
        for label_id in reversed(tracker.label_ids):
            try:
                client.delete_label(label_id=label_id)
            except Exception:
                pass
        for project_id in reversed(tracker.project_ids):
            try:
                client.delete_project(project_id=project_id)
            except Exception:
                pass


@pytest.fixture(autouse=True)
def rate_limit_delay(is_grounding, request):
    """Add a delay after each test in grounding mode to avoid rate limiting."""
    yield
    if is_grounding and "fake_only" not in request.keywords:
        time.sleep(0.3)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "fake_only: test only runs against the fake (skipped in grounding mode)"
    )


def pytest_collection_modifyitems(config, items):
    if not is_grounding_mode():
        return
    skip_fake_only = pytest.mark.skip(reason="skipped in grounding mode (fake_only)")
    for item in items:
        if "fake_only" in item.keywords:
            item.add_marker(skip_fake_only)
