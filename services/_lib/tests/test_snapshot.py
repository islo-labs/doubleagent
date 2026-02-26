import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snapshot_pull.snapshot import save_snapshot


class SnapshotWriterTests(unittest.TestCase):
    def test_save_snapshot_writes_manifest_seed_and_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DOUBLEAGENT_SNAPSHOTS_DIR"] = tmp
            out = save_snapshot(
                service="github",
                profile="default",
                resources={
                    "repos": [{"id": 1, "name": "api"}],
                    "issues": [{"id": 10, "repo_id": 1}],
                },
                connector_name="airbyte:source-github",
                redacted=True,
                incremental=False,
            )

            self.assertEqual(out, Path(tmp) / "github" / "default")
            manifest = json.loads((out / "manifest.json").read_text())
            seed = json.loads((out / "seed.json").read_text())
            repos = json.loads((out / "repos.json").read_text())

            self.assertEqual(manifest["service"], "github")
            self.assertEqual(manifest["connector"], "airbyte:source-github")
            self.assertEqual(manifest["resource_counts"], {"repos": 1, "issues": 1})
            self.assertEqual(seed["repos"][0]["name"], "api")
            self.assertEqual(repos[0]["id"], 1)

    def test_incremental_save_merges_by_id_and_preserves_unmodified_resources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DOUBLEAGENT_SNAPSHOTS_DIR"] = tmp
            save_snapshot(
                service="github",
                profile="default",
                resources={
                    "repos": [{"id": 1, "name": "old"}, {"id": 2, "name": "unchanged"}],
                    "issues": [{"id": 10, "title": "old issue"}],
                },
                connector_name="airbyte:source-github",
                redacted=True,
            )
            out = save_snapshot(
                service="github",
                profile="default",
                resources={"repos": [{"id": 1, "name": "new"}, {"id": 3, "name": "added"}]},
                connector_name="airbyte:source-github",
                redacted=True,
                incremental=True,
            )

            repos = json.loads((out / "repos.json").read_text())
            issues = json.loads((out / "issues.json").read_text())
            seed = json.loads((out / "seed.json").read_text())
            manifest = json.loads((out / "manifest.json").read_text())

            by_id = {r["id"]: r for r in repos}
            self.assertEqual(sorted(by_id), [1, 2, 3])
            self.assertEqual(by_id[1]["name"], "new")
            self.assertEqual(by_id[2]["name"], "unchanged")
            self.assertEqual(by_id[3]["name"], "added")
            self.assertEqual(issues, [{"id": 10, "title": "old issue"}])
            self.assertEqual(len(seed["repos"]), 3)
            self.assertEqual(len(seed["issues"]), 1)
            self.assertEqual(manifest["resource_counts"], {"repos": 3, "issues": 1})


if __name__ == "__main__":
    unittest.main()
