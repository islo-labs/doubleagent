"""Unit tests for StateOverlay copy-on-write semantics."""

import pytest
from doubleagent_sdk.state_overlay import StateOverlay


@pytest.fixture
def empty_state():
    return StateOverlay()


@pytest.fixture
def baseline_state():
    return StateOverlay(baseline={
        "repos": {
            "1": {"id": 1, "name": "repo-alpha"},
            "2": {"id": 2, "name": "repo-beta"},
        },
        "issues": {
            "1": {"id": 1, "title": "Bug report"},
        },
    })


class TestEmptyState:
    def test_get_returns_none(self, empty_state):
        assert empty_state.get("repos", "1") is None

    def test_put_then_get(self, empty_state):
        empty_state.put("repos", "1", {"id": 1, "name": "new"})
        assert empty_state.get("repos", "1")["name"] == "new"

    def test_list_all_empty(self, empty_state):
        assert empty_state.list_all("repos") == []

    def test_delete_nonexistent_returns_false(self, empty_state):
        assert empty_state.delete("repos", "1") is False

    def test_next_id_starts_at_1(self, empty_state):
        assert empty_state.next_id("repos") == 1
        assert empty_state.next_id("repos") == 2


class TestBaselineReads:
    def test_get_baseline(self, baseline_state):
        obj = baseline_state.get("repos", "1")
        assert obj["name"] == "repo-alpha"

    def test_list_all_baseline(self, baseline_state):
        repos = baseline_state.list_all("repos")
        assert len(repos) == 2

    def test_get_returns_deepcopy(self, baseline_state):
        """Mutating the returned dict must not corrupt baseline."""
        obj = baseline_state.get("repos", "1")
        obj["name"] = "CORRUPTED"
        # Re-read from baseline should be untouched
        obj2 = baseline_state.get("repos", "1")
        assert obj2["name"] == "repo-alpha"


class TestOverlayWrites:
    def test_put_creates_in_overlay(self, baseline_state):
        baseline_state.put("repos", "3", {"id": 3, "name": "new-repo"})
        assert baseline_state.get("repos", "3")["name"] == "new-repo"
        # Baseline repos still there
        assert baseline_state.get("repos", "1") is not None

    def test_put_overwrites_baseline(self, baseline_state):
        baseline_state.put("repos", "1", {"id": 1, "name": "overridden"})
        assert baseline_state.get("repos", "1")["name"] == "overridden"

    def test_delete_baseline_tombstones(self, baseline_state):
        assert baseline_state.delete("repos", "1") is True
        assert baseline_state.get("repos", "1") is None
        # "2" still visible
        assert baseline_state.get("repos", "2") is not None

    def test_delete_overlay(self, baseline_state):
        baseline_state.put("repos", "3", {"id": 3, "name": "temp"})
        assert baseline_state.delete("repos", "3") is True
        assert baseline_state.get("repos", "3") is None

    def test_list_all_merged(self, baseline_state):
        baseline_state.put("repos", "3", {"id": 3, "name": "new"})
        repos = baseline_state.list_all("repos")
        assert len(repos) == 3

    def test_list_all_with_tombstone(self, baseline_state):
        baseline_state.delete("repos", "1")
        repos = baseline_state.list_all("repos")
        assert len(repos) == 1
        assert repos[0]["name"] == "repo-beta"

    def test_list_all_with_filter(self, baseline_state):
        repos = baseline_state.list_all("repos", lambda r: r["name"] == "repo-alpha")
        assert len(repos) == 1


class TestResetSemantics:
    def test_reset_clears_overlay(self, baseline_state):
        baseline_state.put("repos", "3", {"id": 3, "name": "temp"})
        baseline_state.delete("repos", "1")
        baseline_state.reset()

        # Overlay-created repo gone
        assert baseline_state.get("repos", "3") is None
        # Tombstoned baseline repo restored
        assert baseline_state.get("repos", "1")["name"] == "repo-alpha"
        assert len(baseline_state.list_all("repos")) == 2

    def test_hard_reset_clears_everything(self, baseline_state):
        baseline_state.put("repos", "3", {"id": 3, "name": "temp"})
        baseline_state.reset_hard()

        assert baseline_state.get("repos", "1") is None
        assert baseline_state.get("repos", "3") is None
        assert len(baseline_state.list_all("repos")) == 0

    def test_reset_clears_counters(self, baseline_state):
        """After reset, counters re-init from baseline max."""
        baseline_state.next_id("repos")
        baseline_state.reset()
        # Should reinitialize from baseline (max id=2) -> next is 3
        assert baseline_state.next_id("repos") == 3


class TestNextId:
    def test_next_id_starts_after_baseline(self, baseline_state):
        """next_id should start after max existing id."""
        nid = baseline_state.next_id("repos")
        assert nid == 3  # baseline has ids 1, 2


class TestSeed:
    def test_seed_merges_into_overlay(self, baseline_state):
        counts = baseline_state.seed({
            "repos": {"3": {"id": 3, "name": "seeded"}},
        })
        assert counts["repos"] == 1
        assert baseline_state.get("repos", "3")["name"] == "seeded"
        # Baseline untouched
        assert baseline_state.get("repos", "1")["name"] == "repo-alpha"


class TestStats:
    def test_stats(self, baseline_state):
        baseline_state.put("repos", "3", {"id": 3, "name": "new"})
        stats = baseline_state.stats()
        assert stats["has_baseline"] is True
        assert stats["baseline_types"]["repos"] == 2
        assert stats["overlay_types"]["repos"] == 1
