"""
pytest fixtures for Slack contract tests.

Uses the official slack_sdk to verify the fake works correctly.
The service is started by the CLI before tests run.
"""

import os

import httpx
import pytest
from slack_sdk import WebClient

SERVICE_URL = os.environ["DOUBLEAGENT_SLACK_URL"]


@pytest.fixture
def slack_client() -> WebClient:
    """Provides official Slack WebClient configured for the fake."""
    return WebClient(
        token="fake-token",
        base_url=SERVICE_URL,
    )


@pytest.fixture(autouse=True)
def reset_fake():
    """Reset fake state before each test."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield
