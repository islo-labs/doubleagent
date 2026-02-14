"""
pytest fixtures for Slack contract tests.

Uses the official slack_sdk to interact with both real Slack
and DoubleAgent fake.
"""

import os
import sys
import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "contracts")))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "sdk", "python")))

from slack_sdk import WebClient
from doubleagent_contracts import Target
from doubleagent import DoubleAgent


@pytest.fixture(scope="session")
def doubleagent():
    """Start DoubleAgent for fake tests."""
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
def target(slack_service) -> Target:
    """
    Provides Target based on DOUBLEAGENT_TARGET env var.
    
    - DOUBLEAGENT_TARGET=fake (default): Uses DoubleAgent fake
    - DOUBLEAGENT_TARGET=real: Uses real Slack API (requires SLACK_BOT_TOKEN)
    """
    return Target.from_env(
        service_name="slack",
        fake_url=slack_service.url,
        real_url="https://slack.com/api",
        auth_env_var="SLACK_BOT_TOKEN",
    )


@pytest.fixture
def slack_client(target: Target) -> WebClient:
    """
    Provides official Slack WebClient configured for the target.
    
    - For fake: Points to DoubleAgent service
    - For real: Points to slack.com with SLACK_BOT_TOKEN
    """
    if target.is_real:
        return WebClient(token=target.auth_token)
    else:
        return WebClient(
            token=target.auth_token,
            base_url=target.base_url,
        )


@pytest.fixture(autouse=True)
def reset_fake(target, slack_service):
    """Reset fake state before each test."""
    if target.is_fake:
        import httpx
        httpx.post(f"{slack_service.url}/_doubleagent/reset")
    yield
