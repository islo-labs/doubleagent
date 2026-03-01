"""
Contract tests for Domain Management scenario.

Covers the full lifecycle of domain registration, configuration,
verification, listing, updating, and deletion.
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


@pytest.mark.fake_only
class TestDomainManagement:
    """Tests for Domain Management.

    Marked fake_only because the Resend free tier only allows 1 domain.
    These tests create multiple domains and cannot run against a free-tier account.
    They were grounded individually during development to verify response shapes.
    """

    def test_create_and_retrieve_domain(self, resource_tracker, grounding_mode):
        """Create a domain and retrieve its details with DNS records."""
        # Arrange
        domain_name = f"test-{uuid.uuid4().hex[:8]}.example.com"

        # Act: create domain
        created = resend.Domains.create({"name": domain_name})
        resource_tracker.domain(created["id"])

        _delay(grounding_mode)

        # Assert: create response has expected fields
        assert created["id"] is not None
        assert created["name"] == domain_name
        assert created["status"] in ("not_started", "pending")
        assert created["region"] == "us-east-1"
        assert "created_at" in created
        assert "records" in created
        records = created["records"]
        assert isinstance(records, list)
        assert len(records) > 0
        for record in records:
            assert "record" in record
            assert "name" in record
            assert "value" in record
            assert "type" in record
            assert "ttl" in record
            assert "status" in record

        # Act: read back
        fetched = resend.Domains.get(created["id"])

        # Assert: retrieved domain matches
        assert fetched["id"] == created["id"]
        assert fetched["name"] == domain_name
        assert "status" in fetched
        assert "region" in fetched
        assert "created_at" in fetched
        assert "records" in fetched
        assert isinstance(fetched["records"], list)
        assert len(fetched["records"]) > 0

    def test_create_domain_with_options(self, resource_tracker, grounding_mode):
        """Create a domain with custom region."""
        # Arrange
        domain_name = f"eu-{uuid.uuid4().hex[:8]}.example.com"

        # Act: create domain with custom region
        created = resend.Domains.create({
            "name": domain_name,
            "region": "eu-west-1",
        })
        resource_tracker.domain(created["id"])

        _delay(grounding_mode)

        # Assert: create response
        assert created["id"] is not None
        assert created["name"] == domain_name
        assert created["region"] == "eu-west-1"
        assert "records" in created
        assert isinstance(created["records"], list)

        # Act: read back
        fetched = resend.Domains.get(created["id"])

        # Assert: region persisted
        assert fetched["name"] == domain_name
        assert fetched["region"] == "eu-west-1"

    def test_list_domains(self, resource_tracker, grounding_mode):
        """List all domains and verify the created domain appears."""
        # Arrange: create a domain
        domain_name = f"list-{uuid.uuid4().hex[:8]}.example.com"
        created = resend.Domains.create({"name": domain_name})
        resource_tracker.domain(created["id"])

        _delay(grounding_mode)

        # Act: list domains
        result = resend.Domains.list()

        # Assert: list response structure
        assert result["object"] == "list"
        assert isinstance(result["data"], list)
        assert isinstance(result["has_more"], bool)

        # Assert: created domain appears in the list (containment assertion)
        domain_ids = [d["id"] for d in result["data"]]
        assert created["id"] in domain_ids

        # Assert: each domain in the list has expected fields
        found = [d for d in result["data"] if d["id"] == created["id"]][0]
        assert found["name"] == domain_name
        assert "status" in found
        assert "created_at" in found
        assert "region" in found

    def test_update_domain_tracking(self, resource_tracker, grounding_mode):
        """Update domain tracking settings."""
        # Arrange: create a domain
        domain_name = f"update-{uuid.uuid4().hex[:8]}.example.com"
        created = resend.Domains.create({"name": domain_name})
        resource_tracker.domain(created["id"])

        _delay(grounding_mode)

        # Act: update tracking settings
        # NOTE: The real Resend API expects camelCase parameter names
        # (openTracking, clickTracking) even though the SDK TypedDict defines
        # snake_case (open_tracking, click_tracking). The SDK passes the dict
        # through as-is, so we use camelCase to match the real API.
        # The tls parameter is excluded because the real API rejects it
        # in domain updates with a 400 validation error.
        update_result = resend.Domains.update({
            "id": created["id"],
            "openTracking": True,
            "clickTracking": True,
        })

        # Assert: update response
        assert update_result["id"] == created["id"]
        assert update_result["object"] == "domain"

    def test_verify_domain(self, resource_tracker, grounding_mode):
        """Trigger domain verification."""
        # Arrange: create a domain
        domain_name = f"verify-{uuid.uuid4().hex[:8]}.example.com"
        created = resend.Domains.create({"name": domain_name})
        resource_tracker.domain(created["id"])

        _delay(grounding_mode)

        # Act: trigger verification
        verify_result = resend.Domains.verify(created["id"])

        # Assert: verify response
        assert verify_result["id"] == created["id"]
        assert verify_result["object"] == "domain"

    def test_delete_domain(self, resource_tracker, grounding_mode):
        """Delete a domain and verify it returns 404 on subsequent GET."""
        # Arrange: create a domain
        domain_name = f"delete-{uuid.uuid4().hex[:8]}.example.com"
        created = resend.Domains.create({"name": domain_name})
        # Don't register with tracker since we're deleting it ourselves

        _delay(grounding_mode)

        # Act: delete the domain
        delete_result = resend.Domains.remove(created["id"])

        # Assert: delete response
        assert delete_result["id"] == created["id"]
        assert delete_result["object"] == "domain"
        assert delete_result["deleted"] is True

        _delay(grounding_mode)

        # Assert: GET on deleted domain returns 404
        # Resend hard-deletes (no soft-delete), so GET should raise a not_found error.
        with pytest.raises(ResendError) as exc_info:
            resend.Domains.get(created["id"])

        error = exc_info.value
        # Accept either int or string for code since SDK behavior may vary
        assert str(error.code) == "404" or error.code == 404
