"""
pytest fixtures for Auth0 contract tests.

Uses both raw httpx and the official auth0-python SDK.
"""

import os

import httpx
import pytest

SERVICE_URL = os.environ["DOUBLEAGENT_AUTH0_URL"]


@pytest.fixture
def base_url() -> str:
    return SERVICE_URL


@pytest.fixture
def mgmt_token(base_url: str) -> str:
    """Get a management API token via client_credentials."""
    resp = httpx.post(
        f"{base_url}/oauth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": "test-client",
            "client_secret": "test-secret",
            "audience": f"{base_url}/api/v2/",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def mgmt_headers(mgmt_token: str) -> dict:
    return {"Authorization": f"Bearer {mgmt_token}"}


@pytest.fixture(autouse=True)
def reset_fake(base_url: str):
    """Reset state before each test."""
    httpx.post(f"{base_url}/_doubleagent/reset", params={"hard": "true"})
    yield
