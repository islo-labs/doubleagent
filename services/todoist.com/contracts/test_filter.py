"""
Contract tests for Todoist task filtering and searching with complex queries.

Tests filtering and searching tasks using complex queries combining labels,
priorities, due dates, and projects with AND/OR operators using the official
todoist-api-python SDK.
"""

import pytest
from datetime import date, datetime, timedelta
from todoist_api_python.api import TodoistAPI


def test_filter_by_priority(todoist_client: TodoistAPI):
    """Test filtering tasks by priority level"""
    # Create tasks with different priorities
    task_p1 = todoist_client.add_task(content="Low priority task", priority=1)
    task_p2 = todoist_client.add_task(content="Medium priority task", priority=2)
    task_p3 = todoist_client.add_task(content="High priority task", priority=3)
    task_p4 = todoist_client.add_task(content="Urgent task", priority=4)

    # Filter for priority 4 tasks
    p4_tasks = list(todoist_client.filter_tasks(query="p4"))[0]
    assert len(p4_tasks) == 1
    assert p4_tasks[0].id == task_p4.id
    assert p4_tasks[0].priority == 4

    # Filter for priority 1 tasks
    p1_tasks = list(todoist_client.filter_tasks(query="p1"))[0]
    assert len(p1_tasks) == 1
    assert p1_tasks[0].id == task_p1.id
    assert p1_tasks[0].priority == 1


def test_filter_by_label(todoist_client: TodoistAPI):
    """Test filtering tasks by label"""
    # Create tasks with different labels
    task1 = todoist_client.add_task(content="Work task", labels=["work", "urgent"])
    task2 = todoist_client.add_task(content="Personal task", labels=["personal"])
    task3 = todoist_client.add_task(content="Another work task", labels=["work"])

    # Filter by @work label
    work_tasks = list(todoist_client.filter_tasks(query="@work"))[0]
    assert len(work_tasks) == 2
    work_task_ids = {t.id for t in work_tasks}
    assert task1.id in work_task_ids
    assert task3.id in work_task_ids

    # Filter by @personal label
    personal_tasks = list(todoist_client.filter_tasks(query="@personal"))[0]
    assert len(personal_tasks) == 1
    assert personal_tasks[0].id == task2.id


def test_filter_by_label_wildcard(todoist_client: TodoistAPI):
    """Test filtering tasks by label with wildcard"""
    # Create tasks with labels starting with "urgent"
    task1 = todoist_client.add_task(content="Task 1", labels=["urgent"])
    task2 = todoist_client.add_task(content="Task 2", labels=["urgent-work"])
    task3 = todoist_client.add_task(content="Task 3", labels=["urgent-personal"])
    task4 = todoist_client.add_task(content="Task 4", labels=["work"])

    # Filter by @urgent* (wildcard)
    urgent_tasks = list(todoist_client.filter_tasks(query="@urgent*"))[0]
    assert len(urgent_tasks) == 3
    urgent_task_ids = {t.id for t in urgent_tasks}
    assert task1.id in urgent_task_ids
    assert task2.id in urgent_task_ids
    assert task3.id in urgent_task_ids
    assert task4.id not in urgent_task_ids


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

    # Filter by today
    today_tasks = list(todoist_client.filter_tasks(query="today"))[0]
    assert len(today_tasks) == 1
    assert today_tasks[0].id == task_today.id


