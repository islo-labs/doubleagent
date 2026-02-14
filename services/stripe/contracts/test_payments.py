"""
Contract tests for Stripe payment-related endpoints.

Tests payment intents, products, prices, subscriptions, and invoices.
"""

import pytest
import stripe
from doubleagent_contracts import contract_test, Target


@contract_test
class TestPaymentIntents:
    """Tests for payment intent operations."""

    def test_create_payment_intent(self, stripe_client: stripe.StripeClient, target: Target):
        pi = stripe_client.v1.payment_intents.create(
            params={"amount": 2000, "currency": "usd"}
        )
        assert pi.id.startswith("pi_")
        assert pi.object == "payment_intent"
        assert pi.amount == 2000
        assert pi.currency == "usd"
        assert pi.status == "requires_payment_method"

    def test_get_payment_intent(self, stripe_client: stripe.StripeClient, target: Target):
        created = stripe_client.v1.payment_intents.create(
            params={"amount": 1000, "currency": "eur"}
        )
        fetched = stripe_client.v1.payment_intents.retrieve(created.id)
        assert fetched.id == created.id
        assert fetched.amount == 1000

    def test_confirm_payment_intent(self, stripe_client: stripe.StripeClient, target: Target):
        pi = stripe_client.v1.payment_intents.create(
            params={"amount": 5000, "currency": "usd"}
        )
        confirmed = stripe_client.v1.payment_intents.confirm(pi.id)
        assert confirmed.status == "succeeded"

    def test_cancel_payment_intent(self, stripe_client: stripe.StripeClient, target: Target):
        pi = stripe_client.v1.payment_intents.create(
            params={"amount": 3000, "currency": "usd"}
        )
        canceled = stripe_client.v1.payment_intents.cancel(pi.id)
        assert canceled.status == "canceled"

    def test_list_payment_intents(self, stripe_client: stripe.StripeClient, target: Target):
        stripe_client.v1.payment_intents.create(params={"amount": 100, "currency": "usd"})
        stripe_client.v1.payment_intents.create(params={"amount": 200, "currency": "usd"})
        result = stripe_client.v1.payment_intents.list(params={"limit": 10})
        assert result.object == "list"
        assert len(result.data) >= 2


@contract_test
class TestProducts:
    """Tests for product operations."""

    def test_create_product(self, stripe_client: stripe.StripeClient, target: Target):
        product = stripe_client.v1.products.create(params={"name": "Test Product"})
        assert product.id.startswith("prod_")
        assert product.object == "product"
        assert product.name == "Test Product"

    def test_get_product(self, stripe_client: stripe.StripeClient, target: Target):
        created = stripe_client.v1.products.create(params={"name": "Get Test"})
        fetched = stripe_client.v1.products.retrieve(created.id)
        assert fetched.id == created.id
        assert fetched.name == "Get Test"

    def test_update_product(self, stripe_client: stripe.StripeClient, target: Target):
        product = stripe_client.v1.products.create(params={"name": "Original"})
        updated = stripe_client.v1.products.update(
            product.id, params={"name": "Updated Name"}
        )
        assert updated.name == "Updated Name"

    def test_list_products(self, stripe_client: stripe.StripeClient, target: Target):
        stripe_client.v1.products.create(params={"name": "Prod A"})
        stripe_client.v1.products.create(params={"name": "Prod B"})
        result = stripe_client.v1.products.list(params={"limit": 10})
        assert result.object == "list"
        assert len(result.data) >= 2


@contract_test
class TestPrices:
    """Tests for price operations."""

    def test_create_price(self, stripe_client: stripe.StripeClient, target: Target):
        product = stripe_client.v1.products.create(params={"name": "Price Test Product"})
        price = stripe_client.v1.prices.create(
            params={
                "unit_amount": 1500,
                "currency": "usd",
                "product": product.id,
            }
        )
        assert price.id.startswith("price_")
        assert price.object == "price"
        assert price.unit_amount == 1500
        assert price.currency == "usd"

    def test_get_price(self, stripe_client: stripe.StripeClient, target: Target):
        product = stripe_client.v1.products.create(params={"name": "Get Price Product"})
        created = stripe_client.v1.prices.create(
            params={"unit_amount": 999, "currency": "usd", "product": product.id}
        )
        fetched = stripe_client.v1.prices.retrieve(created.id)
        assert fetched.id == created.id
        assert fetched.unit_amount == 999

    def test_list_prices(self, stripe_client: stripe.StripeClient, target: Target):
        product = stripe_client.v1.products.create(params={"name": "List Price Product"})
        stripe_client.v1.prices.create(
            params={"unit_amount": 100, "currency": "usd", "product": product.id}
        )
        stripe_client.v1.prices.create(
            params={"unit_amount": 200, "currency": "usd", "product": product.id}
        )
        result = stripe_client.v1.prices.list(params={"limit": 10})
        assert result.object == "list"
        assert len(result.data) >= 2


