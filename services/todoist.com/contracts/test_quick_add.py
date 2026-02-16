"""
Contract tests for Todoist Quick Add natural language processing.

Tests the complete flow of natural language task entry with automatic parsing
of due dates, priorities, project assignments, and labels from task descriptions
using the official todoist-api-python SDK.
"""

import pytest
from todoist_api_python.api import TodoistAPI


def test_quick_add_basic_task(todoist_client: TodoistAPI):
    """Test quick add with basic task content"""
    task = todoist_client.add_task_quick(text="Buy milk")

    assert task.content == "Buy milk"
    assert task.priority == 1
    assert task.labels == []
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
    """Test quick add with single label using @label syntax"""
    task = todoist_client.add_task_quick(text="Buy milk @groceries")

    assert task.content == "Buy milk"
    assert "groceries" in task.labels
    assert "@groceries" not in task.content

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Buy milk"
    assert "groceries" in retrieved_task.labels


def test_quick_add_task_with_multiple_labels(todoist_client: TodoistAPI):
    """Test quick add with multiple labels"""
    task = todoist_client.add_task_quick(text="Finish report @work @urgent @deadline")

    assert task.content == "Finish report"
    assert "work" in task.labels
    assert "urgent" in task.labels
    assert "deadline" in task.labels
    assert len(task.labels) == 3

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Finish report"
    assert len(retrieved_task.labels) == 3
    assert "work" in retrieved_task.labels
    assert "urgent" in retrieved_task.labels
    assert "deadline" in retrieved_task.labels


def test_quick_add_task_with_priority_p1(todoist_client: TodoistAPI):
    """Test quick add with priority level p1"""
    task = todoist_client.add_task_quick(text="Regular task p1")

    assert task.content == "Regular task"
    assert task.priority == 1

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 1


def test_quick_add_task_with_priority_p2(todoist_client: TodoistAPI):
    """Test quick add with priority level p2"""
    task = todoist_client.add_task_quick(text="Medium priority task p2")

    assert task.content == "Medium priority task"
    assert task.priority == 2

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 2


def test_quick_add_task_with_priority_p3(todoist_client: TodoistAPI):
    """Test quick add with priority level p3"""
    task = todoist_client.add_task_quick(text="High priority task p3")

    assert task.content == "High priority task"
    assert task.priority == 3

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 3


def test_quick_add_task_with_priority_p4(todoist_client: TodoistAPI):
    """Test quick add with priority level p4"""
    task = todoist_client.add_task_quick(text="Urgent task p4")

    assert task.content == "Urgent task"
    assert task.priority == 4

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.priority == 4


def test_quick_add_task_with_due_date_today(todoist_client: TodoistAPI):
    """Test quick add with 'today' due date"""
    task = todoist_client.add_task_quick(text="Complete report today")

    assert task.content == "Complete report"
    assert task.due is not None
    assert task.due.string == "today"

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert retrieved_task.due.string == "today"


def test_quick_add_task_with_due_date_tomorrow(todoist_client: TodoistAPI):
    """Test quick add with 'tomorrow' due date"""
    task = todoist_client.add_task_quick(text="Call dentist tomorrow")

    assert task.content == "Call dentist"
    assert task.due is not None
    assert task.due.string == "tomorrow"

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert retrieved_task.due.string == "tomorrow"


def test_quick_add_task_with_due_datetime(todoist_client: TodoistAPI):
    """Test quick add with specific time"""
    task = todoist_client.add_task_quick(text="Meeting tomorrow at 3pm")

    assert task.content == "Meeting"
    assert task.due is not None
    assert "tomorrow at 3pm" in task.due.string

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert "tomorrow at 3pm" in retrieved_task.due.string


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
    assert "next Friday" in task.due.string

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.due is not None
    assert "next Friday" in retrieved_task.due.string


def test_quick_add_task_with_assignee(todoist_client: TodoistAPI):
    """Test quick add with assignee (should be parsed but ignored)"""
    task = todoist_client.add_task_quick(text="Delegate task +Alice")

    assert task.content == "Delegate task"
    assert "+Alice" not in task.content

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Delegate task"


def test_quick_add_task_with_all_features(todoist_client: TodoistAPI):
    """Test quick add with all features combined"""
    # Create a project first
    project = todoist_client.add_project(name="WorkProject")

    task = todoist_client.add_task_quick(
        text="Submit report #WorkProject @work @urgent p3 tomorrow at 4pm"
    )

    assert task.content == "Submit report"
    assert task.project_id == project.id
    assert "work" in task.labels
    assert "urgent" in task.labels
    assert task.priority == 3
    assert task.due is not None
    assert "tomorrow at 4pm" in task.due.string

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Submit report"
    assert retrieved_task.project_id == project.id
    assert "work" in retrieved_task.labels
    assert "urgent" in retrieved_task.labels
    assert retrieved_task.priority == 3
    assert retrieved_task.due is not None
    assert "tomorrow at 4pm" in retrieved_task.due.string


