"""Contract tests for Descope Roles & Permissions Management API."""

import httpx
import uuid


class TestRoleCRUD:
    def test_create_role(self, base_url, mgmt_headers):
        name = f"role-{uuid.uuid4().hex[:8]}"
        resp = httpx.post(
            f"{base_url}/v1/mgmt/role/create",
            json={"name": name, "description": "Test role"},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True

    def test_load_all_roles(self, base_url, mgmt_headers):
        names = [f"r-{uuid.uuid4().hex[:6]}" for _ in range(3)]
        for n in names:
            httpx.post(f"{base_url}/v1/mgmt/role/create", json={"name": n}, headers=mgmt_headers)

        resp = httpx.post(f"{base_url}/v1/mgmt/role/loadall", json={}, headers=mgmt_headers)
        role_names = [r["name"] for r in resp.json()["roles"]]
        for n in names:
            assert n in role_names

    def test_delete_role(self, base_url, mgmt_headers):
        name = f"r-del-{uuid.uuid4().hex[:8]}"
        httpx.post(f"{base_url}/v1/mgmt/role/create", json={"name": name}, headers=mgmt_headers)
        resp = httpx.post(f"{base_url}/v1/mgmt/role/delete", json={"name": name}, headers=mgmt_headers)
        assert resp.json()["ok"] is True

        all_roles = httpx.post(f"{base_url}/v1/mgmt/role/loadall", json={}, headers=mgmt_headers)
        assert name not in [r["name"] for r in all_roles.json()["roles"]]

    def test_duplicate_role_rejected(self, base_url, mgmt_headers):
        name = f"r-dup-{uuid.uuid4().hex[:8]}"
        httpx.post(f"{base_url}/v1/mgmt/role/create", json={"name": name}, headers=mgmt_headers)
        resp = httpx.post(f"{base_url}/v1/mgmt/role/create", json={"name": name}, headers=mgmt_headers)
        assert resp.status_code == 409


class TestUserRoleAssignment:
    def test_add_role_to_user(self, base_url, mgmt_headers):
        # Create role
        role_name = f"r-{uuid.uuid4().hex[:6]}"
        httpx.post(f"{base_url}/v1/mgmt/role/create", json={"name": role_name}, headers=mgmt_headers)

        # Create user
        login_id = f"ur-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user"]["userId"]

        # Add role
        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/addrole",
            json={"userId": user_id, "roleNames": [role_name]},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True

        # Verify
        load = httpx.post(f"{base_url}/v1/mgmt/user/load", json={"userId": user_id}, headers=mgmt_headers)
        assert role_name in load.json()["user"]["roleNames"]


class TestPermissions:
    def test_create_and_load_permissions(self, base_url, mgmt_headers):
        name = f"perm-{uuid.uuid4().hex[:8]}"
        httpx.post(
            f"{base_url}/v1/mgmt/permission/create",
            json={"name": name, "description": "Test permission"},
            headers=mgmt_headers,
        )

        resp = httpx.post(f"{base_url}/v1/mgmt/permission/loadall", json={}, headers=mgmt_headers)
        perm_names = [p["name"] for p in resp.json()["permissions"]]
        assert name in perm_names
