"""
Contract tests for Webhook Configuration scenario.

Covers creating webhooks with event subscriptions, listing, retrieving,
updating, and deleting webhooks.
"""

import time
import uuid

import pytest
import resend
from resend.exceptions import ResendError


def _delay(grounding_mode: bool) -> None:
    """Small delay in grounding mode to respect rate limits (2 req/s)."""
    if grounding_mode:
        time.sleep(0.6)


class TestWebhookConfiguration:
    """Tests for the Webhook Configuration scenario."""

    def test_create_and_retrieve_webhook(self, resource_tracker, grounding_mode):
        """Create a webhook and retrieve its configuration.

        Steps:
        1. Create a webhook with endpoint and multiple event types
        2. Verify the response contains object='webhook', a non-null id, and signing_secret
        3. Retrieve the webhook by id
        4. Verify the retrieved webhook has matching endpoint and events
        """
        # Arrange & Act: create a webhook
        create_result = resend.Webhooks.create({
            "endpoint": "https://hooks.example.com/resend",
            "events": ["email.sent", "email.delivered", "email.bounced"],
        })
        resource_tracker.webhook(create_result["id"])

        _delay(grounding_mode)

        # Assert: create response
        assert create_result["object"] == "webhook"
        assert create_result["id"] is not None
        webhook_id = create_result["id"]

        # Verify UUID format
        uuid.UUID(webhook_id)

        # Signing secret should be present
        assert create_result["signing_secret"] is not None
        assert isinstance(create_result["signing_secret"], str)
        assert len(create_result["signing_secret"]) > 0

        # Act: retrieve the webhook by id
        fetched = resend.Webhooks.get(webhook_id)

        _delay(grounding_mode)

        # Assert: retrieved webhook matches creation params
        assert fetched["id"] == webhook_id
        assert fetched["endpoint"] == "https://hooks.example.com/resend"

        # Containment assertions on events
        fetched_events = fetched["events"]
        assert "email.sent" in fetched_events
        assert "email.delivered" in fetched_events
        assert "email.bounced" in fetched_events

        # Webhook should have standard fields
        assert fetched["object"] == "webhook"
        assert fetched["created_at"] is not None
        assert fetched["status"] in ("enabled", "disabled")

    def test_list_webhooks(self, resource_tracker, grounding_mode):
        """List all configured webhooks.

        Steps:
        1. Create a webhook with a specific endpoint and event
        2. List all webhooks
        3. Verify the created webhook appears in the list
        """
        # Arrange: create a webhook
        create_result = resend.Webhooks.create({
            "endpoint": "https://hooks.example.com/test",
            "events": ["email.opened"],
        })
        resource_tracker.webhook(create_result["id"])
        webhook_id = create_result["id"]

        _delay(grounding_mode)

        # Act: list webhooks
        list_result = resend.Webhooks.list()

        _delay(grounding_mode)

        # Assert: list response structure
        assert list_result["object"] == "list"
        assert isinstance(list_result["data"], list)
        assert isinstance(list_result["has_more"], bool)

        # Containment: the created webhook must be in the list
        listed_ids = [w["id"] for w in list_result["data"]]
        assert webhook_id in listed_ids

        # Find the webhook in the list and verify basic fields
        found = [w for w in list_result["data"] if w["id"] == webhook_id][0]
        assert found["endpoint"] == "https://hooks.example.com/test"
        assert "email.opened" in found["events"]

    def test_update_webhook_events(self, resource_tracker, grounding_mode):
        """Update a webhook's subscribed events.

        Steps:
        1. Create a webhook with a single event
        2. Update it to subscribe to multiple events
        3. Retrieve the webhook and verify the events were updated
        """
        # Arrange: create with one event
        create_result = resend.Webhooks.create({
            "endpoint": "https://hooks.example.com/update-test",
            "events": ["email.sent"],
        })
        resource_tracker.webhook(create_result["id"])
        webhook_id = create_result["id"]

        _delay(grounding_mode)

        # Act: update to subscribe to more events
        update_result = resend.Webhooks.update({
            "webhook_id": webhook_id,
            "events": [
                "email.sent",
                "email.delivered",
                "email.opened",
                "email.clicked",
            ],
        })

        _delay(grounding_mode)

        # Assert: update response
        assert update_result["object"] == "webhook"
        assert update_result["id"] == webhook_id

        # Read-back verification
        fetched = resend.Webhooks.get(webhook_id)

        _delay(grounding_mode)

        # Containment assertions on events
        fetched_events = fetched["events"]
        assert "email.sent" in fetched_events
        assert "email.delivered" in fetched_events
        assert "email.opened" in fetched_events
        assert "email.clicked" in fetched_events

        # Endpoint should remain unchanged
        assert fetched["endpoint"] == "https://hooks.example.com/update-test"

    def test_delete_webhook(self, resource_tracker, grounding_mode):
        """Delete a webhook and verify removal.

        Steps:
        1. Create a webhook
        2. Delete it by id
        3. Attempt to retrieve the deleted webhook — expect 404
        """
        # Arrange: create a webhook
        create_result = resend.Webhooks.create({
            "endpoint": "https://hooks.example.com/delete-test",
            "events": ["email.bounced"],
        })
        webhook_id = create_result["id"]
        # Don't register for cleanup since we'll delete it ourselves

        _delay(grounding_mode)

        # Act: delete the webhook
        delete_result = resend.Webhooks.remove(webhook_id)

        _delay(grounding_mode)

        # Assert: delete response
        assert delete_result["object"] == "webhook"
        assert delete_result["id"] == webhook_id
        assert delete_result["deleted"] is True

        # Hard-delete verification: GET should return 404
        # Resend hard-deletes (no soft-delete), so GET should raise a ResendError.
        with pytest.raises(ResendError) as exc_info:
            resend.Webhooks.get(webhook_id)

        # The error should be a not-found error (status code 404)
        error = exc_info.value
        # Accept either int or string for code since SDK behavior may vary
        assert str(error.code) == "404" or error.code == 404
