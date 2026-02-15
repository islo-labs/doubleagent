"""Tests for smart_filter.py — relational following and sampling."""

from doubleagent_sdk.smart_filter import (
    FollowRule,
    SeedStreamConfig,
    SeedingConfig,
    apply_relational_filter,
)


def test_basic_follow():
    """3 projects → follow issues by project_id → only related issues survive."""
    all_records = {
        "projects": [
            {"id": "P1", "name": "Alpha"},
            {"id": "P2", "name": "Beta"},
            {"id": "P3", "name": "Gamma"},
            {"id": "P4", "name": "Delta"},  # should be excluded (limit=3)
        ],
        "issues": [
            {"id": "I1", "project_id": "P1", "title": "Bug"},
            {"id": "I2", "project_id": "P2", "title": "Feature"},
            {"id": "I3", "project_id": "P4", "title": "Task"},  # excluded (P4 not in roots)
            {"id": "I4", "project_id": "P3", "title": "Epic"},
        ],
    }
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", limit=3, follow=[
            FollowRule(child_stream="issues", foreign_key="project_id"),
        ]),
    ])
    result = apply_relational_filter(all_records, config)

    assert len(result["projects"]) == 3
    assert {r["id"] for r in result["projects"]} == {"P1", "P2", "P3"}

    assert len(result["issues"]) == 3  # I1, I2, I4 (not I3)
    assert {r["id"] for r in result["issues"]} == {"I1", "I2", "I4"}


def test_nested_follow():
    """projects → issues → comments (two-level follow)."""
    all_records = {
        "projects": [
            {"id": "P1", "name": "Alpha"},
        ],
        "issues": [
            {"id": "I1", "project_id": "P1", "title": "Bug"},
            {"id": "I2", "project_id": "P1", "title": "Feature"},
            {"id": "I3", "project_id": "P99", "title": "Orphan"},
        ],
        "comments": [
            {"id": "C1", "issue_id": "I1", "body": "Fix it"},
            {"id": "C2", "issue_id": "I2", "body": "Nice"},
            {"id": "C3", "issue_id": "I3", "body": "Orphan comment"},
        ],
    }
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", limit=1, follow=[
            FollowRule(child_stream="issues", foreign_key="project_id"),
        ]),
        SeedStreamConfig(stream="issues", follow=[
            FollowRule(child_stream="comments", foreign_key="issue_id"),
        ]),
    ])
    result = apply_relational_filter(all_records, config)

    assert len(result["projects"]) == 1
    assert len(result["issues"]) == 2  # I1, I2 (not I3)
    assert len(result["comments"]) == 2  # C1, C2 (not C3)


def test_limit_per_parent():
    """Ensure limit_per_parent caps children per parent."""
    all_records = {
        "projects": [{"id": "P1"}, {"id": "P2"}],
        "issues": [
            {"id": "I1", "project_id": "P1"},
            {"id": "I2", "project_id": "P1"},
            {"id": "I3", "project_id": "P1"},
            {"id": "I4", "project_id": "P2"},
            {"id": "I5", "project_id": "P2"},
        ],
    }
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", limit=2, follow=[
            FollowRule(child_stream="issues", foreign_key="project_id", limit_per_parent=2),
        ]),
    ])
    result = apply_relational_filter(all_records, config)

    assert len(result["projects"]) == 2
    # P1 has 3 issues but limit_per_parent=2, P2 has 2 issues
    assert len(result["issues"]) == 4  # 2 from P1 + 2 from P2


def test_streams_not_in_config_excluded():
    """Streams not mentioned in seed_streams are dropped."""
    all_records = {
        "projects": [{"id": "P1"}],
        "issues": [{"id": "I1", "project_id": "P1"}],
        "labels": [{"id": "L1", "name": "bug"}],  # not in config
    }
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", limit=10),
    ])
    result = apply_relational_filter(all_records, config)

    assert "projects" in result
    assert "labels" not in result
    assert "issues" not in result  # not reachable from projects (no follow rule)


def test_deduplication():
    """Records reachable via multiple paths are deduplicated by id."""
    all_records = {
        "projects": [{"id": "P1"}, {"id": "P2"}],
        "issues": [
            {"id": "I1", "project_id": "P1"},
            {"id": "I1", "project_id": "P1"},  # duplicate
        ],
    }
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", limit=2, follow=[
            FollowRule(child_stream="issues", foreign_key="project_id"),
        ]),
    ])
    result = apply_relational_filter(all_records, config)

    assert len(result["issues"]) == 1  # deduplicated


def test_default_limit():
    """default_limit applies when stream has no explicit limit."""
    all_records = {
        "users": [{"id": f"U{i}"} for i in range(100)],
    }
    config = SeedingConfig(
        default_limit=5,
        seed_streams=[SeedStreamConfig(stream="users")],
    )
    result = apply_relational_filter(all_records, config)

    assert len(result["users"]) == 5


def test_explicit_limit_overrides_default():
    """Stream-level limit takes precedence over default_limit."""
    all_records = {
        "users": [{"id": f"U{i}"} for i in range(100)],
    }
    config = SeedingConfig(
        default_limit=5,
        seed_streams=[SeedStreamConfig(stream="users", limit=3)],
    )
    result = apply_relational_filter(all_records, config)

    assert len(result["users"]) == 3


def test_empty_seed_streams():
    """Empty seed_streams returns nothing."""
    all_records = {
        "projects": [{"id": "P1"}],
    }
    config = SeedingConfig(seed_streams=[])
    result = apply_relational_filter(all_records, config)

    assert result == {}


def test_missing_stream_in_records():
    """Stream in config but not in records is silently skipped."""
    all_records = {
        "projects": [{"id": "P1"}],
    }
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", limit=10),
        SeedStreamConfig(stream="nonexistent", limit=5),
    ])
    result = apply_relational_filter(all_records, config)

    assert "projects" in result
    assert "nonexistent" not in result


def test_from_dict():
    """Parse SeedingConfig from a service.yaml-style dict."""
    data = {
        "default_limit": 50,
        "seed_streams": [
            {
                "stream": "projects",
                "limit": 3,
                "follow": [
                    {
                        "child_stream": "issues",
                        "foreign_key": "project_id",
                        "limit_per_parent": 10,
                    }
                ],
            },
            {"stream": "users", "limit": 20},
        ],
    }
    config = SeedingConfig.from_dict(data)

    assert config.default_limit == 50
    assert len(config.seed_streams) == 2
    assert config.seed_streams[0].stream == "projects"
    assert config.seed_streams[0].limit == 3
    assert len(config.seed_streams[0].follow) == 1
    assert config.seed_streams[0].follow[0].child_stream == "issues"
    assert config.seed_streams[0].follow[0].limit_per_parent == 10


def test_all_stream_names():
    """all_stream_names() returns roots and follow targets."""
    config = SeedingConfig(seed_streams=[
        SeedStreamConfig(stream="projects", follow=[
            FollowRule(child_stream="issues", foreign_key="project_id"),
        ]),
        SeedStreamConfig(stream="users"),
    ])
    assert config.all_stream_names() == {"projects", "issues", "users"}
