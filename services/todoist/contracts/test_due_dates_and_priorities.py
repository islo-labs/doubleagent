"""
Contract tests for scenario: due-dates-and-priorities — Due Dates and Priorities

Tests cover setting and modifying due dates (fixed, recurring, datetime with
timezone), and priority levels on tasks.

Each mutation is verified via a round-trip read-back using a separate SDK call.
Assertions use containment style so tests pass in grounding mode where other
data may exist.
"""

import time
from datetime import date, datetime, timezone

import pytest
from todoist_api_python.api import TodoistAPI


class TestDueDatesAndPriorities:
    """Tests for Due Dates and Priorities."""

    # ------------------------------------------------------------------
    # Test: set-fixed-due-date
    # ------------------------------------------------------------------
    def test_set_fixed_due_date(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with a fixed due date and verify it round-trips."""
        # Arrange / Act — create a task with a date-only due date
        task = todoist_client.add_task(
            content="Submit report",
            due_date=date(2026, 3, 15),
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert on creation response
        assert task.id is not None
        assert task.content == "Submit report"
        assert task.due is not None
        assert task.due.date.strftime("%Y-%m-%d") == "2026-03-15"
        assert task.due.is_recurring is False

        # Round-trip: read back via separate GET
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        assert fetched.due.date.strftime("%Y-%m-%d") == "2026-03-15"
        assert fetched.due.is_recurring is False

    # ------------------------------------------------------------------
    # Test: set-due-datetime
    # ------------------------------------------------------------------
    def test_set_due_datetime(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with a specific due datetime (UTC) and verify."""
        # Act
        task = todoist_client.add_task(
            content="Team meeting",
            due_datetime=datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc),
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert on creation response
        assert task.id is not None
        assert task.due is not None
        assert task.due.is_recurring is False

        # The due.date should include the datetime portion with 2026-03-15
        due_date_str = str(task.due.date)
        assert "2026-03-15" in due_date_str

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        fetched_date_str = str(fetched.due.date)
        assert "2026-03-15" in fetched_date_str
        assert fetched.due.is_recurring is False

    # ------------------------------------------------------------------
    # Test: set-natural-language-recurring-due
    # ------------------------------------------------------------------
    def test_set_natural_language_recurring_due(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with a natural-language recurring due string."""
        # Act
        task = todoist_client.add_task(
            content="Water plants",
            due_string="every monday at 8am",
            due_lang="en",
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Assert on creation response
        assert task.id is not None
        assert task.due is not None
        assert task.due.is_recurring is True
        # The due.string should contain some form of recurrence text
        assert "every" in task.due.string.lower() or "mon" in task.due.string.lower()

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        assert fetched.due.is_recurring is True

    # ------------------------------------------------------------------
    # Test: priority-levels
    # ------------------------------------------------------------------
    def test_priority_levels(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create tasks at each priority level (1-4) and verify values."""
        priority_cases = [
            (1, "Normal prio task"),
            (2, "Medium prio task"),
            (3, "High prio task"),
            (4, "Urgent prio task"),
        ]

        for priority, content in priority_cases:
            task = todoist_client.add_task(
                content=content,
                priority=priority,
            )
            resource_tracker.task(task.id)

            if grounding_mode:
                time.sleep(0.3)

            # Assert on creation response
            assert task.priority == priority, (
                f"Expected priority={priority} for '{content}', got {task.priority}"
            )

            # Round-trip: read back
            fetched = todoist_client.get_task(task_id=task.id)
            assert fetched.priority == priority, (
                f"Round-trip: expected priority={priority} for '{content}', "
                f"got {fetched.priority}"
            )
            assert fetched.content == content

    # ------------------------------------------------------------------
    # Test: update-remove-due-date
    # ------------------------------------------------------------------
    def test_update_due_date(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Update a task's due date to a new value and verify."""
        # Arrange: create a task with an initial due date
        task = todoist_client.add_task(
            content="Flexible task",
            due_date=date(2026, 4, 1),
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        assert task.due is not None
        assert task.due.date.strftime("%Y-%m-%d") == "2026-04-01"

        # Act: update the due date
        updated = todoist_client.update_task(
            task_id=task.id,
            due_date=date(2026, 5, 1),
        )

        if grounding_mode:
            time.sleep(0.3)

        assert updated.due is not None
        assert updated.due.date.strftime("%Y-%m-%d") == "2026-05-01"

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        assert fetched.due.date.strftime("%Y-%m-%d") == "2026-05-01"

    def test_remove_due_date(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Remove a due date from a task using due_string='no date'."""
        # Arrange: create task with due date
        task = todoist_client.add_task(
            content="Clearable task",
            due_date=date(2026, 4, 1),
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        assert task.due is not None

        # Act: clear due date with "no date"
        updated = todoist_client.update_task(
            task_id=task.id,
            due_string="no date",
        )

        if grounding_mode:
            time.sleep(0.3)

        assert updated.due is None

        # Round-trip: read back
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is None

    # ------------------------------------------------------------------
    # Test: due date with due_string (natural language, non-recurring)
    # ------------------------------------------------------------------
    def test_due_string_non_recurring(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with a non-recurring natural language due string."""
        task = todoist_client.add_task(
            content="Due string task",
            due_string="tomorrow at 10am",
            due_lang="en",
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        assert task.due is not None
        assert task.due.is_recurring is False
        # The due.date should have a date portion set
        assert task.due.date is not None

        # Round-trip
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        assert fetched.due.is_recurring is False

    # ------------------------------------------------------------------
    # Test: task defaults — no due date, default priority
    # ------------------------------------------------------------------
    def test_task_defaults_no_due_default_priority(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """A task created without due/priority has due=None and priority=1."""
        task = todoist_client.add_task(content="Plain task no due")
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        assert task.due is None
        assert task.priority == 1

        # Round-trip
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is None
        assert fetched.priority == 1

    # ------------------------------------------------------------------
    # Test: update priority on existing task
    # ------------------------------------------------------------------
    def test_update_priority(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Update a task's priority from 1 to 4 and verify round-trip."""
        # Arrange
        task = todoist_client.add_task(
            content="Escalatable task",
            priority=1,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        assert task.priority == 1

        # Act: escalate to urgent
        updated = todoist_client.update_task(
            task_id=task.id,
            priority=4,
        )

        if grounding_mode:
            time.sleep(0.3)

        assert updated.priority == 4

        # Round-trip
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.priority == 4

    # ------------------------------------------------------------------
    # Test: combined due date + priority
    # ------------------------------------------------------------------
    def test_combined_due_date_and_priority(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Create a task with both a due date and a priority set together."""
        task = todoist_client.add_task(
            content="High-priority deadline",
            due_date=date(2026, 6, 15),
            priority=3,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        assert task.due is not None
        assert task.due.date.strftime("%Y-%m-%d") == "2026-06-15"
        assert task.priority == 3

        # Round-trip
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        assert fetched.due.date.strftime("%Y-%m-%d") == "2026-06-15"
        assert fetched.priority == 3
        assert fetched.content == "High-priority deadline"

    # ------------------------------------------------------------------
    # Test: update both due date and priority in one call
    # ------------------------------------------------------------------
    def test_update_due_and_priority_together(
        self,
        todoist_client: TodoistAPI,
        resource_tracker,
        grounding_mode: bool,
    ):
        """Update both due date and priority in a single update call."""
        # Arrange
        task = todoist_client.add_task(
            content="Multi-update task",
            due_date=date(2026, 3, 1),
            priority=1,
        )
        resource_tracker.task(task.id)

        if grounding_mode:
            time.sleep(0.3)

        # Act: update both
        updated = todoist_client.update_task(
            task_id=task.id,
            due_date=date(2026, 7, 1),
            priority=4,
        )

        if grounding_mode:
            time.sleep(0.3)

        assert updated.due is not None
        assert updated.due.date.strftime("%Y-%m-%d") == "2026-07-01"
        assert updated.priority == 4

        # Round-trip
        fetched = todoist_client.get_task(task_id=task.id)
        assert fetched.due is not None
        assert fetched.due.date.strftime("%Y-%m-%d") == "2026-07-01"
        assert fetched.priority == 4
