"""pytest fixtures for Descope contract tests."""

import os
import httpx
import pytest

SERVICE_URL = os.environ["DOUBLEAGENT_DESCOPE_URL"]

MGMT_KEY = "fake-management-key"


@pytest.fixture
def base_url() -> str:
    return SERVICE_URL


@pytest.fixture
def mgmt_headers() -> dict:
    return {"Authorization": f"Bearer {MGMT_KEY}", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def reset_fake(base_url):
    httpx.post(f"{base_url}/_doubleagent/reset")
    yield
