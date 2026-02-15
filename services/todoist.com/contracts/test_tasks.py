"""
Contract tests for Todoist tasks CRUD operations.

Tests the complete flow: create, read, update, delete, complete, uncomplete tasks
with support for natural language due dates, priority levels (P1-P4), labels,
and recurring task patterns using the official todoist-api-python SDK.
"""

import pytest
from datetime import date, datetime
from todoist_api_python.api import TodoistAPI


def test_create_task_basic(todoist_client: TodoistAPI):
    """Test creating a basic task with just content"""
    task = todoist_client.add_task(content="Buy milk")

    assert task is not None
    assert task.id is not None
    assert task.content == "Buy milk"
    assert task.priority == 1  # Default priority
    assert task.is_completed is False


def test_create_task_with_natural_language_due_date(todoist_client: TodoistAPI):
    """Test creating a task with natural language due date"""
    task = todoist_client.add_task(
        content="Call dentist", due_string="tomorrow at 4pm", due_lang="en"
    )

    assert task is not None
    assert task.content == "Call dentist"
    assert task.due is not None
    assert task.due.string == "tomorrow at 4pm"


def test_create_task_with_priority(todoist_client: TodoistAPI):
    """Test creating tasks with different priority levels (P1-P4)"""
    # P4 - Highest priority
    task_p4 = todoist_client.add_task(content="Urgent task", priority=4)
    assert task_p4.priority == 4

    # P3
    task_p3 = todoist_client.add_task(content="High priority task", priority=3)
    assert task_p3.priority == 3

    # P2
    task_p2 = todoist_client.add_task(content="Medium priority task", priority=2)
    assert task_p2.priority == 2

    # P1 - Default priority
    task_p1 = todoist_client.add_task(content="Normal task", priority=1)
    assert task_p1.priority == 1


def test_create_task_with_labels(todoist_client: TodoistAPI):
    """Test creating a task with labels"""
    task = todoist_client.add_task(
        content="Write report", labels=["work", "urgent", "documentation"]
    )

    assert task is not None
    assert task.labels == ["work", "urgent", "documentation"]


def test_create_task_with_description(todoist_client: TodoistAPI):
    """Test creating a task with a description"""
    task = todoist_client.add_task(
        content="Plan vacation",
        description="Research destinations and book flights for summer trip",
    )

    assert task is not None
    assert task.content == "Plan vacation"
    assert task.description == "Research destinations and book flights for summer trip"


def test_create_task_with_due_date(todoist_client: TodoistAPI):
    """Test creating a task with a specific due date"""
    due_date = date(2026, 3, 15)
    task = todoist_client.add_task(content="Submit tax return", due_date=due_date)

    assert task is not None
    assert task.due is not None
    assert task.due.date == due_date


def test_create_task_with_due_datetime(todoist_client: TodoistAPI):
    """Test creating a task with a specific due datetime"""
    due_datetime = datetime(2026, 3, 15, 14, 30, 0)
    task = todoist_client.add_task(content="Attend meeting", due_datetime=due_datetime)

    assert task is not None
    assert task.due is not None
    # The due.date field contains datetime for datetime tasks
    assert task.due.date == due_datetime


def test_create_task_with_duration(todoist_client: TodoistAPI):
    """Test creating a task with duration"""
    task = todoist_client.add_task(
        content="Review code", duration=30, duration_unit="minute"
    )

    assert task is not None
    assert task.duration is not None
    assert task.duration.amount == 30
    assert task.duration.unit == "minute"


def test_create_task_in_project(todoist_client: TodoistAPI):
    """Test creating a task in a specific project"""
    # First create a project
    project = todoist_client.add_project(name="Work Projects")

    # Create task in that project
    task = todoist_client.add_task(
        content="Prepare presentation", project_id=project.id
    )

    assert task is not None
    assert task.project_id == project.id


def test_get_task(todoist_client: TodoistAPI):
    """Test retrieving a specific task by ID"""
    # Create a task first
    created_task = todoist_client.add_task(content="Task to retrieve")

    # Retrieve it
    retrieved_task = todoist_client.get_task(task_id=created_task.id)

    assert retrieved_task is not None
    assert retrieved_task.id == created_task.id
    assert retrieved_task.content == "Task to retrieve"


def test_get_all_tasks(todoist_client: TodoistAPI):
    """Test retrieving all active tasks"""
    # Create multiple tasks
    todoist_client.add_task(content="Task 1")
    todoist_client.add_task(content="Task 2")
    todoist_client.add_task(content="Task 3")

    # Get all tasks - the SDK returns an iterator of pages
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)

    assert len(all_tasks) >= 3
    task_contents = [t.content for t in all_tasks]
    assert "Task 1" in task_contents
    assert "Task 2" in task_contents
    assert "Task 3" in task_contents


