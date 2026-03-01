"""
Contract tests for Template Lifecycle scenario.

Covers creating, retrieving, listing, publishing, duplicating, updating,
and deleting email templates.
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


class TestTemplateLifecycle:
    """Tests for Template Lifecycle."""

    def test_create_and_retrieve_template(self, resource_tracker, grounding_mode):
        """Create a template and retrieve its full details."""
        # Arrange
        unique = uuid.uuid4().hex[:8]
        template_name = f"Welcome Email {unique}"

        # Act: create template
        # NOTE: Resend templates use triple-brace syntax {{{VARIABLE}}} in html.
        # Using double braces in html triggers a 422 validation error.
        created = resend.Templates.create({
            "name": template_name,
            "subject": "Welcome {{{firstName}}}!",
            "from": "noreply@example.com",
            "html": "<h1>Hello {{{firstName}}}</h1><p>Welcome to our service.</p>",
            "variables": [
                {
                    "key": "firstName",
                    "type": "string",
                    "fallback_value": "there",
                }
            ],
        })
        resource_tracker.template(created["id"])

        # Assert: create response
        assert created["id"] is not None
        assert created["object"] == "template"

        _delay(grounding_mode)

        # Act: read back
        fetched = resend.Templates.get(created["id"])

        # Assert: core fields
        assert fetched["object"] == "template"
        assert fetched["id"] == created["id"]
        assert fetched["name"] == template_name
        assert fetched["subject"] == "Welcome {{{firstName}}}!"
        assert "Hello {{{firstName}}}" in fetched["html"]
        assert fetched["status"] == "draft"

        # Assert: timestamps present
        assert fetched["created_at"] is not None
        assert fetched["updated_at"] is not None

        # Assert: variables (containment check)
        variable_keys = [v["key"] for v in fetched["variables"]]
        assert "firstName" in variable_keys

    def test_publish_template(self, resource_tracker, grounding_mode):
        """Publish a template and verify its status changes to published."""
        # Arrange: create template
        unique = uuid.uuid4().hex[:8]
        created = resend.Templates.create({
            "name": f"Order Confirmation {unique}",
            "subject": "Order #{{{orderNumber}}} Confirmed",
            "from": "orders@example.com",
            "html": "<p>Thank you for order #{{{orderNumber}}}!</p>",
            "variables": [{"key": "orderNumber", "type": "string"}],
        })
        resource_tracker.template(created["id"])
        assert created["id"] is not None

        _delay(grounding_mode)

        # Act: publish template
        publish_resp = resend.Templates.publish(created["id"])

        # Assert: publish response
        assert publish_resp["id"] == created["id"]

        _delay(grounding_mode)

        # Assert: read back and verify published status
        fetched = resend.Templates.get(created["id"])
        assert fetched["status"] == "published"
        assert fetched["published_at"] is not None

    def test_list_templates(self, resource_tracker, grounding_mode):
        """List templates and verify the created template appears."""
        # Arrange: create a template
        unique = uuid.uuid4().hex[:8]
        template_name = f"List Test Template {unique}"
        created = resend.Templates.create({
            "name": template_name,
            "html": "<p>Test</p>",
        })
        resource_tracker.template(created["id"])
        assert created["id"] is not None

        _delay(grounding_mode)

        # Act: list templates (paginate to collect all)
        all_template_ids = []
        list_params = {"limit": 100}
        while True:
            result = resend.Templates.list(list_params)

            # Assert: list response structure
            assert result["object"] == "list"
            assert isinstance(result["data"], list)
            assert isinstance(result["has_more"], bool)

            for t in result["data"]:
                all_template_ids.append(t["id"])
                # Each list item should have summary fields
                assert "name" in t
                assert "status" in t
                assert "created_at" in t
                assert "updated_at" in t

            if not result["has_more"]:
                break
            # Paginate forward
            last_id = result["data"][-1]["id"]
            list_params = {"limit": 100, "after": last_id}
            _delay(grounding_mode)

        # Assert: containment — our template is in the list
        assert created["id"] in all_template_ids

    def test_duplicate_template(self, resource_tracker, grounding_mode):
        """Duplicate an existing template and verify the copy."""
        # Arrange: create original template
        unique = uuid.uuid4().hex[:8]
        created = resend.Templates.create({
            "name": f"Original Template {unique}",
            "html": "<p>Original content</p>",
            "subject": "Original Subject",
        })
        resource_tracker.template(created["id"])
        assert created["id"] is not None

        _delay(grounding_mode)

        # Act: duplicate
        dup_resp = resend.Templates.duplicate(created["id"])

        # Assert: duplicate response has a new, different id
        assert dup_resp["id"] is not None
        assert dup_resp["id"] != created["id"]
        resource_tracker.template(dup_resp["id"])

        _delay(grounding_mode)

        # Assert: read back duplicated template — content matches original
        dup_fetched = resend.Templates.get(dup_resp["id"])
        assert dup_fetched["id"] == dup_resp["id"]
        assert dup_fetched["id"] != created["id"]
        assert "Original content" in dup_fetched["html"]

    def test_update_and_delete_template(self, resource_tracker, grounding_mode):
        """Update a template's content then delete it and verify 404."""
        # Arrange: create template
        unique = uuid.uuid4().hex[:8]
        created = resend.Templates.create({
            "name": f"Mutable Template {unique}",
            "html": "<p>Version 1</p>",
        })
        # Don't register with tracker since we're deleting it ourselves
        assert created["id"] is not None

        _delay(grounding_mode)

        # Act: update template
        update_resp = resend.Templates.update({
            "id": created["id"],
            "name": "Updated Template",
            "html": "<p>Version 2</p>",
        })

        # Assert: update response
        assert update_resp["id"] == created["id"]

        _delay(grounding_mode)

        # Assert: read back updated template
        fetched = resend.Templates.get(created["id"])
        assert fetched["name"] == "Updated Template"
        assert "Version 2" in fetched["html"]

        _delay(grounding_mode)

        # Act: delete template
        delete_resp = resend.Templates.remove(created["id"])

        # Assert: delete response
        assert delete_resp["id"] == created["id"]
        assert delete_resp["object"] == "template"
        assert delete_resp["deleted"] is True

        _delay(grounding_mode)

        # Assert: GET on deleted template returns 404 (hard delete)
        with pytest.raises(ResendError) as exc_info:
            resend.Templates.get(created["id"])

        error = exc_info.value
        assert str(error.code) == "404" or error.code == 404