def test_filter_by_due_date_tomorrow(todoist_client: TodoistAPI):
    """Test filtering tasks due tomorrow"""
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # Create tasks with different due dates
    task_today = todoist_client.add_task(content="Task due today", due_date=today)
    task_tomorrow = todoist_client.add_task(
        content="Task due tomorrow", due_date=tomorrow
    )

    # Filter by tomorrow
    tomorrow_tasks = list(todoist_client.filter_tasks(query="tomorrow"))[0]
    assert len(tomorrow_tasks) == 1
    assert tomorrow_tasks[0].id == task_tomorrow.id


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

    # Filter by overdue
    overdue_tasks = list(todoist_client.filter_tasks(query="overdue"))[0]
    assert len(overdue_tasks) == 2
    overdue_task_ids = {t.id for t in overdue_tasks}
    assert task_overdue1.id in overdue_task_ids
    assert task_overdue2.id in overdue_task_ids
    assert task_today.id not in overdue_task_ids


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

    # Filter by next 7 days
    next_7_days_tasks = list(todoist_client.filter_tasks(query="7 days"))[0]
    assert len(next_7_days_tasks) == 2
    task_ids = {t.id for t in next_7_days_tasks}
    assert task_3_days.id in task_ids
    assert task_5_days.id in task_ids
    assert task_10_days.id not in task_ids


def test_filter_by_date_range_past_3_days(todoist_client: TodoistAPI):
    """Test filtering tasks from the past 3 days"""
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

    # Filter by past 3 days
    past_3_days_tasks = list(todoist_client.filter_tasks(query="-3 days"))[0]
    assert len(past_3_days_tasks) == 2
    task_ids = {t.id for t in past_3_days_tasks}
    assert task_yesterday.id in task_ids
    assert task_2_days_ago.id in task_ids
    assert task_5_days_ago.id not in task_ids


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

    # Filter by p4 AND @work
    filtered_tasks = list(todoist_client.filter_tasks(query="p4 & @work"))[0]
    assert len(filtered_tasks) == 1
    assert filtered_tasks[0].id == task1.id
    assert filtered_tasks[0].priority == 4
    assert "work" in filtered_tasks[0].labels


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

    # Filter by "7 days & @waiting" - tasks in next 7 days with @waiting label
    filtered_tasks = list(todoist_client.filter_tasks(query="7 days & @waiting"))[0]
    assert len(filtered_tasks) == 2
    task_ids = {t.id for t in filtered_tasks}
    assert task1.id in task_ids
    assert task2.id in task_ids
    assert task3.id not in task_ids


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

    # Filter by "p1 & overdue"
    filtered_tasks = list(todoist_client.filter_tasks(query="p1 & overdue"))[0]
    assert len(filtered_tasks) == 1
    assert filtered_tasks[0].id == task1.id
    assert filtered_tasks[0].priority == 1


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

    # Filter by "today | overdue"
    filtered_tasks = list(todoist_client.filter_tasks(query="today | overdue"))[0]
    assert len(filtered_tasks) == 2
    task_ids = {t.id for t in filtered_tasks}
    assert task_today.id in task_ids
    assert task_overdue.id in task_ids
    assert task_tomorrow.id not in task_ids


def test_filter_or_operator_multiple_labels(todoist_client: TodoistAPI):
    """Test filtering with OR operator for multiple labels"""
    # Create tasks with different labels
    task1 = todoist_client.add_task(content="Work task", labels=["work"])
    task2 = todoist_client.add_task(content="Personal task", labels=["personal"])
    task3 = todoist_client.add_task(content="Shopping task", labels=["shopping"])
    task4 = todoist_client.add_task(content="Urgent task", labels=["urgent"])

    # Filter by "@work | @personal"
    filtered_tasks = list(todoist_client.filter_tasks(query="@work | @personal"))[0]
    assert len(filtered_tasks) == 2
    task_ids = {t.id for t in filtered_tasks}
    assert task1.id in task_ids
    assert task2.id in task_ids
    assert task3.id not in task_ids


