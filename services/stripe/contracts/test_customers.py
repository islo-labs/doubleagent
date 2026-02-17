"""
Contract tests for Stripe customer endpoints.

Uses official stripe Python SDK.
"""

import pytest
import stripe


class TestCustomers:
    """Tests for customer CRUD operations."""

    def test_create_customer(self, stripe_client: stripe.StripeClient):
        customer = stripe_client.customers.create(
            params={"name": "Test User", "email": "test@example.com"}
        )
        assert customer.id.startswith("cus_")
        assert customer.object == "customer"
        assert customer.name == "Test User"
        assert customer.email == "test@example.com"

    def test_get_customer(self, stripe_client: stripe.StripeClient):
        created = stripe_client.customers.create(
            params={"name": "Get Test", "email": "get@example.com"}
        )
        fetched = stripe_client.customers.retrieve(created.id)
        assert fetched.id == created.id
        assert fetched.name == "Get Test"

    def test_update_customer(self, stripe_client: stripe.StripeClient):
        customer = stripe_client.customers.create(params={"name": "Original"})
        updated = stripe_client.customers.update(
            customer.id, params={"name": "Updated"}
        )
        assert updated.name == "Updated"
        # Verify persisted
        fetched = stripe_client.customers.retrieve(customer.id)
        assert fetched.name == "Updated"

    def test_delete_customer(self, stripe_client: stripe.StripeClient):
        customer = stripe_client.customers.create(params={"name": "To Delete"})
        deleted = stripe_client.customers.delete(customer.id)
        assert deleted.id == customer.id
        assert deleted.deleted is True

    def test_list_customers(self, stripe_client: stripe.StripeClient):
        stripe_client.customers.create(params={"name": "List Test 1"})
        stripe_client.customers.create(params={"name": "List Test 2"})
        result = stripe_client.customers.list(params={"limit": 10})
        assert result.object == "list"
        assert len(result.data) >= 2

    def test_customer_not_found(self, stripe_client: stripe.StripeClient):
        with pytest.raises(stripe.InvalidRequestError):
            stripe_client.customers.retrieve("cus_nonexistent")
