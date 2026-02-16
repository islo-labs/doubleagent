"""
Contract tests for Todoist Bearer token authentication and request idempotency.

Tests the flow:
- Bearer token authentication (tokens are accepted but not validated)
- Request idempotency using X-Request-Id headers to prevent duplicate operations
- Reliable task creation and updates with retry logic
"""

import pytest
import requests
from todoist_api_python.api import TodoistAPI


def test_bearer_token_authentication_accepted(todoist_client: TodoistAPI):
    """Test that Bearer token authentication is accepted"""
    # The todoist_client fixture already uses a fake token ("fake-token")
    # If authentication fails, this will raise an exception
    task = todoist_client.add_task(content="Test task with fake token")

    assert task is not None
    assert task.id is not None
    assert task.content == "Test task with fake token"

    # Verify round-trip: read back the task to prove it was persisted
    fetched_task = todoist_client.get_task(task_id=task.id)
    assert fetched_task.id == task.id
    assert fetched_task.content == "Test task with fake token"


def test_bearer_token_any_value_accepted(fake_url: str, monkeypatch):
    """Test that any Bearer token value is accepted (not validated)"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    # Try with various token values - all should work
    tokens = [
        "fake-token",
        "invalid-token",
        "random-string-123",
        "",  # Even empty token should work
        "a" * 1000,  # Very long token
    ]

    for token in tokens:
        client = TodoistAPI(token)
        task = client.add_task(content=f"Task with token: {token[:20]}")
        assert task is not None
        assert task.id is not None

        # Verify round-trip: read back the task to prove it was persisted
        fetched_task = client.get_task(task_id=task.id)
        assert fetched_task.id == task.id
        assert fetched_task.content == f"Task with token: {token[:20]}"


def test_idempotent_task_creation(fake_url: str, monkeypatch):
    """Test that task creation with same X-Request-Id is idempotent"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    # Create a client with a custom request_id_fn that returns the same ID
    request_id = "test-request-id-001"
    client = TodoistAPI("fake-token", request_id_fn=lambda: request_id)

    # First request - should create the task
    task1 = client.add_task(
        content="Idempotent task creation test",
        priority=3,
        labels=["test", "idempotency"],
    )
    assert task1.content == "Idempotent task creation test"
    assert task1.priority == 3
    task_id_1 = task1.id

    # Second request with same X-Request-Id - should return cached response
    task2 = client.add_task(
        content="Idempotent task creation test",
        priority=3,
        labels=["test", "idempotency"],
    )

    # Should return the exact same task (same ID)
    assert task2.id == task_id_1
    assert task2.content == task1.content
    assert task2.priority == task1.priority

    # Verify only one task was actually created
    # Create a new client for verification (without request_id_fn)
    verify_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    all_tasks = verify_client.get_tasks()

    # Count tasks with this content
    matching_tasks = [t for t in all_tasks if t.content == "Idempotent task creation test"]
    assert len(matching_tasks) == 1


def test_different_request_ids_create_different_tasks(fake_url: str, monkeypatch):
    """Test that different X-Request-Id values create different tasks"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    # Create three tasks with different request IDs
    request_ids = ["req-001", "req-002", "req-003"]
    created_task_ids = []

    for request_id in request_ids:
        client = TodoistAPI("fake-token", request_id_fn=lambda rid=request_id: rid)
        task = client.add_task(
            content="Task for different request IDs",
            priority=2,
        )
        created_task_ids.append(task.id)

    # All three should have different IDs
    assert len(set(created_task_ids)) == 3

    # Verify round-trip: read back each task to prove they were all persisted
    verify_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    for task_id in created_task_ids:
        fetched_task = verify_client.get_task(task_id=task_id)
        assert fetched_task.id == task_id
        assert fetched_task.content == "Task for different request IDs"
        assert fetched_task.priority == 2


def test_idempotent_task_update(fake_url: str, monkeypatch):
    """Test that task updates with same X-Request-Id are idempotent"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    # First create a task (without request_id_fn)
    create_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    task = create_client.add_task(content="Task to update")
    task_id = task.id

    # Now update it with an X-Request-Id
    request_id = "update-request-id-001"
    update_client = TodoistAPI("fake-token", request_id_fn=lambda: request_id)

    # First update request
    updated_task1 = update_client.update_task(
        task_id=task_id,
        content="Updated task content",
        priority=4,
    )
    assert updated_task1.content == "Updated task content"
    assert updated_task1.priority == 4

    # Second update request with same X-Request-Id - should return cached response
    # even if we change the payload
    updated_task2 = update_client.update_task(
        task_id=task_id,
        content="This should NOT be applied",
        priority=1,
    )

    # Should return the cached response from first update
    assert updated_task2.id == updated_task1.id
    assert updated_task2.content == "Updated task content"
    assert updated_task2.priority == 4

    # Verify the task was only updated once
    verify_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    final_task = verify_client.get_task(task_id=task_id)
    assert final_task.content == "Updated task content"
    assert final_task.priority == 4


