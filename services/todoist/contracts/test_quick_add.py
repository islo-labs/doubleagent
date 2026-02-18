"""
Contract tests for Todoist Quick Add natural language processing.

Tests the complete flow of natural language task entry with automatic parsing
of due dates, priorities, project assignments, and labels from task descriptions
using the official todoist-api-python SDK.

NOTE on Todoist priority numbering:
  - In the UI/natural language: p1 = highest priority, p4 = lowest
  - In the API response: priority 4 = highest (urgent), priority 1 = lowest (normal)
  - So "p1" in quick add text → priority=4 in the API, "p4" → priority=1

NOTE on @labels in quick add:
  The real Todoist API does NOT strip @label tokens from the content text.
  Labels mentioned with @ syntax remain in the content string.
"""

import pytest
from datetime import date, timedelta
from todoist_api_python.api import TodoistAPI


def test_quick_add_basic_task(todoist_client: TodoistAPI):
    """Test quick add with basic task content"""
    task = todoist_client.add_task_quick(text="Buy milk")

    assert task.content == "Buy milk"
    assert task.priority == 1
    assert task.id is not None

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Buy milk"
    assert retrieved_task.priority == 1


def test_quick_add_task_with_project(todoist_client: TodoistAPI):
    """Test quick add with project assignment using #project syntax"""
    # First create a project
    project = todoist_client.add_project(name="Shopping")

    # Quick add task with project
    task = todoist_client.add_task_quick(text="Buy groceries #Shopping")

    assert task.content == "Buy groceries"
    assert task.project_id == project.id
    assert "#Shopping" not in task.content

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Buy groceries"
    assert retrieved_task.project_id == project.id


def test_quick_add_task_with_single_label(todoist_client: TodoistAPI):
    """Test quick add with @label syntax — real API keeps @label in content, labels list is empty"""
    task = todoist_client.add_task_quick(text="Buy milk @groceries")

    assert task.content == "Buy milk @groceries"
    assert task.labels == []

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Buy milk @groceries"
    assert retrieved_task.labels == []


def test_quick_add_task_with_multiple_labels(todoist_client: TodoistAPI):
    """Test quick add with multiple @labels — real API keeps them in content"""
    task = todoist_client.add_task_quick(text="Finish report @work @urgent @deadline")

    assert task.content == "Finish report @work @urgent @deadline"
    assert task.labels == []

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Finish report @work @urgent @deadline"
    assert retrieved_task.labels == []


def test_quick_add_task_with_priority_p1(todoist_client: TodoistAPI):
    """Test quick add with priority level p1 (highest → API priority 4)"""
    task = todoist_client.add_task_quick(text="Regular task p1")

    assert task.content == "Regular task"
    assert task.priority == 4

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 4


def test_quick_add_task_with_priority_p2(todoist_client: TodoistAPI):
    """Test quick add with priority level p2 (→ API priority 3)"""
    task = todoist_client.add_task_quick(text="Medium priority task p2")

    assert task.content == "Medium priority task"
    assert task.priority == 3

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 3


def test_quick_add_task_with_priority_p3(todoist_client: TodoistAPI):
    """Test quick add with priority level p3 (→ API priority 2)"""
    task = todoist_client.add_task_quick(text="High priority task p3")

    assert task.content == "High priority task"
    assert task.priority == 2

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 2


def test_quick_add_task_with_priority_p4(todoist_client: TodoistAPI):
    """Test quick add with priority level p4 (lowest → API priority 1)"""
    task = todoist_client.add_task_quick(text="Urgent task p4")

    assert task.content == "Urgent task"
    assert task.priority == 1

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 1


def test_quick_add_task_with_due_date_today(todoist_client: TodoistAPI):
    """Test quick add with 'today' due date"""
    task = todoist_client.add_task_quick(text="Complete report today")

    assert task.content == "Complete report"
    assert task.due is not None
    # Real API normalizes the due string to an absolute date
    assert task.due.date == date.today()

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert retrieved_task.due.date == date.today()


def test_quick_add_task_with_due_date_tomorrow(todoist_client: TodoistAPI):
    """Test quick add with 'tomorrow' due date"""
    task = todoist_client.add_task_quick(text="Call dentist tomorrow")

    assert task.content == "Call dentist"
    assert task.due is not None
    tomorrow = date.today() + timedelta(days=1)
    assert task.due.date == tomorrow

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert retrieved_task.due.date == tomorrow


def test_quick_add_task_with_due_datetime(todoist_client: TodoistAPI):
    """Test quick add with specific time"""
    task = todoist_client.add_task_quick(text="Meeting tomorrow at 3pm")

    assert task.content == "Meeting"
    assert task.due is not None
    # The due date should be tomorrow
    tomorrow = date.today() + timedelta(days=1)
    assert task.due.date.date() == tomorrow

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert retrieved_task.due.date.date() == tomorrow


def test_quick_add_task_with_recurring_pattern(todoist_client: TodoistAPI):
    """Test quick add with recurring due date pattern"""
    task = todoist_client.add_task_quick(text="Weekly meeting every Monday")

    assert task.content == "Weekly meeting"
    assert task.due is not None
    assert task.due.string == "every Monday"
    assert task.due.is_recurring is True

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Weekly meeting"
    assert retrieved_task.due is not None
    assert retrieved_task.due.string == "every Monday"
    assert retrieved_task.due.is_recurring is True


def test_quick_add_task_with_next_pattern(todoist_client: TodoistAPI):
    """Test quick add with 'next' date pattern"""
    task = todoist_client.add_task_quick(text="Review budget next Friday")

    assert task.content == "Review budget"
    assert task.due is not None
    # The due date should be on a Friday
    assert task.due.date.weekday() == 4  # Friday

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert retrieved_task.due.date.weekday() == 4


