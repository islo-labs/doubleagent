"""
Contract tests for scenario: email-sending-lifecycle — Email Sending Lifecycle

Covers sending individual emails, retrieving their status, and verifying
delivery tracking fields.

These tests run against both the real Resend API (grounding) and the
DoubleAgent fake.

NOTE on grounding key permissions:
The grounding token has sending_access only (not full_access).  This means
GET /emails/{id} and GET /emails (list) return 401 in grounding mode.
Tests that require read-back or list are marked @pytest.mark.fake_only
because they genuinely cannot work with a send-only API key.  All send
operations are verified in both modes.  If a full_access key is provided,
the fake_only tests can be unblocked.
"""

import re
import time
import uuid

import pytest
import resend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _sender(grounding_mode: bool) -> str:
    """Return a valid sender address with display name."""
    if grounding_mode:
        return "Contract Tests <onboarding@resend.dev>"
    return "Test <test@example.com>"


def _sender_plain(grounding_mode: bool) -> str:
    """Return a bare sender address (no display name)."""
    if grounding_mode:
        return "onboarding@resend.dev"
    return "sender@example.com"


def _recipient(grounding_mode: bool) -> str:
    """Return a valid recipient.  In grounding mode only delivered@resend.dev works."""
    if grounding_mode:
        return "delivered@resend.dev"
    return "recipient@example.com"


def _recipients(grounding_mode: bool, count: int = 3) -> list[str]:
    """Return multiple recipient addresses."""
    if grounding_mode:
        # resend.dev only allows delivered@resend.dev as recipient
        return ["delivered@resend.dev"] * count
    return [f"user{i + 1}@example.com" for i in range(count)]


