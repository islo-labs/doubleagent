"""Contract tests for Descope COW state, bootstrap, and reset."""

import httpx
import uuid

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_DESCOPE_URL"]


class TestCOWState:
    def test_baseline_survives_soft_reset(self, base_url, mgmt_headers):
        """After bootstrap, soft reset clears overlay but keeps baseline."""
        # Bootstrap with a user
        httpx.post(
            f"{base_url}/_doubleagent/bootstrap",
            json={
                "users": {"U_baseline": {
                    "userId": "U_baseline",
                    "loginIds": ["baseline@example.com"],
                    "email": "baseline@example.com",
                    "name": "Baseline User",
                    "roleNames": [],
                    "userTenants": [],
                    "customAttributes": {},
                    "status": "enabled",
                    "createdTime": 0,
                }},
            },
        )

        # Create overlay user
        httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": f"overlay-{uuid.uuid4().hex[:6]}@example.com"},
            headers=mgmt_headers,
        )

        # Soft reset
        httpx.post(f"{base_url}/_doubleagent/reset")

        # Baseline user survives
        resp = httpx.post(f"{base_url}/v1/mgmt/user/load", json={"userId": "U_baseline"}, headers=mgmt_headers)
        assert resp.json()["ok"] is True

        # Overlay users gone
        search = httpx.post(f"{base_url}/v1/mgmt/user/search", json={}, headers=mgmt_headers)
        assert len(search.json()["users"]) == 1  # only baseline

    def test_hard_reset_clears_everything(self, base_url, mgmt_headers):
        httpx.post(
            f"{base_url}/_doubleagent/bootstrap",
            json={"users": {"U_gone": {"userId": "U_gone", "loginIds": ["gone@x.com"], "email": "gone@x.com"}}},
        )

        httpx.post(f"{base_url}/_doubleagent/reset", params={"hard": "true"})

        resp = httpx.post(f"{base_url}/v1/mgmt/user/load", json={"userId": "U_gone"}, headers=mgmt_headers)
        assert resp.status_code == 404


class TestNamespaceIsolation:
    def test_different_namespaces_isolated(self, base_url, mgmt_headers):
        ns_a = f"ns-{uuid.uuid4().hex[:6]}"
        ns_b = f"ns-{uuid.uuid4().hex[:6]}"

        # Create user in ns_a
        headers_a = {**mgmt_headers, "X-DoubleAgent-Namespace": ns_a}
        httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": "ns-a-user@example.com"},
            headers=headers_a,
        )

        # Should not be visible in ns_b
        headers_b = {**mgmt_headers, "X-DoubleAgent-Namespace": ns_b}
        search = httpx.post(f"{base_url}/v1/mgmt/user/search", json={}, headers=headers_b)
        assert len(search.json()["users"]) == 0
