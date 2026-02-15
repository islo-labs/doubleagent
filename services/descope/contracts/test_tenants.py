"""Contract tests for Descope Tenant Management API."""

import httpx
import uuid

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_DESCOPE_URL"]


class TestTenantCRUD:
    def test_create_tenant(self, base_url, mgmt_headers):
        tid = f"t-{uuid.uuid4().hex[:8]}"
        resp = httpx.post(
            f"{base_url}/v1/mgmt/tenant/create",
            json={"id": tid, "name": "Acme Corp"},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True
        assert resp.json()["id"] == tid

    def test_load_tenant(self, base_url, mgmt_headers):
        tid = f"t-{uuid.uuid4().hex[:8]}"
        httpx.post(f"{base_url}/v1/mgmt/tenant/create", json={"id": tid, "name": "Test"}, headers=mgmt_headers)

        resp = httpx.post(f"{base_url}/v1/mgmt/tenant/load", json={"id": tid}, headers=mgmt_headers)
        assert resp.json()["ok"] is True
        assert resp.json()["tenant"]["name"] == "Test"

    def test_load_all_tenants(self, base_url, mgmt_headers):
        for i in range(3):
            httpx.post(
                f"{base_url}/v1/mgmt/tenant/create",
                json={"name": f"Tenant {i}"},
                headers=mgmt_headers,
            )
        resp = httpx.post(f"{base_url}/v1/mgmt/tenant/loadall", json={}, headers=mgmt_headers)
        assert len(resp.json()["tenants"]) >= 3

    def test_update_tenant(self, base_url, mgmt_headers):
        tid = f"t-{uuid.uuid4().hex[:8]}"
        httpx.post(f"{base_url}/v1/mgmt/tenant/create", json={"id": tid, "name": "Old"}, headers=mgmt_headers)

        resp = httpx.post(f"{base_url}/v1/mgmt/tenant/update", json={"id": tid, "name": "New"}, headers=mgmt_headers)
        assert resp.json()["ok"] is True

        load = httpx.post(f"{base_url}/v1/mgmt/tenant/load", json={"id": tid}, headers=mgmt_headers)
        assert load.json()["tenant"]["name"] == "New"

    def test_delete_tenant(self, base_url, mgmt_headers):
        tid = f"t-{uuid.uuid4().hex[:8]}"
        httpx.post(f"{base_url}/v1/mgmt/tenant/create", json={"id": tid, "name": "Gone"}, headers=mgmt_headers)
        httpx.post(f"{base_url}/v1/mgmt/tenant/delete", json={"id": tid}, headers=mgmt_headers)

        resp = httpx.post(f"{base_url}/v1/mgmt/tenant/load", json={"id": tid}, headers=mgmt_headers)
        assert resp.status_code == 404


class TestUserTenantAssignment:
    def test_add_tenant_to_user(self, base_url, mgmt_headers):
        # Create tenant
        tid = f"t-{uuid.uuid4().hex[:8]}"
        httpx.post(f"{base_url}/v1/mgmt/tenant/create", json={"id": tid, "name": "T"}, headers=mgmt_headers)

        # Create user
        login_id = f"tu-{uuid.uuid4().hex[:8]}@example.com"
        create_resp = httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id},
            headers=mgmt_headers,
        )
        user_id = create_resp.json()["user"]["userId"]

        # Add tenant
        resp = httpx.post(
            f"{base_url}/v1/mgmt/user/addtenant",
            json={"userId": user_id, "tenantId": tid},
            headers=mgmt_headers,
        )
        assert resp.json()["ok"] is True

        # Verify
        load = httpx.post(f"{base_url}/v1/mgmt/user/load", json={"userId": user_id}, headers=mgmt_headers)
        assert tid in load.json()["user"]["userTenants"]
