"""
Contract tests for snapshot bootstrap, COW state overlay, and reset semantics.

These tests exercise the /_doubleagent/bootstrap, /_doubleagent/reset,
and /_doubleagent/seed endpoints to verify copy-on-write behavior.
"""

import os
import uuid

import httpx
import pytest
from github import Github

SERVICE_URL = os.environ["DOUBLEAGENT_GITHUB_URL"]


@pytest.fixture
def github_client() -> Github:
    return Github(base_url=SERVICE_URL, login_or_token="fake-token")


@pytest.fixture(autouse=True)
def reset_hard():
    """Hard-reset before each test so no baseline bleeds between tests."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})
    yield


# -- helpers ------------------------------------------------------------------

def _bootstrap(data: dict) -> dict:
    """POST to /_doubleagent/bootstrap and return response JSON."""
    resp = httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=data)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _reset(hard: bool = False) -> dict:
    params = {"hard": "true"} if hard else {}
    resp = httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _seed(data: dict) -> dict:
    resp = httpx.post(f"{SERVICE_URL}/_doubleagent/seed", json=data)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_repo(owner: str = "doubleagent", name: str = "snap-repo") -> dict:
    return {
        "id": 100,
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner, "id": 1, "type": "User"},
        "private": False,
        "description": "Snapshot repo",
        "default_branch": "main",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }


# -- tests --------------------------------------------------------------------


class TestBootstrap:
    """Verify /_doubleagent/bootstrap loads a baseline."""

    def test_bootstrap_loads_repos(self, github_client: Github):
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        fetched = github_client.get_repo("doubleagent/snap-repo")
        assert fetched.name == "snap-repo"
        assert fetched.description == "Snapshot repo"

    def test_bootstrap_returns_counts(self):
        repo = _make_repo()
        result = _bootstrap({"repos": {repo["full_name"]: repo}})
        assert result["loaded"]["repos"] == 1


class TestCopyOnWrite:
    """Verify that mutations go to the overlay, baseline is preserved."""

    def test_create_in_overlay_visible(self, github_client: Github):
        """Creating a resource on top of a baseline is visible."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        user = github_client.get_user()
        new = user.create_repo(name="overlay-repo")
        assert new.name == "overlay-repo"

        # Both baseline and overlay repos visible
        repos = list(user.get_repos())
        names = {r.name for r in repos}
        assert "snap-repo" in names
        assert "overlay-repo" in names

    def test_update_baseline_resource(self, github_client: Github):
        """Updating a baseline resource writes to overlay, baseline untouched."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        fetched = github_client.get_repo("doubleagent/snap-repo")
        fetched.edit(description="Modified via overlay")

        updated = github_client.get_repo("doubleagent/snap-repo")
        assert updated.description == "Modified via overlay"

    def test_delete_baseline_resource(self, github_client: Github):
        """Deleting a baseline resource creates a tombstone."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        fetched = github_client.get_repo("doubleagent/snap-repo")
        fetched.delete()

        with pytest.raises(Exception):
            github_client.get_repo("doubleagent/snap-repo")


class TestResetSemantics:
    """Verify reset returns to baseline, hard reset returns to empty."""

    def test_reset_restores_baseline(self, github_client: Github):
        """After mutations, reset returns to snapshot baseline."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        # Mutate
        user = github_client.get_user()
        user.create_repo(name="extra-repo")
        fetched = github_client.get_repo("doubleagent/snap-repo")
        fetched.edit(description="Changed")

        # Reset (soft) -> back to baseline
        _reset(hard=False)

        # Baseline repo restored with original description
        restored = github_client.get_repo("doubleagent/snap-repo")
        assert restored.description == "Snapshot repo"

        # Overlay-only repo gone
        with pytest.raises(Exception):
            github_client.get_repo("doubleagent/extra-repo")

    def test_hard_reset_clears_everything(self, github_client: Github):
        """Hard reset clears baseline + overlay -> empty state."""
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        _reset(hard=True)

        with pytest.raises(Exception):
            github_client.get_repo("doubleagent/snap-repo")

    def test_reset_without_snapshot_is_empty(self, github_client: Github):
        """Without a snapshot, reset returns to empty (backward compat)."""
        user = github_client.get_user()
        user.create_repo(name="ephemeral")

        _reset(hard=False)

        repos = list(user.get_repos())
        assert len(repos) == 0


class TestSeedOnTopOfSnapshot:
    """Verify seeding merges into overlay, baseline preserved."""

    def test_seed_adds_to_overlay(self, github_client: Github):
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        _seed({
            "repos": [
                {"owner": "doubleagent", "name": "seeded-repo", "description": "From seed"},
            ],
        })

        user = github_client.get_user()
        repos = list(user.get_repos())
        names = {r.name for r in repos}
        assert "snap-repo" in names
        assert "seeded-repo" in names

    def test_reset_after_seed_restores_baseline(self, github_client: Github):
        repo = _make_repo()
        _bootstrap({"repos": {repo["full_name"]: repo}})

        _seed({
            "repos": [
                {"owner": "doubleagent", "name": "seeded-repo"},
            ],
        })

        _reset(hard=False)

        user = github_client.get_user()
        repos = list(user.get_repos())
        names = {r.name for r in repos}
        assert "snap-repo" in names
        assert "seeded-repo" not in names
