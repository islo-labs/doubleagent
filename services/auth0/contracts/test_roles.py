"""
Contract tests for Auth0 Roles Management API + User-Role assignments.
"""

import httpx
import uuid


class TestRoleCRUD:
    def test_create_role(self, base_url, mgmt_headers):
        resp = httpx.post(
            f"{base_url}/api/v2/roles",
            json={"name": f"admin-{uuid.uuid4().hex[:8]}", "description": "Admin role"},
            headers=mgmt_headers,
        )
        assert resp.status_code == 200
        role = resp.json()
        assert role["name"].startswith("admin-")
        assert role["id"].startswith("rol_")

    def test_list_roles(self, base_url, mgmt_headers):
        for i in range(3):
            httpx.post(
                f"{base_url}/api/v2/roles",
                json={"name": f"role-{i}-{uuid.uuid4().hex[:6]}"},
                headers=mgmt_headers,
            )
        resp = httpx.get(f"{base_url}/api/v2/roles", headers=mgmt_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 3

    def test_get_role(self, base_url, mgmt_headers):
        create_resp = httpx.post(
            f"{base_url}/api/v2/roles",
            json={"name": f"get-{uuid.uuid4().hex[:8]}"},
            headers=mgmt_headers,
        )
        role_id = create_resp.json()["id"]

        resp = httpx.get(f"{base_url}/api/v2/roles/{role_id}", headers=mgmt_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == role_id

    def test_delete_role(self, base_url, mgmt_headers):
        create_resp = httpx.post(
            f"{base_url}/api/v2/roles",
            json={"name": f"del-{uuid.uuid4().hex[:8]}"},
            headers=mgmt_headers,
        )
        role_id = create_resp.json()["id"]

        del_resp = httpx.delete(f"{base_url}/api/v2/roles/{role_id}", headers=mgmt_headers)
        assert del_resp.status_code == 200

        get_resp = httpx.get(f"{base_url}/api/v2/roles/{role_id}", headers=mgmt_headers)
        assert get_resp.status_code == 404


class TestUserRoleAssignment:
    def test_assign_and_list_roles(self, base_url, mgmt_headers):
        # Create user
        email = f"assign-{uuid.uuid4().hex[:8]}@example.com"
        user_resp = httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication"},
            headers=mgmt_headers,
        )
        user_id = user_resp.json()["user_id"]

        # Create role
        role_resp = httpx.post(
            f"{base_url}/api/v2/roles",
            json={"name": f"assign-{uuid.uuid4().hex[:8]}"},
            headers=mgmt_headers,
        )
        role_id = role_resp.json()["id"]

        # Assign role
        assign_resp = httpx.post(
            f"{base_url}/api/v2/users/{user_id}/roles",
            json={"roles": [role_id]},
            headers=mgmt_headers,
        )
        assert assign_resp.status_code == 204

        # List roles
        roles_resp = httpx.get(f"{base_url}/api/v2/users/{user_id}/roles", headers=mgmt_headers)
        assert roles_resp.status_code == 200
        role_ids = [r["id"] for r in roles_resp.json()]
        assert role_id in role_ids