@contract_test
class TestSubscriptions:
    """Tests for subscription operations."""

    @pytest.fixture(autouse=True)
    def setup_customer_and_price(self, stripe_client: stripe.StripeClient):
        self.customer = stripe_client.v1.customers.create(
            params={"name": "Sub Customer", "email": "sub@example.com"}
        )
        self.product = stripe_client.v1.products.create(params={"name": "Sub Product"})
        self.price = stripe_client.v1.prices.create(
            params={
                "unit_amount": 2000,
                "currency": "usd",
                "product": self.product.id,
                "recurring": {"interval": "month"},
            }
        )

    def test_create_subscription(self, stripe_client: stripe.StripeClient, target: Target):
        sub = stripe_client.v1.subscriptions.create(
            params={
                "customer": self.customer.id,
                "items": [{"price": self.price.id}],
            }
        )
        assert sub.id.startswith("sub_")
        assert sub.object == "subscription"
        assert sub.status == "active"
        assert sub.customer == self.customer.id

    def test_get_subscription(self, stripe_client: stripe.StripeClient, target: Target):
        created = stripe_client.v1.subscriptions.create(
            params={
                "customer": self.customer.id,
                "items": [{"price": self.price.id}],
            }
        )
        fetched = stripe_client.v1.subscriptions.retrieve(created.id)
        assert fetched.id == created.id
        assert fetched.status == "active"

    def test_cancel_subscription(self, stripe_client: stripe.StripeClient, target: Target):
        sub = stripe_client.v1.subscriptions.create(
            params={
                "customer": self.customer.id,
                "items": [{"price": self.price.id}],
            }
        )
        canceled = stripe_client.v1.subscriptions.cancel(sub.id)
        assert canceled.status == "canceled"

    def test_list_subscriptions(self, stripe_client: stripe.StripeClient, target: Target):
        stripe_client.v1.subscriptions.create(
            params={
                "customer": self.customer.id,
                "items": [{"price": self.price.id}],
            }
        )
        result = stripe_client.v1.subscriptions.list(params={"limit": 10})
        assert result.object == "list"
        assert len(result.data) >= 1


@contract_test
class TestInvoices:
    """Tests for invoice operations."""

    @pytest.fixture(autouse=True)
    def setup_customer(self, stripe_client: stripe.StripeClient):
        self.customer = stripe_client.v1.customers.create(
            params={"name": "Invoice Customer"}
        )

    def test_create_invoice(self, stripe_client: stripe.StripeClient, target: Target):
        invoice = stripe_client.v1.invoices.create(
            params={"customer": self.customer.id}
        )
        assert invoice.id.startswith("in_")
        assert invoice.object == "invoice"
        assert invoice.status == "draft"

    def test_get_invoice(self, stripe_client: stripe.StripeClient, target: Target):
        created = stripe_client.v1.invoices.create(
            params={"customer": self.customer.id}
        )
        fetched = stripe_client.v1.invoices.retrieve(created.id)
        assert fetched.id == created.id

    def test_finalize_invoice(self, stripe_client: stripe.StripeClient, target: Target):
        invoice = stripe_client.v1.invoices.create(
            params={"customer": self.customer.id}
        )
        finalized = stripe_client.v1.invoices.finalize_invoice(invoice.id)
        assert finalized.status == "open"

    def test_pay_invoice(self, stripe_client: stripe.StripeClient, target: Target):
        invoice = stripe_client.v1.invoices.create(
            params={"customer": self.customer.id}
        )
        stripe_client.v1.invoices.finalize_invoice(invoice.id)
        paid = stripe_client.v1.invoices.pay(invoice.id)
        assert paid.status == "paid"

    def test_list_invoices(self, stripe_client: stripe.StripeClient, target: Target):
        stripe_client.v1.invoices.create(params={"customer": self.customer.id})
        result = stripe_client.v1.invoices.list(params={"limit": 10})
        assert result.object == "list"
        assert len(result.data) >= 1
