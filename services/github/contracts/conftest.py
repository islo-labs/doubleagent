"""
pytest fixtures for GitHub contract tests.

Uses the official PyGithub SDK to verify the fake works correctly.
"""

import os
import sys
import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "sdk", "python")))

from github import Github
from doubleagent import DoubleAgent


@pytest.fixture(scope="session")
def doubleagent():
    """Start DoubleAgent framework."""
    da = DoubleAgent()
    yield da
    da.stop_all()


@pytest.fixture(scope="session")
def github_service(doubleagent):
    """Start GitHub fake service."""
    import asyncio
    loop = asyncio.new_event_loop()
    service = loop.run_until_complete(doubleagent.start("github", port=18080))
    yield service
    loop.close()


@pytest.fixture
def github_client(github_service) -> Github:
    """Provides official PyGithub client configured for the fake."""
    return Github(
        base_url=github_service.url,
        login_or_token="fake-token",
    )


@pytest.fixture(autouse=True)
def reset_fake(github_service):
    """Reset fake state before each test."""
    import httpx
    httpx.post(f"{github_service.url}/_doubleagent/reset")
    yield
