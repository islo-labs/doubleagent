"""
Contract tests for Todoist task lifecycle management.

Tests closing completed tasks, reopening tasks, and filtering active tasks
by project, section, label, and priority using the official todoist-api-python SDK.

NOTE on Todoist priority numbering:
  - In the UI/filter language: p1 = highest priority, p4 = lowest
  - In the API response: priority 4 = highest (urgent), priority 1 = lowest (normal)
  - So filter query "p1" matches tasks with API priority=4
"""

import pytest
from todoist_api_python.api import TodoistAPI


def test_close_task(todoist_client: TodoistAPI):
    """Test closing a task marks it as completed"""
    # Create a task
    task = todoist_client.add_task(content="Task to close")

    # Close the task
    result = todoist_client.complete_task(task_id=task.id)
    assert result is True

    # Verify it's completed
    completed_task = todoist_client.get_task(task_id=task.id)
    assert completed_task.is_completed is True


def test_reopen_task(todoist_client: TodoistAPI):
    """Test reopening a completed task"""
    # Create and close a task
    task = todoist_client.add_task(content="Task to reopen")
    todoist_client.complete_task(task_id=task.id)

    # Reopen the task
    result = todoist_client.uncomplete_task(task_id=task.id)
    assert result is True

    # Verify it's no longer completed
    reopened_task = todoist_client.get_task(task_id=task.id)
    assert reopened_task.is_completed is False


def test_completed_tasks_excluded_from_active_list(todoist_client: TodoistAPI):
    """Test that completed tasks are excluded from get_tasks()"""
    # Create multiple tasks
    active_task = todoist_client.add_task(content="Active task")
    completed_task = todoist_client.add_task(content="Task to complete")

    # Complete one task
    todoist_client.complete_task(task_id=completed_task.id)

    # Get all active tasks
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)

    # Verify only active task appears
    task_ids = [t.id for t in all_tasks]
    assert active_task.id in task_ids
    assert completed_task.id not in task_ids


def test_reopened_tasks_appear_in_active_list(todoist_client: TodoistAPI):
    """Test that reopened tasks appear in the active task list"""
    # Create and complete a task
    task = todoist_client.add_task(content="Task to reopen")
    todoist_client.complete_task(task_id=task.id)

    # Reopen the task
    todoist_client.uncomplete_task(task_id=task.id)

    # Get all active tasks
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)

    # Verify reopened task appears
    task_ids = [t.id for t in all_tasks]
    assert task.id in task_ids


def test_filter_tasks_by_project(todoist_client: TodoistAPI):
    """Test filtering active tasks by project"""
    # Create projects
    project_a = todoist_client.add_project(name="Project A")
    project_b = todoist_client.add_project(name="Project B")

    # Create tasks in different projects
    task_a1 = todoist_client.add_task(content="Task A1", project_id=project_a.id)
    task_a2 = todoist_client.add_task(content="Task A2", project_id=project_a.id)
    task_b1 = todoist_client.add_task(content="Task B1", project_id=project_b.id)

    # Filter by project A
    project_a_tasks = []
    for page in todoist_client.get_tasks(project_id=project_a.id):
        project_a_tasks.extend(page)

    # Verify only project A tasks appear
    task_ids = [t.id for t in project_a_tasks]
    assert len(project_a_tasks) == 2
    assert task_a1.id in task_ids
    assert task_a2.id in task_ids
    assert task_b1.id not in task_ids


def test_filter_tasks_by_section(todoist_client: TodoistAPI):
    """Test filtering active tasks by section"""
    # Create a project with real sections
    project = todoist_client.add_project(name="Test Project")
    section1 = todoist_client.add_section(name="Section 1", project_id=project.id)
    section2 = todoist_client.add_section(name="Section 2", project_id=project.id)

    # Create tasks in different sections
    task_section1 = todoist_client.add_task(
        content="Task in section 1",
        project_id=project.id,
        section_id=section1.id
    )
    task_section2 = todoist_client.add_task(
        content="Task in section 2",
        project_id=project.id,
        section_id=section2.id
    )
    task_no_section = todoist_client.add_task(
        content="Task without section",
        project_id=project.id
    )

    # Verify round-trip for task creation
    retrieved_task1 = todoist_client.get_task(task_id=task_section1.id)
    assert retrieved_task1.section_id == section1.id

    # Filter by section 1
    section1_tasks = []
    for page in todoist_client.get_tasks(section_id=section1.id):
        section1_tasks.extend(page)

    # Verify only section 1 task appears
    task_ids = [t.id for t in section1_tasks]
    assert len(section1_tasks) == 1
    assert task_section1.id in task_ids
    assert task_section2.id not in task_ids
    assert task_no_section.id not in task_ids


