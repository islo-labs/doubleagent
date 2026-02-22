"""
Contract tests for scenario: comment-threading
Comment Threading on Tasks and Projects

Tests adding, reading, updating, and deleting comments on both tasks and projects.
"""

import time

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


def _delay_if_grounding(grounding_mode: bool) -> None:
    """Small delay between rapid API calls in grounding mode."""
    if grounding_mode:
        time.sleep(0.35)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCommentCrudOnTask:
    """Full comment CRUD lifecycle on a task."""

    def test_add_comment_to_task(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Create a task and add a comment to it; verify the comment is persisted."""
        # Arrange: create a task
        task = todoist_client.add_task(content="Discuss design")
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        # Act: add a comment
        comment = todoist_client.add_comment(
            "I think we should use a card layout",
            task_id=task.id,
        )
        resource_tracker.comment(comment.id)
        _delay_if_grounding(grounding_mode)

        # Assert: comment fields
        assert comment.id is not None
        assert comment.content == "I think we should use a card layout"
        assert comment.task_id == task.id
        assert comment.posted_at is not None
        assert comment.poster_id is not None

        # Round-trip: read back via get_comment
        fetched = todoist_client.get_comment(comment.id)
        assert fetched.id == comment.id
        assert fetched.content == comment.content
        assert fetched.task_id == task.id

    def test_multiple_comments_on_task(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Add two comments to a task and verify both appear in the list."""
        # Arrange
        task = todoist_client.add_task(content="Multi-comment task")
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        # Act: add two comments
        comment1 = todoist_client.add_comment(
            "I think we should use a card layout",
            task_id=task.id,
        )
        resource_tracker.comment(comment1.id)
        _delay_if_grounding(grounding_mode)

        comment2 = todoist_client.add_comment(
            "Agreed, let us prototype it",
            task_id=task.id,
        )
        resource_tracker.comment(comment2.id)
        _delay_if_grounding(grounding_mode)

        # Assert: list comments and check both are present (containment)
        all_comments = collect_all(todoist_client.get_comments(task_id=task.id))
        all_comment_ids = [c.id for c in all_comments]
        assert comment1.id in all_comment_ids
        assert comment2.id in all_comment_ids

        # Verify each comment has the correct task_id
        for c in all_comments:
            if c.id in (comment1.id, comment2.id):
                assert c.task_id == task.id

    def test_update_comment_content(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Update a comment's content and verify the change is persisted."""
        # Arrange
        task = todoist_client.add_task(content="Update comment task")
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        comment = todoist_client.add_comment(
            "I think we should use a card layout",
            task_id=task.id,
        )
        resource_tracker.comment(comment.id)
        _delay_if_grounding(grounding_mode)

        # Act: update the comment
        updated = todoist_client.update_comment(
            comment.id,
            "Updated: use a grid layout instead",
        )
        _delay_if_grounding(grounding_mode)

        # Assert: update response
        assert updated.id == comment.id
        assert updated.content == "Updated: use a grid layout instead"

        # Round-trip: read back
        fetched = todoist_client.get_comment(comment.id)
        assert fetched.content == "Updated: use a grid layout instead"

    def test_delete_comment(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Delete a comment and verify it no longer appears in the task's comment list."""
        # Arrange
        task = todoist_client.add_task(content="Delete comment task")
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        comment1 = todoist_client.add_comment(
            "Comment to keep",
            task_id=task.id,
        )
        resource_tracker.comment(comment1.id)
        _delay_if_grounding(grounding_mode)

        comment2 = todoist_client.add_comment(
            "Comment to delete",
            task_id=task.id,
        )
        resource_tracker.comment(comment2.id)
        _delay_if_grounding(grounding_mode)

        # Act: delete comment2
        result = todoist_client.delete_comment(comment2.id)
        _delay_if_grounding(grounding_mode)

        # Assert: delete returned True
        assert result is True

        # Verify via list: deleted comment should NOT appear (soft-delete excludes from list)
        remaining = collect_all(todoist_client.get_comments(task_id=task.id))
        remaining_ids = [c.id for c in remaining]
        assert comment1.id in remaining_ids
        assert comment2.id not in remaining_ids

    def test_full_comment_crud_lifecycle(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """End-to-end: create task, add comments, list, update, delete, verify list."""
        # 1. Create task
        task = todoist_client.add_task(content="Discuss design")
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        # 2. Add first comment
        comment1 = todoist_client.add_comment(
            "I think we should use a card layout",
            task_id=task.id,
        )
        resource_tracker.comment(comment1.id)
        _delay_if_grounding(grounding_mode)

        # 3. Add second comment
        comment2 = todoist_client.add_comment(
            "Agreed, let us prototype it",
            task_id=task.id,
        )
        resource_tracker.comment(comment2.id)
        _delay_if_grounding(grounding_mode)

        # 4. List comments — both should be present
        all_comments = collect_all(todoist_client.get_comments(task_id=task.id))
        comment_ids = [c.id for c in all_comments]
        assert comment1.id in comment_ids
        assert comment2.id in comment_ids
        _delay_if_grounding(grounding_mode)

        # 5. Update first comment
        updated = todoist_client.update_comment(
            comment1.id,
            "Updated: use a grid layout instead",
        )
        assert updated.content == "Updated: use a grid layout instead"
        _delay_if_grounding(grounding_mode)

        # 6. Read back updated comment
        fetched = todoist_client.get_comment(comment1.id)
        assert fetched.content == "Updated: use a grid layout instead"
        _delay_if_grounding(grounding_mode)

        # 7. Delete first comment
        todoist_client.delete_comment(comment1.id)
        _delay_if_grounding(grounding_mode)

        # 8. Verify deletion: first comment excluded from list, second remains
        remaining = collect_all(todoist_client.get_comments(task_id=task.id))
        remaining_ids = [c.id for c in remaining]
        assert comment1.id not in remaining_ids
        assert comment2.id in remaining_ids


class TestCommentOnProject:
    """Add comments to a project instead of a task."""

    def test_add_comment_to_project(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Create a project, add a comment to it, and verify via list."""
        # Arrange: create project
        project = todoist_client.add_project(name="Commented Project")
        resource_tracker.project(project.id)
        _delay_if_grounding(grounding_mode)

        # Act: add comment to the project
        comment = todoist_client.add_comment(
            "Project kickoff notes",
            project_id=project.id,
        )
        resource_tracker.comment(comment.id)
        _delay_if_grounding(grounding_mode)

        # Assert: comment fields
        assert comment.id is not None
        assert comment.content == "Project kickoff notes"
        assert comment.project_id == project.id
        # project comments should NOT have task_id
        assert comment.task_id is None
        assert comment.posted_at is not None
        assert comment.poster_id is not None

        # Round-trip: read back
        fetched = todoist_client.get_comment(comment.id)
        assert fetched.id == comment.id
        assert fetched.content == "Project kickoff notes"
        assert fetched.project_id == project.id
        assert fetched.task_id is None
        _delay_if_grounding(grounding_mode)

        # Verify via list
        all_comments = collect_all(todoist_client.get_comments(project_id=project.id))
        comment_ids = [c.id for c in all_comments]
        assert comment.id in comment_ids

        # All returned comments should reference this project
        for c in all_comments:
            if c.id == comment.id:
                assert c.project_id == project.id

    def test_multiple_project_comments(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Add multiple comments to a project and verify all appear in the list."""
        # Arrange
        project = todoist_client.add_project(name="Multi-comment Project")
        resource_tracker.project(project.id)
        _delay_if_grounding(grounding_mode)

        # Act: add two comments
        c1 = todoist_client.add_comment(
            "First project note",
            project_id=project.id,
        )
        resource_tracker.comment(c1.id)
        _delay_if_grounding(grounding_mode)

        c2 = todoist_client.add_comment(
            "Second project note",
            project_id=project.id,
        )
        resource_tracker.comment(c2.id)
        _delay_if_grounding(grounding_mode)

        # Assert: both in list (containment)
        all_comments = collect_all(todoist_client.get_comments(project_id=project.id))
        comment_ids = [c.id for c in all_comments]
        assert c1.id in comment_ids
        assert c2.id in comment_ids

    def test_update_project_comment(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Update a project comment and read it back."""
        # Arrange
        project = todoist_client.add_project(name="Update Comment Project")
        resource_tracker.project(project.id)
        _delay_if_grounding(grounding_mode)

        comment = todoist_client.add_comment(
            "Original project note",
            project_id=project.id,
        )
        resource_tracker.comment(comment.id)
        _delay_if_grounding(grounding_mode)

        # Act
        updated = todoist_client.update_comment(comment.id, "Revised project note")
        _delay_if_grounding(grounding_mode)

        # Assert
        assert updated.content == "Revised project note"

        # Round-trip
        fetched = todoist_client.get_comment(comment.id)
        assert fetched.content == "Revised project note"
        assert fetched.project_id == project.id

    def test_delete_project_comment(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Delete a project comment and verify it disappears from the list."""
        # Arrange
        project = todoist_client.add_project(name="Delete Comment Project")
        resource_tracker.project(project.id)
        _delay_if_grounding(grounding_mode)

        comment = todoist_client.add_comment(
            "Note to be deleted",
            project_id=project.id,
        )
        resource_tracker.comment(comment.id)
        _delay_if_grounding(grounding_mode)

        # Act
        todoist_client.delete_comment(comment.id)
        _delay_if_grounding(grounding_mode)

        # Assert: not in list
        remaining = collect_all(todoist_client.get_comments(project_id=project.id))
        remaining_ids = [c.id for c in remaining]
        assert comment.id not in remaining_ids


class TestCommentIsolation:
    """Verify comments on tasks vs projects are properly isolated."""

    def test_task_comments_not_in_project_comments(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """Comments added to a task do not appear in the project's comment list."""
        # Arrange: project + task
        project = todoist_client.add_project(name="Isolation Test Project")
        resource_tracker.project(project.id)
        _delay_if_grounding(grounding_mode)

        task = todoist_client.add_task(content="Isolation task", project_id=project.id)
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        # Act: add a comment to the task
        task_comment = todoist_client.add_comment(
            "This is on the task",
            task_id=task.id,
        )
        resource_tracker.comment(task_comment.id)
        _delay_if_grounding(grounding_mode)

        # Add a comment to the project
        project_comment = todoist_client.add_comment(
            "This is on the project",
            project_id=project.id,
        )
        resource_tracker.comment(project_comment.id)
        _delay_if_grounding(grounding_mode)

        # Assert: task comment appears in task's list, not project's
        task_comments = collect_all(todoist_client.get_comments(task_id=task.id))
        task_comment_ids = [c.id for c in task_comments]
        assert task_comment.id in task_comment_ids
        assert project_comment.id not in task_comment_ids

        # Assert: project comment appears in project's list, not task's
        proj_comments = collect_all(todoist_client.get_comments(project_id=project.id))
        proj_comment_ids = [c.id for c in proj_comments]
        assert project_comment.id in proj_comment_ids
        assert task_comment.id not in proj_comment_ids

    def test_comment_get_preserves_type(self, todoist_client: TodoistAPI, resource_tracker, grounding_mode: bool):
        """A task comment has task_id set and project_id null; a project comment vice versa."""
        # Arrange
        project = todoist_client.add_project(name="Type Check Project")
        resource_tracker.project(project.id)
        _delay_if_grounding(grounding_mode)

        task = todoist_client.add_task(content="Type check task", project_id=project.id)
        resource_tracker.task(task.id)
        _delay_if_grounding(grounding_mode)

        # Task comment
        tc = todoist_client.add_comment("Task note", task_id=task.id)
        resource_tracker.comment(tc.id)
        _delay_if_grounding(grounding_mode)

        # Project comment
        pc = todoist_client.add_comment("Project note", project_id=project.id)
        resource_tracker.comment(pc.id)
        _delay_if_grounding(grounding_mode)

        # Assert via get_comment
        fetched_tc = todoist_client.get_comment(tc.id)
        assert fetched_tc.task_id == task.id
        assert fetched_tc.project_id is None

        _delay_if_grounding(grounding_mode)

        fetched_pc = todoist_client.get_comment(pc.id)
        assert fetched_pc.project_id == project.id
        assert fetched_pc.task_id is None