def _delay(grounding_mode: bool) -> None:
    """Small delay in grounding mode to respect rate limits (2 req/s)."""
    if grounding_mode:
        time.sleep(0.6)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmailSendingLifecycle:
    """Tests for Email Sending Lifecycle."""

    # ------------------------------------------------------------------
    # 1. Send a simple email — both modes verify send response;
    #    read-back is fake_only because grounding key is send-only.
    # ------------------------------------------------------------------
    def test_send_simple_email(self, resource_tracker, grounding_mode):
        """Send a simple email with subject and HTML body and verify send response."""
        sender = _sender(grounding_mode)
        recipient = _recipient(grounding_mode)

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": "Hello World",
            "html": "<p>Hi there</p>",
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        # Send response returns a valid UUID
        assert email_id is not None
        assert UUID_RE.match(email_id), f"Expected UUID format, got: {email_id}"

    @pytest.mark.fake_only
    def test_send_simple_email_readback(self, resource_tracker, grounding_mode):
        """Send a simple email then retrieve it to verify all persisted fields."""
        sender = _sender(grounding_mode)
        recipient = _recipient(grounding_mode)

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": "Hello World",
            "html": "<p>Hi there</p>",
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)
        assert UUID_RE.match(email_id)

        _delay(grounding_mode)

        # Round-trip: retrieve the email by ID
        fetched = resend.Emails.get(email_id)

        assert fetched["id"] == email_id
        assert fetched["object"] == "email"
        assert fetched["subject"] == "Hello World"
        assert fetched["html"] == "<p>Hi there</p>"

        # `to` is always an array
        assert recipient in fetched["to"]

        # `from` should match what we sent
        assert sender == fetched["from"] or "resend.dev" in fetched["from"] or "example.com" in fetched["from"]

        # created_at is a valid ISO 8601 timestamp
        assert ISO8601_RE.match(fetched["created_at"]), (
            f"Expected ISO 8601 timestamp, got: {fetched['created_at']}"
        )

        # Optional fields should be null or empty when not set
        assert fetched.get("bcc") is None or fetched.get("bcc") == []
        assert fetched.get("cc") is None or fetched.get("cc") == []
        assert fetched.get("reply_to") is None or fetched.get("reply_to") == []

    # ------------------------------------------------------------------
    # 2. Send an email with cc, bcc, reply_to, and tags
    # ------------------------------------------------------------------
    def test_send_email_with_all_options(self, resource_tracker, grounding_mode):
        """Send an email with cc, bcc, reply_to, and tags — verify send response."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)

        if grounding_mode:
            cc_addr = "delivered@resend.dev"
            bcc_addr = "delivered@resend.dev"
            reply_to_addr = "delivered@resend.dev"
        else:
            cc_addr = "cc@example.com"
            bcc_addr = "bcc@example.com"
            reply_to_addr = "reply@example.com"

        tags = [
            {"name": "category", "value": "test"},
            {"name": "environment", "value": "staging"},
        ]

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "cc": cc_addr,
            "bcc": bcc_addr,
            "reply_to": reply_to_addr,
            "subject": "Full Options",
            "html": "<p>Test</p>",
            "tags": tags,
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        assert email_id is not None
        assert UUID_RE.match(email_id), f"Expected UUID format, got: {email_id}"

    @pytest.mark.fake_only
    def test_send_email_with_all_options_readback(self, resource_tracker, grounding_mode):
        """Send email with all options then retrieve to verify cc, bcc, reply_to, tags."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)
        cc_addr = "cc@example.com"
        bcc_addr = "bcc@example.com"
        reply_to_addr = "reply@example.com"

        tags = [
            {"name": "category", "value": "test"},
            {"name": "environment", "value": "staging"},
        ]

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "cc": cc_addr,
            "bcc": bcc_addr,
            "reply_to": reply_to_addr,
            "subject": "Full Options",
            "html": "<p>Test</p>",
            "tags": tags,
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        _delay(grounding_mode)
        fetched = resend.Emails.get(email_id)

        assert fetched["id"] == email_id
        assert fetched["subject"] == "Full Options"
        assert recipient in fetched["to"]

        # cc, bcc, reply_to are arrays
        assert cc_addr in fetched["cc"]
        assert bcc_addr in fetched["bcc"]
        assert reply_to_addr in fetched["reply_to"]

        # Tags
        fetched_tags = fetched.get("tags", [])
        tag_map = {t["name"]: t["value"] for t in fetched_tags}
        assert tag_map.get("category") == "test"
        assert tag_map.get("environment") == "staging"

    # ------------------------------------------------------------------
    # 3. Send an email with plain text body instead of HTML
    # ------------------------------------------------------------------
    def test_send_email_with_plain_text(self, resource_tracker, grounding_mode):
        """Send an email with text body and verify send response."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": "Plain Text Email",
            "text": "This is plain text content",
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        assert email_id is not None
        assert UUID_RE.match(email_id)

    @pytest.mark.fake_only
    def test_send_email_with_plain_text_readback(self, resource_tracker, grounding_mode):
        """Send email with text body then retrieve to verify text/html fields."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": "Plain Text Email",
            "text": "This is plain text content",
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        _delay(grounding_mode)
        fetched = resend.Emails.get(email_id)

        assert fetched["id"] == email_id
        assert fetched["subject"] == "Plain Text Email"
        assert fetched["text"] == "This is plain text content"
        assert fetched.get("html") is None

    # ------------------------------------------------------------------
    # 4. Send an email to multiple recipients
    # ------------------------------------------------------------------
    def test_send_email_multiple_recipients(self, resource_tracker, grounding_mode):
        """Send an email to multiple recipients and verify send response."""
        sender = _sender_plain(grounding_mode)
        recipients = _recipients(grounding_mode, count=3)

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipients,
            "subject": "Multi-recipient",
            "html": "<p>Hello all</p>",
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        assert email_id is not None
        assert UUID_RE.match(email_id)

    @pytest.mark.fake_only
    def test_send_email_multiple_recipients_readback(self, resource_tracker, grounding_mode):
        """Send to multiple recipients then retrieve to verify to array."""
        sender = _sender_plain(grounding_mode)
        recipients = _recipients(grounding_mode, count=3)

        send_result = resend.Emails.send({
            "from": sender,
            "to": recipients,
            "subject": "Multi-recipient",
            "html": "<p>Hello all</p>",
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        _delay(grounding_mode)
        fetched = resend.Emails.get(email_id)

        assert fetched["id"] == email_id
        fetched_to = fetched["to"]
        assert isinstance(fetched_to, list)
        for r in recipients:
            assert r in fetched_to

    # ------------------------------------------------------------------
    # 5. Idempotency: same key returns same id (both modes)
    # ------------------------------------------------------------------
    def test_send_email_idempotency(self, resource_tracker, grounding_mode):
        """Sending the same email twice with an idempotency key returns the same id."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)

        # Use a unique idempotency key per test run
        idempotency_key = f"contract-test-{uuid.uuid4()}"

        email_params = {
            "from": sender,
            "to": recipient,
            "subject": "Idempotent Email",
            "html": "<p>Test</p>",
        }

        # First send
        result1 = resend.Emails.send(
            email_params,
            options={"idempotency_key": idempotency_key},
        )
        email_id_1 = result1["id"]
        resource_tracker.email(email_id_1)
        assert email_id_1 is not None

        _delay(grounding_mode)

        # Second send with same idempotency key
        result2 = resend.Emails.send(
            email_params,
            options={"idempotency_key": idempotency_key},
        )
        email_id_2 = result2["id"]

        # Same id returned — no duplicate
        assert email_id_1 == email_id_2

    # ------------------------------------------------------------------
    # 6. List sent emails — send works in both modes; list is fake_only
    # ------------------------------------------------------------------
    def test_list_sent_emails_send(self, resource_tracker, grounding_mode):
        """Send two emails and verify both send responses return valid ids."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)

        result1 = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": f"List Test 1 {uuid.uuid4().hex[:8]}",
            "html": "<p>1</p>",
        })
        email_id_1 = result1["id"]
        resource_tracker.email(email_id_1)
        assert UUID_RE.match(email_id_1)

        _delay(grounding_mode)

        result2 = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": f"List Test 2 {uuid.uuid4().hex[:8]}",
            "html": "<p>2</p>",
        })
        email_id_2 = result2["id"]
        resource_tracker.email(email_id_2)
        assert UUID_RE.match(email_id_2)

        # Both ids should be distinct
        assert email_id_1 != email_id_2

    @pytest.mark.fake_only
    def test_list_sent_emails(self, resource_tracker, grounding_mode):
        """Send two emails then list to verify they appear with correct fields."""
        sender = _sender_plain(grounding_mode)
        recipient = _recipient(grounding_mode)

        result1 = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": "List Test A",
            "html": "<p>A</p>",
        })
        email_id_1 = result1["id"]
        resource_tracker.email(email_id_1)

        _delay(grounding_mode)

        result2 = resend.Emails.send({
            "from": sender,
            "to": recipient,
            "subject": "List Test B",
            "html": "<p>B</p>",
        })
        email_id_2 = result2["id"]
        resource_tracker.email(email_id_2)

        _delay(grounding_mode)

        # List emails
        list_response = resend.Emails.list({"limit": 100})

        # Envelope structure
        assert list_response["object"] == "list"
        assert isinstance(list_response["data"], list)
        assert isinstance(list_response["has_more"], bool)

        # Containment: both emails should appear
        listed_ids = [e["id"] for e in list_response["data"]]
        assert email_id_1 in listed_ids, (
            f"Email {email_id_1} not found in listed emails"
        )
        assert email_id_2 in listed_ids, (
            f"Email {email_id_2} not found in listed emails"
        )

        # Each listed email has the expected summary fields
        for email_data in list_response["data"]:
            if email_data["id"] in (email_id_1, email_id_2):
                assert "id" in email_data
                assert "to" in email_data
                assert "from" in email_data
                assert "subject" in email_data
                assert "created_at" in email_data