def test_quick_add_task_with_assignee(todoist_client: TodoistAPI):
    """Test quick add with +assignee syntax — real API keeps it in content"""
    task = todoist_client.add_task_quick(text="Delegate task +Alice")

    assert task.content == "Delegate task +Alice"

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Delegate task +Alice"


def test_quick_add_task_with_all_features(todoist_client: TodoistAPI):
    """Test quick add with project, priority, and due date combined"""
    # Create a project first
    project = todoist_client.add_project(name="WorkProject")

    task = todoist_client.add_task_quick(
        text="Submit report #WorkProject p3 tomorrow at 4pm"
    )

    assert "Submit report" in task.content
    assert task.project_id == project.id
    # p3 in natural language → priority 2 in API
    assert task.priority == 2
    assert task.due is not None
    tomorrow = date.today() + timedelta(days=1)
    assert task.due.date.date() == tomorrow

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert "Submit report" in retrieved_task.content
    assert retrieved_task.project_id == project.id
    assert retrieved_task.priority == 2
    assert retrieved_task.due is not None
    assert retrieved_task.due.date.date() == tomorrow


def test_quick_add_task_with_note(todoist_client: TodoistAPI):
    """Test quick add with note parameter — real API ignores it"""
    task = todoist_client.add_task_quick(
        text="Buy groceries",
        note="Don't forget milk, eggs, and bread",
    )

    assert task.content == "Buy groceries"
    # Real API ignores the note parameter
    assert task.description == ""

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Buy groceries"
    assert retrieved_task.description == ""


def test_quick_add_task_appears_in_rest_api(todoist_client: TodoistAPI):
    """Test that quick add tasks appear in REST API task list"""
    # Create task via quick add
    quick_task = todoist_client.add_task_quick(text="Test task p2")

    # Retrieve via REST API
    rest_task = todoist_client.get_task(task_id=quick_task.id)

    assert rest_task is not None
    assert rest_task.id == quick_task.id
    assert "Test task" in rest_task.content
    # p2 in NL → priority 3 in API
    assert rest_task.priority == 3


def test_quick_add_task_multiple_tasks(todoist_client: TodoistAPI):
    """Test creating multiple tasks via quick add"""
    # Create first task
    task1 = todoist_client.add_task_quick(text="First task")

    # Create second task
    task2 = todoist_client.add_task_quick(text="Second task")

    assert task1.id != task2.id
    assert "First task" in task1.content
    assert "Second task" in task2.content

    # Verify round-trip: read back both tasks to prove persistence
    retrieved_task1 = todoist_client.get_task(task_id=task1.id)
    assert "First task" in retrieved_task1.content

    retrieved_task2 = todoist_client.get_task(task_id=task2.id)
    assert "Second task" in retrieved_task2.content


def test_quick_add_task_without_text_parameter(todoist_client: TodoistAPI):
    """Test quick add fails without required text parameter"""
    with pytest.raises(Exception):
        # SDK should raise an error if text is empty
        todoist_client.add_task_quick(text="")


def test_quick_add_complex_natural_language(todoist_client: TodoistAPI):
    """Test quick add with complex natural language patterns"""
    tomorrow = date.today() + timedelta(days=1)

    test_cases = [
        {
            "text": "Dentist appointment tomorrow at 2:30pm",
            "content": "Dentist appointment",
            "due_date": tomorrow,
            "is_datetime": True,
        },
        {
            "text": "Review code every Friday",
            "content": "Review code",
            "due_string": "every Friday",
            "is_recurring": True,
        },
    ]

    for test_case in test_cases:
        task = todoist_client.add_task_quick(text=test_case["text"])

        assert task.content == test_case["content"]
        assert task.due is not None
        if "due_date" in test_case:
            if test_case.get("is_datetime"):
                assert task.due.date.date() == test_case["due_date"]
            else:
                assert task.due.date == test_case["due_date"]
        if "due_string" in test_case:
            assert task.due.string == test_case["due_string"]
        if test_case.get("is_recurring"):
            assert task.due.is_recurring is True

        # Verify round-trip: read back to prove persistence
        retrieved_task = todoist_client.get_task(task_id=task.id)
        assert retrieved_task.content == test_case["content"]
        assert retrieved_task.due is not None


def test_quick_add_preserves_special_characters(todoist_client: TodoistAPI):
    """Test that special characters in content are preserved"""
    task = todoist_client.add_task_quick(text="Email subject: Important!")

    assert task.content == "Email subject: Important!"

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Email subject: Important!"


def test_quick_add_with_nonexistent_project(todoist_client: TodoistAPI):
    """Test quick add with project name that doesn't exist — kept in content"""
    task = todoist_client.add_task_quick(text="Task in fake project #NonExistentProject")

    # When project doesn't exist, #tag stays in content
    assert "#NonExistentProject" in task.content
    # Task gets assigned to inbox/default project
    assert task.project_id is not None

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert "#NonExistentProject" in retrieved_task.content


def test_quick_add_case_insensitive_priority(todoist_client: TodoistAPI):
    """Test that priority parsing is case-insensitive.

    Todoist priority mapping: P1(highest)→4, P2→3, P3→2, P4(lowest)→1
    """
    test_cases = [
        ("Task with P1", 4),
        ("Task with P2", 3),
        ("Task with P3", 2),
        ("Task with P4", 1),
    ]

    for text, expected_priority in test_cases:
        task = todoist_client.add_task_quick(text=text)
        assert task.priority == expected_priority

        # Verify round-trip: read back to prove persistence
        retrieved_task = todoist_client.get_task(task_id=task.id)
        assert retrieved_task.priority == expected_priority
