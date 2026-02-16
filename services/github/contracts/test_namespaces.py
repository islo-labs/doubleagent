"""
Contract tests for per-agent namespace isolation.

Verifies that agents using different X-DoubleAgent-Namespace headers
see isolated state while sharing the same baseline snapshot.
"""

import os

import httpx
import pytest

SERVICE_URL = os.environ["DOUBLEAGENT_GITHUB_URL"]

HEADERS_AGENT_A = {"X-DoubleAgent-Namespace": "agent-a"}
HEADERS_AGENT_B = {"X-DoubleAgent-Namespace": "agent-b"}


@pytest.fixture(autouse=True)
def reset_hard():
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})
    yield


def _bootstrap(data: dict) -> dict:
    resp = httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=data)
    assert resp.status_code == 200
    return resp.json()


def _make_repo(name: str = "shared-repo") -> dict:
    return {
        "id": 200,
        "name": name,
        "full_name": f"doubleagent/{name}",
        "owner": {"login": "doubleagent", "id": 1, "type": "User"},
        "private": False,
        "description": "Shared baseline",
        "default_branch": "main",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


class TestNamespaceIsolation:
    """Verify state isolation between namespaces."""

    def test_both_see_baseline(self):
        """Both agents see the same snapshot baseline."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        # Agent A sees baseline
        resp_a = httpx.get(
            f"{SERVICE_URL}/repos/doubleagent/shared-repo",
            headers=HEADERS_AGENT_A,
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["name"] == "shared-repo"

        # Agent B sees same baseline
        resp_b = httpx.get(
            f"{SERVICE_URL}/repos/doubleagent/shared-repo",
            headers=HEADERS_AGENT_B,
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["name"] == "shared-repo"

    def test_mutation_isolated_between_agents(self):
        """A mutation by Agent A is not visible to Agent B."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        # Agent A creates a repo
        resp_a = httpx.post(
            f"{SERVICE_URL}/user/repos",
            json={"name": "agent-a-only"},
            headers=HEADERS_AGENT_A,
        )
        assert resp_a.status_code == 201

        # Agent A can see it
        repos_a = httpx.get(f"{SERVICE_URL}/user/repos", headers=HEADERS_AGENT_A)
        names_a = {r["name"] for r in repos_a.json()}
        assert "agent-a-only" in names_a

        # Agent B cannot
        repos_b = httpx.get(f"{SERVICE_URL}/user/repos", headers=HEADERS_AGENT_B)
        names_b = {r["name"] for r in repos_b.json()}
        assert "agent-a-only" not in names_b
        # But Agent B still sees baseline
        assert "shared-repo" in names_b

    def test_delete_in_one_namespace_not_visible_in_other(self):
        """Agent A deleting a baseline resource doesn't affect Agent B."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        # Agent A deletes the baseline repo
        resp_del = httpx.delete(
            f"{SERVICE_URL}/repos/doubleagent/shared-repo",
            headers=HEADERS_AGENT_A,
        )
        assert resp_del.status_code == 204

        # Agent A can't see it
        resp_a = httpx.get(
            f"{SERVICE_URL}/repos/doubleagent/shared-repo",
            headers=HEADERS_AGENT_A,
        )
        assert resp_a.status_code == 404

        # Agent B still sees it
        resp_b = httpx.get(
            f"{SERVICE_URL}/repos/doubleagent/shared-repo",
            headers=HEADERS_AGENT_B,
        )
        assert resp_b.status_code == 200

    def test_reset_one_namespace_preserves_other(self):
        """Resetting Agent A doesn't affect Agent B's overlay."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        # Both agents create repos
        httpx.post(
            f"{SERVICE_URL}/user/repos",
            json={"name": "a-extra"},
            headers=HEADERS_AGENT_A,
        )
        httpx.post(
            f"{SERVICE_URL}/user/repos",
            json={"name": "b-extra"},
            headers=HEADERS_AGENT_B,
        )

        # Reset Agent A
        httpx.post(
            f"{SERVICE_URL}/_doubleagent/reset",
            headers=HEADERS_AGENT_A,
        )

        # Agent A overlay cleared, only baseline
        repos_a = httpx.get(f"{SERVICE_URL}/user/repos", headers=HEADERS_AGENT_A)
        names_a = {r["name"] for r in repos_a.json()}
        assert "a-extra" not in names_a
        assert "shared-repo" in names_a

        # Agent B overlay intact
        repos_b = httpx.get(f"{SERVICE_URL}/user/repos", headers=HEADERS_AGENT_B)
        names_b = {r["name"] for r in repos_b.json()}
        assert "b-extra" in names_b
        assert "shared-repo" in names_b


class TestNamespaceIntrospection:
    """Verify the /_doubleagent/namespaces endpoint."""

    def test_list_namespaces_after_requests(self):
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        # Trigger creation of two namespaces
        httpx.get(f"{SERVICE_URL}/user/repos", headers=HEADERS_AGENT_A)
        httpx.get(f"{SERVICE_URL}/user/repos", headers=HEADERS_AGENT_B)

        resp = httpx.get(f"{SERVICE_URL}/_doubleagent/namespaces")
        assert resp.status_code == 200
        ns_names = {ns["namespace"] for ns in resp.json()}
        assert "agent-a" in ns_names
        assert "agent-b" in ns_names
