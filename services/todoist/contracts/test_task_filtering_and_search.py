"""
Contract tests for Task Filtering and Search.

Verifies that filter queries, ID-based retrieval, and section-based filtering
return the correct subsets of tasks. Uses the official todoist-api-python SDK
and runs against both the real Todoist API (grounding) and the DoubleAgent fake.
"""

import time

import pytest
from todoist_api_python.api import TodoistAPI

from conftest import ResourceTracker


def _collect_all_tasks(paginator) -> list:
    """Exhaust a ResultsPaginator and return a flat list of Task objects."""
    all_tasks = []
    for page in paginator:
        all_tasks.extend(page)
    return all_tasks


class TestTaskFilteringAndSearch:
    """Tests for Task Filtering and Search."""

    def test_filter_by_filter_query(
        self,
        todoist_client: TodoistAPI,
        resource_tracker: ResourceTracker,
        grounding_mode: bool,
    ):
        """Use filter query to find tasks matching 'today & p1'.

        Creates three tasks with different priority/due-date combinations
        and verifies that filter_tasks(query="today & p1") returns only
        the task that is both urgent (priority=4) AND due today.

        Note: In Todoist filter syntax, 'p1' maps to API priority=4 (urgent).
        """
        # Arrange: create three tasks with different priority + due combos
        urgent_today = todoist_client.add_task(
            content="CT urgent today task",
            priority=4,
            due_string="today",
            due_lang="en",
        )
        resource_tracker.task(urgent_today.id)
        if grounding_mode:
            time.sleep(0.3)

        low_today = todoist_client.add_task(
            content="CT low priority today task",
            priority=1,
            due_string="today",
            due_lang="en",
        )
        resource_tracker.task(low_today.id)
        if grounding_mode:
            time.sleep(0.3)

        urgent_future = todoist_client.add_task(
            content="CT urgent future task",
            priority=4,
            due_string="next week",
            due_lang="en",
        )
        resource_tracker.task(urgent_future.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: filter with "today & p1" (p1 in filter syntax = priority 4)
        filtered_tasks = _collect_all_tasks(
            todoist_client.filter_tasks(query="today & p1")
        )
        filtered_ids = [t.id for t in filtered_tasks]

        # Assert: only the urgent-today task should appear
        assert urgent_today.id in filtered_ids, (
            f"Expected urgent today task {urgent_today.id} in filter results"
        )
        assert low_today.id not in filtered_ids, (
            "Low-priority today task should NOT appear in 'today & p1' filter"
        )
        assert urgent_future.id not in filtered_ids, (
            "Urgent future task should NOT appear in 'today & p1' filter"
        )

        # Round-trip: verify the filtered task has correct properties
        matching = [t for t in filtered_tasks if t.id == urgent_today.id][0]
        assert matching.priority == 4
        assert matching.content == "CT urgent today task"

    def test_get_tasks_by_ids(
        self,
        todoist_client: TodoistAPI,
        resource_tracker: ResourceTracker,
        grounding_mode: bool,
    ):
        """Retrieve multiple specific tasks by their IDs.

        Creates three tasks, then fetches only two by ID. Verifies
        that the result contains exactly the requested tasks and not the third.
        """
        # Arrange: create three tasks
        task_alpha = todoist_client.add_task(content="CT Task Alpha")
        resource_tracker.task(task_alpha.id)
        if grounding_mode:
            time.sleep(0.3)

        task_beta = todoist_client.add_task(content="CT Task Beta")
        resource_tracker.task(task_beta.id)
        if grounding_mode:
            time.sleep(0.3)

        task_gamma = todoist_client.add_task(content="CT Task Gamma")
        resource_tracker.task(task_gamma.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: fetch only alpha and beta by IDs
        fetched_tasks = _collect_all_tasks(
            todoist_client.get_tasks(ids=[task_alpha.id, task_beta.id])
        )
        fetched_ids = [t.id for t in fetched_tasks]

        # Assert: containment — alpha and beta present, gamma absent
        assert task_alpha.id in fetched_ids, (
            f"Task Alpha ({task_alpha.id}) should be in IDs result"
        )
        assert task_beta.id in fetched_ids, (
            f"Task Beta ({task_beta.id}) should be in IDs result"
        )
        assert task_gamma.id not in fetched_ids, (
            f"Task Gamma ({task_gamma.id}) should NOT be in IDs result"
        )

        # Round-trip: verify content matches
        alpha_match = [t for t in fetched_tasks if t.id == task_alpha.id][0]
        assert alpha_match.content == "CT Task Alpha"

        beta_match = [t for t in fetched_tasks if t.id == task_beta.id][0]
        assert beta_match.content == "CT Task Beta"

    def test_filter_by_section(
        self,
        todoist_client: TodoistAPI,
        resource_tracker: ResourceTracker,
        grounding_mode: bool,
    ):
        """Filter tasks by section_id.

        Creates a project with one section, places a task in that section
        and another task with no section, then filters by section_id.
        Only the sectioned task should appear in the result.
        """
        # Arrange: create project
        project = todoist_client.add_project(name="CT Filter Section Test")
        resource_tracker.project(project.id)
        if grounding_mode:
            time.sleep(0.3)

        # Create a section in the project
        section_a = todoist_client.add_section(
            name="CT Section A", project_id=project.id
        )
        resource_tracker.section(section_a.id)
        if grounding_mode:
            time.sleep(0.3)

        # Create a task in section A
        task_in_section = todoist_client.add_task(
            content="CT In section A",
            project_id=project.id,
            section_id=section_a.id,
        )
        resource_tracker.task(task_in_section.id)
        if grounding_mode:
            time.sleep(0.3)

        # Create a task with no section (same project)
        task_no_section = todoist_client.add_task(
            content="CT No section",
            project_id=project.id,
        )
        resource_tracker.task(task_no_section.id)
        if grounding_mode:
            time.sleep(0.3)

        # Act: filter by section_id
        section_tasks = _collect_all_tasks(
            todoist_client.get_tasks(section_id=section_a.id)
        )
        section_task_ids = [t.id for t in section_tasks]

        # Assert: only the sectioned task appears
        assert task_in_section.id in section_task_ids, (
            f"Task in section A ({task_in_section.id}) should appear in section filter"
        )
        assert task_no_section.id not in section_task_ids, (
            f"Task with no section ({task_no_section.id}) should NOT appear in section filter"
        )

        # Round-trip: verify task properties
        matched_task = [t for t in section_tasks if t.id == task_in_section.id][0]
        assert matched_task.content == "CT In section A"
        assert matched_task.section_id == section_a.id
        assert matched_task.project_id == project.id

        # Additional round-trip: read the task back individually
        readback = todoist_client.get_task(task_id=task_in_section.id)
        assert readback.section_id == section_a.id
        assert readback.content == "CT In section A"
