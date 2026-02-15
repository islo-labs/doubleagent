"""Contract tests for Descope User Management API."""

import httpx
import uuid

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_DESCOPE_URL"]


class TestUserCRUD:
    def test_create_user(self, base_url, mgmt_headers):
        login_id = f"user-{uuid.uuid4().hex[:8]}@example.com"
        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id, "email": login_id, "name": "Test User"},
            headers=mgmt_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["user"]["email"] == login_id
        assert data["user"]["userId"].startswith("U")

    def test_load_user_by_id(self, base_url, mgmt_headers):
        login_id = f"load-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id, "email": login_id},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user"]["userId"]

        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/load",
            json={"userId": user_id},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True
        assert resp.json()["user"]["email"] == login_id

    def test_load_user_by_login_id(self, base_url, mgmt_headers):
        login_id = f"login-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id, "email": login_id},
            headers=mgmt_headers,
        )

        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/load",
            json={"loginId": login_id},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True

    def test_search_users(self, base_url, mgmt_headers):
        for i in range(3):
            httpx.post(
                f"{base_url}/v1/mgmt/user/create",
                json={"loginId": f"search-{i}-{uuid.uuid4().hex[:6]}@example.com"},
                headers=mgmt_headers,
            )
        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/search",
            json={"limit": 100},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True
        assert len(resp.json()["users"]) >= 3

    def test_update_user(self, base_url, mgmt_headers):
        login_id = f"upd-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id, "name": "Old Name"},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user"]["userId"]

        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/update",
            json={"userId": user_id, "name": "New Name"},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True
        assert resp.json()["user"]["name"] == "New Name"

    def test_delete_user(self, base_url, mgmt_headers):
        login_id = f"del-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user"]["userId"]

        httpx.post(f"{base_url}/v1/mgmt/user/delete", json={"userId": user_id}, headers=mgmt_headers)

        resp = httpx.post(f"{base_url}/v1/mgmt/user/load", json={"userId": user_id}, headers=mgmt_headers)
        assert resp.status_code == 404

    def test_duplicate_user_rejected(self, base_url, mgmt_headers):
        login_id = f"dup-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(f"{base_url}/v1/mgmt/user/create", json={"loginId": login_id}, headers=mgmt_headers)
        resp = httpx.post(f"{base_url}/v1/mgmt/user/create", json={"loginId": login_id}, headers=mgmt_headers)
        assert resp.status_code == 409

    def test_unauthorized_without_bearer(self, base_url):
        resp = httpx.post(f"{base_url}/v1/mgmt/user/search", json={})
        assert resp.status_code == 401
