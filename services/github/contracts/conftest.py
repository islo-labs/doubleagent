"""
pytest fixtures for GitHub contract tests.

Uses the official PyGithub SDK to verify the fake works correctly.
The service is started by the CLI before tests run.
"""

import os

import httpx
import pytest
from github import Github

SERVICE_URL = os.environ["DOUBLEAGENT_GITHUB_URL"]


@pytest.fixture
def github_client() -> Github:
    """Provides official PyGithub client configured for the fake."""
    return Github(
        base_url=SERVICE_URL,
        login_or_token="fake-token",
    )


@pytest.fixture(autouse=True)
def reset_fake():
    """Reset fake state before each test."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield
