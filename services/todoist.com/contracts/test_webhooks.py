"""
Contract tests for Todoist webhook event delivery.

Tests webhook registration, event delivery for real-time notifications on
item:added, item:updated, item:deleted, and project:added events with
HMAC signature verification using the official todoist-api-python SDK.
"""

import pytest
import requests
import hmac
import hashlib
import base64
import json
from todoist_api_python.api import TodoistAPI


def verify_hmac_signature(payload: dict, signature: str, client_secret: str) -> bool:
    """Verify HMAC-SHA256 signature for webhook payload

    Uses the same JSON serialization format as the server (compact, no spaces, sorted keys).
    """
    # Must use the same separators and sort_keys as the server for correct signature
    payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
    expected_signature = hmac.new(
        client_secret.encode('utf-8'),
        payload_json.encode('utf-8'),
        hashlib.sha256
    ).digest()
    expected_signature_b64 = base64.b64encode(expected_signature).decode('utf-8')
    return signature == expected_signature_b64


def test_register_webhook(fake_url: str, reset_state):
    """Test registering a webhook for event notifications"""
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "url": "https://example.com/webhook",
        "events": ["item:added", "item:updated", "item:deleted", "project:added"]
    }

    response = requests.post(
        f"{fake_url}/sync/v9/webhooks",
        json=webhook_data,
        headers={"Authorization": "Bearer fake-token"}
    )

    assert response.status_code == 200
    data = response.json()

    assert "id" in data
    webhook_id = data["id"]
    assert data["url"] == "https://example.com/webhook"
    assert data["events"] == ["item:added", "item:updated", "item:deleted", "project:added"]
    assert data["user_id"] == "1"

    # Round-trip verification: List webhooks to confirm registration persisted
    list_response = requests.get(
        f"{fake_url}/sync/v9/webhooks",
        headers={"Authorization": "Bearer fake-token"}
    )
    assert list_response.status_code == 200
    webhooks = list_response.json()
    assert len(webhooks) == 1
    assert webhooks[0]["id"] == webhook_id
    assert webhooks[0]["url"] == "https://example.com/webhook"
    assert webhooks[0]["events"] == ["item:added", "item:updated", "item:deleted", "project:added"]


def test_list_webhooks(fake_url: str, reset_state):
    """Test listing registered webhooks"""
    # Register two webhooks
    webhook1_data = {
        "client_id": "client-1",
        "client_secret": "secret-1",
        "url": "https://example.com/webhook1",
        "events": ["item:added"]
    }
    webhook2_data = {
        "client_id": "client-2",
        "client_secret": "secret-2",
        "url": "https://example.com/webhook2",
        "events": ["project:added"]
    }

    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook1_data)
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook2_data)

    # List webhooks
    response = requests.get(
        f"{fake_url}/sync/v9/webhooks",
        headers={"Authorization": "Bearer fake-token"}
    )

    assert response.status_code == 200
    webhooks = response.json()

    assert len(webhooks) == 2
    assert webhooks[0]["url"] == "https://example.com/webhook1"
    assert webhooks[0]["events"] == ["item:added"]
    assert webhooks[1]["url"] == "https://example.com/webhook2"
    assert webhooks[1]["events"] == ["project:added"]


def test_delete_webhook(fake_url: str, reset_state):
    """Test deleting a webhook"""
    # Register a webhook
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "url": "https://example.com/webhook",
        "events": ["item:added"]
    }

    response = requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)
    webhook_id = response.json()["id"]

    # Round-trip verification before delete: Confirm webhook exists
    list_response_before = requests.get(f"{fake_url}/sync/v9/webhooks")
    webhooks_before = list_response_before.json()
    assert len(webhooks_before) == 1
    assert webhooks_before[0]["id"] == webhook_id

    # Delete the webhook
    delete_response = requests.delete(
        f"{fake_url}/sync/v9/webhooks/{webhook_id}",
        headers={"Authorization": "Bearer fake-token"}
    )

    assert delete_response.status_code == 204

    # Round-trip verification after delete: Confirm webhook is gone
    list_response = requests.get(f"{fake_url}/sync/v9/webhooks")
    webhooks = list_response.json()
    assert len(webhooks) == 0


def test_webhook_delivery_on_item_added(fake_url: str, todoist_client: TodoistAPI):
    """Test webhook delivery when a task is created (item:added event)"""
    client_secret = "my-secret-key"

    # Register webhook for item:added events
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": client_secret,
        "url": "https://example.com/webhook",
        "events": ["item:added"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Create a task using the SDK
    task = todoist_client.add_task(
        content="Test webhook task",
        priority=2,
        labels=["urgent"]
    )

    # Round-trip verification: Read back the task to prove persistence
    persisted_task = todoist_client.get_task(task_id=task.id)
    assert persisted_task.id == task.id
    assert persisted_task.content == "Test webhook task"
    assert persisted_task.priority == 2
    assert persisted_task.labels == ["urgent"]

    # Check webhook deliveries
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    assert deliveries_response.status_code == 200

    deliveries = deliveries_response.json()["deliveries"]
    assert len(deliveries) == 1

    delivery = deliveries[0]
    assert delivery["event_name"] == "item:added"

    # Verify payload structure
    payload = delivery["payload"]
    assert payload["event_name"] == "item:added"
    assert payload["user_id"] == 1
    assert "initiator" in payload
    assert payload["initiator"]["id"] == 1
    assert payload["initiator"]["email"] == "user@example.com"
    assert "event_data" in payload

    # Verify event data contains task info
    event_data = payload["event_data"]
    assert event_data["id"] == task.id
    assert event_data["content"] == "Test webhook task"
    assert event_data["priority"] == 2
    assert event_data["labels"] == ["urgent"]

    # Verify HMAC signature
    signature = delivery["signature"]
    assert verify_hmac_signature(payload, signature, client_secret)


def test_webhook_delivery_on_item_updated(fake_url: str, todoist_client: TodoistAPI):
    """Test webhook delivery when a task is updated (item:updated event)"""
    client_secret = "update-secret"

    # Register webhook for item:updated events
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": client_secret,
        "url": "https://example.com/webhook",
        "events": ["item:updated"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Create and update a task
    task = todoist_client.add_task(content="Original content")
    todoist_client.update_task(task_id=task.id, content="Updated content")

    # Round-trip verification: Read back the task to prove update persisted
    persisted_task = todoist_client.get_task(task_id=task.id)
    assert persisted_task.id == task.id
    assert persisted_task.content == "Updated content"

    # Check webhook deliveries (should only have item:updated, not item:added)
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    deliveries = deliveries_response.json()["deliveries"]

    # Filter for item:updated events
    update_deliveries = [d for d in deliveries if d["event_name"] == "item:updated"]
    assert len(update_deliveries) == 1

    delivery = update_deliveries[0]
    payload = delivery["payload"]
    assert payload["event_name"] == "item:updated"
    assert payload["event_data"]["content"] == "Updated content"

    # Verify HMAC signature
    assert verify_hmac_signature(payload, delivery["signature"], client_secret)


def test_webhook_delivery_on_item_deleted(fake_url: str, todoist_client: TodoistAPI):
    """Test webhook delivery when a task is deleted (item:deleted event)"""
    client_secret = "delete-secret"

    # Register webhook for item:deleted events
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": client_secret,
        "url": "https://example.com/webhook",
        "events": ["item:deleted"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Create a task and verify it exists
    task = todoist_client.add_task(content="Task to delete")
    task_id = task.id

    # Round-trip verification before delete: Read back to confirm it was created
    persisted_task = todoist_client.get_task(task_id=task_id)
    assert persisted_task.id == task_id
    assert persisted_task.content == "Task to delete"

    # Delete the task
    todoist_client.delete_task(task_id=task_id)

    # Round-trip verification after delete: Confirm deletion by trying to read
    try:
        todoist_client.get_task(task_id=task_id)
        assert False, "Task should have been deleted but still exists"
    except Exception:
        # Expected: task should not be found after deletion
        pass

    # Check webhook deliveries
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    deliveries = deliveries_response.json()["deliveries"]

    # Filter for item:deleted events
    delete_deliveries = [d for d in deliveries if d["event_name"] == "item:deleted"]
    assert len(delete_deliveries) == 1

    delivery = delete_deliveries[0]
    payload = delivery["payload"]
    assert payload["event_name"] == "item:deleted"
    assert payload["event_data"]["id"] == task_id
    assert payload["event_data"]["content"] == "Task to delete"

    # Verify HMAC signature
    assert verify_hmac_signature(payload, delivery["signature"], client_secret)


def test_webhook_delivery_on_project_added(fake_url: str, todoist_client: TodoistAPI):
    """Test webhook delivery when a project is created (project:added event)"""
    client_secret = "project-secret"

    # Register webhook for project:added events
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": client_secret,
        "url": "https://example.com/webhook",
        "events": ["project:added"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Create a project using the SDK
    project = todoist_client.add_project(
        name="Webhook Test Project",
        color="blue"
    )

    # Round-trip verification: Read back the project to prove persistence
    persisted_project = todoist_client.get_project(project_id=project.id)
    assert persisted_project.id == project.id
    assert persisted_project.name == "Webhook Test Project"
    assert persisted_project.color == "blue"

    # Check webhook deliveries
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    deliveries = deliveries_response.json()["deliveries"]

    assert len(deliveries) == 1

    delivery = deliveries[0]
    payload = delivery["payload"]
    assert payload["event_name"] == "project:added"
    assert payload["event_data"]["id"] == project.id
    assert payload["event_data"]["name"] == "Webhook Test Project"
    assert payload["event_data"]["color"] == "blue"

    # Verify HMAC signature
    assert verify_hmac_signature(payload, delivery["signature"], client_secret)


def test_webhook_multiple_events_subscription(fake_url: str, todoist_client: TodoistAPI):
    """Test webhook receiving multiple event types"""
    client_secret = "multi-event-secret"

    # Register webhook for multiple event types
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": client_secret,
        "url": "https://example.com/webhook",
        "events": ["item:added", "item:updated", "item:deleted"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Perform multiple operations with round-trip verification
    task = todoist_client.add_task(content="Multi-event task")

    # Verify task creation persisted
    persisted_task = todoist_client.get_task(task_id=task.id)
    assert persisted_task.content == "Multi-event task"

    # Update the task
    todoist_client.update_task(task_id=task.id, content="Updated task")

    # Verify update persisted
    updated_task = todoist_client.get_task(task_id=task.id)
    assert updated_task.content == "Updated task"

    # Delete the task
    todoist_client.delete_task(task_id=task.id)

    # Verify deletion (task should not be found)
    try:
        todoist_client.get_task(task_id=task.id)
        assert False, "Task should have been deleted"
    except Exception:
        pass  # Expected

    # Check webhook deliveries
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    deliveries = deliveries_response.json()["deliveries"]

    assert len(deliveries) == 3

    # Verify we got all three event types
    event_names = [d["event_name"] for d in deliveries]
    assert "item:added" in event_names
    assert "item:updated" in event_names
    assert "item:deleted" in event_names

    # Verify all signatures
    for delivery in deliveries:
        assert verify_hmac_signature(
            delivery["payload"],
            delivery["signature"],
            client_secret
        )


def test_webhook_event_filtering(fake_url: str, todoist_client: TodoistAPI):
    """Test that webhooks only receive events they're subscribed to"""
    # Register webhook only for item:added
    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": "filter-secret",
        "url": "https://example.com/webhook",
        "events": ["item:added"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Perform multiple operations with round-trip verification
    task = todoist_client.add_task(content="Filter test task")

    # Verify task creation persisted
    persisted_task = todoist_client.get_task(task_id=task.id)
    assert persisted_task.content == "Filter test task"

    # Update the task
    todoist_client.update_task(task_id=task.id, content="Updated")

    # Verify update persisted
    updated_task = todoist_client.get_task(task_id=task.id)
    assert updated_task.content == "Updated"

    # Delete the task
    todoist_client.delete_task(task_id=task.id)

    # Verify deletion
    try:
        todoist_client.get_task(task_id=task.id)
        assert False, "Task should have been deleted"
    except Exception:
        pass  # Expected

    # Check webhook deliveries - should only have item:added
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    deliveries = deliveries_response.json()["deliveries"]

    assert len(deliveries) == 1
    assert deliveries[0]["event_name"] == "item:added"


def test_webhook_registration_validation(fake_url: str, reset_state):
    """Test webhook registration with invalid data"""
    # Missing client_id
    response = requests.post(
        f"{fake_url}/sync/v9/webhooks",
        json={
            "client_secret": "secret",
            "url": "https://example.com/webhook",
            "events": ["item:added"]
        }
    )
    assert response.status_code == 400
    assert "client_id" in response.json()["error"]

    # Missing client_secret
    response = requests.post(
        f"{fake_url}/sync/v9/webhooks",
        json={
            "client_id": "client",
            "url": "https://example.com/webhook",
            "events": ["item:added"]
        }
    )
    assert response.status_code == 400
    assert "client_secret" in response.json()["error"]

    # Missing url
    response = requests.post(
        f"{fake_url}/sync/v9/webhooks",
        json={
            "client_id": "client",
            "client_secret": "secret",
            "events": ["item:added"]
        }
    )
    assert response.status_code == 400
    assert "url" in response.json()["error"]

    # Missing events
    response = requests.post(
        f"{fake_url}/sync/v9/webhooks",
        json={
            "client_id": "client",
            "client_secret": "secret",
            "url": "https://example.com/webhook"
        }
    )
    assert response.status_code == 400
    assert "events" in response.json()["error"]


def test_webhook_payload_structure(fake_url: str, todoist_client: TodoistAPI):
    """Test that webhook payload matches Todoist's expected structure"""
    client_secret = "structure-test-secret"

    webhook_data = {
        "client_id": "test-client-id",
        "client_secret": client_secret,
        "url": "https://example.com/webhook",
        "events": ["item:added"]
    }
    requests.post(f"{fake_url}/sync/v9/webhooks", json=webhook_data)

    # Create a task
    task = todoist_client.add_task(content="Structure test")

    # Round-trip verification: Read back the task to prove persistence
    persisted_task = todoist_client.get_task(task_id=task.id)
    assert persisted_task.content == "Structure test"

    # Check webhook delivery structure
    deliveries_response = requests.get(f"{fake_url}/_doubleagent/webhook_deliveries")
    deliveries = deliveries_response.json()["deliveries"]

    assert len(deliveries) == 1
    payload = deliveries[0]["payload"]

    # Verify top-level structure
    assert "event_name" in payload
    assert "user_id" in payload
    assert "initiator" in payload
    assert "event_data" in payload
    assert "version" in payload

    # Verify initiator structure
    initiator = payload["initiator"]
    assert "id" in initiator
    assert "email" in initiator
    assert "full_name" in initiator
    assert "is_premium" in initiator

    # Verify version
    assert payload["version"] == "9"