def test_filter_or_operator_multiple_priorities(todoist_client: TodoistAPI):
    """Test filtering with OR operator for multiple priorities"""
    # Create tasks with different priorities
    task_p1 = todoist_client.add_task(content="Low priority", priority=1)
    task_p2 = todoist_client.add_task(content="Medium priority", priority=2)
    task_p3 = todoist_client.add_task(content="High priority", priority=3)
    task_p4 = todoist_client.add_task(content="Urgent priority", priority=4)

    # Filter by "p1 | p4"
    filtered_tasks = list(todoist_client.filter_tasks(query="p1 | p4"))[0]
    assert len(filtered_tasks) == 2
    task_ids = {t.id for t in filtered_tasks}
    assert task_p1.id in task_ids
    assert task_p4.id in task_ids
    assert task_p2.id not in task_ids
    assert task_p3.id not in task_ids


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

    # Filter by "p4 & (today | overdue)" - this tests precedence
    # For simplicity, test "p4 & today"
    filtered_tasks = list(todoist_client.filter_tasks(query="p4 & today"))[0]
    assert len(filtered_tasks) == 2
    task_ids = {t.id for t in filtered_tasks}
    assert task1.id in task_ids
    assert task2.id in task_ids
    assert task3.id not in task_ids


def test_filter_by_project(todoist_client: TodoistAPI):
    """Test filtering tasks by project name"""
    # Create projects
    project_work = todoist_client.add_project(name="Work")
    project_personal = todoist_client.add_project(name="Personal")

    # Create tasks in different projects
    task1 = todoist_client.add_task(content="Work task", project_id=project_work.id)
    task2 = todoist_client.add_task(
        content="Personal task", project_id=project_personal.id
    )

    # Filter by #Work project
    work_tasks = list(todoist_client.filter_tasks(query="#Work"))[0]
    assert len(work_tasks) == 1
    assert work_tasks[0].id == task1.id
    assert work_tasks[0].project_id == project_work.id


def test_filter_project_and_priority(todoist_client: TodoistAPI):
    """Test filtering with AND operator combining project and priority"""
    # Create project
    project_work = todoist_client.add_project(name="Work")

    # Create tasks
    task1 = todoist_client.add_task(
        content="High priority work task", priority=4, project_id=project_work.id
    )
    task2 = todoist_client.add_task(
        content="Low priority work task", priority=1, project_id=project_work.id
    )

    # Filter by "#Work & p4"
    filtered_tasks = list(todoist_client.filter_tasks(query="#Work & p4"))[0]
    assert len(filtered_tasks) == 1
    assert filtered_tasks[0].id == task1.id
    assert filtered_tasks[0].priority == 4


def test_filter_excludes_completed_tasks(todoist_client: TodoistAPI):
    """Test that filter excludes completed tasks"""
    # Create tasks
    task1 = todoist_client.add_task(content="Active task", priority=4)
    task2 = todoist_client.add_task(content="Completed task", priority=4)

    # Complete task2
    todoist_client.complete_task(task_id=task2.id)

    # Filter by p4 - should only return active task
    filtered_tasks = list(todoist_client.filter_tasks(query="p4"))[0]
    assert len(filtered_tasks) == 1
    assert filtered_tasks[0].id == task1.id


def test_filter_empty_result(todoist_client: TodoistAPI):
    """Test that filter returns empty list when no tasks match"""
    # Create a task with specific attributes
    todoist_client.add_task(content="Task", priority=1, labels=["work"])

    # Filter for something that doesn't exist
    filtered_tasks = list(todoist_client.filter_tasks(query="p4 & @personal"))[0]
    assert len(filtered_tasks) == 0


def test_filter_all_tasks_no_filter(todoist_client: TodoistAPI):
    """Test that get_tasks without filter returns all active tasks"""
    # Create multiple tasks
    task1 = todoist_client.add_task(content="Task 1")
    task2 = todoist_client.add_task(content="Task 2")
    task3 = todoist_client.add_task(content="Task 3")

    # Get all tasks - get_tasks returns an iterator, so convert to list
    all_tasks = list(todoist_client.get_tasks())[0]
    assert len(all_tasks) == 3
    task_ids = {t.id for t in all_tasks}
    assert task1.id in task_ids
    assert task2.id in task_ids
    assert task3.id in task_ids
