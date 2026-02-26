import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snapshot_pull.redactor import PiiRedactor


class RedactorTests(unittest.TestCase):
    def test_emails_are_anonymized_deterministically(self) -> None:
        redactor = PiiRedactor()
        result1 = redactor.redact_scalar("alice@company.com")
        result2 = redactor.redact_scalar("alice@company.com")
        self.assertEqual(result1, result2)
        self.assertIn("@doubleagent.local", result1)
        self.assertNotIn("alice", result1)

    def test_different_emails_get_different_aliases(self) -> None:
        redactor = PiiRedactor()
        r1 = redactor.redact_scalar("alice@company.com")
        r2 = redactor.redact_scalar("bob@company.com")
        self.assertNotEqual(r1, r2)
        self.assertIn("user-1@doubleagent.local", r1)
        self.assertIn("user-2@doubleagent.local", r2)

    def test_secret_like_strings_are_redacted(self) -> None:
        redactor = PiiRedactor()
        for value in ["my-secret-key", "Bearer token-xyz", "password123", "api_key_abc"]:
            result = redactor.redact_scalar(value)
            self.assertTrue(result.startswith("redacted-"), f"Expected redaction for: {value}")

    def test_normal_strings_pass_through(self) -> None:
        redactor = PiiRedactor()
        for value in ["Hello world", "project-name", "42", "2026-02-23"]:
            self.assertEqual(redactor.redact_scalar(value), value)

    def test_non_strings_pass_through(self) -> None:
        redactor = PiiRedactor()
        self.assertEqual(redactor.redact_scalar(42), 42)
        self.assertEqual(redactor.redact_scalar(True), True)
        self.assertIsNone(redactor.redact_scalar(None))

    def test_nested_objects_are_recursively_redacted(self) -> None:
        redactor = PiiRedactor()
        data = {
            "user": {
                "email": "alice@company.com",
                "name": "Alice",
                "tokens": ["secret-abc"],
            },
            "count": 5,
        }
        result = redactor.redact_obj(data)
        self.assertIn("@doubleagent.local", result["user"]["email"])
        self.assertEqual(result["user"]["name"], "Alice")
        self.assertTrue(result["user"]["tokens"][0].startswith("redacted-"))
        self.assertEqual(result["count"], 5)


if __name__ == "__main__":
    unittest.main()
