"""
pytest fixtures for PostHog contract tests.

Uses the official posthog Python SDK to verify the fake works correctly.
The service is started by the CLI before tests run.
"""

import os

import httpx
import pytest
from posthog import Posthog

SERVICE_URL = os.environ["DOUBLEAGENT_POSTHOG_URL"]


@pytest.fixture
def posthog_client() -> Posthog:
    """Provides official PostHog client configured for the fake."""
    client = Posthog(
        project_api_key="phc_fake_test_key",
        host=SERVICE_URL,
        sync_mode=True,
        disable_geoip=True,
    )
    yield client
    client.shutdown()


@pytest.fixture
def posthog_local_eval_client() -> Posthog:
    """Provides PostHog client configured for local flag evaluation."""
    client = Posthog(
        project_api_key="phc_fake_test_key",
        personal_api_key="phx_fake_personal_key",
        host=SERVICE_URL,
        sync_mode=True,
        disable_geoip=True,
    )
    yield client
    client.shutdown()


@pytest.fixture(autouse=True)
def reset_fake():
    """Reset fake state before each test."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield
