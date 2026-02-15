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


def test_idempotent_task_creation(fake_url: str):
    """Test that task creation with same X-Request-Id is idempotent"""
    # Make a direct HTTP request with X-Request-Id header
    # The SDK doesn't expose X-Request-Id, so we test via raw HTTP

    request_id = "test-request-id-001"
    headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
    }

    payload = {
        "content": "Idempotent task creation test",
        "priority": 3,
        "labels": ["test", "idempotency"],
    }

    # First request - should create the task
    response1 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response1.status_code == 200
    task1 = response1.json()
    assert task1["content"] == "Idempotent task creation test"
    assert task1["priority"] == 3
    task_id_1 = task1["id"]

    # Second request with same X-Request-Id - should return cached response
    response2 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response2.status_code == 200
    task2 = response2.json()

    # Should return the exact same task (same ID)
    assert task2["id"] == task_id_1
    assert task2["content"] == task1["content"]
    assert task2["priority"] == task1["priority"]

    # Verify only one task was actually created
    get_response = requests.get(
        f"{fake_url}/api/v1/tasks",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert get_response.status_code == 200
    all_tasks = get_response.json()["results"]

    # Count tasks with this content
    matching_tasks = [t for t in all_tasks if t["content"] == "Idempotent task creation test"]
    assert len(matching_tasks) == 1


def test_different_request_ids_create_different_tasks(fake_url: str):
    """Test that different X-Request-Id values create different tasks"""
    base_headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
    }

    payload = {
        "content": "Task for different request IDs",
        "priority": 2,
    }

    # Create three tasks with different request IDs
    request_ids = ["req-001", "req-002", "req-003"]
    created_task_ids = []

    for request_id in request_ids:
        headers = {**base_headers, "X-Request-Id": request_id}
        response = requests.post(
            f"{fake_url}/api/v1/tasks",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 200
        task = response.json()
        created_task_ids.append(task["id"])

    # All three should have different IDs
    assert len(set(created_task_ids)) == 3


def test_idempotent_task_update(fake_url: str):
    """Test that task updates with same X-Request-Id are idempotent"""
    # First create a task
    headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
    }

    create_response = requests.post(
        f"{fake_url}/api/v1/tasks",
        json={"content": "Task to update"},
        headers=headers,
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["id"]

    # Now update it with an X-Request-Id
    request_id = "update-request-id-001"
    update_headers = {
        **headers,
        "X-Request-Id": request_id,
    }

    update_payload = {
        "content": "Updated task content",
        "priority": 4,
    }

    # First update request
    update_response1 = requests.post(
        f"{fake_url}/api/v1/tasks/{task_id}",
        json=update_payload,
        headers=update_headers,
    )
    assert update_response1.status_code == 200
    updated_task1 = update_response1.json()
    assert updated_task1["content"] == "Updated task content"
    assert updated_task1["priority"] == 4

    # Second update request with same X-Request-Id - should return cached response
    # even if we change the payload
    different_payload = {
        "content": "This should NOT be applied",
        "priority": 1,
    }

    update_response2 = requests.post(
        f"{fake_url}/api/v1/tasks/{task_id}",
        json=different_payload,
        headers=update_headers,
    )
    assert update_response2.status_code == 200
    updated_task2 = update_response2.json()

    # Should return the cached response from first update
    assert updated_task2["id"] == updated_task1["id"]
    assert updated_task2["content"] == "Updated task content"
    assert updated_task2["priority"] == 4

    # Verify the task was only updated once
    get_response = requests.get(
        f"{fake_url}/api/v1/tasks/{task_id}",
        headers=headers,
    )
    assert get_response.status_code == 200
    final_task = get_response.json()
    assert final_task["content"] == "Updated task content"
    assert final_task["priority"] == 4


def test_idempotent_project_creation(fake_url: str):
    """Test that project creation with same X-Request-Id is idempotent"""
    request_id = "project-request-id-001"
    headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
    }

    payload = {
        "name": "Idempotent Project",
        "color": "blue",
        "is_favorite": True,
    }

    # First request - should create the project
    response1 = requests.post(
        f"{fake_url}/api/v1/projects",
        json=payload,
        headers=headers,
    )
    assert response1.status_code == 200
    project1 = response1.json()
    assert project1["name"] == "Idempotent Project"
    project_id_1 = project1["id"]

    # Second request with same X-Request-Id - should return cached response
    response2 = requests.post(
        f"{fake_url}/api/v1/projects",
        json=payload,
        headers=headers,
    )
    assert response2.status_code == 200
    project2 = response2.json()

    # Should return the exact same project (same ID)
    assert project2["id"] == project_id_1
    assert project2["name"] == project1["name"]

    # Verify only one project was actually created
    get_response = requests.get(
        f"{fake_url}/api/v1/projects",
        headers={"Authorization": "Bearer fake-token"},
    )
    assert get_response.status_code == 200
    all_projects = get_response.json()["results"]

    # Count projects with this name
    matching_projects = [p for p in all_projects if p["name"] == "Idempotent Project"]
    assert len(matching_projects) == 1


