"""
Contract tests for error-handling scenario: Error Handling and Edge Cases.

Covers authentication failures, validation errors, not-found errors,
and other edge cases that AI agents must handle gracefully.
"""

import uuid
import time

import pytest
import resend
from resend.exceptions import ResendError


def _delay(grounding_mode: bool) -> None:
    """Small delay in grounding mode to respect rate limits (2 req/s)."""
    if grounding_mode:
        time.sleep(0.6)


class TestMissingRequiredEmailFields:
    """Sending an email without required fields returns validation error."""

    def test_send_email_missing_to_field(self, resource_tracker, grounding_mode):
        """Attempt to send an email with only 'from', omitting 'to' and 'subject'.

        Per the API validation order, missing `to` is checked first and
        returns a 422 error with name 'missing_required_field'.
        """
        _delay(grounding_mode)

        with pytest.raises(ResendError) as exc_info:
            resend.Emails.send(
                {
                    "from": "sender@resend.dev",
                }
            )

        err = exc_info.value
        # The API returns 422 for missing required fields
        assert str(err.code) == "422" or int(err.code) == 422
        # The error message should mention the missing `to` field
        assert "to" in err.message.lower()


class TestRetrieveNonexistentEmail:
    """Retrieving a non-existent email returns 404."""

    def test_get_email_with_random_uuid(self, resource_tracker, grounding_mode):
        """Attempt to retrieve an email with a random UUID that does not exist."""
        _delay(grounding_mode)

        fake_id = str(uuid.uuid4())

        with pytest.raises(ResendError) as exc_info:
            resend.Emails.get(fake_id)

        err = exc_info.value
        assert str(err.code) == "404" or int(err.code) == 404
        assert err.error_type == "not_found"


class TestInvalidApiKey:
    """Using an invalid API key returns an error.

    Per the API substrate docs, an invalid API key actually returns
    HTTP 400 with name 'validation_error' (NOT 401 or 403).
    The SDK maps this to ValidationError.
    """

    def test_list_emails_with_invalid_key(self, grounding_mode):
        """Attempt to list emails using an invalid API key."""
        _delay(grounding_mode)

        # Save the original key and URL so we can restore them
        original_key = resend.api_key
        original_url = resend.api_url

        try:
            # Set a deliberately invalid API key
            resend.api_key = "re_invalid_key_12345"
            # Keep the same URL (real API or fake)

            with pytest.raises(ResendError) as exc_info:
                resend.Emails.list()

            err = exc_info.value
            # The real API returns 400 with validation_error for invalid keys
            assert int(err.code) in (400, 403)
            assert "invalid" in err.message.lower() or "api key" in err.message.lower()
        finally:
            # Restore the original SDK configuration
            resend.api_key = original_key
            resend.api_url = original_url


class TestMissingApiKey:
    """Omitting the Authorization header returns 401.

    Note: The SDK always sends the api_key from module state. To test
    a truly missing key, we set api_key to an empty string which
    results in 'Bearer ' header — the API treats this as missing/invalid.
    """

    def test_send_email_without_api_key(self, grounding_mode):
        """Attempt to send an email without any valid API key."""
        _delay(grounding_mode)

        original_key = resend.api_key
        original_url = resend.api_url

        try:
            # Set an empty API key to simulate missing auth
            resend.api_key = ""

            with pytest.raises(ResendError) as exc_info:
                resend.Emails.send(
                    {
                        "from": "sender@resend.dev",
                        "to": "delivered@resend.dev",
                        "subject": "No Auth",
                        "html": "<p>Should fail</p>",
                    }
                )

            err = exc_info.value
            # Empty key is treated as missing or invalid by the API.
            # The API may return 401 (missing_api_key) or 400 (validation_error).
            assert int(err.code) in (400, 401)
        finally:
            resend.api_key = original_key
            resend.api_url = original_url


class TestCreateContactWithSpecialCharacters:
    """Create a contact with special characters in name fields."""

    def test_unicode_and_special_chars_preserved(self, resource_tracker, grounding_mode):
        """Create a contact with unicode first_name and special-char last_name,
        then read it back and verify the characters are preserved exactly."""
        _delay(grounding_mode)

        unique_email = f"special-{uuid.uuid4().hex[:8]}@example.com"

        # Create contact with special characters
        created = resend.Contacts.create(
            {
                "email": unique_email,
                "first_name": "José María",
                "last_name": "O'Connor-Smith",
            }
        )
        assert created["id"] is not None
        contact_id = created["id"]
        resource_tracker.contact(contact_id)

        _delay(grounding_mode)

        # Read back and verify special characters are preserved
        fetched = resend.Contacts.get(id=contact_id)
        assert fetched["id"] == contact_id
        assert fetched["email"] == unique_email
        assert fetched["first_name"] == "José María"
        assert fetched["last_name"] == "O'Connor-Smith"


class TestApiKeyNameMaxLength:
    """Creating an API key with a name exceeding 50 characters.

    The API documentation states a 50-character maximum for API key names,
    but the real API does not enforce this limit and accepts longer names.
    This test verifies the API key creation succeeds even with a long name,
    and verifies it appears in the list.
    """

    def test_api_key_name_at_boundary(self, resource_tracker, grounding_mode):
        """Create an API key with a 51-character name and verify it is accepted."""
        _delay(grounding_mode)

        long_name = "A" * 51  # 51 characters — exceeds the documented 50-char limit

        # The real API accepts names longer than 50 characters
        created = resend.ApiKeys.create(
            {
                "name": long_name,
            }
        )
        assert created["id"] is not None
        assert created["token"] is not None
        assert created["token"].startswith("re_")
        resource_tracker.api_key(created["id"])

        _delay(grounding_mode)

        # Verify the key appears in the list with the long name
        list_result = resend.ApiKeys.list()
        key_ids = [k["id"] for k in list_result["data"]]
        assert created["id"] in key_ids

        found = [k for k in list_result["data"] if k["id"] == created["id"]][0]
        assert found["name"] == long_name


class TestRetrieveNonexistentDomain:
    """Retrieving a non-existent domain returns 404."""

    def test_get_domain_with_random_uuid(self, resource_tracker, grounding_mode):
        """Attempt to retrieve a domain with a random UUID that does not exist."""
        _delay(grounding_mode)

        fake_id = str(uuid.uuid4())

        with pytest.raises(ResendError) as exc_info:
            resend.Domains.get(fake_id)

        err = exc_info.value
        assert str(err.code) == "404" or int(err.code) == 404
        assert err.error_type == "not_found"


class TestRetrieveNonexistentTemplate:
    """Retrieving a non-existent template returns 404."""

    def test_get_template_with_random_uuid(self, resource_tracker, grounding_mode):
        """Attempt to retrieve a template with a random UUID that does not exist."""
        _delay(grounding_mode)

        fake_id = str(uuid.uuid4())

        with pytest.raises(ResendError) as exc_info:
            resend.Templates.get(fake_id)

        err = exc_info.value
        assert str(err.code) == "404" or int(err.code) == 404
        assert err.error_type == "not_found"


class TestRetrieveNonexistentContact:
    """Retrieving a non-existent contact returns 404."""

    def test_get_contact_with_random_uuid(self, resource_tracker, grounding_mode):
        """Attempt to retrieve a contact with a random UUID that does not exist."""
        _delay(grounding_mode)

        fake_id = str(uuid.uuid4())

        with pytest.raises(ResendError) as exc_info:
            resend.Contacts.get(id=fake_id)

        err = exc_info.value
        assert str(err.code) == "404" or int(err.code) == 404
        assert err.error_type == "not_found"