def test_idempotent_project_creation(fake_url: str, monkeypatch):
    """Test that project creation with same X-Request-Id is idempotent"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    request_id = "project-request-id-001"
    client = TodoistAPI("fake-token", request_id_fn=lambda: request_id)

    # First request - should create the project
    project1 = client.add_project(
        name="Idempotent Project",
        color="blue",
        is_favorite=True,
    )
    assert project1.name == "Idempotent Project"
    project_id_1 = project1.id

    # Second request with same X-Request-Id - should return cached response
    project2 = client.add_project(
        name="Idempotent Project",
        color="blue",
        is_favorite=True,
    )

    # Should return the exact same project (same ID)
    assert project2.id == project_id_1
    assert project2.name == project1.name

    # Verify only one project was actually created
    verify_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    all_projects = verify_client.get_projects()

    # Count projects with this name
    matching_projects = [p for p in all_projects if p.name == "Idempotent Project"]
    assert len(matching_projects) == 1


def test_request_without_x_request_id_not_cached(fake_url: str, monkeypatch):
    """Test that requests without X-Request-Id are not cached and can be repeated"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    # Create client without request_id_fn (will not send X-Request-Id header)
    client = TodoistAPI("fake-token", request_id_fn=lambda: None)

    # Make two identical requests without X-Request-Id
    task1 = client.add_task(
        content="Task without request ID",
        priority=2,
    )

    task2 = client.add_task(
        content="Task without request ID",
        priority=2,
    )

    # Should create two different tasks (different IDs)
    assert task1.id != task2.id
    assert task1.content == task2.content

    # Verify round-trip: read back both tasks to prove they were persisted
    fetched_task1 = client.get_task(task_id=task1.id)
    assert fetched_task1.id == task1.id
    assert fetched_task1.content == "Task without request ID"

    fetched_task2 = client.get_task(task_id=task2.id)
    assert fetched_task2.id == task2.id
    assert fetched_task2.content == "Task without request ID"


def test_request_id_cache_cleared_on_reset(fake_url: str, monkeypatch):
    """Test that request ID cache is cleared when state is reset"""
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    request_id = "persistent-request-id"
    client = TodoistAPI("fake-token", request_id_fn=lambda: request_id)

    # Create a task with X-Request-Id
    task1 = client.add_task(content="Task before reset")
    task1_id = task1.id

    # Reset the state (control plane endpoint - raw HTTP is OK)
    reset_response = requests.post(f"{fake_url}/_doubleagent/reset")
    assert reset_response.status_code == 200

    # Make another request with the same X-Request-Id
    # After reset, this should create a new task, not return cached response
    task2 = client.add_task(content="Task before reset")

    # After reset, counters restart, so ID might be the same
    # But this is a fresh task, not a cached response
    # We can verify by checking that only this task exists
    verify_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    all_tasks = verify_client.get_tasks()
    assert len(all_tasks) == 1
    assert all_tasks[0].content == "Task before reset"


def test_retry_logic_simulation(fake_url: str, monkeypatch):
    """
    Simulate a retry scenario where a client retries a failed request.
    This is the primary use case for idempotency.
    """
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints
    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    request_id = "retry-request-id-001"
    client = TodoistAPI("fake-token", request_id_fn=lambda: request_id)

    # Initial request (imagine this succeeds on server but client doesn't get response)
    task1 = client.add_task(
        content="Task creation with retry",
        priority=4,
        labels=["important", "urgent"],
    )

    # Client retries with same request ID (to ensure idempotency)
    task2 = client.add_task(
        content="Task creation with retry",
        priority=4,
        labels=["important", "urgent"],
    )

    # Both responses should be identical
    assert task1.id == task2.id
    assert task1.content == task2.content
    assert task1.priority == task2.priority
    assert task1.labels == task2.labels

    # Verify only ONE task was created despite two requests
    verify_client = TodoistAPI("fake-token", request_id_fn=lambda: None)
    all_tasks = verify_client.get_tasks()
    matching_tasks = [t for t in all_tasks if t.content == "Task creation with retry"]
    assert len(matching_tasks) == 1

    # Client makes a third retry
    task3 = client.add_task(
        content="Task creation with retry",
        priority=4,
        labels=["important", "urgent"],
    )
    assert task3.id == task1.id

    # Still only ONE task should exist
    all_tasks = verify_client.get_tasks()
    matching_tasks = [t for t in all_tasks if t.content == "Task creation with retry"]
    assert len(matching_tasks) == 1
