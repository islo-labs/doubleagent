"""
Contract tests for Slack namespace isolation.
"""

import os
import httpx
import pytest
from slack_sdk import WebClient

SERVICE_URL = os.environ["DOUBLEAGENT_SLACK_URL"]


@pytest.fixture
def ns_client_a() -> WebClient:
    """Client for namespace 'agent-a'."""
    return WebClient(
        token="fake-token",
        base_url=SERVICE_URL,
        headers={"X-DoubleAgent-Namespace": "agent-a"},
    )


@pytest.fixture
def ns_client_b() -> WebClient:
    """Client for namespace 'agent-b'."""
    return WebClient(
        token="fake-token",
        base_url=SERVICE_URL,
        headers={"X-DoubleAgent-Namespace": "agent-b"},
    )


class TestNamespaceIsolation:
    def setup_method(self):
        httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})

    def test_channels_isolated_between_namespaces(self, ns_client_a, ns_client_b):
        ns_client_a.conversations_create(name="ns-a-chan")
        ns_client_b.conversations_create(name="ns-b-chan")

        a_channels = ns_client_a.conversations_list()
        b_channels = ns_client_b.conversations_list()

        a_names = [c["name"] for c in a_channels["channels"]]
        b_names = [c["name"] for c in b_channels["channels"]]

        assert "ns-a-chan" in a_names
        assert "ns-b-chan" not in a_names
        assert "ns-b-chan" in b_names
        assert "ns-a-chan" not in b_names

    def test_shared_baseline_visible_to_all(self, ns_client_a, ns_client_b):
        snapshot = {
            "channels": {
                "C999": {"id": "C999", "name": "shared", "is_channel": True,
                         "is_private": False, "is_archived": False, "created": 1000,
                         "creator": "U1", "topic": {"value": "", "creator": "", "last_set": 0},
                         "purpose": {"value": "", "creator": "", "last_set": 0},
                         "num_members": 1},
            },
        }
        httpx.post(f"{SERVICE_URL}/_doubleagent/bootstrap", json=snapshot)

        a_names = [c["name"] for c in ns_client_a.conversations_list()["channels"]]
        b_names = [c["name"] for c in ns_client_b.conversations_list()["channels"]]

        assert "shared" in a_names
        assert "shared" in b_names

    def test_namespaces_endpoint(self, ns_client_a, ns_client_b):
        ns_client_a.conversations_create(name="trigger-a")
        ns_client_b.conversations_create(name="trigger-b")

        resp = httpx.get(f"{SERVICE_URL}/_doubleagent/namespaces")
        ns_list = resp.json()
        ns_names = [ns["namespace"] for ns in ns_list]

        assert "agent-a" in ns_names
        assert "agent-b" in ns_names