def test_get_tasks_by_project(todoist_client: TodoistAPI):
    """Test filtering tasks by project"""
    # Create projects
    project1 = todoist_client.add_project(name="Project A")
    project2 = todoist_client.add_project(name="Project B")

    # Create tasks in different projects
    todoist_client.add_task(content="Task in A", project_id=project1.id)
    todoist_client.add_task(content="Another task in A", project_id=project1.id)
    todoist_client.add_task(content="Task in B", project_id=project2.id)

    # Get tasks for project A
    project_a_tasks = []
    for page in todoist_client.get_tasks(project_id=project1.id):
        project_a_tasks.extend(page)

    assert len(project_a_tasks) == 2
    task_contents = [t.content for t in project_a_tasks]
    assert "Task in A" in task_contents
    assert "Another task in A" in task_contents
    assert "Task in B" not in task_contents


def test_get_tasks_by_label(todoist_client: TodoistAPI):
    """Test filtering tasks by label"""
    # Create tasks with different labels
    todoist_client.add_task(content="Work task 1", labels=["work"])
    todoist_client.add_task(content="Work task 2", labels=["work", "urgent"])
    todoist_client.add_task(content="Personal task", labels=["personal"])

    # Get tasks with "work" label
    work_tasks = []
    for page in todoist_client.get_tasks(label="work"):
        work_tasks.extend(page)

    assert len(work_tasks) == 2
    task_contents = [t.content for t in work_tasks]
    assert "Work task 1" in task_contents
    assert "Work task 2" in task_contents
    assert "Personal task" not in task_contents


def test_update_task_content(todoist_client: TodoistAPI):
    """Test updating a task's content"""
    # Create a task
    task = todoist_client.add_task(content="Original content")

    # Update the content
    updated_task = todoist_client.update_task(
        task_id=task.id, content="Updated content"
    )

    assert updated_task.id == task.id
    assert updated_task.content == "Updated content"


def test_update_task_priority(todoist_client: TodoistAPI):
    """Test updating a task's priority"""
    # Create a task with P1 priority
    task = todoist_client.add_task(content="Task to prioritize", priority=1)

    # Update to P4 (highest)
    updated_task = todoist_client.update_task(task_id=task.id, priority=4)

    assert updated_task.id == task.id
    assert updated_task.priority == 4


def test_update_task_labels(todoist_client: TodoistAPI):
    """Test updating a task's labels"""
    # Create a task with initial labels
    task = todoist_client.add_task(content="Labeled task", labels=["old-label"])

    # Update the labels
    updated_task = todoist_client.update_task(
        task_id=task.id, labels=["new-label", "another-label"]
    )

    assert updated_task.id == task.id
    assert updated_task.labels == ["new-label", "another-label"]


def test_update_task_due_date(todoist_client: TodoistAPI):
    """Test updating a task's due date"""
    # Create a task without due date
    task = todoist_client.add_task(content="Task to schedule")

    # Add a due date
    updated_task = todoist_client.update_task(
        task_id=task.id, due_string="next Monday"
    )

    assert updated_task.id == task.id
    assert updated_task.due is not None
    assert updated_task.due.string == "next Monday"


def test_update_task_remove_due_date(todoist_client: TodoistAPI):
    """Test removing a task's due date"""
    # Create a task with a due date
    task = todoist_client.add_task(content="Scheduled task", due_string="tomorrow")

    # Remove the due date
    updated_task = todoist_client.update_task(task_id=task.id, due_string="no date")

    assert updated_task.id == task.id
    assert updated_task.due is None


def test_update_task_duration(todoist_client: TodoistAPI):
    """Test updating a task's duration"""
    # Create a task with duration
    task = todoist_client.add_task(
        content="Timed task", duration=15, duration_unit="minute"
    )

    # Update the duration
    updated_task = todoist_client.update_task(
        task_id=task.id, duration=60, duration_unit="minute"
    )

    assert updated_task.id == task.id
    assert updated_task.duration is not None
    assert updated_task.duration.amount == 60
    assert updated_task.duration.unit == "minute"


def test_delete_task(todoist_client: TodoistAPI):
    """Test deleting a task"""
    # Create a task
    task = todoist_client.add_task(content="Task to delete")
    task_id = task.id

    # Delete it
    result = todoist_client.delete_task(task_id=task_id)

    assert result is True

    # Verify it's gone
    with pytest.raises(Exception):
        todoist_client.get_task(task_id=task_id)


def test_complete_task(todoist_client: TodoistAPI):
    """Test marking a task as completed"""
    # Create a task
    task = todoist_client.add_task(content="Task to complete")

    # Complete it
    result = todoist_client.complete_task(task_id=task.id)
    assert result is True

    # Retrieve and verify it's completed
    completed_task = todoist_client.get_task(task_id=task.id)
    assert completed_task.is_completed is True


