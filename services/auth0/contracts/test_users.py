"""
Contract tests for Auth0 Users Management API.
"""

import httpx
import uuid

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_AUTH0_URL"]


class TestUserCRUD:
    """Full create/read/update/delete lifecycle."""

    def test_create_user(self, base_url, mgmt_headers):
        email = f"test-{uuid.uuid4().hex[:8]}@example.com"
        resp = httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication"},
            headers=mgmt_headers,
        )
        assert resp.status_code == 201
        user = resp.json()
        assert user["email"] == email
        assert user["user_id"].startswith("auth0|")

    def test_get_user(self, base_url, mgmt_headers):
        email = f"get-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication"},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user_id"]

        resp = httpx.get(f"{base_url}/api/v2/users/{user_id}", headers=mgmt_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == email

    def test_list_users(self, base_url, mgmt_headers):
        for i in range(3):
            httpx.post(
                f"{base_url}/api/v2/users",
                json={"email": f"list-{i}-{uuid.uuid4().hex[:6]}@example.com",
                      "connection": "Username-Password-Authentication"},
                headers=mgmt_headers,
            )
        resp = httpx.get(f"{base_url}/api/v2/users", headers=mgmt_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 3

    def test_update_user(self, base_url, mgmt_headers):
        email = f"update-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication", "name": "Old Name"},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user_id"]

        resp = httpx.patch(
            f"{base_url}/api/v2/users/{user_id}",
            json={"name": "New Name"},
            headers=mgmt_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    def test_delete_user(self, base_url, mgmt_headers):
        email = f"del-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication"},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user_id"]

        del_resp = httpx.delete(f"{base_url}/api/v2/users/{user_id}", headers=mgmt_headers)
        assert del_resp.status_code == 204

        get_resp = httpx.get(f"{base_url}/api/v2/users/{user_id}", headers=mgmt_headers)
        assert get_resp.status_code == 404

    def test_duplicate_email_rejected(self, base_url, mgmt_headers):
        email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication"},
            headers=mgmt_headers,
        )
        resp = httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication"},
            headers=mgmt_headers,
        )
        assert resp.status_code == 409

    def test_get_nonexistent_user_404(self, base_url, mgmt_headers):
        resp = httpx.get(f"{base_url}/api/v2/users/auth0|nonexistent", headers=mgmt_headers)
        assert resp.status_code == 404

    def test_unauthorized_without_token(self, base_url):
        resp = httpx.get(f"{base_url}/api/v2/users")
        assert resp.status_code == 401
