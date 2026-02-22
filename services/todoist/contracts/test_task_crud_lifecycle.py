"""
Contract tests for Task CRUD Lifecycle.

Covers: creation with minimal/full fields, updating, deletion, listing,
special characters in content, and error handling for invalid requests.
"""

import time
import uuid
from datetime import date

import pytest
from requests.exceptions import HTTPError
from todoist_api_python.api import TodoistAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_all(paginator) -> list:
    """Exhaust a ResultsPaginator and return a flat list of all items."""
    items = []
    for page in paginator:
        items.extend(page)
    return items


def _unique(prefix: str = "test") -> str:
    """Generate a unique name to avoid collisions in grounding mode."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# A syntactically valid-looking ID that doesn't correspond to any real resource.
# 16-char alphanumeric matching the Todoist ID format.
NONEXISTENT_TASK_ID = "ZZZZZZZZZZZZZZZZ"
NONEXISTENT_PROJECT_ID = "ZZZZZZZZZZZZZZZZ"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTaskCrudLifecycle:
    """Tests for Task CRUD Lifecycle."""

    # -----------------------------------------------------------------------
    # create-task-minimal
    # -----------------------------------------------------------------------
    def test_create_task_minimal(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with only required fields and verify defaults."""
        content = _unique("Buy groceries")
        task = todoist_client.add_task(content=content)
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Verify creation response
        assert task.id is not None
        assert isinstance(task.id, str)
        assert len(task.id) > 0
        assert task.content == content
        assert task.description == ""
        assert task.is_completed is False
        assert task.priority == 1
        assert task.labels == [] or task.labels is None
        assert task.due is None
        assert task.parent_id is None
        assert task.section_id is None
        assert task.creator_id is not None
        assert task.created_at is not None
        assert task.project_id is not None  # Should be assigned to Inbox

        # Round-trip: read back via GET
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.id == task.id
        assert fetched.content == content
        assert fetched.description == ""
        assert fetched.is_completed is False
        assert fetched.priority == 1
        assert fetched.project_id == task.project_id

    # -----------------------------------------------------------------------
    # create-task-all-fields
    # -----------------------------------------------------------------------
    def test_create_task_all_fields(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with all optional fields populated."""
        # Arrange: create project and section
        project_name = _unique("Work Project")
        project = todoist_client.add_project(name=project_name)
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        section_name = _unique("Sprint 1")
        section = todoist_client.add_section(
            name=section_name,
            project_id=project.id,
        )
        resource_tracker.section(section.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create task with many fields
        content = _unique("Implement login page")
        task = todoist_client.add_task(
            content=content,
            description="Build the OAuth2 login flow",
            project_id=project.id,
            section_id=section.id,
            priority=4,
            due_string="tomorrow at 10am",
            due_lang="en",
            labels=["frontend", "urgent"],
            duration=120,
            duration_unit="minute",
        )
        resource_tracker.task(task.id)

        # Assert creation response
        assert task.content == content
        assert task.description == "Build the OAuth2 login flow"
        assert task.project_id == project.id
        assert task.section_id == section.id
        assert task.priority == 4
        assert "frontend" in task.labels
        assert "urgent" in task.labels
        assert task.due is not None
        assert task.due.is_recurring is False
        assert task.duration is not None
        assert task.duration.amount == 120
        assert task.duration.unit == "minute"

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.project_id == project.id
        assert fetched.section_id == section.id
        assert fetched.priority == 4
        assert "frontend" in fetched.labels
        assert "urgent" in fetched.labels
        assert fetched.duration.amount == 120

    # -----------------------------------------------------------------------
    # update-task-fields
    # -----------------------------------------------------------------------
    def test_update_task_fields(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Update multiple fields on an existing task."""
        # Arrange: create task with initial values
        content = _unique("Draft report")
        task = todoist_client.add_task(content=content)
        resource_tracker.task(task.id)

        assert task.content == content
        assert task.priority == 1

        if grounding_mode:
            time.sleep(0.3)

        # Act: update several fields
        new_content = _unique("Draft quarterly report")
        updated = todoist_client.update_task(
            task_id=task.id,
            content=new_content,
            priority=3,
            description="Q4 2025 financial summary",
            labels=["reports"],
            due_date=date(2026, 3, 1),
        )

        # Assert update response
        assert updated.content == new_content
        assert updated.priority == 3
        assert updated.description == "Q4 2025 financial summary"
        assert "reports" in updated.labels
        assert updated.due is not None
        assert updated.due.date == date(2026, 3, 1)
        assert updated.due.is_recurring is False

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: verify persistence
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.content == new_content
        assert fetched.priority == 3
        assert fetched.description == "Q4 2025 financial summary"
        assert "reports" in fetched.labels
        assert fetched.due is not None
        assert fetched.due.date == date(2026, 3, 1)

    # -----------------------------------------------------------------------
    # delete-task
    # -----------------------------------------------------------------------
    def test_delete_task(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Delete a task and verify it is no longer active."""
        # Create a task in its own project so we can filter the list
        project = todoist_client.add_project(name=_unique("Delete Test"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        content = _unique("Temporary task")
        task = todoist_client.add_task(content=content, project_id=project.id)
        # Don't track for cleanup — we're about to delete it
        task_id = task.id

        if grounding_mode:
            time.sleep(0.3)

        # Verify task exists in list before deletion
        pre_delete_tasks = collect_all(
            todoist_client.get_tasks(project_id=project.id)
        )
        assert task_id in [t.id for t in pre_delete_tasks]

        if grounding_mode:
            time.sleep(0.3)

        # Act: delete the task
        result = todoist_client.delete_task(task_id=task_id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # Verify: deleted task should NOT appear in active task list
        post_delete_tasks = collect_all(
            todoist_client.get_tasks(project_id=project.id)
        )
        assert task_id not in [t.id for t in post_delete_tasks]

    # -----------------------------------------------------------------------
    # list-tasks-in-project
    # -----------------------------------------------------------------------
    def test_list_tasks_in_project(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """List active tasks filtered by project."""
        # Arrange: create project with two tasks
        project = todoist_client.add_project(name=_unique("Test Project"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        content_a = _unique("Task A")
        task_a = todoist_client.add_task(
            content=content_a, project_id=project.id
        )
        resource_tracker.task(task_a.id)

        if grounding_mode:
            time.sleep(0.3)

        content_b = _unique("Task B")
        task_b = todoist_client.add_task(
            content=content_b, project_id=project.id
        )
        resource_tracker.task(task_b.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: list tasks in project
        all_tasks = collect_all(
            todoist_client.get_tasks(project_id=project.id)
        )

        # Assert: both tasks are in the list (containment, not exact count)
        task_ids = [t.id for t in all_tasks]
        assert task_a.id in task_ids
        assert task_b.id in task_ids

        # Verify project_id on each returned task
        for t in all_tasks:
            if t.id in (task_a.id, task_b.id):
                assert t.project_id == project.id

    # -----------------------------------------------------------------------
    # special-characters-in-content
    # -----------------------------------------------------------------------
    def test_special_characters_in_content(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Task content with special characters, markdown, and Unicode."""
        # Test markdown in content and description
        md_content = "Task with **bold** and [link](https://example.com)"
        md_description = "Description with `code` and newlines"
        task_md = todoist_client.add_task(
            content=md_content,
            description=md_description,
        )
        resource_tracker.task(task_md.id)
        assert task_md.content == md_content
        assert task_md.description == md_description

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back markdown task
        fetched_md = todoist_client.get_task(task_id=task_md.id)
        assert fetched_md.content == md_content
        assert fetched_md.description == md_description

        if grounding_mode:
            time.sleep(0.3)

        # Test Unicode and emoji in content
        unicode_content = "日本語タスク 🎯"
        task_uni = todoist_client.add_task(content=unicode_content)
        resource_tracker.task(task_uni.id)
        assert task_uni.content == unicode_content

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back unicode task
        fetched_uni = todoist_client.get_task(task_id=task_uni.id)
        assert fetched_uni.content == unicode_content

    # -----------------------------------------------------------------------
    # invalid-requests
    # -----------------------------------------------------------------------
    def test_get_nonexistent_task_returns_error(
        self,
        todoist_client: TodoistAPI,
        grounding_mode: bool,
    ):
        """GET a non-existent task returns an HTTP error."""
        with pytest.raises(HTTPError) as exc_info:
            todoist_client.get_task(task_id=NONEXISTENT_TASK_ID)

        # Should be 400 (invalid ID format) or 404 (not found)
        status = exc_info.value.response.status_code
        assert status in (400, 404)

    def test_get_nonexistent_project_returns_error(
        self,
        todoist_client: TodoistAPI,
        grounding_mode: bool,
    ):
        """GET a non-existent project returns an HTTP error."""
        with pytest.raises(HTTPError) as exc_info:
            todoist_client.get_project(project_id=NONEXISTENT_PROJECT_ID)

        status = exc_info.value.response.status_code
        assert status in (400, 404)

    def test_delete_nonexistent_task_returns_error(
        self,
        todoist_client: TodoistAPI,
        grounding_mode: bool,
    ):
        """DELETE a non-existent task returns an HTTP error."""
        with pytest.raises(HTTPError) as exc_info:
            todoist_client.delete_task(task_id=NONEXISTENT_TASK_ID)

        status = exc_info.value.response.status_code
        assert status in (400, 404)

    def test_create_task_empty_content_returns_error(
        self,
        todoist_client: TodoistAPI,
        grounding_mode: bool,
    ):
        """Creating a task with empty content should fail.

        The SDK validates MinLen(1) client-side, so we expect either
        a client-side validation error or an HTTP 400.
        """
        with pytest.raises(Exception):
            todoist_client.add_task(content="")
