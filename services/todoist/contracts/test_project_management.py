"""
Contract tests for Project Management.

Covers: full project CRUD lifecycle, sub-project hierarchy, archive/unarchive,
inbox project defaults, and cascade deletion of tasks when a project is deleted.
"""

import time
import uuid

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


# A syntactically-valid-looking ID that doesn't correspond to any real resource.
NONEXISTENT_PROJECT_ID = "ZZZZZZZZZZZZZZZZ"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProjectManagement:
    """Tests for Project Management."""

    # -----------------------------------------------------------------------
    # project-crud: Full project CRUD lifecycle
    # -----------------------------------------------------------------------
    def test_project_crud_lifecycle(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create, read, update, list, delete a project and verify hard-delete (404)."""
        # --- Create ---
        name = _unique("My Project")
        project = todoist_client.add_project(
            name=name,
            color="blue",
            is_favorite=True,
            view_style="list",
        )
        resource_tracker.project(project.id)

        assert project.id is not None
        assert isinstance(project.id, str)
        assert len(project.id) > 0
        assert project.name == name
        assert project.color == "blue"
        assert project.is_favorite is True
        assert project.view_style == "list"
        assert project.parent_id is None
        assert project.is_inbox_project is False

        if grounding_mode:
            time.sleep(0.3)

        # --- Read back (round-trip) ---
        fetched = todoist_client.get_project(project_id=project.id)
        assert fetched.id == project.id
        assert fetched.name == name
        assert fetched.color == "blue"
        assert fetched.is_favorite is True
        assert fetched.view_style == "list"

        if grounding_mode:
            time.sleep(0.3)

        # --- Update ---
        updated = todoist_client.update_project(
            project_id=project.id,
            name=_unique("Renamed Project"),
            color="green",
        )
        assert updated.name.startswith("Renamed Project")
        assert updated.color == "green"
        # is_favorite should be unchanged
        assert updated.is_favorite is True

        if grounding_mode:
            time.sleep(0.3)

        # --- Read back updated project ---
        fetched_updated = todoist_client.get_project(project_id=project.id)
        assert fetched_updated.name == updated.name
        assert fetched_updated.color == "green"
        assert fetched_updated.is_favorite is True

        if grounding_mode:
            time.sleep(0.3)

        # --- List: verify project appears ---
        all_projects = collect_all(todoist_client.get_projects())
        project_ids = [p.id for p in all_projects]
        assert project.id in project_ids

        # Find our project and verify its name
        our_project = next(p for p in all_projects if p.id == project.id)
        assert our_project.name == updated.name

        if grounding_mode:
            time.sleep(0.3)

        # --- Delete ---
        result = todoist_client.delete_project(project_id=project.id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: project is hard-deleted (GET returns 404) ---
        with pytest.raises(HTTPError) as exc_info:
            todoist_client.get_project(project_id=project.id)
        assert exc_info.value.response.status_code == 404

        # Remove from tracker since it's already deleted
        resource_tracker._projects.remove(project.id)

    # -----------------------------------------------------------------------
    # sub-project-hierarchy: Create a sub-project under a parent project
    # -----------------------------------------------------------------------
    def test_sub_project_hierarchy(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a child project under a parent and verify the parent_id relationship."""
        # --- Create parent ---
        parent_name = _unique("Parent Project")
        parent = todoist_client.add_project(name=parent_name)
        resource_tracker.project(parent.id)

        assert parent.parent_id is None

        if grounding_mode:
            time.sleep(0.3)

        # --- Create child under parent ---
        child_name = _unique("Child Project")
        child = todoist_client.add_project(
            name=child_name,
            parent_id=parent.id,
        )
        resource_tracker.project(child.id)

        assert child.name == child_name
        assert child.parent_id == parent.id

        if grounding_mode:
            time.sleep(0.3)

        # --- Round-trip: read back child and verify parent_id ---
        fetched_child = todoist_client.get_project(project_id=child.id)
        assert fetched_child.parent_id == parent.id
        assert fetched_child.name == child_name

    # -----------------------------------------------------------------------
    # archive-unarchive-project: Archive and unarchive a project
    # -----------------------------------------------------------------------
    def test_archive_unarchive_project(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Archive a project, verify it's excluded from listings, then unarchive."""
        # --- Create project ---
        name = _unique("Archive Test")
        project = todoist_client.add_project(name=name)
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        # --- Create a task in the project (to verify it survives archive) ---
        task_content = _unique("Task in project")
        task = todoist_client.add_task(
            content=task_content,
            project_id=project.id,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # --- Archive ---
        archived = todoist_client.archive_project(project_id=project.id)
        # archive_project returns a Project object (200, not 204)
        assert archived is not None
        assert archived.id == project.id

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: archived project should NOT appear in the project list ---
        all_projects = collect_all(todoist_client.get_projects())
        project_ids = [p.id for p in all_projects]
        assert project.id not in project_ids

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: GET by ID still works, and shows is_archived=true ---
        fetched_archived = todoist_client.get_project(project_id=project.id)
        assert fetched_archived.is_archived is True

        if grounding_mode:
            time.sleep(0.3)

        # --- Unarchive ---
        unarchived = todoist_client.unarchive_project(project_id=project.id)
        assert unarchived is not None
        assert unarchived.id == project.id

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: project is restored and accessible ---
        fetched_restored = todoist_client.get_project(project_id=project.id)
        assert fetched_restored.name == name
        assert fetched_restored.is_archived is False

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: project appears in listings again ---
        all_projects_after = collect_all(todoist_client.get_projects())
        project_ids_after = [p.id for p in all_projects_after]
        assert project.id in project_ids_after

    # -----------------------------------------------------------------------
    # inbox-project-default: Tasks without project_id default to Inbox
    # -----------------------------------------------------------------------
    def test_inbox_project_default(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Tasks created without a project_id are assigned to the Inbox project."""
        # --- Find the Inbox project ---
        all_projects = collect_all(todoist_client.get_projects())
        inbox_projects = [p for p in all_projects if p.is_inbox_project is True]
        assert len(inbox_projects) >= 1, "Expected at least one Inbox project"
        inbox_id = inbox_projects[0].id

        if grounding_mode:
            time.sleep(0.3)

        # --- Create task without project_id ---
        content = _unique("Inbox task")
        task = todoist_client.add_task(content=content)
        resource_tracker.task(task.id)

        # --- Verify it was assigned to the Inbox project ---
        assert task.project_id == inbox_id

        if grounding_mode:
            time.sleep(0.3)

        # --- Round-trip: read back and confirm ---
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.project_id == inbox_id

    # -----------------------------------------------------------------------
    # delete-project-cascades: Deleting a project removes all its tasks
    # -----------------------------------------------------------------------
    def test_delete_project_cascades_to_tasks(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Deleting a project cascade-deletes all tasks within it."""
        # --- Create a project ---
        name = _unique("Doomed Project")
        project = todoist_client.add_project(name=name)
        # Don't track for cleanup — we're about to delete it
        project_id = project.id

        if grounding_mode:
            time.sleep(0.3)

        # --- Create a task in the project ---
        task_content = _unique("Doomed task")
        task = todoist_client.add_task(
            content=task_content,
            project_id=project_id,
        )
        task_id = task.id
        # Don't track for cleanup — cascade-delete will handle it

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify task exists before deletion ---
        pre_task = todoist_client.get_task(task_id=task_id)
        assert pre_task.id == task_id
        assert pre_task.project_id == project_id

        if grounding_mode:
            time.sleep(0.3)

        # --- Delete the project ---
        result = todoist_client.delete_project(project_id=project_id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: project is hard-deleted ---
        with pytest.raises(HTTPError) as exc_info:
            todoist_client.get_project(project_id=project_id)
        assert exc_info.value.response.status_code == 404

        if grounding_mode:
            time.sleep(0.3)

        # --- Verify: task was cascade-deleted (returns 404) ---
        with pytest.raises(HTTPError) as exc_info:
            todoist_client.get_task(task_id=task_id)
        assert exc_info.value.response.status_code == 404
