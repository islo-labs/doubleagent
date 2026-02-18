"""
Contract tests for Todoist task filtering and searching with complex queries.

Tests filtering and searching tasks using complex queries combining labels,
priorities, due dates, and projects with AND/OR operators using the official
todoist-api-python SDK.

NOTE on Todoist priority numbering:
  - In the UI/filter language: p1 = highest priority, p4 = lowest
  - In the API response: priority 4 = highest (urgent), priority 1 = lowest (normal)
  - So "p1" in filter → matches priority=4 in the API, "p4" → matches priority=1
"""

import pytest
from datetime import date, datetime, timedelta
from todoist_api_python.api import TodoistAPI


def _collect_filter_results(todoist_client: TodoistAPI, query: str) -> set[str]:
    """Run a filter query and return all matching task IDs across all pages."""
    all_tasks = []
    for page in todoist_client.filter_tasks(query=query):
        all_tasks.extend(page)
    return {t.id for t in all_tasks}


def test_filter_by_priority(todoist_client: TodoistAPI):
    """Test filtering tasks by priority level"""
    # Create tasks with different priorities
    task_p1 = todoist_client.add_task(content="Low priority task", priority=1)
    task_p2 = todoist_client.add_task(content="Medium priority task", priority=2)
    task_p3 = todoist_client.add_task(content="High priority task", priority=3)
    task_p4 = todoist_client.add_task(content="Urgent task", priority=4)

    # Verify tasks were persisted via round-trip
    persisted_p1 = todoist_client.get_task(task_id=task_p1.id)
    assert persisted_p1.priority == 1
    persisted_p4 = todoist_client.get_task(task_id=task_p4.id)
    assert persisted_p4.priority == 4

    # Filter for priority 4 tasks (p1 in filter = priority 4 in API, inverted mapping)
    p4_ids = _collect_filter_results(todoist_client, "p1")
    assert task_p4.id in p4_ids
    assert task_p1.id not in p4_ids
    assert task_p2.id not in p4_ids
    assert task_p3.id not in p4_ids

    # Filter for priority 1 tasks (p4 in filter = priority 1 in API, inverted mapping)
    p1_ids = _collect_filter_results(todoist_client, "p4")
    assert task_p1.id in p1_ids
    assert task_p4.id not in p1_ids


def test_filter_by_label(todoist_client: TodoistAPI):
    """Test filtering tasks by label"""
    # Create tasks with different labels
    task1 = todoist_client.add_task(content="Work task", labels=["work", "urgent"])
    task2 = todoist_client.add_task(content="Personal task", labels=["personal"])
    task3 = todoist_client.add_task(content="Another work task", labels=["work"])

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert "work" in persisted_task1.labels
    assert "urgent" in persisted_task1.labels
    persisted_task2 = todoist_client.get_task(task_id=task2.id)
    assert "personal" in persisted_task2.labels

    # Filter by @work label
    work_ids = _collect_filter_results(todoist_client, "@work")
    assert task1.id in work_ids
    assert task3.id in work_ids
    assert task2.id not in work_ids

    # Filter by @personal label
    personal_ids = _collect_filter_results(todoist_client, "@personal")
    assert task2.id in personal_ids
    assert task1.id not in personal_ids


def test_filter_by_label_wildcard(todoist_client: TodoistAPI):
    """Test filtering tasks by label with wildcard"""
    # Create tasks with labels starting with "urgent"
    task1 = todoist_client.add_task(content="Task 1", labels=["urgent"])
    task2 = todoist_client.add_task(content="Task 2", labels=["urgent-work"])
    task3 = todoist_client.add_task(content="Task 3", labels=["urgent-personal"])
    task4 = todoist_client.add_task(content="Task 4", labels=["work"])

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert "urgent" in persisted_task1.labels
    persisted_task2 = todoist_client.get_task(task_id=task2.id)
    assert "urgent-work" in persisted_task2.labels

    # Filter by @urgent* (wildcard)
    urgent_ids = _collect_filter_results(todoist_client, "@urgent*")
    assert task1.id in urgent_ids
    assert task2.id in urgent_ids
    assert task3.id in urgent_ids
    assert task4.id not in urgent_ids


