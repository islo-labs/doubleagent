import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from snapshot_pull.smart_filter import SeedingConfig, apply_relational_filter


class SmartFilterTests(unittest.TestCase):
    def test_relational_filter_applies_limits_and_follow_rules(self) -> None:
        resources = {
            "repos": [
                {"id": 1, "name": "a"},
                {"id": 2, "name": "b"},
                {"id": 3, "name": "c"},
            ],
            "issues": [
                {"id": 10, "repo_id": 1},
                {"id": 11, "repo_id": 1},
                {"id": 12, "repo_id": 1},
                {"id": 20, "repo_id": 2},
                {"id": 30, "repo_id": 3},
            ],
            "comments": [
                {"id": 100, "issue_id": 10},
                {"id": 101, "issue_id": 11},
                {"id": 102, "issue_id": 20},
                {"id": 103, "issue_id": 999},
            ],
        }
        config = SeedingConfig.from_dict(
            {
                "default_limit": 2,
                "seed_streams": [
                    {
                        "stream": "repos",
                        "follow": [
                            {
                                "child_stream": "issues",
                                "foreign_key": "repo_id",
                                "limit_per_parent": 1,
                            }
                        ],
                    },
                    {
                        "stream": "issues",
                        "follow": [{"child_stream": "comments", "foreign_key": "issue_id"}],
                    },
                ],
            }
        )

        filtered = apply_relational_filter(resources, config)

        self.assertEqual([r["id"] for r in filtered["repos"]], [1, 2])
        # issues appears both as a root stream and as a followed stream; ids are deduped.
        self.assertEqual([r["id"] for r in filtered["issues"]], [10, 11, 20])
        # comments follow the first issues selection path due to visited edge tracking.
        self.assertEqual([r["id"] for r in filtered["comments"]], [100, 101])

    def test_relational_filter_deduplicates_same_record_from_multiple_paths(self) -> None:
        resources = {
            "users": [{"id": "u1"}],
            "memberships": [
                {"id": "m1", "user_id": "u1", "team_id": "t1"},
                {"id": "m2", "user_id": "u1", "team_id": "t2"},
            ],
            "teams": [{"id": "t1"}, {"id": "t2"}],
        }
        config = SeedingConfig.from_dict(
            {
                "seed_streams": [
                    {
                        "stream": "users",
                        "follow": [{"child_stream": "memberships", "foreign_key": "user_id"}],
                    },
                    {
                        "stream": "teams",
                        "follow": [{"child_stream": "memberships", "foreign_key": "team_id"}],
                    },
                ]
            }
        )

        filtered = apply_relational_filter(resources, config)
        self.assertEqual(len(filtered["memberships"]), 2)
        self.assertEqual(sorted(r["id"] for r in filtered["memberships"]), ["m1", "m2"])


if __name__ == "__main__":
    unittest.main()
