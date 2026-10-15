"""Check the deterministic upstream fixture used by importer contracts."""

import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from import_stub import ImportStub


class ImportStubTests(unittest.TestCase):
    def get(self, stub, path, token="test-source-token"):
        request = Request(f"{stub.url}{path}", headers={"Authorization": f"Bearer {token}"})
        with urlopen(request) as response:
            return json.load(response)

    def test_pagination_and_boundaries(self):
        with ImportStub() as stub:
            first = self.get(stub, "/messages?page=1")
            second = self.get(stub, "/messages?page=2")
            self.assertEqual(first["next_page"], 2)
            self.assertIsNone(second["next_page"])
            self.assertEqual(first["items"][0]["created_at"], "2026-09-15T12:00:00Z")
            self.assertEqual(second["items"][0]["created_at"], "2026-10-15T12:00:00Z")
            self.assertEqual(stub.requests[0], ("messages", 1, "Bearer test-source-token"))

    def test_error_modes_and_missing_parent(self):
        for mode, status in (("rate_limit", 429), ("fail", 500)):
            with self.subTest(mode=mode), ImportStub(mode=mode) as stub:
                with self.assertRaises(HTTPError) as error:
                    self.get(stub, "/users?page=2")
                self.assertEqual(error.exception.code, status)
        with ImportStub(mode="missing_parent") as stub:
            users = self.get(stub, "/users?page=1")["items"]
            self.assertNotIn("U-old", [user["id"] for user in users])

    def test_invalid_credential(self):
        with ImportStub() as stub:
            with self.assertRaises(HTTPError) as error:
                self.get(stub, "/users?page=1", token="wrong")
            self.assertEqual(error.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
