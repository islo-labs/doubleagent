"""Unit tests for snapshot file storage."""

import json
import os
import tempfile

import pytest
from doubleagent_sdk.snapshot import (
    SnapshotManifest,
    save_snapshot,
    save_snapshot_incremental,
    load_snapshot,
    list_snapshots,
    delete_snapshot,
)


@pytest.fixture(autouse=True)
def tmp_snapshots_dir(monkeypatch, tmp_path):
    """Redirect snapshot storage to a temp dir."""
    monkeypatch.setenv("DOUBLEAGENT_SNAPSHOTS_DIR", str(tmp_path))
    return tmp_path


class TestSaveAndLoad:
    def test_round_trip(self, tmp_snapshots_dir):
        resources = {
            "repos": [
                {"id": 1, "name": "repo-one"},
                {"id": 2, "name": "repo-two"},
            ],
            "issues": [
                {"id": 10, "title": "Bug"},
            ],
        }
        path = save_snapshot("github", "test-profile", resources, connector_name="test")
        assert path.exists()
        assert (path / "manifest.json").exists()
        assert (path / "repos.json").exists()

        manifest, baseline = load_snapshot("github", "test-profile")
        assert manifest.service == "github"
        assert manifest.profile == "test-profile"
        assert manifest.resource_counts == {"repos": 2, "issues": 1}
        assert manifest.redacted is True
        assert "1" in baseline["repos"]
        assert baseline["repos"]["1"]["name"] == "repo-one"

    def test_load_missing_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_snapshot("github", "nonexistent")


class TestListSnapshots:
    def test_list_empty(self):
        assert list_snapshots() == []

    def test_list_after_save(self):
        save_snapshot("github", "p1", {"repos": [{"id": 1}]})
        save_snapshot("slack", "p2", {"channels": [{"id": 1}]})

        all_snaps = list_snapshots()
        assert len(all_snaps) == 2

        github_snaps = list_snapshots("github")
        assert len(github_snaps) == 1
        assert github_snaps[0]["service"] == "github"


class TestDeleteSnapshot:
    def test_delete_existing(self):
        save_snapshot("github", "to-delete", {"repos": []})
        assert delete_snapshot("github", "to-delete") is True
        assert list_snapshots("github") == []

    def test_delete_nonexistent(self):
        assert delete_snapshot("github", "nope") is False


class TestIncrementalSave:
    def test_incremental_adds_new_items(self):
        # Initial save
        save_snapshot("github", "inc", {"repos": [{"id": 1, "name": "repo-1"}]})

        # Incremental: adds repo 2, skips repo 1
        save_snapshot_incremental(
            "github", "inc",
            {"repos": [{"id": 1, "name": "repo-1-dup"}, {"id": 2, "name": "repo-2"}]},
        )

        manifest, baseline = load_snapshot("github", "inc")
        assert manifest.resource_counts["repos"] == 2
        # Original item preserved (not replaced by dup)
        assert baseline["repos"]["1"]["name"] == "repo-1"
        assert baseline["repos"]["2"]["name"] == "repo-2"

    def test_incremental_creates_if_not_exists(self):
        save_snapshot_incremental(
            "github", "new-inc",
            {"repos": [{"id": 1, "name": "first"}]},
        )
        manifest, baseline = load_snapshot("github", "new-inc")
        assert manifest.resource_counts["repos"] == 1

    def test_incremental_adds_new_resource_types(self):
        save_snapshot("github", "types", {"repos": [{"id": 1}]})
        save_snapshot_incremental(
            "github", "types",
            {"issues": [{"id": 10, "title": "Bug"}]},
        )
        manifest, baseline = load_snapshot("github", "types")
        assert "repos" in manifest.resource_counts
        assert "issues" in manifest.resource_counts
        assert manifest.resource_counts["repos"] == 1
        assert manifest.resource_counts["issues"] == 1


class TestManifest:
    def test_source_hash_computed(self, tmp_snapshots_dir):
        save_snapshot("github", "hashed", {"repos": [{"id": 1}]})
        manifest, _ = load_snapshot("github", "hashed")
        assert manifest.source_hash.startswith("sha256:")
        assert len(manifest.source_hash) > 10
