"""
Contract tests for PostHog feature flags.

Uses the official posthog Python SDK to verify the fake works correctly.
"""

import httpx
import os
from posthog import Posthog

SERVICE_URL = os.environ["DOUBLEAGENT_POSTHOG_URL"]


def _seed_flags(flags: list[dict]):
    """Helper to seed feature flags into the fake."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/seed", json={"feature_flags": flags})


def test_flag_enabled(posthog_client: Posthog):
    """Test that a seeded enabled flag returns True."""
    _seed_flags([{"key": "beta-feature", "enabled": True}])

    result = posthog_client.feature_enabled("beta-feature", "user-1")
    assert result is True


def test_flag_disabled(posthog_client: Posthog):
    """Test that a seeded disabled flag returns False."""
    _seed_flags([{"key": "beta-feature", "enabled": False}])

    result = posthog_client.feature_enabled("beta-feature", "user-1")
    assert result is False


def test_missing_flag(posthog_client: Posthog):
    """Test that a flag that was never seeded returns None."""
    result = posthog_client.get_feature_flag("nonexistent-flag", "user-1")
    assert result is None


def test_get_feature_flag_boolean(posthog_client: Posthog):
    """Test get_feature_flag() for a boolean flag."""
    _seed_flags([{"key": "simple-flag", "enabled": True}])

    result = posthog_client.get_feature_flag("simple-flag", "user-1")
    assert result is True


def test_get_feature_flag_multivariate(posthog_client: Posthog):
    """Test get_feature_flag() for a multivariate (variant) flag."""
    _seed_flags([{"key": "experiment", "enabled": True, "variant": "control"}])

    result = posthog_client.get_feature_flag("experiment", "user-1")
    assert result == "control"


def test_get_feature_flag_payload(posthog_client: Posthog):
    """Test get_feature_flag_payload() returns the seeded payload."""
    _seed_flags([
        {"key": "styled-feature", "enabled": True, "payload": '{"color": "blue"}'}
    ])

    payload = posthog_client.get_feature_flag_payload("styled-feature", "user-1")
    # The SDK auto-parses JSON string payloads into dicts
    assert payload == {"color": "blue"}


def test_get_all_flags(posthog_client: Posthog):
    """Test get_all_flags() returns all seeded flags."""
    _seed_flags([
        {"key": "flag-a", "enabled": True},
        {"key": "flag-b", "enabled": False},
        {"key": "flag-c", "enabled": True, "variant": "test"},
    ])

    flags = posthog_client.get_all_flags("user-1")
    assert flags["flag-a"] is True
    assert flags["flag-b"] is False
    assert flags["flag-c"] == "test"


def test_feature_enabled_with_groups(posthog_client: Posthog):
    """Test feature_enabled() with group context (matches islo usage)."""
    _seed_flags([{"key": "tenant-feature", "enabled": True}])

    result = posthog_client.feature_enabled(
        "tenant-feature",
        "user-1",
        groups={"tenant": "tenant-123"},
    )
    assert result is True


def test_load_feature_flags_local_evaluation(posthog_local_eval_client: Posthog):
    """Test load_feature_flags() fetches flag definitions from /api/feature_flag/local_evaluation/."""
    _seed_flags([
        {"key": "local-bool", "enabled": True},
        {"key": "local-variant", "enabled": True, "variant": "control"},
    ])

    posthog_local_eval_client.load_feature_flags()

    # Evaluate locally — should NOT hit /flags/, only use loaded definitions
    result_bool = posthog_local_eval_client.get_feature_flag(
        "local-bool", "user-1", only_evaluate_locally=True
    )
    result_variant = posthog_local_eval_client.get_feature_flag(
        "local-variant", "user-1", only_evaluate_locally=True
    )

    assert result_bool is True
    assert result_variant == "control"


def test_local_evaluation_payload(posthog_local_eval_client: Posthog):
    """Test that locally evaluated flags return payloads correctly."""
    _seed_flags([
        {"key": "payload-flag", "enabled": True, "payload": '{"theme": "dark"}'}
    ])

    posthog_local_eval_client.load_feature_flags()

    payload = posthog_local_eval_client.get_feature_flag_payload(
        "payload-flag", "user-1", only_evaluate_locally=True
    )
    assert payload == {"theme": "dark"}
