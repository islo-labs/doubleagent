"""
Contract tests for Contact Management scenario.

Covers creating, retrieving, updating, listing, and deleting contacts
including subscription management and lookup by email.

These tests run against both the real Resend API (grounding) and the
DoubleAgent fake.

SDK method signatures (from source inspection):
    resend.Contacts.create(params)          -> {"object": "contact", "id": "..."}
    resend.Contacts.get(audience_id=None, id=None, email=None) -> Contact dict
    resend.Contacts.update(params)          -> {"object": "contact", "id": "..."}
    resend.Contacts.list(audience_id=None, params=None)  -> ListResponse
    resend.Contacts.remove(audience_id=None, id=None, email=None) -> {"object": "contact", "contact": "...", "deleted": true}

Key quirks:
- Contacts.get/remove use keyword args (id=, email=), NOT positional
- Contacts.update takes a dict with "id" or "email" for identification
- Email takes precedence over id when both are provided
- Delete response uses "contact" field for the id, NOT "id"
- Resend hard-deletes: GET after DELETE returns 404
"""

import re
import time
import uuid

import pytest
import resend
from resend.exceptions import ResendError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _unique_email(prefix: str = "test") -> str:
    """Generate a unique email address for test isolation."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


def _delay(grounding_mode: bool) -> None:
    """Small delay in grounding mode to respect rate limits (2 req/s)."""
    if grounding_mode:
        time.sleep(0.6)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContactManagement:
    """Tests for Contact Management."""

    # ------------------------------------------------------------------
    # 1. Create a contact and retrieve it by id
    # ------------------------------------------------------------------
    def test_create_and_retrieve_contact(self, resource_tracker, grounding_mode):
        """Create a contact and retrieve it by id."""
        # Arrange
        email = _unique_email("john")

        # Act: create contact
        created = resend.Contacts.create({
            "email": email,
            "first_name": "John",
            "last_name": "Doe",
        })
        contact_id = created["id"]
        resource_tracker.contact(contact_id)

        # Assert: create response
        assert contact_id is not None
        assert UUID_RE.match(contact_id), f"Expected UUID format, got: {contact_id}"
        assert created["object"] == "contact"

        _delay(grounding_mode)

        # Act: read back by id
        fetched = resend.Contacts.get(id=contact_id)

        # Assert: retrieved contact matches what we created
        assert fetched["id"] == contact_id
        assert fetched["object"] == "contact"
        assert fetched["email"] == email
        assert fetched["first_name"] == "John"
        assert fetched["last_name"] == "Doe"
        assert fetched["unsubscribed"] is False
        assert ISO8601_RE.match(fetched["created_at"]), (
            f"Expected ISO 8601 timestamp, got: {fetched['created_at']}"
        )

    # ------------------------------------------------------------------
    # 2. Retrieve a contact using email address instead of id
    # ------------------------------------------------------------------
    def test_retrieve_contact_by_email(self, resource_tracker, grounding_mode):
        """Retrieve a contact using email address instead of id."""
        # Arrange
        email = _unique_email("lookup")

        # Act: create contact
        created = resend.Contacts.create({
            "email": email,
            "first_name": "Lookup",
            "last_name": "User",
        })
        contact_id = created["id"]
        resource_tracker.contact(contact_id)

        assert contact_id is not None
        assert created["object"] == "contact"

        _delay(grounding_mode)

        # Act: retrieve by email
        fetched = resend.Contacts.get(email=email)

        # Assert: fetched contact matches
        assert fetched["id"] == contact_id
        assert fetched["email"] == email
        assert fetched["first_name"] == "Lookup"
        assert fetched["last_name"] == "User"

    # ------------------------------------------------------------------
    # 3. Update a contact's name and subscription status
    # ------------------------------------------------------------------
    def test_update_contact_fields(self, resource_tracker, grounding_mode):
        """Update a contact's name and subscription status."""
        # Arrange: create a contact
        email = _unique_email("update-me")
        created = resend.Contacts.create({
            "email": email,
            "first_name": "Original",
            "last_name": "Name",
        })
        contact_id = created["id"]
        resource_tracker.contact(contact_id)

        _delay(grounding_mode)

        # Act: update the contact
        update_result = resend.Contacts.update({
            "id": contact_id,
            "first_name": "Updated",
            "last_name": "Person",
            "unsubscribed": True,
        })

        # Assert: update response
        assert update_result["id"] == contact_id
        assert update_result["object"] == "contact"

        _delay(grounding_mode)

        # Act: read back to verify persistence
        fetched = resend.Contacts.get(id=contact_id)

        # Assert: updated fields are persisted
        assert fetched["first_name"] == "Updated"
        assert fetched["last_name"] == "Person"
        assert fetched["unsubscribed"] is True

    # ------------------------------------------------------------------
    # 4. List contacts with limit and cursor-based pagination
    # ------------------------------------------------------------------
    def test_list_contacts_with_pagination(self, resource_tracker, grounding_mode):
        """List contacts and verify created contacts appear (containment)."""
        # Arrange: create three contacts with unique emails
        emails = [_unique_email(f"page{i}") for i in range(1, 4)]
        contact_ids = []

        for email in emails:
            created = resend.Contacts.create({
                "email": email,
                "first_name": f"Page",
                "last_name": f"Contact",
            })
            contact_ids.append(created["id"])
            resource_tracker.contact(created["id"])
            _delay(grounding_mode)

        _delay(grounding_mode)

        # Act: list contacts — collect all pages to handle pagination
        all_contacts = []
        list_params = {"limit": 100}
        result = resend.Contacts.list(params=list_params)

        # Assert: list response structure
        assert result["object"] == "list"
        assert isinstance(result["data"], list)
        assert isinstance(result["has_more"], bool)

        all_contacts.extend(result["data"])

        # If there are more pages, paginate through them
        while result["has_more"] and len(result["data"]) > 0:
            last_id = result["data"][-1]["id"]
            _delay(grounding_mode)
            result = resend.Contacts.list(params={"limit": 100, "after": last_id})
            all_contacts.extend(result["data"])

        # Assert: all three created contacts appear in the list (containment)
        all_ids = [c["id"] for c in all_contacts]
        for cid in contact_ids:
            assert cid in all_ids, f"Contact {cid} not found in list results"

        # Assert: each contact in the list has expected fields
        for contact_data in all_contacts:
            if contact_data["id"] in contact_ids:
                assert "id" in contact_data
                assert "email" in contact_data
                assert "created_at" in contact_data

    # ------------------------------------------------------------------
    # 5. Delete a contact by id and verify removal
    # ------------------------------------------------------------------
    def test_delete_contact_by_id(self, resource_tracker, grounding_mode):
        """Delete a contact by id and verify it returns 404 on subsequent GET."""
        # Arrange: create a contact
        email = _unique_email("delete-me")
        created = resend.Contacts.create({
            "email": email,
        })
        contact_id = created["id"]
        # Don't register with tracker since we're deleting it ourselves

        _delay(grounding_mode)

        # Act: delete the contact by id
        delete_result = resend.Contacts.remove(id=contact_id)

        # Assert: delete response
        # NOTE: Contact delete uses "contact" field (not "id") for the identifier
        assert delete_result["object"] == "contact"
        assert delete_result["contact"] == contact_id
        assert delete_result["deleted"] is True

        _delay(grounding_mode)

        # Assert: GET on deleted contact returns 404 (hard-delete)
        with pytest.raises(ResendError) as exc_info:
            resend.Contacts.get(id=contact_id)

        error = exc_info.value
        assert str(error.code) == "404" or error.code == 404

    # ------------------------------------------------------------------
    # 6. Delete a contact using email address
    # ------------------------------------------------------------------
    def test_delete_contact_by_email(self, resource_tracker, grounding_mode):
        """Delete a contact using email address and verify removal."""
        # Arrange: create a contact
        email = _unique_email("delete-by-email")
        created = resend.Contacts.create({
            "email": email,
        })
        contact_id = created["id"]
        # Don't register with tracker since we're deleting it ourselves

        _delay(grounding_mode)

        # Act: delete the contact by email
        delete_result = resend.Contacts.remove(email=email)

        # Assert: delete response
        assert delete_result["object"] == "contact"
        assert delete_result["deleted"] is True

        _delay(grounding_mode)

        # Assert: GET on deleted contact by email returns 404 (hard-delete)
        with pytest.raises(ResendError) as exc_info:
            resend.Contacts.get(email=email)

        error = exc_info.value
        assert str(error.code) == "404" or error.code == 404
