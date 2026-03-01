"""
Contract tests for API Key Management scenario.

Covers creating API keys with different permission levels,
listing keys, and deleting keys.
"""

import re
import time
import uuid

import pytest
import resend


def _delay(grounding_mode: bool) -> None:
    """Small delay in grounding mode to respect rate limits (2 req/s)."""
    if grounding_mode:
        time.sleep(0.6)


class TestApiKeyManagement:
    """Tests for API Key Management."""

    def test_create_full_access_api_key(self, resource_tracker, grounding_mode):
        """Create an API key with full access permissions and verify it appears in the list."""
        # Arrange
        key_name = f"Production Key {uuid.uuid4().hex[:8]}"

        # Act: create API key with full_access permission
        created = resend.ApiKeys.create({
            "name": key_name,
            "permission": "full_access",
        })
        resource_tracker.api_key(created["id"])

        # Assert: create response has expected fields
        assert created["id"] is not None
        # ID should be a UUID
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            created["id"],
        )
        # Token should start with 're_'
        assert created["token"] is not None
        assert created["token"].startswith("re_")

        _delay(grounding_mode)

        # Act: list API keys to verify the created key appears
        list_result = resend.ApiKeys.list()

        # Assert: list response structure
        assert list_result["object"] == "list"
        assert isinstance(list_result["data"], list)
        assert isinstance(list_result["has_more"], bool)

        # Assert: created key appears in the list (containment assertion)
        key_ids = [k["id"] for k in list_result["data"]]
        assert created["id"] in key_ids

        # Assert: the key in the list has expected fields
        found = [k for k in list_result["data"] if k["id"] == created["id"]][0]
        assert found["name"] == key_name
        assert "created_at" in found

    @pytest.mark.fake_only
    def test_create_sending_access_api_key_with_domain(self, resource_tracker, grounding_mode):
        """Create an API key restricted to sending from a specific domain.

        Marked fake_only because it creates a domain, which is limited to 1 on the free tier.
        """
        # Arrange: create a domain first
        domain_name = f"restricted-{uuid.uuid4().hex[:8]}.example.com"
        domain = resend.Domains.create({"name": domain_name})
        resource_tracker.domain(domain["id"])

        _delay(grounding_mode)

        # Act: create API key with sending_access scoped to the domain
        key_name = f"Restricted Sender {uuid.uuid4().hex[:8]}"
        created = resend.ApiKeys.create({
            "name": key_name,
            "permission": "sending_access",
            "domain_id": domain["id"],
        })
        resource_tracker.api_key(created["id"])

        # Assert: create response
        assert created["id"] is not None
        assert created["token"] is not None
        assert created["token"].startswith("re_")

        _delay(grounding_mode)

        # Act: list API keys to verify the restricted key appears
        list_result = resend.ApiKeys.list()

        # Assert: the restricted key appears in the list (containment assertion)
        key_names = [k["name"] for k in list_result["data"]]
        assert key_name in key_names

        # Verify the key in the list has the correct name
        found = [k for k in list_result["data"] if k["id"] == created["id"]][0]
        assert found["name"] == key_name

    def test_delete_api_key(self, resource_tracker, grounding_mode):
        """Delete an API key and verify it is removed from the list."""
        # Arrange: create an API key
        key_name = f"Temporary Key {uuid.uuid4().hex[:8]}"
        created = resend.ApiKeys.create({
            "name": key_name,
        })
        # Don't register with tracker since we're deleting it ourselves

        # Assert: key was created
        assert created["id"] is not None
        assert created["token"] is not None

        _delay(grounding_mode)

        # Act: delete the API key
        # ApiKeys.remove() returns None (empty body from API)
        result = resend.ApiKeys.remove(created["id"])
        assert result is None

        _delay(grounding_mode)

        # Act: list API keys to verify the deleted key is gone
        list_result = resend.ApiKeys.list()

        # Assert: the deleted key does NOT appear in the list
        key_ids = [k["id"] for k in list_result["data"]]
        assert created["id"] not in key_ids
