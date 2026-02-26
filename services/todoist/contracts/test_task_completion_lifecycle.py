"""
Contract tests for scenario: task-completion-lifecycle
Task Completion and Reopening

Covers:
  - Closing (completing) a non-recurring task and verifying it leaves the active list
  - Reopening a closed task and verifying it returns to the active list
  - Closing a parent task cascades to all subtasks
  - Closing a recurring task reschedules it to the next occurrence
"""

import time
from datetime import datetime

import pytest
from todoist_api_python.api import TodoistAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def collect_all_pages(paginator) -> list:
    """Exhaust a ResultsPaginator and return a flat list of items."""
    items = []
    for page in paginator:
        items.extend(page)
    return items


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTaskCompletionLifecycle:
    """Tests for Task Completion and Reopening."""

    # ----- close-and-reopen-task -----

    def test_close_task_marks_completed(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """After closing a task, GET shows it as completed (is_completed=True, completed_at set)."""
        # Arrange
        task = todoist_client.add_task(content="Review PR #42 close-test")
        resource_tracker.task(task.id)

        assert task.is_completed is False
        assert task.completed_at is None

        if grounding_mode:
            time.sleep(0.3)

        # Act
        result = todoist_client.complete_task(task_id=task.id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # Assert – read back to verify persistence
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.is_completed is True
        assert fetched.completed_at is not None

    def test_closed_task_excluded_from_active_list(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """A completed task should not appear in the active tasks list for its project."""
        # Arrange – create a project so we can filter precisely
        project = todoist_client.add_project(name="Completion Test Project")
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        task = todoist_client.add_task(
            content="Task to close for list check",
            project_id=project.id,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act
        todoist_client.complete_task(task_id=task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert – the closed task must NOT appear in active tasks
        all_tasks = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        task_ids = [t.id for t in all_tasks]
        assert task.id not in task_ids

    def test_reopen_task_restores_active(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """Reopening a closed task sets is_completed=False and clears completed_at."""
        # Arrange
        task = todoist_client.add_task(content="Review PR #42 reopen-test")
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        todoist_client.complete_task(task_id=task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act
        result = todoist_client.uncomplete_task(task_id=task.id)
        assert result is True

        if grounding_mode:
            time.sleep(0.3)

        # Assert – read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.is_completed is False
        assert fetched.completed_at is None
        assert fetched.content == "Review PR #42 reopen-test"

    def test_reopened_task_appears_in_active_list(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """After reopening, the task should appear again in the active tasks list."""
        # Arrange
        project = todoist_client.add_project(name="Reopen List Test Project")
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        task = todoist_client.add_task(
            content="Task to reopen for list check",
            project_id=project.id,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        todoist_client.complete_task(task_id=task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act
        todoist_client.uncomplete_task(task_id=task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert
        all_tasks = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        task_ids = [t.id for t in all_tasks]
        assert task.id in task_ids

    # ----- close-parent-closes-subtasks -----

    def test_close_parent_closes_subtasks(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """Closing a parent task also closes all its subtasks."""
        # Arrange – create parent + two subtasks in a dedicated project
        project = todoist_client.add_project(name="Subtask Close Test")
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        parent = todoist_client.add_task(
            content="Parent task", project_id=project.id,
        )
        resource_tracker.task(parent.id)

        if grounding_mode:
            time.sleep(0.3)

        sub1 = todoist_client.add_task(
            content="Subtask 1", parent_id=parent.id,
        )
        resource_tracker.task(sub1.id)

        if grounding_mode:
            time.sleep(0.3)

        sub2 = todoist_client.add_task(
            content="Subtask 2", parent_id=parent.id,
        )
        resource_tracker.task(sub2.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act
        todoist_client.complete_task(task_id=parent.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert – neither parent nor subtasks appear in active list
        all_tasks = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        active_ids = [t.id for t in all_tasks]
        assert parent.id not in active_ids
        assert sub1.id not in active_ids
        assert sub2.id not in active_ids

    def test_close_parent_subtasks_are_completed(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """After closing a parent, each subtask should have is_completed=True when fetched directly."""
        # Arrange
        parent = todoist_client.add_task(content="Parent for subtask completion check")
        resource_tracker.task(parent.id)

        if grounding_mode:
            time.sleep(0.3)

        sub1 = todoist_client.add_task(content="Subtask A", parent_id=parent.id)
        resource_tracker.task(sub1.id)

        if grounding_mode:
            time.sleep(0.3)

        sub2 = todoist_client.add_task(content="Subtask B", parent_id=parent.id)
        resource_tracker.task(sub2.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act
        todoist_client.complete_task(task_id=parent.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert – read each subtask individually
        fetched_parent = todoist_client.get_task(task_id=parent.id)
        assert fetched_parent.is_completed is True

        fetched_sub1 = todoist_client.get_task(task_id=sub1.id)
        assert fetched_sub1.is_completed is True
        assert fetched_sub1.completed_at is not None

        fetched_sub2 = todoist_client.get_task(task_id=sub2.id)
        assert fetched_sub2.is_completed is True
        assert fetched_sub2.completed_at is not None

    # ----- close-recurring-task-reschedules -----

    def test_close_recurring_task_advances_due_date(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """Closing a recurring task advances due.date to the next occurrence instead of completing it."""
        # Arrange
        task = todoist_client.add_task(
            content="Daily standup recurring test",
            due_string="every day at 9am",
            due_lang="en",
        )
        resource_tracker.task(task.id)

        assert task.due is not None
        assert task.due.is_recurring is True

        # Record the original due date for comparison
        original_due_date = task.due.date

        if grounding_mode:
            time.sleep(0.3)

        # Act
        todoist_client.complete_task(task_id=task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert – read back
        fetched = todoist_client.get_task(task_id=task.id)

        # Task should NOT be completed – it should remain active
        assert fetched.is_completed is False
        assert fetched.completed_at is None

        # Due should still be recurring
        assert fetched.due is not None
        assert fetched.due.is_recurring is True

        # Due date should have advanced (be later than the original)
        new_due_date = fetched.due.date
        assert new_due_date != original_due_date, (
            f"Expected due date to advance but it stayed at {original_due_date}"
        )

    def test_recurring_task_stays_in_active_list(
        self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool,
    ):
        """After closing a recurring task, it should still appear in the active tasks list."""
        # Arrange
        project = todoist_client.add_project(name="Recurring Active List Test")
        resource_tracker.project(project.id)

        if grounding_mode:
            time.sleep(0.3)

        task = todoist_client.add_task(
            content="Recurring standup list test",
            due_string="every day at 9am",
            due_lang="en",
            project_id=project.id,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act
        todoist_client.complete_task(task_id=task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert – task should still be in active list
        all_tasks = collect_all_pages(
            todoist_client.get_tasks(project_id=project.id)
        )
        task_ids = [t.id for t in all_tasks]
        assert task.id in task_ids
