"""
Contract tests for webhook delivery, retry, and logging.

These tests register webhooks, trigger events, and verify
the /_doubleagent/webhooks delivery log.
"""

import os
import time

import httpx
import pytest

SERVICE_URL = os.environ["DOUBLEAGENT_GITHUB_URL"]


@pytest.fixture(autouse=True)
def reset_hard():
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})
    yield


def _create_repo(name: str = "hook-test") -> dict:
    resp = httpx.post(
        f"{SERVICE_URL}/user/repos",
        json={"name": name},
    )
    assert resp.status_code == 201
    return resp.json()


def _register_webhook(owner: str, repo: str, url: str, events: list[str] | None = None) -> dict:
    resp = httpx.post(
        f"{SERVICE_URL}/repos/{owner}/{repo}/hooks",
        json={
            "config": {"url": url, "content_type": "json"},
            "events": events or ["*"],
        },
    )
    assert resp.status_code == 201
    return resp.json()


class TestWebhookRegistration:
    """Verify webhook CRUD."""

    def test_create_webhook(self):
        repo = _create_repo("wh-create")
        hook = _register_webhook("doubleagent", "wh-create", "http://localhost:9999/hook")
        assert hook["id"] >= 1
        assert hook["active"] is True

    def test_list_webhooks(self):
        repo = _create_repo("wh-list")
        _register_webhook("doubleagent", "wh-list", "http://localhost:9999/hook1")
        _register_webhook("doubleagent", "wh-list", "http://localhost:9999/hook2")

        resp = httpx.get(f"{SERVICE_URL}/repos/doubleagent/wh-list/hooks")
        assert resp.status_code == 200
        hooks = resp.json()
        assert len(hooks) == 2

    def test_get_webhook(self):
        repo = _create_repo("wh-get")
        hook = _register_webhook("doubleagent", "wh-get", "http://localhost:9999/hook")

        resp = httpx.get(f"{SERVICE_URL}/repos/doubleagent/wh-get/hooks/{hook['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == hook["id"]

    def test_delete_webhook(self):
        repo = _create_repo("wh-del")
        hook = _register_webhook("doubleagent", "wh-del", "http://localhost:9999/hook")

        resp = httpx.delete(f"{SERVICE_URL}/repos/doubleagent/wh-del/hooks/{hook['id']}")
        assert resp.status_code == 204

        resp = httpx.get(f"{SERVICE_URL}/repos/doubleagent/wh-del/hooks/{hook['id']}")
        assert resp.status_code == 404


class TestWebhookDeliveryLog:
    """Verify that webhook deliveries appear in the /_doubleagent/webhooks log."""

    def test_issue_created_triggers_delivery(self):
        """Creating an issue fires an issues webhook and logs it."""
        repo = _create_repo("wh-issue")
        _register_webhook(
            "doubleagent", "wh-issue",
            "http://localhost:19999/noop",  # target won't be listening
            events=["issues"],
        )

        # Create issue -> should trigger webhook
        httpx.post(
            f"{SERVICE_URL}/repos/doubleagent/wh-issue/issues",
            json={"title": "Test webhook"},
        )

        # Give background delivery task time to complete retries
        time.sleep(4)

        resp = httpx.get(f"{SERVICE_URL}/_doubleagent/webhooks")
        assert resp.status_code == 200
        deliveries = resp.json()
        assert len(deliveries) >= 1
        d = deliveries[0]
        assert d["event_type"] == "issues"
        assert d["target_url"] == "http://localhost:19999/noop"
        # Will be failed (nothing listening) or still pending during retry
        assert d["status"] in ("failed", "delivered", "pending")

    def test_delivery_log_filterable_by_event_type(self):
        """Delivery log can be filtered by event_type query param."""
        repo = _create_repo("wh-filter")
        _register_webhook(
            "doubleagent", "wh-filter",
            "http://localhost:19999/noop",
            events=["*"],
        )

        # Create issue (fires "issues") and PR (fires "pull_request")
        httpx.post(
            f"{SERVICE_URL}/repos/doubleagent/wh-filter/issues",
            json={"title": "Issue for filter test"},
        )
        httpx.post(
            f"{SERVICE_URL}/repos/doubleagent/wh-filter/pulls",
            json={"title": "PR for filter", "head": "feature", "base": "main"},
        )

        time.sleep(1.5)

        # Filter by issues only
        resp = httpx.get(
            f"{SERVICE_URL}/_doubleagent/webhooks",
            params={"event_type": "issues"},
        )
        deliveries = resp.json()
        assert all(d["event_type"] == "issues" for d in deliveries)
        assert len(deliveries) >= 1
