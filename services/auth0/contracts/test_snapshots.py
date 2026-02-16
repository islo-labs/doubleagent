"""
Contract tests for Auth0 COW state, bootstrap, and reset.
"""

import httpx
import uuid

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_AUTH0_URL"]


class TestBootstrapAndCOW:
    def setup_method(self):
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})

    def test_bootstrap_loads_users(self, base_url, mgmt_headers):
        snapshot = {
            "users": {
                "auth0|snap1": {
                    "user_id": "auth0|snap1", "email": "snap@example.com",
                    "name": "Snapshot User", "email_verified": True,
                    "nickname": "snap", "given_name": "Snap", "family_name": "User",
                    "connection": "Username-Password-Authentication",
                    "blocked": False, "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "user_metadata": {}, "app_metadata": {},
                    "identities": [{"connection": "Username-Password-Authentication",
                                    "user_id": "snap1", "provider": "auth0", "isSocial": False}],
                },
            },
            "roles": {
                "rol_admin": {"id": "rol_admin", "name": "admin", "description": "Administrator"},
            },
        }
        resp = httpx.post(f"{base_url}/_doubleagent/bootstrap", json=snapshot)
        assert resp.status_code == 200

        # User visible
        user_resp = httpx.get(f"{base_url}/api/v2/users/auth0|snap1", headers=mgmt_headers)
        assert user_resp.status_code == 200
        assert user_resp.json()["email"] == "snap@example.com"

        # Role visible
        role_resp = httpx.get(f"{base_url}/api/v2/roles/rol_admin", headers=mgmt_headers)
        assert role_resp.status_code == 200
        assert role_resp.json()["name"] == "admin"

    def test_reset_restores_baseline(self, base_url, mgmt_headers):
        snapshot = {
            "users": {
                "auth0|base1": {
                    "user_id": "auth0|base1", "email": "base@example.com",
                    "name": "Baseline User", "email_verified": False,
                    "nickname": "base", "given_name": "", "family_name": "",
                    "connection": "Username-Password-Authentication",
                    "blocked": False, "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "user_metadata": {}, "app_metadata": {},
                    "identities": [],
                },
            },
        }
        httpx.post(f"{base_url}/_doubleagent/bootstrap", json=snapshot)

        # Mutate
        httpx.patch(
            f"{base_url}/api/v2/users/auth0|base1",
            json={"name": "Changed"},
            headers=mgmt_headers,
        )

        # Soft reset
        httpx.post(f"{base_url}/_doubleagent/reset")

        # Baseline restored
        user_resp = httpx.get(f"{base_url}/api/v2/users/auth0|base1", headers=mgmt_headers)
        assert user_resp.json()["name"] == "Baseline User"

    def test_hard_reset_clears_baseline(self, base_url, mgmt_headers):
        snapshot = {
            "users": {
                "auth0|gone": {
                    "user_id": "auth0|gone", "email": "gone@example.com",
                    "name": "Gone", "email_verified": False,
                    "nickname": "", "given_name": "", "family_name": "",
                    "connection": "Username-Password-Authentication",
                    "blocked": False, "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "user_metadata": {}, "app_metadata": {},
                    "identities": [],
                },
            },
        }
        httpx.post(f"{base_url}/_doubleagent/bootstrap", json=snapshot)
        httpx.post(f"{base_url}/_doubleagent/reset", params={"hard": "true"})

        user_resp = httpx.get(f"{base_url}/api/v2/users/auth0|gone", headers=mgmt_headers)
        assert user_resp.status_code == 404


class TestNamespaceIsolation:
    def setup_method(self):
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})

    def test_users_isolated_between_namespaces(self, base_url, mgmt_headers):
        headers_a = {**mgmt_headers, "X-DoubleAgent-Namespace": "ns-a"}
        headers_b = {**mgmt_headers, "X-DoubleAgent-Namespace": "ns-b"}

        # Create in ns-a
        httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": "a@example.com", "connection": "Username-Password-Authentication"},
            headers=headers_a,
        )
        # Create in ns-b
        httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": "b@example.com", "connection": "Username-Password-Authentication"},
            headers=headers_b,
        )

        users_a = httpx.get(f"{base_url}/api/v2/users", headers=headers_a).json()
        users_b = httpx.get(f"{base_url}/api/v2/users", headers=headers_b).json()

        emails_a = [u["email"] for u in users_a]
        emails_b = [u["email"] for u in users_b]

        assert "a@example.com" in emails_a
        assert "b@example.com" not in emails_a
        assert "b@example.com" in emails_b
        assert "a@example.com" not in emails_b