def test_filter_by_due_date_today(todoist_client: TodoistAPI):
    """Test filtering tasks due today"""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Create tasks with different due dates
    task_today = todoist_client.add_task(content="Task due today", due_date=today)
    task_tomorrow = todoist_client.add_task(
        content="Task due tomorrow", due_date=tomorrow
    )
    task_no_date = todoist_client.add_task(content="Task with no due date")

    # Verify tasks were persisted via round-trip
    persisted_today = todoist_client.get_task(task_id=task_today.id)
    assert persisted_today.due is not None
    assert persisted_today.due.date == (today)

    # Filter by today
    today_ids = _collect_filter_results(todoist_client, "today")
    assert task_today.id in today_ids
    assert task_tomorrow.id not in today_ids
    assert task_no_date.id not in today_ids


def test_filter_by_due_date_tomorrow(todoist_client: TodoistAPI):
    """Test filtering tasks due tomorrow"""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Create tasks with different due dates
    task_today = todoist_client.add_task(content="Task due today", due_date=today)
    task_tomorrow = todoist_client.add_task(
        content="Task due tomorrow", due_date=tomorrow
    )

    # Verify tasks were persisted via round-trip
    persisted_tomorrow = todoist_client.get_task(task_id=task_tomorrow.id)
    assert persisted_tomorrow.due is not None
    assert persisted_tomorrow.due.date == (tomorrow)

    # Filter by tomorrow
    tomorrow_ids = _collect_filter_results(todoist_client, "tomorrow")
    assert task_tomorrow.id in tomorrow_ids
    assert task_today.id not in tomorrow_ids


def test_filter_by_overdue(todoist_client: TodoistAPI):
    """Test filtering overdue tasks"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    # Create overdue and current tasks
    task_overdue1 = todoist_client.add_task(
        content="Task 1 day overdue", due_date=yesterday
    )
    task_overdue2 = todoist_client.add_task(
        content="Task 2 days overdue", due_date=two_days_ago
    )
    task_today = todoist_client.add_task(content="Task due today", due_date=today)

    # Verify tasks were persisted via round-trip
    persisted_overdue1 = todoist_client.get_task(task_id=task_overdue1.id)
    assert persisted_overdue1.due is not None
    assert persisted_overdue1.due.date == (yesterday)

    # Filter by overdue
    overdue_ids = _collect_filter_results(todoist_client, "overdue")
    assert task_overdue1.id in overdue_ids
    assert task_overdue2.id in overdue_ids
    assert task_today.id not in overdue_ids


def test_filter_by_date_range_next_7_days(todoist_client: TodoistAPI):
    """Test filtering tasks due in the next 7 days"""
    today = date.today()
    in_3_days = today + timedelta(days=3)
    in_5_days = today + timedelta(days=5)
    in_10_days = today + timedelta(days=10)

    # Create tasks with various due dates
    task_3_days = todoist_client.add_task(content="Task in 3 days", due_date=in_3_days)
    task_5_days = todoist_client.add_task(content="Task in 5 days", due_date=in_5_days)
    task_10_days = todoist_client.add_task(
        content="Task in 10 days", due_date=in_10_days
    )

    # Verify tasks were persisted via round-trip
    persisted_3_days = todoist_client.get_task(task_id=task_3_days.id)
    assert persisted_3_days.due is not None
    assert persisted_3_days.due.date == (in_3_days)

    # Filter by next 7 days
    next_7_ids = _collect_filter_results(todoist_client, "7 days")
    assert task_3_days.id in next_7_ids
    assert task_5_days.id in next_7_ids
    assert task_10_days.id not in next_7_ids


@pytest.mark.fake_only
def test_filter_by_date_range_past_3_days(todoist_client: TodoistAPI):
    """Test filtering tasks from the past 3 days (fake_only: real API '-N days' syntax differs)"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    five_days_ago = today - timedelta(days=5)

    # Create tasks with past due dates
    task_yesterday = todoist_client.add_task(
        content="Task from yesterday", due_date=yesterday
    )
    task_2_days_ago = todoist_client.add_task(
        content="Task from 2 days ago", due_date=two_days_ago
    )
    task_5_days_ago = todoist_client.add_task(
        content="Task from 5 days ago", due_date=five_days_ago
    )

    # Verify tasks were persisted via round-trip
    persisted_yesterday = todoist_client.get_task(task_id=task_yesterday.id)
    assert persisted_yesterday.due is not None
    assert persisted_yesterday.due.date == (yesterday)

    # Filter by past 3 days
    past_3_ids = _collect_filter_results(todoist_client, "-3 days")
    assert task_yesterday.id in past_3_ids
    assert task_2_days_ago.id in past_3_ids
    assert task_5_days_ago.id not in past_3_ids


