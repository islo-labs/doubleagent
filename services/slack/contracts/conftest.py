"""
pytest fixtures for Slack contract tests.

Uses the official slack_sdk to verify the fake works correctly.
"""

import os
import sys
import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "sdk", "python")))

from slack_sdk import WebClient
from doubleagent import DoubleAgent


@pytest.fixture(scope="session")
def doubleagent():
    """Start DoubleAgent framework."""
    da = DoubleAgent()
    yield da
    da.stop_all()


@pytest.fixture(scope="session")
def slack_service(doubleagent):
    """Start Slack fake service."""
    import asyncio
    loop = asyncio.new_event_loop()
    service = loop.run_until_complete(doubleagent.start("slack", port=18083))
    yield service
    loop.close()


@pytest.fixture
def slack_client(slack_service) -> WebClient:
    """Provides official Slack WebClient configured for the fake."""
    return WebClient(
        token="fake-token",
        base_url=slack_service.url,
    )


@pytest.fixture(autouse=True)
def reset_fake(slack_service):
    """Reset fake state before each test."""
    import httpx
    httpx.post(f"{slack_service.url}/_doubleagent/reset")
    yield
