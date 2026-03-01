"""
Contract tests for Scheduled Email Management.

Covers scheduling emails for future delivery, updating the scheduled time,
and canceling scheduled emails.

These tests run against both the real Resend API (grounding) and the
DoubleAgent fake, verifying behavioral parity.
"""

import time
from datetime import datetime, timedelta, timezone

import resend


def _future_iso(hours: int) -> str:
    """Return an ISO 8601 timestamp N hours in the future."""
    dt = datetime.now(timezone.utc) + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to a datetime, tolerant of trailing Z."""
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


# The resend.dev shared domain can only send to delivered@resend.dev
SENDER = "Contract Test <test@resend.dev>"
RECIPIENT = "delivered@resend.dev"


class TestScheduledEmailManagement:
    """Tests for Scheduled Email Management."""

    def test_schedule_email_for_future(self, resource_tracker, grounding_mode):
        """Schedule an email for future delivery and verify scheduled_at and last_event."""
        # Arrange: compute a future time 24 hours from now
        scheduled_time = _future_iso(hours=24)

        if grounding_mode:
            time.sleep(0.5)

        # Act: send a scheduled email
        send_result = resend.Emails.send({
            "from": SENDER,
            "to": RECIPIENT,
            "subject": "Scheduled Email",
            "html": "<p>Future delivery</p>",
            "scheduled_at": scheduled_time,
        })

        email_id = send_result["id"]
        assert email_id is not None
        resource_tracker.email(email_id)

        if grounding_mode:
            time.sleep(3)  # emails need time to become retrievable on the real API

        # Assert: retrieve and verify the email
        fetched = resend.Emails.get(email_id=email_id)
        assert fetched["id"] == email_id
        assert fetched["subject"] == "Scheduled Email"

        # Verify scheduled_at is set and roughly matches what we sent
        assert fetched["scheduled_at"] is not None
        fetched_scheduled = _parse_iso(fetched["scheduled_at"])
        expected_scheduled = _parse_iso(scheduled_time)
        # Allow some tolerance (the API may round to seconds)
        assert abs((fetched_scheduled - expected_scheduled).total_seconds()) < 60

        # Verify the email is in "scheduled" state
        assert fetched["last_event"] == "scheduled"

    def test_update_scheduled_email_time(self, resource_tracker, grounding_mode):
        """Update the scheduled time of a pending email and verify the change."""
        # Arrange: send a scheduled email 48h from now
        original_time = _future_iso(hours=48)

        if grounding_mode:
            time.sleep(0.5)

        send_result = resend.Emails.send({
            "from": SENDER,
            "to": RECIPIENT,
            "subject": "Reschedule Test",
            "html": "<p>Test</p>",
            "scheduled_at": original_time,
        })

        email_id = send_result["id"]
        assert email_id is not None
        resource_tracker.email(email_id)

        if grounding_mode:
            time.sleep(0.5)

        # Act: update the scheduled time to 72h from now
        new_time = _future_iso(hours=72)
        update_result = resend.Emails.update({
            "id": email_id,
            "scheduled_at": new_time,
        })

        assert update_result["object"] == "email"
        assert update_result["id"] == email_id

        if grounding_mode:
            time.sleep(0.5)

        # Assert: retrieve and verify the updated scheduled_at
        fetched = resend.Emails.get(email_id=email_id)
        assert fetched["id"] == email_id
        assert fetched["scheduled_at"] is not None

        fetched_scheduled = _parse_iso(fetched["scheduled_at"])
        expected_new = _parse_iso(new_time)
        assert abs((fetched_scheduled - expected_new).total_seconds()) < 60

    def test_cancel_scheduled_email(self, resource_tracker, grounding_mode):
        """Cancel a scheduled email and verify last_event becomes 'canceled'."""
        # Arrange: send a scheduled email 48h from now
        scheduled_time = _future_iso(hours=48)

        if grounding_mode:
            time.sleep(0.5)

        send_result = resend.Emails.send({
            "from": SENDER,
            "to": RECIPIENT,
            "subject": "Cancel Me",
            "html": "<p>This will be canceled</p>",
            "scheduled_at": scheduled_time,
        })

        email_id = send_result["id"]
        assert email_id is not None
        resource_tracker.email(email_id)

        if grounding_mode:
            time.sleep(0.5)

        # Act: cancel the scheduled email
        cancel_result = resend.Emails.cancel(email_id=email_id)

        assert cancel_result["object"] == "email"
        assert cancel_result["id"] == email_id

        if grounding_mode:
            time.sleep(0.5)

        # Assert: retrieve and verify the email is canceled
        fetched = resend.Emails.get(email_id=email_id)
        assert fetched["id"] == email_id
        assert fetched["last_event"] == "canceled"
