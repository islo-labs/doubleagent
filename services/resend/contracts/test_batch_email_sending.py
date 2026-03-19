"""
Contract tests for scenario: batch-email-sending — Batch Email Sending.

Covers sending multiple emails in a single API call, verifying individual
email tracking, and testing that each email in a batch can have different
recipients and options.

These tests run against both the real Resend API (grounding) and the
DoubleAgent fake server.
"""

import time
import uuid

import resend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sender(grounding_mode: bool) -> str:
    """Return a valid sender address for the current mode."""
    if grounding_mode:
        return "Contract Test <test@resend.dev>"
    return "sender@example.com"


def _recipient(grounding_mode: bool, label: str = "") -> str:
    """
    Return a valid recipient address for the current mode.

    In grounding mode, the resend.dev shared domain only allows sending
    to delivered@resend.dev, so ALL recipients map to that address.
    """
    if grounding_mode:
        return "delivered@resend.dev"
    return f"{label or 'user'}@example.com"


def _unique_subject(prefix: str) -> str:
    """Generate a unique subject line to avoid collisions in grounding mode."""
    return f"{prefix} {uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestBatchEmailSending:
    """Tests for Batch Email Sending scenario."""

    def test_send_batch_emails(self, resource_tracker, grounding_mode):
        """
        Send a batch of 3 emails in one request and verify each can be
        retrieved individually with correct fields.

        BDD spec: send-batch-emails
        """
        sender = _sender(grounding_mode)
        recipient1 = _recipient(grounding_mode, "user1")
        recipient2 = _recipient(grounding_mode, "user2")
        recipient3 = _recipient(grounding_mode, "user3")

        subject1 = _unique_subject("Batch 1")
        subject2 = _unique_subject("Batch 2")
        subject3 = _unique_subject("Batch 3")

        # --- Act: send batch of 3 emails ---
        batch_response = resend.Batch.send([
            {
                "from": sender,
                "to": [recipient1],
                "subject": subject1,
                "html": "<p>Batch test 1</p>",
            },
            {
                "from": sender,
                "to": [recipient2],
                "subject": subject2,
                "html": "<p>Batch test 2</p>",
            },
            {
                "from": sender,
                "to": [recipient3],
                "subject": subject3,
                "html": "<p>Batch test 3</p>",
            },
        ])

        # --- Assert: batch response shape ---
        assert "data" in batch_response
        data = batch_response["data"]
        assert len(data) == 3

        ids = []
        for item in data:
            assert "id" in item
            assert item["id"] is not None
            ids.append(item["id"])

        # All IDs must be unique
        assert len(set(ids)) == 3

        # Track for cleanup (emails aren't deletable, but track for reference)
        for eid in ids:
            resource_tracker.email(eid)

        if grounding_mode:
            time.sleep(3)  # emails need time to become retrievable on the real API

        # --- Round-trip: retrieve first email ---
        email1 = resend.Emails.get(email_id=ids[0])
        assert email1["id"] == ids[0]
        assert email1["subject"] == subject1
        assert recipient1 in email1["to"]
        # The from field should contain the sender (may be formatted differently)
        assert sender.split("<")[-1].rstrip(">") in email1["from"] or sender in str(email1["from"])

        if grounding_mode:
            time.sleep(0.5)

        # --- Round-trip: retrieve third email ---
        email3 = resend.Emails.get(email_id=ids[2])
        assert email3["id"] == ids[2]
        assert email3["subject"] == subject3
        assert recipient3 in email3["to"]

    def test_batch_emails_individual_options(self, resource_tracker, grounding_mode):
        """
        Each email in a batch can have different recipients and options
        (tags, reply_to, etc.).

        BDD spec: batch-emails-individual-options
        """
        sender = _sender(grounding_mode)
        recipient_alice = _recipient(grounding_mode, "alice")
        recipient_bob = _recipient(grounding_mode, "bob")

        subject_alice = _unique_subject("For Alice")
        subject_bob = _unique_subject("For Bob")

        # Use a unique reply_to that is distinguishable
        reply_to_addr = "support@example.com"

        # --- Act: send batch of 2 emails with different options ---
        batch_response = resend.Batch.send([
            {
                "from": sender,
                "to": [recipient_alice],
                "subject": subject_alice,
                "html": "<p>Hello Alice</p>",
                "tags": [{"name": "type", "value": "greeting"}],
            },
            {
                "from": sender,
                "to": [recipient_bob],
                "subject": subject_bob,
                "html": "<p>Hello Bob</p>",
                "reply_to": [reply_to_addr],
            },
        ])

        # --- Assert: batch response shape ---
        assert "data" in batch_response
        data = batch_response["data"]
        assert len(data) == 2

        id_alice = data[0]["id"]
        id_bob = data[1]["id"]
        assert id_alice is not None
        assert id_bob is not None
        assert id_alice != id_bob

        resource_tracker.email(id_alice)
        resource_tracker.email(id_bob)

        if grounding_mode:
            time.sleep(3)  # emails need time to become retrievable on the real API

        # --- Round-trip: retrieve Alice's email ---
        email_alice = resend.Emails.get(email_id=id_alice)
        assert email_alice["id"] == id_alice
        assert email_alice["subject"] == subject_alice
        assert recipient_alice in email_alice["to"]
        # Tags should contain the one we set
        tags = email_alice.get("tags") or []
        tag_names = [t["name"] for t in tags]
        tag_values = [t["value"] for t in tags]
        assert "type" in tag_names
        assert "greeting" in tag_values

        if grounding_mode:
            time.sleep(0.5)

        # --- Round-trip: retrieve Bob's email ---
        email_bob = resend.Emails.get(email_id=id_bob)
        assert email_bob["id"] == id_bob
        assert email_bob["subject"] == subject_bob
        assert recipient_bob in email_bob["to"]
        # reply_to should contain our support address
        reply_to = email_bob.get("reply_to") or []
        assert reply_to_addr in reply_to
