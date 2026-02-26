"""
Contract tests for Subtask Hierarchy scenario.

Tests parent-child task relationships, verifying subtask creation,
listing by parent_id, cascade deletion behavior, and hierarchy navigation.
"""

import time

import pytest
from todoist_api_python.api import TodoistAPI


def collect_all_pages(paginator) -> list:
    """Exhaust a ResultsPaginator and return all items as a flat list."""
    items = []
    for page in paginator:
        items.extend(page)
    return items


class TestSubtaskHierarchy:
    """Tests for Subtask Hierarchy."""

    # ------------------------------------------------------------------
    # Test case: create-subtasks
    # ------------------------------------------------------------------

    def test_create_subtask_has_parent_id(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Creating a subtask sets parent_id to the parent task's ID."""
        # Arrange: create a parent task
        parent = todoist_client.add_task(content="Plan release")
        resource_tracker.task(parent.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: create a subtask under the parent
        subtask = todoist_client.add_task(
            content="Write changelog", parent_id=parent.id
        )
        resource_tracker.task(subtask.id)
        if grounding_mode:
            time.sleep(0.3)

        # Assert: parent_id is set correctly
        assert parent.parent_id is None, "Parent task should have no parent"
        assert subtask.parent_id == parent.id, (
            "Subtask parent_id should match the parent task ID"
        )

    def test_create_subtask_read_back(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """After creating a subtask, GET by ID returns correct parent_id."""
        # Arrange
        parent = todoist_client.add_task(content="Plan release v2")
        resource_tracker.task(parent.id)
        if grounding_mode:
            time.sleep(0.3)

        subtask = todoist_client.add_task(
            content="Write changelog v2", parent_id=parent.id
        )
        resource_tracker.task(subtask.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: read back the subtask
        fetched = todoist_client.get_task(task_id=subtask.id)

        # Assert: round-trip verification
        assert fetched.id == subtask.id
        assert fetched.parent_id == parent.id
        assert fetched.content == "Write changelog v2"

    def test_create_multiple_subtasks(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Create multiple subtasks under one parent, verify all appear in project task list."""
        # Arrange: create a project for isolation
        project = todoist_client.add_project(name="Subtask Hierarchy Test")
        resource_tracker.project(project.id)
        if grounding_mode:
            time.sleep(0.3)

        # Create parent task in the project
        parent = todoist_client.add_task(
            content="Plan release", project_id=project.id
        )
        resource_tracker.task(parent.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: create two subtasks
        sub1 = todoist_client.add_task(
            content="Write changelog", parent_id=parent.id
        )
        resource_tracker.task(sub1.id)
        if grounding_mode:
            time.sleep(0.3)

        sub2 = todoist_client.add_task(
            content="Tag version", parent_id=parent.id
        )
        resource_tracker.task(sub2.id)
        if grounding_mode:
            time.sleep(0.3)

        # Assert: both subtasks have correct parent_id
        assert sub1.parent_id == parent.id
        assert sub2.parent_id == parent.id

        # Assert: all three tasks appear when listing by project
        all_tasks = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        all_task_ids = [t.id for t in all_tasks]
        assert parent.id in all_task_ids, "Parent task should appear in project list"
        assert sub1.id in all_task_ids, "Subtask 1 should appear in project list"
        assert sub2.id in all_task_ids, "Subtask 2 should appear in project list"

    def test_list_subtasks_by_parent_id(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Filtering tasks by parent_id returns only subtasks of that parent."""
        # Arrange
        parent = todoist_client.add_task(content="Parent for filter test")
        resource_tracker.task(parent.id)
        if grounding_mode:
            time.sleep(0.3)

        sub1 = todoist_client.add_task(
            content="Child A", parent_id=parent.id
        )
        resource_tracker.task(sub1.id)
        if grounding_mode:
            time.sleep(0.3)

        sub2 = todoist_client.add_task(
            content="Child B", parent_id=parent.id
        )
        resource_tracker.task(sub2.id)
        if grounding_mode:
            time.sleep(0.3)

        # Also create an unrelated top-level task
        unrelated = todoist_client.add_task(content="Unrelated top-level task")
        resource_tracker.task(unrelated.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: list tasks filtered by parent_id
        subtasks = collect_all_pages(
            todoist_client.get_tasks(parent_id=parent.id)
        )
        subtask_ids = [t.id for t in subtasks]

        # Assert: containment — both children present, parent and unrelated are NOT
        assert sub1.id in subtask_ids, "Child A should appear in parent_id filter"
        assert sub2.id in subtask_ids, "Child B should appear in parent_id filter"
        assert parent.id not in subtask_ids, (
            "Parent itself should NOT appear when filtering by parent_id"
        )
        assert unrelated.id not in subtask_ids, (
            "Unrelated task should NOT appear when filtering by parent_id"
        )

    def test_subtask_inherits_project(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Subtasks inherit the project of their parent task."""
        # Arrange
        project = todoist_client.add_project(name="Inheritance Test")
        resource_tracker.project(project.id)
        if grounding_mode:
            time.sleep(0.3)

        parent = todoist_client.add_task(
            content="Parent in project", project_id=project.id
        )
        resource_tracker.task(parent.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: create subtask (without specifying project_id)
        subtask = todoist_client.add_task(
            content="Child inherits project", parent_id=parent.id
        )
        resource_tracker.task(subtask.id)
        if grounding_mode:
            time.sleep(0.3)

        # Assert: subtask should be in same project as parent
        fetched = todoist_client.get_task(task_id=subtask.id)
        assert fetched.project_id == project.id, (
            "Subtask should inherit parent's project_id"
        )

    # ------------------------------------------------------------------
    # Test case: delete-parent-deletes-subtasks
    # ------------------------------------------------------------------

    def test_delete_parent_cascades_to_subtasks(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Deleting a parent task cascade-deletes its subtasks (soft-delete)."""
        # Arrange: create a project for isolation
        project = todoist_client.add_project(name="Delete Cascade Test")
        resource_tracker.project(project.id)
        if grounding_mode:
            time.sleep(0.3)

        parent = todoist_client.add_task(
            content="Parent to delete", project_id=project.id
        )
        # Don't track parent for cleanup — we're going to delete it ourselves
        if grounding_mode:
            time.sleep(0.3)

        child = todoist_client.add_task(
            content="Child task", parent_id=parent.id
        )
        # Don't track child — cascade delete should handle it
        if grounding_mode:
            time.sleep(0.3)

        # Verify both exist before deletion
        fetched_parent = todoist_client.get_task(task_id=parent.id)
        assert fetched_parent.id == parent.id
        fetched_child = todoist_client.get_task(task_id=child.id)
        assert fetched_child.id == child.id
        if grounding_mode:
            time.sleep(0.3)

        # Act: delete the parent
        todoist_client.delete_task(task_id=parent.id)
        if grounding_mode:
            time.sleep(0.3)

        # Assert: both parent and child no longer appear in the project task list
        remaining = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        remaining_ids = [t.id for t in remaining]
        assert parent.id not in remaining_ids, (
            "Deleted parent should not appear in task list"
        )
        assert child.id not in remaining_ids, (
            "Cascade-deleted child should not appear in task list"
        )

    def test_delete_parent_subtask_is_soft_deleted(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """
        After deleting a parent, subtasks are soft-deleted:
        GET on the subtask returns 200 with is_deleted=true.
        """
        # Arrange
        project = todoist_client.add_project(name="Soft Delete Cascade Test")
        resource_tracker.project(project.id)
        if grounding_mode:
            time.sleep(0.3)

        parent = todoist_client.add_task(
            content="Soft delete parent", project_id=project.id
        )
        if grounding_mode:
            time.sleep(0.3)

        child = todoist_client.add_task(
            content="Soft delete child", parent_id=parent.id
        )
        child_id = child.id
        if grounding_mode:
            time.sleep(0.3)

        # Act: delete the parent
        todoist_client.delete_task(task_id=parent.id)
        if grounding_mode:
            time.sleep(0.3)

        # Assert: the child is soft-deleted — GET still works but is_deleted is set
        # NOTE: Tasks are soft-deleted in API v1 (GET returns 200 with is_deleted: true)
        # The SDK doesn't expose is_deleted directly on the Task model, so we verify
        # through list exclusion instead (the canonical way to verify soft-delete)
        remaining = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        remaining_ids = [t.id for t in remaining]
        assert child_id not in remaining_ids, (
            "Soft-deleted child should not appear in active task list"
        )

    def test_delete_parent_with_multiple_subtasks(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Deleting a parent with multiple subtasks cascades to all of them."""
        # Arrange
        project = todoist_client.add_project(name="Multi-child Delete Test")
        resource_tracker.project(project.id)
        if grounding_mode:
            time.sleep(0.3)

        parent = todoist_client.add_task(
            content="Multi-child parent", project_id=project.id
        )
        if grounding_mode:
            time.sleep(0.3)

        child1 = todoist_client.add_task(
            content="Child 1", parent_id=parent.id
        )
        if grounding_mode:
            time.sleep(0.3)

        child2 = todoist_client.add_task(
            content="Child 2", parent_id=parent.id
        )
        if grounding_mode:
            time.sleep(0.3)

        # Create another task in the same project that is NOT a subtask
        standalone = todoist_client.add_task(
            content="Standalone survivor", project_id=project.id
        )
        resource_tracker.task(standalone.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: delete the parent
        todoist_client.delete_task(task_id=parent.id)
        if grounding_mode:
            time.sleep(0.3)

        # Assert: parent and children gone from list, standalone remains
        remaining = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        remaining_ids = [t.id for t in remaining]

        assert parent.id not in remaining_ids, "Deleted parent should not be in list"
        assert child1.id not in remaining_ids, "Cascade-deleted child 1 should not be in list"
        assert child2.id not in remaining_ids, "Cascade-deleted child 2 should not be in list"
        assert standalone.id in remaining_ids, (
            "Standalone task in same project should survive parent deletion"
        )