def test_quick_add_task_with_note(todoist_client: TodoistAPI):
    """Test quick add with note/description parameter"""
    task = todoist_client.add_task_quick(
        text="Buy groceries @shopping",
        note="Don't forget milk, eggs, and bread",
    )

    assert task.content == "Buy groceries"
    assert task.description == "Don't forget milk, eggs, and bread"
    assert "shopping" in task.labels

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Buy groceries"
    assert retrieved_task.description == "Don't forget milk, eggs, and bread"
    assert "shopping" in retrieved_task.labels


def test_quick_add_task_appears_in_rest_api(todoist_client: TodoistAPI):
    """Test that quick add tasks appear in REST API task list"""
    # Create task via quick add
    quick_task = todoist_client.add_task_quick(text="Test task @label1 p2")

    # Retrieve via REST API
    rest_task = todoist_client.get_task(task_id=quick_task.id)

    assert rest_task is not None
    assert rest_task.id == quick_task.id
    assert rest_task.content == "Test task"
    assert "label1" in rest_task.labels
    assert rest_task.priority == 2


def test_quick_add_task_multiple_tasks(todoist_client: TodoistAPI):
    """Test creating multiple tasks via quick add"""
    # Create first task
    task1 = todoist_client.add_task_quick(text="First task @label1")

    # Create second task
    task2 = todoist_client.add_task_quick(text="Second task @label2")

    assert task1.id != task2.id
    assert task1.content == "First task"
    assert task2.content == "Second task"
    assert "label1" in task1.labels
    assert "label2" in task2.labels

    # Verify round-trip: read back both tasks to prove persistence
    retrieved_task1 = todoist_client.get_task(task_id=task1.id)
    assert retrieved_task1.content == "First task"
    assert "label1" in retrieved_task1.labels

    retrieved_task2 = todoist_client.get_task(task_id=task2.id)
    assert retrieved_task2.content == "Second task"
    assert "label2" in retrieved_task2.labels


def test_quick_add_task_without_text_parameter(todoist_client: TodoistAPI):
    """Test quick add fails without required text parameter"""
    with pytest.raises(Exception):
        # SDK should raise an error if text is empty
        todoist_client.add_task_quick(text="")


def test_quick_add_complex_natural_language(todoist_client: TodoistAPI):
    """Test quick add with complex natural language patterns"""
    test_cases = [
        {
            "text": "Dentist appointment tomorrow at 2:30pm",
            "content": "Dentist appointment",
            "due_contains": "tomorrow at 2:30pm",
        },
        {
            "text": "Review code every Friday",
            "content": "Review code",
            "due_contains": "every Friday",
            "is_recurring": True,
        },
        {
            "text": "Submit tax return this March",
            "content": "Submit tax return",
            "due_contains": "this March",
        },
    ]

    for test_case in test_cases:
        task = todoist_client.add_task_quick(text=test_case["text"])

        assert task.content == test_case["content"]
        if "due_contains" in test_case:
            assert task.due is not None
            assert test_case["due_contains"] in task.due.string
        if test_case.get("is_recurring"):
            assert task.due.is_recurring is True

        # Verify round-trip: read back to prove persistence
        retrieved_task = todoist_client.get_task(task_id=task.id)
        assert retrieved_task.content == test_case["content"]
        if "due_contains" in test_case:
            assert retrieved_task.due is not None
            assert test_case["due_contains"] in retrieved_task.due.string
        if test_case.get("is_recurring"):
            assert retrieved_task.due.is_recurring is True


def test_quick_add_preserves_special_characters(todoist_client: TodoistAPI):
    """Test that special characters in content are preserved"""
    task = todoist_client.add_task_quick(text="Email subject: Important! @work")

    assert task.content == "Email subject: Important!"
    assert "work" in task.labels

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Email subject: Important!"
    assert "work" in retrieved_task.labels


def test_quick_add_with_nonexistent_project(todoist_client: TodoistAPI):
    """Test quick add with project name that doesn't exist"""
    task = todoist_client.add_task_quick(text="Task in fake project #NonExistentProject")

    assert task.content == "Task in fake project"
    # Project ID should be "inbox" when project not found
    assert task.project_id == "inbox"

    # Verify round-trip: read back to prove persistence
    retrieved_task = todoist_client.get_task(task_id=task.id)
    assert retrieved_task.content == "Task in fake project"
    assert retrieved_task.project_id == "inbox"


def test_quick_add_case_insensitive_priority(todoist_client: TodoistAPI):
    """Test that priority parsing is case-insensitive"""
    test_cases = [
        ("Task with P1", 1),
        ("Task with P2", 2),
        ("Task with P3", 3),
        ("Task with P4", 4),
    ]

    for text, expected_priority in test_cases:
        task = todoist_client.add_task_quick(text=text)
        assert task.priority == expected_priority

        # Verify round-trip: read back to prove persistence
        retrieved_task = todoist_client.get_task(task_id=task.id)
        assert retrieved_task.priority == expected_priority
