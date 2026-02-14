"""
pytest fixtures for Stripe contract tests.

Uses the official stripe Python SDK to interact with both real Stripe
and DoubleAgent fake.
"""

import os
import sys
import pytest

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "contracts")))
sys.path.insert(0, str(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "sdk", "python")))

import stripe
from doubleagent_contracts import Target
from doubleagent import DoubleAgent


@pytest.fixture(scope="session")
def doubleagent():
    da = DoubleAgent()
    yield da
    da.stop_all()


@pytest.fixture(scope="session")
def stripe_service(doubleagent):
    import asyncio
    loop = asyncio.new_event_loop()
    service = loop.run_until_complete(doubleagent.start("stripe", port=18082))
    yield service
    loop.close()


@pytest.fixture
def target(stripe_service) -> Target:
    return Target.from_env(
        service_name="stripe",
        fake_url=stripe_service.url,
        real_url="https://api.stripe.com",
        auth_env_var="STRIPE_API_KEY",
    )


@pytest.fixture
def stripe_client(target: Target) -> stripe.StripeClient:
    """Provides official Stripe client configured for the target."""
    return stripe.StripeClient(
        api_key=target.auth_token,
        base_addresses={"api": target.base_url},
    )


@pytest.fixture(autouse=True)
def reset_fake(target, stripe_service):
    """Reset fake state before each test."""
    if target.is_fake:
        import httpx
        httpx.post(f"{stripe_service.url}/_doubleagent/reset")
    yield