def test_filter_tasks_by_label(todoist_client: TodoistAPI):
    """Test filtering active tasks by label"""
    # Create tasks with different labels
    task_work = todoist_client.add_task(content="Work task", labels=["work"])
    task_personal = todoist_client.add_task(content="Personal task", labels=["personal"])
    task_both = todoist_client.add_task(
        content="Work and personal",
        labels=["work", "personal"]
    )

    # Filter by "work" label
    work_tasks = []
    for page in todoist_client.get_tasks(label="work"):
        work_tasks.extend(page)

    # Verify work-labeled tasks appear
    task_ids = [t.id for t in work_tasks]
    assert len(work_tasks) == 2
    assert task_work.id in task_ids
    assert task_both.id in task_ids
    assert task_personal.id not in task_ids


def test_filter_tasks_by_priority(todoist_client: TodoistAPI):
    """Test filtering active tasks by priority level.

    Todoist filter syntax: "p1" = highest priority = API priority 4
    """
    # Create tasks with different priorities
    task_p1 = todoist_client.add_task(content="Normal priority", priority=1)
    task_p2 = todoist_client.add_task(content="Medium priority", priority=2)
    task_p3 = todoist_client.add_task(content="High priority", priority=3)
    task_p4 = todoist_client.add_task(content="Urgent priority", priority=4)

    # Filter by "p1" in filter language = API priority 4 (urgent)
    urgent_tasks = []
    for page in todoist_client.filter_tasks(query="p1"):
        urgent_tasks.extend(page)

    # Verify only P4 (urgent) task appears
    task_ids = [t.id for t in urgent_tasks]
    assert len(urgent_tasks) == 1
    assert task_p4.id in task_ids
    assert task_p1.id not in task_ids
    assert task_p2.id not in task_ids
    assert task_p3.id not in task_ids


def test_filter_high_priority_tasks(todoist_client: TodoistAPI):
    """Test filtering for high priority tasks (p1 and p2 in filter language)"""
    # Create tasks with various priorities
    todoist_client.add_task(content="Normal task", priority=1)
    task_p3 = todoist_client.add_task(content="High priority", priority=3)
    task_p4 = todoist_client.add_task(content="Urgent", priority=4)

    # Filter p2 in filter language = API priority 3
    p2_tasks = []
    for page in todoist_client.filter_tasks(query="p2"):
        p2_tasks.extend(page)

    # Filter p1 in filter language = API priority 4
    p1_tasks = []
    for page in todoist_client.filter_tasks(query="p1"):
        p1_tasks.extend(page)

    # Verify correct filtering
    assert len(p2_tasks) == 1
    assert p2_tasks[0].id == task_p3.id
    assert len(p1_tasks) == 1
    assert p1_tasks[0].id == task_p4.id


def test_combined_filters_project_and_label(todoist_client: TodoistAPI):
    """Test filtering with multiple criteria: project and label"""
    # Create projects
    work_project = todoist_client.add_project(name="Work")
    personal_project = todoist_client.add_project(name="Personal")

    # Create tasks with various combinations
    task_work_urgent = todoist_client.add_task(
        content="Urgent work task",
        project_id=work_project.id,
        labels=["urgent"]
    )
    task_work_normal = todoist_client.add_task(
        content="Normal work task",
        project_id=work_project.id,
        labels=["normal"]
    )
    task_personal_urgent = todoist_client.add_task(
        content="Urgent personal task",
        project_id=personal_project.id,
        labels=["urgent"]
    )

    # Filter by work project only
    work_tasks = []
    for page in todoist_client.get_tasks(project_id=work_project.id):
        work_tasks.extend(page)

    work_task_ids = [t.id for t in work_tasks]
    assert len(work_tasks) == 2
    assert task_work_urgent.id in work_task_ids
    assert task_work_normal.id in work_task_ids
    assert task_personal_urgent.id not in work_task_ids

    # Filter by urgent label only
    urgent_tasks = []
    for page in todoist_client.get_tasks(label="urgent"):
        urgent_tasks.extend(page)

    urgent_task_ids = [t.id for t in urgent_tasks]
    assert len(urgent_tasks) == 2
    assert task_work_urgent.id in urgent_task_ids
    assert task_personal_urgent.id in urgent_task_ids
    assert task_work_normal.id not in urgent_task_ids


def test_combined_filters_project_and_priority(todoist_client: TodoistAPI):
    """Test filtering with multiple criteria: project and priority"""
    # Create a project
    project = todoist_client.add_project(name="Important Project")

    # Create tasks with various priorities
    task_p1 = todoist_client.add_task(
        content="Normal in project",
        project_id=project.id,
        priority=1
    )
    task_p4 = todoist_client.add_task(
        content="Urgent in project",
        project_id=project.id,
        priority=4
    )
    task_p4_other = todoist_client.add_task(
        content="Urgent in other project",
        priority=4
    )

    # Get all p1 (filter language) = priority 4 (API) tasks and filter by project client-side
    all_p1_tasks = []
    for page in todoist_client.filter_tasks(query="p1"):
        all_p1_tasks.extend(page)

    # Filter to only include tasks in the specific project
    project_urgent_tasks = [t for t in all_p1_tasks if t.project_id == project.id]

    # Verify only urgent tasks in the project appear
    task_ids = [t.id for t in project_urgent_tasks]
    assert len(project_urgent_tasks) == 1
    assert task_p4.id in task_ids
    assert task_p1.id not in task_ids
    assert task_p4_other.id not in task_ids


def test_filter_with_completed_tasks_excluded(todoist_client: TodoistAPI):
    """Test that filters only apply to active tasks, not completed ones"""
    # Create a project
    project = todoist_client.add_project(name="Project")

    # Create tasks in the project
    active_task = todoist_client.add_task(
        content="Active task",
        project_id=project.id,
        labels=["test"]
    )
    completed_task = todoist_client.add_task(
        content="Completed task",
        project_id=project.id,
        labels=["test"]
    )

    # Complete one task
    todoist_client.complete_task(task_id=completed_task.id)

    # Filter by project
    project_tasks = []
    for page in todoist_client.get_tasks(project_id=project.id):
        project_tasks.extend(page)

    # Verify only active task appears
    task_ids = [t.id for t in project_tasks]
    assert len(project_tasks) == 1
    assert active_task.id in task_ids
    assert completed_task.id not in task_ids

    # Filter by label
    label_tasks = []
    for page in todoist_client.get_tasks(label="test"):
        label_tasks.extend(page)

    # Verify only active task appears
    task_ids = [t.id for t in label_tasks]
    assert len(label_tasks) == 1
    assert active_task.id in task_ids
    assert completed_task.id not in task_ids


def test_close_and_reopen_lifecycle(todoist_client: TodoistAPI):
    """Test complete lifecycle: create, close, reopen, verify in lists"""
    # Create a task with multiple properties
    project = todoist_client.add_project(name="Lifecycle Project")
    task = todoist_client.add_task(
        content="Lifecycle task",
        project_id=project.id,
        labels=["lifecycle", "test"],
        priority=4
    )

    # Verify it appears in various filtered lists
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)
    assert task.id in [t.id for t in all_tasks]

    project_tasks = []
    for page in todoist_client.get_tasks(project_id=project.id):
        project_tasks.extend(page)
    assert task.id in [t.id for t in project_tasks]

    # "p1" in filter language = API priority 4
    priority_tasks = []
    for page in todoist_client.filter_tasks(query="p1"):
        priority_tasks.extend(page)
    assert task.id in [t.id for t in priority_tasks]

    # Close the task
    todoist_client.complete_task(task_id=task.id)

    # Verify it's excluded from all filtered lists
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)
    assert task.id not in [t.id for t in all_tasks]

    project_tasks = []
    for page in todoist_client.get_tasks(project_id=project.id):
        project_tasks.extend(page)
    assert task.id not in [t.id for t in project_tasks]

    priority_tasks = []
    for page in todoist_client.filter_tasks(query="p1"):
        priority_tasks.extend(page)
    assert task.id not in [t.id for t in priority_tasks]

    # Reopen the task
    todoist_client.uncomplete_task(task_id=task.id)

    # Verify it reappears in all filtered lists
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)
    assert task.id in [t.id for t in all_tasks]

    project_tasks = []
    for page in todoist_client.get_tasks(project_id=project.id):
        project_tasks.extend(page)
    assert task.id in [t.id for t in project_tasks]

    priority_tasks = []
    for page in todoist_client.filter_tasks(query="p1"):
        priority_tasks.extend(page)
    assert task.id in [t.id for t in priority_tasks]


def test_close_task_with_recurring_due_date(todoist_client: TodoistAPI):
    """Test that closing a task with recurring due date reschedules it.

    In the real API, completing a recurring task doesn't permanently complete it.
    Instead it reschedules to the next occurrence and remains active.
    """
    # Create a recurring task
    task = todoist_client.add_task(
        content="Weekly meeting",
        due_string="every Monday"
    )

    # Close the task
    result = todoist_client.complete_task(task_id=task.id)
    assert result is True

    # Verify the task still exists and has a due date (rescheduled)
    rescheduled_task = todoist_client.get_task(task_id=task.id)
    # Recurring tasks get rescheduled, not permanently completed
    assert rescheduled_task.due is not None


def test_filter_tasks_with_no_matches(todoist_client: TodoistAPI):
    """Test filtering with criteria that match no tasks"""
    # Create a task with known properties
    project = todoist_client.add_project(name="FilterNoMatch")
    todoist_client.add_task(content="Test task", priority=1, project_id=project.id)

    # Filter by non-existent label
    tasks = []
    for page in todoist_client.get_tasks(label="nonexistent_label_xyz"):
        tasks.extend(page)
    assert len(tasks) == 0


def test_close_already_completed_task(todoist_client: TodoistAPI):
    """Test closing an already completed task (idempotent operation)"""
    # Create and close a task
    task = todoist_client.add_task(content="Task to close twice")
    todoist_client.complete_task(task_id=task.id)

    # Close it again (should be idempotent)
    result = todoist_client.complete_task(task_id=task.id)
    assert result is True

    # Verify it's still completed
    completed_task = todoist_client.get_task(task_id=task.id)
    assert completed_task.is_completed is True


def test_reopen_already_active_task(todoist_client: TodoistAPI):
    """Test reopening an already active task (idempotent operation)"""
    # Create a task (active by default)
    task = todoist_client.add_task(content="Active task")

    # Reopen it (should be idempotent)
    result = todoist_client.uncomplete_task(task_id=task.id)
    assert result is True

    # Verify it's still active
    active_task = todoist_client.get_task(task_id=task.id)
    assert active_task.is_completed is False


def test_filter_subtasks_by_parent(todoist_client: TodoistAPI):
    """Test filtering subtasks using parent_id"""
    # Create parent and subtasks
    parent = todoist_client.add_task(content="Parent task")
    subtask1 = todoist_client.add_task(content="Subtask 1", parent_id=parent.id)
    subtask2 = todoist_client.add_task(content="Subtask 2", parent_id=parent.id)
    other_task = todoist_client.add_task(content="Other task")

    # Filter by parent
    subtasks = []
    for page in todoist_client.get_tasks(parent_id=parent.id):
        subtasks.extend(page)

    # Verify only subtasks appear
    task_ids = [t.id for t in subtasks]
    assert len(subtasks) == 2
    assert subtask1.id in task_ids
    assert subtask2.id in task_ids
    assert parent.id not in task_ids
    assert other_task.id not in task_ids


def test_close_parent_task(todoist_client: TodoistAPI):
    """Test closing a parent task"""
    # Create parent and subtasks
    parent = todoist_client.add_task(content="Parent task")
    subtask1 = todoist_client.add_task(content="Subtask 1", parent_id=parent.id)
    subtask2 = todoist_client.add_task(content="Subtask 2", parent_id=parent.id)

    # Close the parent
    todoist_client.complete_task(task_id=parent.id)

    # Verify parent is completed
    parent_completed = todoist_client.get_task(task_id=parent.id)
    assert parent_completed.is_completed is True
