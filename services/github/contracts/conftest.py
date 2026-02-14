"""
pytest fixtures for GitHub contract tests.

Uses the official PyGithub SDK to interact with both real GitHub
and DoubleAgent fake.
"""

import os
import sys
import pytest

# Add parent directories to path for imports
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "contracts")))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "sdk", "python")))

from github import Github
from doubleagent_contracts import Target
from doubleagent import DoubleAgent


@pytest.fixture(scope="session")
def doubleagent():
    """Start DoubleAgent for fake tests."""
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
def target(github_service) -> Target:
    """
    Provides Target based on DOUBLEAGENT_TARGET env var.
    
    - DOUBLEAGENT_TARGET=fake (default): Uses DoubleAgent fake
    - DOUBLEAGENT_TARGET=real: Uses real GitHub API (requires GITHUB_TOKEN)
    """
    return Target.from_env(
        service_name="github",
        fake_url=github_service.url,
        real_url="https://api.github.com",
        auth_env_var="GITHUB_TOKEN",
    )


@pytest.fixture
def github_client(target: Target) -> Github:
    """
    Provides official PyGithub client configured for the target.
    
    - For fake: Points to DoubleAgent service
    - For real: Points to api.github.com with GITHUB_TOKEN
    """
    if target.is_real:
        return Github(target.auth_token)
    else:
        return Github(
            base_url=target.base_url,
            login_or_token=target.auth_token,
        )


@pytest.fixture(autouse=True)
def reset_fake(target, github_service):
    """Reset fake state before each test."""
    if target.is_fake:
        import httpx
        httpx.post(f"{github_service.url}/_doubleagent/reset")
    yield
