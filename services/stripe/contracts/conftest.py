"""
pytest fixtures for Stripe contract tests.

Uses the official stripe Python SDK to verify the fake works correctly.
The service is started by the CLI before tests run.
"""

import os

import httpx
import pytest
import stripe

SERVICE_URL = os.environ["DOUBLEAGENT_STRIPE_URL"]


@pytest.fixture
def stripe_client() -> stripe.StripeClient:
    """Provides official Stripe client configured for the fake."""
    return stripe.StripeClient(
        api_key="sk_test_fake_key",
        base_addresses={"api": SERVICE_URL},
    )


@pytest.fixture(autouse=True)
def reset_fake():
    """Reset fake state before each test."""
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield
