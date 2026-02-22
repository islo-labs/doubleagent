"""
Contract tests for Section Organization.

Covers: section CRUD (create, read, update, delete) within projects,
listing sections filtered by project, creating tasks in specific sections,
and filtering tasks by section_id.
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSectionOrganization:
    """Tests for Section Organization."""

    # -----------------------------------------------------------------------
    # section-crud: Create, update, and delete sections within a project
    # -----------------------------------------------------------------------
    def test_create_section_in_project(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create sections within a project and verify via read-back."""
        # Arrange: create a project
        project = todoist_client.add_project(name=_unique("Sectioned Project"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create first section
        section_name_1 = _unique("To Do")
        section_1 = todoist_client.add_section(
            name=section_name_1,
            project_id=project.id,
        )
        resource_tracker.section(section_1.id)

        # Assert creation response
        assert section_1.id is not None
        assert isinstance(section_1.id, str)
        assert len(section_1.id) > 0
        assert section_1.name == section_name_1
        assert section_1.project_id == project.id

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back via GET
        fetched_1 = todoist_client.get_section(section_id=section_1.id)
        assert fetched_1.id == section_1.id
        assert fetched_1.name == section_name_1
        assert fetched_1.project_id == project.id

    def test_create_multiple_sections_and_list(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create two sections and verify both appear in the section list."""
        # Arrange: create a project
        project = todoist_client.add_project(name=_unique("Multi Section"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create two sections
        section_name_1 = _unique("To Do")
        section_1 = todoist_client.add_section(
            name=section_name_1,
            project_id=project.id,
        )
        resource_tracker.section(section_1.id)

        if grounding_mode:
            time.sleep(0.3)

        section_name_2 = _unique("In Progress")
        section_2 = todoist_client.add_section(
            name=section_name_2,
            project_id=project.id,
        )
        resource_tracker.section(section_2.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert: list sections for the project
        all_sections = collect_all(
            todoist_client.get_sections(project_id=project.id)
        )

        section_ids = [s.id for s in all_sections]
        assert section_1.id in section_ids
        assert section_2.id in section_ids

        # Verify project_id on returned sections
        for s in all_sections:
            if s.id in (section_1.id, section_2.id):
                assert s.project_id == project.id

        # Verify section names via containment
        section_names = [s.name for s in all_sections]
        assert section_name_1 in section_names
        assert section_name_2 in section_names

    def test_update_section_name(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Update a section's name and verify persistence."""
        # Arrange: create project and section
        project = todoist_client.add_project(name=_unique("Update Section"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        original_name = _unique("In Progress")
        section = todoist_client.add_section(
            name=original_name,
            project_id=project.id,
        )
        resource_tracker.section(section.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: rename the section
        new_name = _unique("Done")
        updated = todoist_client.update_section(
            section_id=section.id,
            name=new_name,
        )

        # Assert update response
        assert updated.name == new_name
        assert updated.id == section.id
        assert updated.project_id == project.id

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back to verify persistence
        fetched = todoist_client.get_section(section_id=section.id)
        assert fetched.name == new_name
        assert fetched.project_id == project.id

    def test_delete_section(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Delete a section and verify it is excluded from list results.

        Sections are soft-deleted: GET may still return 200 with is_deleted=true,
        but they should NOT appear in the list endpoint.
        """
        # Arrange: create project and section
        project = todoist_client.add_project(name=_unique("Delete Section"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        section_name = _unique("Doomed Section")
        section = todoist_client.add_section(
            name=section_name,
            project_id=project.id,
        )
        section_id = section.id
        # Don't track for cleanup — we're about to delete it

        if grounding_mode:
            time.sleep(0.3)

        # Verify section exists in list before deletion
        pre_delete = collect_all(
            todoist_client.get_sections(project_id=project.id)
        )
        assert section_id in [s.id for s in pre_delete]

        if grounding_mode:
            time.sleep(0.3)

        # Act: delete the section
        result = todoist_client.delete_section(section_id=section_id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # Assert: deleted section should NOT appear in list results
        post_delete = collect_all(
            todoist_client.get_sections(project_id=project.id)
        )
        assert section_id not in [s.id for s in post_delete]

    def test_section_crud_full_lifecycle(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """End-to-end: create, list, update, delete a section within a project."""
        # Arrange: create project
        project = todoist_client.add_project(name=_unique("Lifecycle Proj"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        # Step 1: Create section
        section_name = _unique("To Do")
        section = todoist_client.add_section(
            name=section_name,
            project_id=project.id,
        )
        resource_tracker.section(section.id)

        assert section.name == section_name
        assert section.project_id == project.id

        if grounding_mode:
            time.sleep(0.3)

        # Step 2: Verify in list
        sections = collect_all(
            todoist_client.get_sections(project_id=project.id)
        )
        assert section.id in [s.id for s in sections]

        if grounding_mode:
            time.sleep(0.3)

        # Step 3: Update name
        new_name = _unique("Done")
        updated = todoist_client.update_section(
            section_id=section.id,
            name=new_name,
        )
        assert updated.name == new_name

        if grounding_mode:
            time.sleep(0.3)

        # Step 4: Verify update persisted
        fetched = todoist_client.get_section(section_id=section.id)
        assert fetched.name == new_name

        if grounding_mode:
            time.sleep(0.3)

        # Step 5: Delete section
        todoist_client.delete_section(section_id=section.id)
        # Remove from tracker since we deleted it
        resource_tracker._sections.remove(section.id)

        if grounding_mode:
            time.sleep(0.3)

        # Step 6: Verify deletion via list exclusion (soft-delete)
        post_delete = collect_all(
            todoist_client.get_sections(project_id=project.id)
        )
        assert section.id not in [s.id for s in post_delete]

    # -----------------------------------------------------------------------
    # tasks-in-sections: Create tasks in specific sections, filter by section
    # -----------------------------------------------------------------------
    def test_create_task_in_section(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task in a specific section and verify section_id."""
        # Arrange: create project and section
        project = todoist_client.add_project(name=_unique("Task Section"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        section_name = _unique("Backlog")
        section = todoist_client.add_section(
            name=section_name,
            project_id=project.id,
        )
        resource_tracker.section(section.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create a task in the section
        content = _unique("Backlog item")
        task = todoist_client.add_task(
            content=content,
            project_id=project.id,
            section_id=section.id,
        )
        resource_tracker.task(task.id)

        # Assert creation response
        assert task.section_id == section.id
        assert task.project_id == project.id
        assert task.content == content

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.section_id == section.id
        assert fetched.project_id == project.id

    def test_tasks_in_different_sections(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create tasks in two sections; verify each task has the correct section_id."""
        # Arrange: create project and two sections
        project = todoist_client.add_project(name=_unique("Kanban Project"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        backlog_name = _unique("Backlog")
        backlog = todoist_client.add_section(
            name=backlog_name,
            project_id=project.id,
        )
        resource_tracker.section(backlog.id)

        if grounding_mode:
            time.sleep(0.3)

        active_name = _unique("Active")
        active = todoist_client.add_section(
            name=active_name,
            project_id=project.id,
        )
        resource_tracker.section(active.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create tasks in each section
        backlog_content = _unique("Backlog item")
        backlog_task = todoist_client.add_task(
            content=backlog_content,
            project_id=project.id,
            section_id=backlog.id,
        )
        resource_tracker.task(backlog_task.id)

        if grounding_mode:
            time.sleep(0.3)

        active_content = _unique("Active item")
        active_task = todoist_client.add_task(
            content=active_content,
            project_id=project.id,
            section_id=active.id,
        )
        resource_tracker.task(active_task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert: each task has correct section_id
        fetched_backlog = todoist_client.get_task(task_id=backlog_task.id)
        assert fetched_backlog.section_id == backlog.id

        if grounding_mode:
            time.sleep(0.3)

        fetched_active = todoist_client.get_task(task_id=active_task.id)
        assert fetched_active.section_id == active.id

    def test_filter_tasks_by_section(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Filter tasks by section_id, ensuring only tasks from that section appear."""
        # Arrange: create project and two sections
        project = todoist_client.add_project(name=_unique("Filter Section"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        backlog_name = _unique("Backlog")
        backlog = todoist_client.add_section(
            name=backlog_name,
            project_id=project.id,
        )
        resource_tracker.section(backlog.id)

        if grounding_mode:
            time.sleep(0.3)

        active_name = _unique("Active")
        active = todoist_client.add_section(
            name=active_name,
            project_id=project.id,
        )
        resource_tracker.section(active.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create tasks in different sections
        backlog_content = _unique("Backlog item")
        backlog_task = todoist_client.add_task(
            content=backlog_content,
            project_id=project.id,
            section_id=backlog.id,
        )
        resource_tracker.task(backlog_task.id)

        if grounding_mode:
            time.sleep(0.3)

        active_content = _unique("Active item")
        active_task = todoist_client.add_task(
            content=active_content,
            project_id=project.id,
            section_id=active.id,
        )
        resource_tracker.task(active_task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert: filter by backlog section should contain backlog task
        backlog_tasks = collect_all(
            todoist_client.get_tasks(section_id=backlog.id)
        )
        backlog_task_ids = [t.id for t in backlog_tasks]
        assert backlog_task.id in backlog_task_ids
        # Active task should NOT appear when filtering by backlog section
        assert active_task.id not in backlog_task_ids

        if grounding_mode:
            time.sleep(0.3)

        # Also verify filtering by active section
        active_tasks = collect_all(
            todoist_client.get_tasks(section_id=active.id)
        )
        active_task_ids = [t.id for t in active_tasks]
        assert active_task.id in active_task_ids
        assert backlog_task.id not in active_task_ids

    def test_task_without_section_has_null_section_id(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """A task created without a section_id should have section_id=null."""
        # Arrange: create project
        project = todoist_client.add_project(name=_unique("No Section"))
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: create task without specifying section
        content = _unique("Unsectioned task")
        task = todoist_client.add_task(
            content=content,
            project_id=project.id,
        )
        resource_tracker.task(task.id)

        # Assert: section_id should be null
        assert task.section_id is None

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: verify via GET
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.section_id is None