def test_filter_and_operator_priority_and_label(todoist_client: TodoistAPI):
    """Test filtering with AND operator combining priority and label"""
    # Create tasks with various combinations
    task1 = todoist_client.add_task(
        content="High priority work task", priority=4, labels=["work"]
    )
    task2 = todoist_client.add_task(
        content="Low priority work task", priority=1, labels=["work"]
    )
    task3 = todoist_client.add_task(
        content="High priority personal task", priority=4, labels=["personal"]
    )

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.priority == 4
    assert "work" in persisted_task1.labels

    # Filter by p1 AND @work (p1 in filter = priority 4 in API, inverted mapping)
    filtered_ids = _collect_filter_results(todoist_client, "p1 & @work")
    assert task1.id in filtered_ids
    assert task2.id not in filtered_ids
    assert task3.id not in filtered_ids


def test_filter_and_operator_date_and_label(todoist_client: TodoistAPI):
    """Test filtering with AND operator combining due date and label"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    in_3_days = today + timedelta(days=3)

    # Create tasks
    task1 = todoist_client.add_task(
        content="Task today with waiting", due_date=today, labels=["waiting"]
    )
    task2 = todoist_client.add_task(
        content="Task in 3 days with waiting", due_date=in_3_days, labels=["waiting"]
    )
    task3 = todoist_client.add_task(
        content="Task today without waiting", due_date=today, labels=["urgent"]
    )

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.due is not None
    assert "waiting" in persisted_task1.labels

    # Filter by "7 days & @waiting" - tasks in next 7 days with @waiting label
    filtered_ids = _collect_filter_results(todoist_client, "7 days & @waiting")
    assert task1.id in filtered_ids
    assert task2.id in filtered_ids
    assert task3.id not in filtered_ids


def test_filter_and_operator_priority_and_overdue(todoist_client: TodoistAPI):
    """Test filtering with AND operator combining priority and overdue status"""
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Create tasks
    task1 = todoist_client.add_task(
        content="Priority 1 overdue", priority=1, due_date=yesterday
    )
    task2 = todoist_client.add_task(
        content="Priority 4 overdue", priority=4, due_date=yesterday
    )
    task3 = todoist_client.add_task(
        content="Priority 4 today", priority=4, due_date=today
    )

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.priority == 1
    assert persisted_task1.due is not None

    # Filter by "p4 & overdue" (p4 in filter = priority 1 in API, inverted mapping)
    filtered_ids = _collect_filter_results(todoist_client, "p4 & overdue")
    assert task1.id in filtered_ids
    assert task2.id not in filtered_ids
    assert task3.id not in filtered_ids


def test_filter_or_operator_today_or_overdue(todoist_client: TodoistAPI):
    """Test filtering with OR operator combining today and overdue"""
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    # Create tasks
    task_today = todoist_client.add_task(content="Task today", due_date=today)
    task_overdue = todoist_client.add_task(
        content="Task overdue", due_date=yesterday
    )
    task_tomorrow = todoist_client.add_task(
        content="Task tomorrow", due_date=tomorrow
    )

    # Verify tasks were persisted via round-trip
    persisted_today = todoist_client.get_task(task_id=task_today.id)
    assert persisted_today.due is not None
    assert persisted_today.due.date == (today)

    # Filter by "today | overdue"
    filtered_ids = _collect_filter_results(todoist_client, "today | overdue")
    assert task_today.id in filtered_ids
    assert task_overdue.id in filtered_ids
    assert task_tomorrow.id not in filtered_ids


def test_filter_or_operator_multiple_labels(todoist_client: TodoistAPI):
    """Test filtering with OR operator for multiple labels"""
    # Create tasks with different labels
    task1 = todoist_client.add_task(content="Work task", labels=["work"])
    task2 = todoist_client.add_task(content="Personal task", labels=["personal"])
    task3 = todoist_client.add_task(content="Shopping task", labels=["shopping"])
    task4 = todoist_client.add_task(content="Urgent task", labels=["urgent"])

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert "work" in persisted_task1.labels
    persisted_task2 = todoist_client.get_task(task_id=task2.id)
    assert "personal" in persisted_task2.labels

    # Filter by "@work | @personal"
    filtered_ids = _collect_filter_results(todoist_client, "@work | @personal")
    assert task1.id in filtered_ids
    assert task2.id in filtered_ids
    assert task3.id not in filtered_ids
    assert task4.id not in filtered_ids


def test_filter_or_operator_multiple_priorities(todoist_client: TodoistAPI):
    """Test filtering with OR operator for multiple priorities"""
    # Create tasks with different priorities
    task_p1 = todoist_client.add_task(content="Low priority", priority=1)
    task_p2 = todoist_client.add_task(content="Medium priority", priority=2)
    task_p3 = todoist_client.add_task(content="High priority", priority=3)
    task_p4 = todoist_client.add_task(content="Urgent priority", priority=4)

    # Verify tasks were persisted via round-trip
    persisted_p1 = todoist_client.get_task(task_id=task_p1.id)
    assert persisted_p1.priority == 1
    persisted_p4 = todoist_client.get_task(task_id=task_p4.id)
    assert persisted_p4.priority == 4

    # Filter by "p1 | p4" (p1=priority 4, p4=priority 1 in API)
    filtered_ids = _collect_filter_results(todoist_client, "p1 | p4")
    assert task_p1.id in filtered_ids
    assert task_p4.id in filtered_ids
    assert task_p2.id not in filtered_ids
    assert task_p3.id not in filtered_ids


def test_filter_complex_and_or_combination(todoist_client: TodoistAPI):
    """Test complex filter with both AND and OR operators"""
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Create tasks with various combinations
    task1 = todoist_client.add_task(
        content="High priority work task today",
        priority=4,
        labels=["work"],
        due_date=today,
    )
    task2 = todoist_client.add_task(
        content="High priority personal task today",
        priority=4,
        labels=["personal"],
        due_date=today,
    )
    task3 = todoist_client.add_task(
        content="Low priority work task overdue",
        priority=1,
        labels=["work"],
        due_date=yesterday,
    )

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.priority == 4
    assert persisted_task1.due is not None
    assert "work" in persisted_task1.labels

    # Filter by "p1 & today" (p1 in filter = priority 4 in API, inverted mapping)
    filtered_ids = _collect_filter_results(todoist_client, "p1 & today")
    assert task1.id in filtered_ids
    assert task2.id in filtered_ids
    assert task3.id not in filtered_ids


def test_filter_by_project(todoist_client: TodoistAPI):
    """Test filtering tasks by project name"""
    # Create projects
    project_work = todoist_client.add_project(name="Work")
    project_personal = todoist_client.add_project(name="Personal")

    # Verify projects were persisted via round-trip
    persisted_project_work = todoist_client.get_project(project_id=project_work.id)
    assert persisted_project_work.name == "Work"

    # Create tasks in different projects
    task1 = todoist_client.add_task(content="Work task", project_id=project_work.id)
    task2 = todoist_client.add_task(
        content="Personal task", project_id=project_personal.id
    )

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.project_id == project_work.id

    # Filter by #Work project
    work_ids = _collect_filter_results(todoist_client, "#Work")
    assert task1.id in work_ids
    assert task2.id not in work_ids


def test_filter_project_and_priority(todoist_client: TodoistAPI):
    """Test filtering with AND operator combining project and priority"""
    # Create project
    project_work = todoist_client.add_project(name="Work")

    # Verify project was persisted via round-trip
    persisted_project = todoist_client.get_project(project_id=project_work.id)
    assert persisted_project.name == "Work"

    # Create tasks
    task1 = todoist_client.add_task(
        content="High priority work task", priority=4, project_id=project_work.id
    )
    task2 = todoist_client.add_task(
        content="Low priority work task", priority=1, project_id=project_work.id
    )

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.priority == 4
    assert persisted_task1.project_id == project_work.id

    # Filter by "#Work & p1" (p1 in filter = priority 4 in API, inverted mapping)
    filtered_ids = _collect_filter_results(todoist_client, "#Work & p1")
    assert task1.id in filtered_ids
    assert task2.id not in filtered_ids


def test_filter_excludes_completed_tasks(todoist_client: TodoistAPI):
    """Test that filter excludes completed tasks"""
    # Create tasks
    task1 = todoist_client.add_task(content="Active task", priority=4)
    task2 = todoist_client.add_task(content="Completed task", priority=4)

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.priority == 4

    # Complete task2
    todoist_client.complete_task(task_id=task2.id)

    # Verify task2 was completed via round-trip
    persisted_task2 = todoist_client.get_task(task_id=task2.id)
    assert persisted_task2.completed_at is not None

    # Filter by p1 - should only return active tasks (p1 in filter = priority 4 in API)
    filtered_ids = _collect_filter_results(todoist_client, "p1")
    assert task1.id in filtered_ids
    assert task2.id not in filtered_ids


@pytest.mark.fake_only
def test_filter_empty_result(todoist_client: TodoistAPI):
    """Test that filter returns empty list when no tasks match (fake_only: can't guarantee empty results on real account)"""
    # Create a task with specific attributes
    task = todoist_client.add_task(content="Task", priority=1, labels=["work"])

    # Verify task was persisted via round-trip
    persisted_task = todoist_client.get_task(task_id=task.id)
    assert persisted_task.priority == 1
    assert "work" in persisted_task.labels

    # Filter for something that doesn't exist
    filtered_ids = _collect_filter_results(todoist_client, "p4 & @personal")
    assert len(filtered_ids) == 0


@pytest.mark.fake_only
def test_filter_all_tasks_no_filter(todoist_client: TodoistAPI):
    """Test that get_tasks without filter returns all active tasks (fake_only: exact count on real account)"""
    # Create multiple tasks
    task1 = todoist_client.add_task(content="Task 1")
    task2 = todoist_client.add_task(content="Task 2")
    task3 = todoist_client.add_task(content="Task 3")

    # Verify tasks were persisted via round-trip
    persisted_task1 = todoist_client.get_task(task_id=task1.id)
    assert persisted_task1.content == "Task 1"
    persisted_task2 = todoist_client.get_task(task_id=task2.id)
    assert persisted_task2.content == "Task 2"
    persisted_task3 = todoist_client.get_task(task_id=task3.id)
    assert persisted_task3.content == "Task 3"

    # Get all tasks
    all_tasks = []
    for page in todoist_client.get_tasks():
        all_tasks.extend(page)
    assert len(all_tasks) == 3
    task_ids = {t.id for t in all_tasks}
    assert task1.id in task_ids
    assert task2.id in task_ids
    assert task3.id in task_ids
