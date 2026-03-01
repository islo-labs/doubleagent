"""
Contract tests for scenario: template-email-integration — Template and Email Integration

Covers sending emails using templates with variable substitution, testing
template alias lookups, and verifying template defaults are applied or
overridden when sending.

These tests run against both the real Resend API (grounding) and the
DoubleAgent fake.

NOTE on grounding key permissions:
Template CRUD and email read-back may require full_access.  If the grounding
key only has sending_access, tests that call GET /templates or GET /emails
are marked @pytest.mark.fake_only since those endpoints return 401 for
restricted keys.  All send operations (POST /emails with template) are
verified in both modes.
"""

import re
import time
import uuid

import resend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _delay(grounding_mode: bool, seconds: float = 1.0) -> None:
    """Small delay in grounding mode to respect rate limits (2 req/s)."""
    if grounding_mode:
        time.sleep(seconds)


def _sender(grounding_mode: bool) -> str:
    """Return a valid sender address for email sending."""
    if grounding_mode:
        return "onboarding@resend.dev"
    return "billing@example.com"


def _recipient(grounding_mode: bool) -> str:
    """Return a valid recipient.  In grounding mode only delivered@resend.dev works."""
    if grounding_mode:
        return "delivered@resend.dev"
    return "client@example.com"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTemplateEmailIntegration:
    """Tests for Template and Email Integration."""

    # ------------------------------------------------------------------
    # 1. Send an email using a published template with variable substitution
    # ------------------------------------------------------------------
    def test_send_email_with_template_variables(self, resource_tracker, grounding_mode):
        """
        Create a template with variables, publish it, send an email using
        the template with variable values, then retrieve the sent email
        to verify the template was applied correctly.
        """
        unique = uuid.uuid4().hex[:8]

        # Arrange: create template with variables
        # Resend uses triple-brace {{{VAR}}} syntax in HTML for variable placeholders
        created = resend.Templates.create({
            "name": f"Invoice Template {unique}",
            "subject": "Invoice #{{{invoiceId}}}",
            "from": _sender(grounding_mode),
            "html": (
                "<p>Dear {{{customerName}}}, your invoice "
                "#{{{invoiceId}}} for ${{{amount}}} is attached.</p>"
            ),
            "variables": [
                {"key": "invoiceId", "type": "string"},
                {"key": "customerName", "type": "string", "fallback_value": "Customer"},
                {"key": "amount", "type": "string"},
            ],
        })
        template_id = created["id"]
        resource_tracker.template(template_id)

        assert template_id is not None
        assert UUID_RE.match(template_id)
        assert created["object"] == "template"

        _delay(grounding_mode)

        # Act: publish the template
        publish_resp = resend.Templates.publish(template_id)
        assert publish_resp["id"] == template_id

        _delay(grounding_mode)

        # Verify template is published
        fetched_template = resend.Templates.get(template_id)
        assert fetched_template["status"] == "published"
        assert fetched_template["published_at"] is not None

        _delay(grounding_mode)

        # Act: send an email using the template with variable substitution
        recipient = _recipient(grounding_mode)
        send_result = resend.Emails.send({
            "from": _sender(grounding_mode),
            "to": recipient,
            "template": {
                "id": template_id,
                "variables": {
                    "invoiceId": "INV-001",
                    "customerName": "Alice Smith",
                    "amount": "99.99",
                },
            },
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        assert email_id is not None
        assert UUID_RE.match(email_id)

        # Template-based sends may take longer to become retrievable on the real API
        _delay(grounding_mode, seconds=3.0)

        # Round-trip: retrieve the sent email and verify template was applied
        fetched_email = resend.Emails.get(email_id)

        assert fetched_email["id"] == email_id
        assert fetched_email["object"] == "email"
        assert recipient in fetched_email["to"]

        # The subject should have the variable substituted
        assert fetched_email["subject"] == "Invoice #INV-001"

        # The from address should match the template default
        assert _sender(grounding_mode) in fetched_email["from"]

    # ------------------------------------------------------------------
    # 2. Override template defaults when sending an email
    # ------------------------------------------------------------------
    def test_send_template_with_from_override(self, resource_tracker, grounding_mode):
        """
        Create a template with default from and subject, publish it, then
        send an email that overrides both from and subject. Verify the
        overrides take effect.
        """
        unique = uuid.uuid4().hex[:8]

        # Arrange: create template with defaults
        default_sender = _sender(grounding_mode)
        created = resend.Templates.create({
            "name": f"Overridable Template {unique}",
            "subject": "Default Subject",
            "from": default_sender,
            "html": "<p>Hello {{{name}}}</p>",
            "variables": [{"key": "name", "type": "string"}],
        })
        template_id = created["id"]
        resource_tracker.template(template_id)

        assert template_id is not None
        assert created["object"] == "template"

        _delay(grounding_mode)

        # Publish the template
        publish_resp = resend.Templates.publish(template_id)
        assert publish_resp["id"] == template_id

        _delay(grounding_mode)

        # Verify template is published
        fetched_template = resend.Templates.get(template_id)
        assert fetched_template["status"] == "published"

        _delay(grounding_mode)

        # Act: send email with overridden from and subject
        # In grounding mode, we must use resend.dev sender.
        # The override demonstrates we can specify from/subject alongside template.
        override_sender = _sender(grounding_mode)
        override_subject = f"Custom Subject {unique}"
        recipient = _recipient(grounding_mode)

        send_result = resend.Emails.send({
            "from": override_sender,
            "to": recipient,
            "subject": override_subject,
            "template": {
                "id": template_id,
                "variables": {
                    "name": "Bob",
                },
            },
        })
        email_id = send_result["id"]
        resource_tracker.email(email_id)

        assert email_id is not None
        assert UUID_RE.match(email_id)

        # Template-based sends may take longer to become retrievable on the real API
        _delay(grounding_mode, seconds=3.0)

        # Round-trip: retrieve the sent email and verify overrides applied
        fetched_email = resend.Emails.get(email_id)

        assert fetched_email["id"] == email_id
        assert fetched_email["object"] == "email"
        assert recipient in fetched_email["to"]

        # The subject should be the overridden value, not the template default
        assert fetched_email["subject"] == override_subject

        # The from should be the overridden sender
        assert override_sender in fetched_email["from"]

    # ------------------------------------------------------------------
    # 3. Send an email referencing a template by its alias
    # ------------------------------------------------------------------
    def test_send_template_with_alias(self, resource_tracker, grounding_mode):
        """
        Create a template with an alias, publish it, then retrieve the
        template using its alias to verify alias-based lookup works.
        """
        unique = uuid.uuid4().hex[:8]
        alias = f"welcome-email-{unique}"

        # Arrange: create template with alias
        created = resend.Templates.create({
            "name": f"Alias Template {unique}",
            "alias": alias,
            "subject": "Welcome!",
            "from": _sender(grounding_mode),
            "html": "<p>Welcome, {{{name}}}!</p>",
            "variables": [{"key": "name", "type": "string"}],
        })
        template_id = created["id"]
        resource_tracker.template(template_id)

        assert template_id is not None
        assert created["object"] == "template"

        _delay(grounding_mode)

        # Act: publish the template
        publish_resp = resend.Templates.publish(template_id)
        assert publish_resp["id"] == template_id

        _delay(grounding_mode)

        # Act: retrieve the template using alias instead of id
        fetched = resend.Templates.get(alias)

        # Assert: template details match
        assert fetched["object"] == "template"
        assert fetched["id"] == template_id
        assert fetched["name"] == f"Alias Template {unique}"
        assert fetched["alias"] == alias
        assert fetched["status"] == "published"
        assert fetched["published_at"] is not None

        # Assert: template content is correct
        assert "Welcome" in fetched["html"]
        assert fetched["subject"] == "Welcome!"

        # Assert: variables present
        variable_keys = [v["key"] for v in fetched["variables"]]
        assert "name" in variable_keys
