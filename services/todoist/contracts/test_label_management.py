"""
Contract tests for the Label Management scenario.

Tests cover:
  - Label CRUD lifecycle (create, read, update, delete)
  - Assigning labels to tasks and filtering tasks by label
  - Updating labels on a task replaces the entire label set
"""

import time

import pytest
from requests.exceptions import HTTPError
from todoist_api_python.api import TodoistAPI


def _collect_all_pages(paginator) -> list:
    """Exhaust a ResultsPaginator and return a flat list of all items."""
    items = []
    for page in paginator:
        items.extend(page)
    return items


class TestLabelCrud:
    """Create, update, and delete a personal label."""

    def test_create_label_with_all_fields(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Create a label with name, color, is_favorite, and order, then read it back."""
        # Act: create label
        label = todoist_client.add_label(
            name="ct-urgent",
            color="red",
            is_favorite=True,
            item_order=1,
        )
        resource_tracker.label(label.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert: creation response
        assert label.id is not None
        assert label.name == "ct-urgent"
        assert label.color == "red"
        assert label.is_favorite is True
        assert label.order == 1

        # Round-trip: read back via GET
        fetched = todoist_client.get_label(label_id=label.id)
        assert fetched.id == label.id
        assert fetched.name == "ct-urgent"
        assert fetched.color == "red"
        assert fetched.is_favorite is True
        assert fetched.order == 1

    def test_label_appears_in_list(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """After creating a label, it appears in the labels list."""
        label = todoist_client.add_label(name="ct-list-check", color="blue")
        resource_tracker.label(label.id)

        if grounding_mode:
            time.sleep(0.3)

        # List all labels and verify containment
        all_labels = _collect_all_pages(todoist_client.get_labels())
        all_label_ids = [l.id for l in all_labels]
        assert label.id in all_label_ids

        # Also check by name
        matching = [l for l in all_labels if l.id == label.id]
        assert len(matching) >= 1
        assert matching[0].name == "ct-list-check"

    def test_update_label(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Update a label's name and color; verify is_favorite is preserved."""
        # Arrange: create label
        label = todoist_client.add_label(
            name="ct-to-update",
            color="red",
            is_favorite=True,
        )
        resource_tracker.label(label.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: update name and color
        updated = todoist_client.update_label(
            label_id=label.id,
            name="ct-updated",
            color="berry_red",
        )

        # Assert: updated fields
        assert updated.name == "ct-updated"
        assert updated.color == "berry_red"
        # is_favorite should be preserved (not changed)
        assert updated.is_favorite is True

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back
        fetched = todoist_client.get_label(label_id=label.id)
        assert fetched.name == "ct-updated"
        assert fetched.color == "berry_red"
        assert fetched.is_favorite is True

    def test_delete_label_excluded_from_list(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """After deleting a label, it no longer appears in the labels list.

        Note: Labels are soft-deleted. GET by ID may still return 200,
        but the label should be excluded from the list endpoint.
        """
        # Arrange: create label
        label = todoist_client.add_label(name="ct-to-delete", color="green")
        # Don't track for cleanup since we're deleting it ourselves

        if grounding_mode:
            time.sleep(0.3)

        # Verify it exists in the list first
        all_labels_before = _collect_all_pages(todoist_client.get_labels())
        assert label.id in [l.id for l in all_labels_before]

        if grounding_mode:
            time.sleep(0.3)

        # Act: delete the label
        result = todoist_client.delete_label(label_id=label.id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # Assert: label is excluded from list
        all_labels_after = _collect_all_pages(todoist_client.get_labels())
        assert label.id not in [l.id for l in all_labels_after]


class TestAssignLabelsToTasks:
    """Assign labels to tasks and filter tasks by label."""

    def test_create_tasks_with_labels_and_filter(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Create tasks with different labels, then filter by label name."""
        # Use unique label names to avoid collisions with existing data
        backend_label = "ct-backend-filter"
        frontend_label = "ct-frontend-filter"

        # Arrange: create tasks with labels
        task1 = todoist_client.add_task(
            content="Build API (label test)",
            labels=[backend_label],
        )
        resource_tracker.task(task1.id)

        if grounding_mode:
            time.sleep(0.3)

        task2 = todoist_client.add_task(
            content="Build UI (label test)",
            labels=[frontend_label],
        )
        resource_tracker.task(task2.id)

        if grounding_mode:
            time.sleep(0.3)

        task3 = todoist_client.add_task(
            content="Full stack task (label test)",
            labels=[backend_label, frontend_label],
        )
        resource_tracker.task(task3.id)

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: verify labels on each task
        fetched1 = todoist_client.get_task(task_id=task1.id)
        assert backend_label in fetched1.labels
        assert frontend_label not in fetched1.labels

        fetched2 = todoist_client.get_task(task_id=task2.id)
        assert frontend_label in fetched2.labels
        assert backend_label not in fetched2.labels

        fetched3 = todoist_client.get_task(task_id=task3.id)
        assert backend_label in fetched3.labels
        assert frontend_label in fetched3.labels

        if grounding_mode:
            time.sleep(0.3)

        # Act: filter tasks by the backend label
        backend_tasks = _collect_all_pages(
            todoist_client.get_tasks(label=backend_label)
        )
        backend_task_ids = [t.id for t in backend_tasks]

        # Assert: containment checks (not exact count due to shared API)
        assert task1.id in backend_task_ids, "Task with backend label should appear"
        assert task3.id in backend_task_ids, "Full stack task should appear (has backend label)"
        assert task2.id not in backend_task_ids, "Task with only frontend label should NOT appear"

    def test_task_with_multiple_labels_roundtrip(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """A task created with multiple labels preserves all of them."""
        labels = ["ct-multi-a", "ct-multi-b"]

        task = todoist_client.add_task(
            content="Multi-label task",
            labels=labels,
        )
        resource_tracker.task(task.id)

        # Assert on creation response
        assert set(labels).issubset(set(task.labels))

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert set(labels).issubset(set(fetched.labels))


class TestUpdateTaskLabelsReplaces:
    """Updating labels on a task replaces the entire label set."""

    def test_update_replaces_labels(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """When updating a task's labels, the old labels are replaced entirely."""
        old_label = "ct-old-label"
        new_labels = ["ct-new-label-1", "ct-new-label-2"]

        # Arrange: create task with old label
        task = todoist_client.add_task(
            content="Labeled task (replace test)",
            labels=[old_label],
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Verify the old label is present
        fetched_before = todoist_client.get_task(task_id=task.id)
        assert old_label in fetched_before.labels

        if grounding_mode:
            time.sleep(0.3)

        # Act: update labels to the new set
        updated = todoist_client.update_task(
            task_id=task.id,
            labels=new_labels,
        )

        # Assert: old label gone, new labels present
        assert old_label not in updated.labels
        assert set(new_labels).issubset(set(updated.labels))

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back
        fetched_after = todoist_client.get_task(task_id=task.id)
        assert old_label not in fetched_after.labels
        assert set(new_labels).issubset(set(fetched_after.labels))

    def test_update_to_empty_labels(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool
    ):
        """Updating labels to an empty list removes all labels from the task."""
        # Arrange: create task with a label
        task = todoist_client.add_task(
            content="Task to clear labels",
            labels=["ct-will-be-removed"],
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Verify label is present
        fetched_before = todoist_client.get_task(task_id=task.id)
        assert "ct-will-be-removed" in fetched_before.labels

        if grounding_mode:
            time.sleep(0.3)

        # Act: update labels to empty list
        updated = todoist_client.update_task(
            task_id=task.id,
            labels=[],
        )

        # Assert: labels are empty
        assert updated.labels == [] or updated.labels is None

        if grounding_mode:
            time.sleep(0.3)

        # Round-trip: read back
        fetched_after = todoist_client.get_task(task_id=task.id)
        assert fetched_after.labels == [] or fetched_after.labels is None