def test_request_without_x_request_id_not_cached(fake_url: str):
    """Test that requests without X-Request-Id are not cached and can be repeated"""
    headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
    }

    payload = {
        "content": "Task without request ID",
        "priority": 2,
    }

    # Make two identical requests without X-Request-Id
    response1 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response1.status_code == 200
    task1 = response1.json()

    response2 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response2.status_code == 200
    task2 = response2.json()

    # Should create two different tasks (different IDs)
    assert task1["id"] != task2["id"]
    assert task1["content"] == task2["content"]


def test_request_id_cache_cleared_on_reset(fake_url: str):
    """Test that request ID cache is cleared when state is reset"""
    request_id = "persistent-request-id"
    headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
    }

    payload = {
        "content": "Task before reset",
    }

    # Create a task with X-Request-Id
    response1 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response1.status_code == 200
    task1_id = response1.json()["id"]

    # Reset the state
    reset_response = requests.post(f"{fake_url}/_doubleagent/reset")
    assert reset_response.status_code == 200

    # Make another request with the same X-Request-Id
    # After reset, this should create a new task, not return cached response
    response2 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response2.status_code == 200
    task2 = response2.json()

    # After reset, counters restart, so ID might be the same
    # But this is a fresh task, not a cached response
    # We can verify by checking that only this task exists
    get_response = requests.get(
        f"{fake_url}/api/v1/tasks",
        headers={"Authorization": "Bearer fake-token"},
    )
    all_tasks = get_response.json()["results"]
    assert len(all_tasks) == 1
    assert all_tasks[0]["content"] == "Task before reset"


def test_retry_logic_simulation(fake_url: str):
    """
    Simulate a retry scenario where a client retries a failed request.
    This is the primary use case for idempotency.
    """
    request_id = "retry-request-id-001"
    headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
    }

    payload = {
        "content": "Task creation with retry",
        "priority": 4,
        "labels": ["important", "urgent"],
    }

    # Initial request (imagine this succeeds on server but client doesn't get response)
    response1 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response1.status_code == 200
    task1 = response1.json()

    # Client retries with same request ID (to ensure idempotency)
    response2 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response2.status_code == 200
    task2 = response2.json()

    # Both responses should be identical
    assert task1["id"] == task2["id"]
    assert task1["content"] == task2["content"]
    assert task1["priority"] == task2["priority"]
    assert task1["labels"] == task2["labels"]

    # Verify only ONE task was created despite two requests
    all_tasks_response = requests.get(
        f"{fake_url}/api/v1/tasks",
        headers={"Authorization": "Bearer fake-token"},
    )
    all_tasks = all_tasks_response.json()["results"]
    matching_tasks = [t for t in all_tasks if t["content"] == "Task creation with retry"]
    assert len(matching_tasks) == 1

    # Client makes a third retry
    response3 = requests.post(
        f"{fake_url}/api/v1/tasks",
        json=payload,
        headers=headers,
    )
    assert response3.status_code == 200
    task3 = response3.json()
    assert task3["id"] == task1["id"]

    # Still only ONE task should exist
    all_tasks_response = requests.get(
        f"{fake_url}/api/v1/tasks",
        headers={"Authorization": "Bearer fake-token"},
    )
    all_tasks = all_tasks_response.json()["results"]
    matching_tasks = [t for t in all_tasks if t["content"] == "Task creation with retry"]
    assert len(matching_tasks) == 1
