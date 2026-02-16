"""
Contract tests for Slack COW state overlay: bootstrap, reset, seed interaction.
"""

import os
import httpx
import pytest
from slack_sdk import WebClient

SERVICE_URL = os.environ["DOUBLEAGENT_SLACK_URL"]


@pytest.fixture
def slack_client() -> WebClient:
    return WebClient(token="fake-token", base_url=SERVICE_URL)


class TestBootstrapAndCOW:
    """Verify baseline loading and copy-on-write semantics."""

    def setup_method(self):
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})

    def test_bootstrap_loads_baseline(self, slack_client: WebClient):
        snapshot = {
            "channels": {
                "C100": {"id": "C100", "name": "general", "is_channel": True,
                         "is_private": False, "is_archived": False, "created": 1000,
                         "creator": "U1", "topic": {"value": "", "creator": "", "last_set": 0},
                         "purpose": {"value": "", "creator": "", "last_set": 0},
                         "num_members": 5},
            },
            "users": {
                "U100": {"id": "U100", "name": "alice", "real_name": "Alice",
                         "team_id": "T1", "is_bot": False, "is_admin": False},
            },
        }
        resp = httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=snapshot)
        assert resp.status_code == 200

        # Verify data visible via SDK
        channels = slack_client.conversations_list()
        assert channels["ok"]
        names = [c["name"] for c in channels["channels"]]
        assert "general" in names

    def test_mutation_does_not_affect_baseline(self, slack_client: WebClient):
        snapshot = {
            "channels": {
                "C200": {"id": "C200", "name": "snapshot-chan", "is_channel": True,
                         "is_private": False, "is_archived": False, "created": 1000,
                         "creator": "U1", "topic": {"value": "orig", "creator": "", "last_set": 0},
                         "purpose": {"value": "", "creator": "", "last_set": 0},
                         "num_members": 1},
            },
        }
        httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=snapshot)

        # Mutate topic
        slack_client.conversations_setTopic(channel="C200", topic="changed")

        # Reset to baseline
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset")

        # Verify baseline restored
        info = slack_client.conversations_info(channel="C200")
        assert info["channel"]["topic"]["value"] == "orig"

    def test_hard_reset_clears_everything(self, slack_client: WebClient):
        snapshot = {
            "channels": {
                "C300": {"id": "C300", "name": "ephemeral", "is_channel": True,
                         "is_private": False, "is_archived": False, "created": 1000,
                         "creator": "U1", "topic": {"value": "", "creator": "", "last_set": 0},
                         "purpose": {"value": "", "creator": "", "last_set": 0},
                         "num_members": 1},
            },
        }
        httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=snapshot)

        # Hard reset
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})

        # Baseline gone
        channels = slack_client.conversations_list()
        names = [c["name"] for c in channels.get("channels", [])]
        assert "ephemeral" not in names


class TestSeedInteraction:
    """Verify seed merges into overlay on top of baseline."""

    def setup_method(self):
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})

    def test_seed_creates_channels(self, slack_client: WebClient):
        seed = {
            "channels": [
                {"name": "seed-chan-1"},
                {"name": "seed-chan-2", "is_private": True},
            ],
        }
        resp = httpx.post(f"{SERVICE_URL}/_doubleagent/seed", json=seed)
        assert resp.status_code == 200

        channels = slack_client.conversations_list()
        names = [c["name"] for c in channels["channels"]]
        assert "seed-chan-1" in names
        assert "seed-chan-2" in names

    def test_seed_on_top_of_baseline(self, slack_client: WebClient):
        snapshot = {
            "channels": {
                "C400": {"id": "C400", "name": "baseline-chan", "is_channel": True,
                         "is_private": False, "is_archived": False, "created": 1000,
                         "creator": "U1", "topic": {"value": "", "creator": "", "last_set": 0},
                         "purpose": {"value": "", "creator": "", "last_set": 0},
                         "num_members": 1},
            },
        }
        httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=snapshot)

        seed = {"channels": [{"name": "overlay-chan"}]}
        httpx.post(f"{SERVICE_URL}/_doubleagent/seed", json=seed)

        channels = slack_client.conversations_list()
        names = [c["name"] for c in channels["channels"]]
        assert "baseline-chan" in names
        assert "overlay-chan" in names