def test_uncomplete_task(todoist_client: TodoistAPI):
    """Test reopening a completed task"""
    # Create and complete a task
    task = todoist_client.add_task(content="Task to reopen")
    todoist_client.complete_task(task_id=task.id)

    # Uncomplete it
    result = todoist_client.uncomplete_task(task_id=task.id)
    assert result is True

    # Verify it's no longer completed
    reopened_task = todoist_client.get_task(task_id=task.id)
    assert reopened_task.is_completed is False


def test_completed_tasks_not_in_active_list(todoist_client: TodoistAPI):
    """Test that completed tasks don't appear in get_tasks list"""
    # Create tasks
    task1 = todoist_client.add_task(content="Active task")
    task2 = todoist_client.add_task(content="Task to complete")

    # Complete one task
    todoist_client.complete_task(task_id=task2.id)

    # Get all active tasks
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)

    task_ids = [t.id for t in all_tasks]
    assert task1.id in task_ids
    assert task2.id not in task_ids  # Completed task should not appear


def test_complete_task_lifecycle(todoist_client: TodoistAPI):
    """Test the complete CRUD lifecycle of a task with all features"""
    # Create a project
    project = todoist_client.add_project(name="Test Project")

    # Create a task with all features
    task = todoist_client.add_task(
        content="Complete lifecycle task",
        description="This task tests all features",
        project_id=project.id,
        labels=["test", "lifecycle"],
        priority=3,
        due_string="tomorrow at 2pm",
        duration=45,
        duration_unit="minute",
    )

    # Verify creation
    assert task.content == "Complete lifecycle task"
    assert task.description == "This task tests all features"
    assert task.project_id == project.id
    assert task.labels == ["test", "lifecycle"]
    assert task.priority == 3
    assert task.due is not None
    assert task.duration is not None

    # Read
    retrieved = todoist_client.get_task(task_id=task.id)
    assert retrieved.id == task.id
    assert retrieved.content == task.content

    # Update
    updated = todoist_client.update_task(
        task_id=task.id,
        content="Updated lifecycle task",
        priority=4,
        labels=["updated"],
    )
    assert updated.content == "Updated lifecycle task"
    assert updated.priority == 4
    assert updated.labels == ["updated"]

    # Complete
    todoist_client.complete_task(task_id=task.id)
    completed = todoist_client.get_task(task_id=task.id)
    assert completed.is_completed is True

    # Uncomplete
    todoist_client.uncomplete_task(task_id=task.id)
    uncompleted = todoist_client.get_task(task_id=task.id)
    assert uncompleted.is_completed is False

    # Delete
    result = todoist_client.delete_task(task_id=task.id)
    assert result is True


def test_create_task_with_recurring_pattern(todoist_client: TodoistAPI):
    """Test creating a task with recurring due date pattern"""
    task = todoist_client.add_task(content="Weekly meeting", due_string="every Monday")

    assert task is not None
    assert task.content == "Weekly meeting"
    assert task.due is not None
    assert task.due.string == "every Monday"
    # Note: is_recurring would be set by the real API's NLP parser
    # Our fake just stores the string


def test_create_subtask(todoist_client: TodoistAPI):
    """Test creating a subtask (child task)"""
    # Create parent task
    parent = todoist_client.add_task(content="Parent task")

    # Create subtask
    subtask = todoist_client.add_task(
        content="Subtask 1", parent_id=parent.id
    )

    assert subtask is not None
    assert subtask.parent_id == parent.id
    assert subtask.content == "Subtask 1"


def test_get_tasks_by_parent(todoist_client: TodoistAPI):
    """Test filtering tasks by parent task"""
    # Create parent and subtasks
    parent = todoist_client.add_task(content="Parent task")
    subtask1 = todoist_client.add_task(content="Subtask 1", parent_id=parent.id)
    subtask2 = todoist_client.add_task(content="Subtask 2", parent_id=parent.id)
    todoist_client.add_task(content="Other task")  # Not a subtask

    # Get subtasks
    subtasks = []
    for page in todoist_client.get_tasks(parent_id=parent.id):
        subtasks.extend(page)

    assert len(subtasks) == 2
    subtask_contents = [t.content for t in subtasks]
    assert "Subtask 1" in subtask_contents
    assert "Subtask 2" in subtask_contents


def test_create_task_with_multiple_features(todoist_client: TodoistAPI):
    """Test creating a task with multiple features combined"""
    project = todoist_client.add_project(name="Multi-feature Project")

    task = todoist_client.add_task(
        content="Complex task",
        description="This task has many features: priority, labels, due date, duration",
        project_id=project.id,
        labels=["important", "work", "deadline"],
        priority=4,
        due_string="tomorrow at 4pm",
        due_lang="en",
        duration=120,
        duration_unit="minute",
    )

    assert task.content == "Complex task"
    assert len(task.description) > 0
    assert task.project_id == project.id
    assert len(task.labels) == 3
    assert task.priority == 4
    assert task.due is not None
    assert task.duration is not None
    assert task.duration.amount == 120
    assert task.duration.unit == "minute"
