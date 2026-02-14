"""
Stripe API Fake - DoubleAgent Service

A high-fidelity fake of the Stripe API for AI agent testing.
Supports form-encoded POST bodies, prefixed IDs, Stripe-style responses.
"""

import os
import time
import asyncio
import uuid
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# =============================================================================
# State
# =============================================================================

state: dict[str, dict] = {
    "customers": {},
    "payment_intents": {},
    "products": {},
    "prices": {},
    "subscriptions": {},
    "invoices": {},
    "webhook_endpoints": {},
}

counters: dict[str, int] = {
    "customer": 0,
    "payment_intent": 0,
    "product": 0,
    "price": 0,
    "subscription": 0,
    "invoice": 0,
    "webhook_endpoint": 0,
}

idempotency_cache: dict[str, Any] = {}

ID_PREFIXES = {
    "customer": "cus_",
    "payment_intent": "pi_",
    "product": "prod_",
    "price": "price_",
    "subscription": "sub_",
    "invoice": "in_",
    "webhook_endpoint": "we_",
}


def next_id(resource: str) -> str:
    counters[resource] += 1
    prefix = ID_PREFIXES[resource]
    return f"{prefix}{uuid.uuid4().hex[:14]}"


def now_ts() -> int:
    return int(time.time())


def reset_state() -> None:
    global idempotency_cache
    for k in state:
        state[k] = {}
    for k in counters:
        counters[k] = 0
    idempotency_cache = {}


def stripe_error(status: int, error_type: str, message: str):
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def stripe_list(data: list, url: str = "/v1/unknown") -> dict:
    return {
        "object": "list",
        "data": data,
        "has_more": False,
        "url": url,
    }


async def parse_form_or_json(request: Request) -> dict:
    """Parse Stripe-style form-encoded or JSON body."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        return await request.json()
    # Form-encoded (Stripe default)
    form = await request.form()
    result: dict[str, Any] = {}
    for key, value in form.multi_items():
        # Handle nested keys like metadata[key]
        if "[" in key:
            parts = key.replace("]", "").split("[")
            d = result
            for part in parts[:-1]:
                if part not in d:
                    d[part] = {}
                d = d[part]
            d[parts[-1]] = value
        else:
            result[key] = value
    return result


# =============================================================================
# Auth dependency
# =============================================================================

async def verify_auth(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        # Also accept Basic auth (stripe SDK uses this)
        if not auth.startswith("Basic "):
            return stripe_error(401, "authentication_error", "No valid API key provided.")
    return None


# =============================================================================
# App
# =============================================================================

app = FastAPI(title="Stripe API Fake", version="1.0.0")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Skip auth for doubleagent endpoints
    if request.url.path.startswith("/_doubleagent"):
        return await call_next(request)
    
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") and not auth.startswith("Basic "):
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "authentication_error", "message": "No valid API key provided."}},
        )
    
    # Idempotency-Key check
    idem_key = request.headers.get("idempotency-key")
    if idem_key and idem_key in idempotency_cache:
        return JSONResponse(content=idempotency_cache[idem_key]["body"],
                            status_code=idempotency_cache[idem_key]["status"])
    
    response = await call_next(request)
    
    # Cache idempotent response (only for POST)
    if idem_key and request.method == "POST":
        body = b""
        async for chunk in response.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()
        import json
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body.decode()
        idempotency_cache[idem_key] = {"body": parsed, "status": response.status_code}
        return JSONResponse(content=parsed, status_code=response.status_code)
    
    return response


# =============================================================================
# /_doubleagent endpoints (REQUIRED)
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    reset_state()
    return {"status": "ok"}


class SeedData(BaseModel):
    customers: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []


@app.post("/_doubleagent/seed")
async def seed(data: SeedData):
    seeded: dict[str, int] = {}
    if data.customers:
        for c in data.customers:
            cid = next_id("customer")
            ts = now_ts()
            state["customers"][cid] = {
                "id": cid,
                "object": "customer",
                "name": c.get("name", None),
                "email": c.get("email", None),
                "metadata": c.get("metadata", {}),
                "created": ts,
                "livemode": False,
            }
        seeded["customers"] = len(data.customers)
    if data.products:
        for p in data.products:
            pid = next_id("product")
            ts = now_ts()
            state["products"][pid] = {
                "id": pid,
                "object": "product",
                "name": p.get("name", ""),
                "description": p.get("description", None),
                "active": True,
                "metadata": p.get("metadata", {}),
                "created": ts,
                "livemode": False,
            }
        seeded["products"] = len(data.products)
    return {"status": "ok", "seeded": seeded}


# =============================================================================
# Customers
# =============================================================================

@app.post("/v1/customers")
async def create_customer(request: Request):
    data = await parse_form_or_json(request)
    cid = next_id("customer")
    ts = now_ts()
    customer = {
        "id": cid,
        "object": "customer",
        "name": data.get("name", None),
        "email": data.get("email", None),
        "description": data.get("description", None),
        "metadata": data.get("metadata", {}),
        "created": ts,
        "livemode": False,
    }
    state["customers"][cid] = customer
    await dispatch_event("customer.created", customer)
    return JSONResponse(content=customer, status_code=200)


@app.get("/v1/customers/{customer_id}")
async def get_customer(customer_id: str):
    if customer_id not in state["customers"]:
        return stripe_error(404, "invalid_request_error", f"No such customer: '{customer_id}'")
    return state["customers"][customer_id]


@app.post("/v1/customers/{customer_id}")
async def update_customer(customer_id: str, request: Request):
    if customer_id not in state["customers"]:
        return stripe_error(404, "invalid_request_error", f"No such customer: '{customer_id}'")
    data = await parse_form_or_json(request)
    c = state["customers"][customer_id]
    for field in ("name", "email", "description"):
        if field in data:
            c[field] = data[field]
    if "metadata" in data:
        c["metadata"].update(data["metadata"])
    await dispatch_event("customer.updated", c)
    return c


@app.delete("/v1/customers/{customer_id}")
async def delete_customer(customer_id: str):
    if customer_id not in state["customers"]:
        return stripe_error(404, "invalid_request_error", f"No such customer: '{customer_id}'")
    del state["customers"][customer_id]
    return {"id": customer_id, "object": "customer", "deleted": True}


@app.get("/v1/customers")
async def list_customers(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    customers = list(state["customers"].values())[:limit]
    return stripe_list(customers, "/v1/customers")


# =============================================================================
# Payment Intents
# =============================================================================

@app.post("/v1/payment_intents")
async def create_payment_intent(request: Request):
    data = await parse_form_or_json(request)
    amount = data.get("amount")
    currency = data.get("currency")
    if not amount or not currency:
        return stripe_error(400, "invalid_request_error", "Missing required param: amount or currency.")
    pid = next_id("payment_intent")
    ts = now_ts()
    pi = {
        "id": pid,
        "object": "payment_intent",
        "amount": int(amount),
        "currency": currency.lower() if isinstance(currency, str) else currency,
        "status": "requires_payment_method",
        "customer": data.get("customer", None),
        "description": data.get("description", None),
        "metadata": data.get("metadata", {}),
        "created": ts,
        "livemode": False,
        "client_secret": f"{pid}_secret_{uuid.uuid4().hex[:16]}",
        "payment_method_types": ["card"],
    }
    state["payment_intents"][pid] = pi
    await dispatch_event("payment_intent.created", pi)
    return JSONResponse(content=pi, status_code=200)


@app.get("/v1/payment_intents/{pi_id}")
async def get_payment_intent(pi_id: str):
    if pi_id not in state["payment_intents"]:
        return stripe_error(404, "invalid_request_error", f"No such payment_intent: '{pi_id}'")
    return state["payment_intents"][pi_id]


@app.post("/v1/payment_intents/{pi_id}")
async def update_payment_intent(pi_id: str, request: Request):
    if pi_id not in state["payment_intents"]:
        return stripe_error(404, "invalid_request_error", f"No such payment_intent: '{pi_id}'")
    data = await parse_form_or_json(request)
    pi = state["payment_intents"][pi_id]
    for field in ("amount", "currency", "description", "customer"):
        if field in data:
            val = data[field]
            if field == "amount":
                val = int(val)
            pi[field] = val
    if "metadata" in data:
        pi["metadata"].update(data["metadata"])
    return pi


@app.post("/v1/payment_intents/{pi_id}/confirm")
async def confirm_payment_intent(pi_id: str, request: Request):
    if pi_id not in state["payment_intents"]:
        return stripe_error(404, "invalid_request_error", f"No such payment_intent: '{pi_id}'")
    pi = state["payment_intents"][pi_id]
    # Simulate successful confirmation
    pi["status"] = "succeeded"
    await dispatch_event("payment_intent.succeeded", pi)
    return pi


@app.post("/v1/payment_intents/{pi_id}/cancel")
async def cancel_payment_intent(pi_id: str, request: Request):
    if pi_id not in state["payment_intents"]:
        return stripe_error(404, "invalid_request_error", f"No such payment_intent: '{pi_id}'")
    pi = state["payment_intents"][pi_id]
    pi["status"] = "canceled"
    await dispatch_event("payment_intent.canceled", pi)
    return pi


@app.get("/v1/payment_intents")
async def list_payment_intents(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    pis = list(state["payment_intents"].values())[:limit]
    return stripe_list(pis, "/v1/payment_intents")


# =============================================================================
# Products
# =============================================================================

@app.post("/v1/products")
async def create_product(request: Request):
    data = await parse_form_or_json(request)
    name = data.get("name")
    if not name:
        return stripe_error(400, "invalid_request_error", "Missing required param: name.")
    pid = next_id("product")
    ts = now_ts()
    product = {
        "id": pid,
        "object": "product",
        "name": name,
        "description": data.get("description", None),
        "active": True,
        "metadata": data.get("metadata", {}),
        "created": ts,
        "livemode": False,
    }
    state["products"][pid] = product
    return JSONResponse(content=product, status_code=200)


@app.get("/v1/products/{product_id}")
async def get_product(product_id: str):
    if product_id not in state["products"]:
        return stripe_error(404, "invalid_request_error", f"No such product: '{product_id}'")
    return state["products"][product_id]


@app.post("/v1/products/{product_id}")
async def update_product(product_id: str, request: Request):
    if product_id not in state["products"]:
        return stripe_error(404, "invalid_request_error", f"No such product: '{product_id}'")
    data = await parse_form_or_json(request)
    p = state["products"][product_id]
    for field in ("name", "description", "active"):
        if field in data:
            val = data[field]
            if field == "active":
                val = val in (True, "true", "True")
            p[field] = val
    if "metadata" in data:
        p["metadata"].update(data["metadata"])
    return p


@app.get("/v1/products")
async def list_products(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    products = list(state["products"].values())[:limit]
    return stripe_list(products, "/v1/products")


# =============================================================================
# Prices
# =============================================================================

@app.post("/v1/prices")
async def create_price(request: Request):
    data = await parse_form_or_json(request)
    currency = data.get("currency")
    product = data.get("product")
    if not currency:
        return stripe_error(400, "invalid_request_error", "Missing required param: currency.")
    pid = next_id("price")
    ts = now_ts()
    
    recurring = data.get("recurring", None)
    if isinstance(recurring, dict):
        recurring = {k: v for k, v in recurring.items()}
    
    price = {
        "id": pid,
        "object": "price",
        "currency": currency.lower() if isinstance(currency, str) else currency,
        "product": product,
        "unit_amount": int(data["unit_amount"]) if "unit_amount" in data else None,
        "active": True,
        "type": "recurring" if recurring else "one_time",
        "recurring": recurring,
        "metadata": data.get("metadata", {}),
        "created": ts,
        "livemode": False,
    }
    state["prices"][pid] = price
    return JSONResponse(content=price, status_code=200)


@app.get("/v1/prices/{price_id}")
async def get_price(price_id: str):
    if price_id not in state["prices"]:
        return stripe_error(404, "invalid_request_error", f"No such price: '{price_id}'")
    return state["prices"][price_id]


@app.get("/v1/prices")
async def list_prices(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    product = request.query_params.get("product", None)
    prices = list(state["prices"].values())
    if product:
        prices = [p for p in prices if p.get("product") == product]
    return stripe_list(prices[:limit], "/v1/prices")


# =============================================================================
# Subscriptions
# =============================================================================

@app.post("/v1/subscriptions")
async def create_subscription(request: Request):
    data = await parse_form_or_json(request)
    customer = data.get("customer")
    if not customer:
        return stripe_error(400, "invalid_request_error", "Missing required param: customer.")
    if customer not in state["customers"]:
        return stripe_error(400, "invalid_request_error", f"No such customer: '{customer}'")
    
    sid = next_id("subscription")
    ts = now_ts()
    
    # Parse items
    items_data = data.get("items", {})
    sub_items = []
    if isinstance(items_data, dict):
        # Form-encoded: items[0][price]=price_xxx
        idx = 0
        while str(idx) in items_data:
            item = items_data[str(idx)]
            price_id = item.get("price", "") if isinstance(item, dict) else item
            sub_items.append({
                "id": f"si_{uuid.uuid4().hex[:14]}",
                "object": "subscription_item",
                "price": state["prices"].get(price_id, {"id": price_id, "object": "price"}),
                "quantity": int(item.get("quantity", 1)) if isinstance(item, dict) else 1,
            })
            idx += 1
    elif isinstance(items_data, list):
        for item in items_data:
            price_id = item.get("price", "")
            sub_items.append({
                "id": f"si_{uuid.uuid4().hex[:14]}",
                "object": "subscription_item",
                "price": state["prices"].get(price_id, {"id": price_id, "object": "price"}),
                "quantity": int(item.get("quantity", 1)),
            })
    
    sub = {
        "id": sid,
        "object": "subscription",
        "customer": customer,
        "status": "active",
        "items": {"object": "list", "data": sub_items, "has_more": False},
        "metadata": data.get("metadata", {}),
        "current_period_start": ts,
        "current_period_end": ts + 30 * 86400,
        "created": ts,
        "cancel_at_period_end": False,
        "livemode": False,
    }
    state["subscriptions"][sid] = sub
    await dispatch_event("customer.subscription.created", sub)
    return JSONResponse(content=sub, status_code=200)


@app.get("/v1/subscriptions/{sub_id}")
async def get_subscription(sub_id: str):
    if sub_id not in state["subscriptions"]:
        return stripe_error(404, "invalid_request_error", f"No such subscription: '{sub_id}'")
    return state["subscriptions"][sub_id]


@app.post("/v1/subscriptions/{sub_id}")
async def update_subscription(sub_id: str, request: Request):
    if sub_id not in state["subscriptions"]:
        return stripe_error(404, "invalid_request_error", f"No such subscription: '{sub_id}'")
    data = await parse_form_or_json(request)
    sub = state["subscriptions"][sub_id]
    if "cancel_at_period_end" in data:
        val = data["cancel_at_period_end"]
        sub["cancel_at_period_end"] = val in (True, "true", "True")
    if "metadata" in data:
        sub["metadata"].update(data["metadata"])
    await dispatch_event("customer.subscription.updated", sub)
    return sub


@app.delete("/v1/subscriptions/{sub_id}")
async def cancel_subscription(sub_id: str):
    if sub_id not in state["subscriptions"]:
        return stripe_error(404, "invalid_request_error", f"No such subscription: '{sub_id}'")
    sub = state["subscriptions"][sub_id]
    sub["status"] = "canceled"
    await dispatch_event("customer.subscription.deleted", sub)
    return sub


@app.get("/v1/subscriptions")
async def list_subscriptions(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    customer = request.query_params.get("customer", None)
    subs = list(state["subscriptions"].values())
    if customer:
        subs = [s for s in subs if s.get("customer") == customer]
    return stripe_list(subs[:limit], "/v1/subscriptions")


# =============================================================================
# Invoices
# =============================================================================

@app.post("/v1/invoices")
async def create_invoice(request: Request):
    data = await parse_form_or_json(request)
    customer = data.get("customer")
    if not customer:
        return stripe_error(400, "invalid_request_error", "Missing required param: customer.")
    iid = next_id("invoice")
    ts = now_ts()
    invoice = {
        "id": iid,
        "object": "invoice",
        "customer": customer,
        "status": "draft",
        "amount_due": int(data.get("amount_due", 0)),
        "currency": data.get("currency", "usd"),
        "metadata": data.get("metadata", {}),
        "created": ts,
        "livemode": False,
    }
    state["invoices"][iid] = invoice
    return JSONResponse(content=invoice, status_code=200)


@app.get("/v1/invoices/{invoice_id}")
async def get_invoice(invoice_id: str):
    if invoice_id not in state["invoices"]:
        return stripe_error(404, "invalid_request_error", f"No such invoice: '{invoice_id}'")
    return state["invoices"][invoice_id]


@app.get("/v1/invoices")
async def list_invoices(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    customer = request.query_params.get("customer", None)
    invoices = list(state["invoices"].values())
    if customer:
        invoices = [i for i in invoices if i.get("customer") == customer]
    return stripe_list(invoices[:limit], "/v1/invoices")


@app.post("/v1/invoices/{invoice_id}/finalize")
async def finalize_invoice(invoice_id: str, request: Request):
    if invoice_id not in state["invoices"]:
        return stripe_error(404, "invalid_request_error", f"No such invoice: '{invoice_id}'")
    inv = state["invoices"][invoice_id]
    inv["status"] = "open"
    await dispatch_event("invoice.finalized", inv)
    return inv


@app.post("/v1/invoices/{invoice_id}/pay")
async def pay_invoice(invoice_id: str, request: Request):
    if invoice_id not in state["invoices"]:
        return stripe_error(404, "invalid_request_error", f"No such invoice: '{invoice_id}'")
    inv = state["invoices"][invoice_id]
    inv["status"] = "paid"
    await dispatch_event("invoice.paid", inv)
    return inv


# =============================================================================
# Webhook Endpoints
# =============================================================================

@app.post("/v1/webhook_endpoints")
async def create_webhook_endpoint(request: Request):
    data = await parse_form_or_json(request)
    url = data.get("url")
    if not url:
        return stripe_error(400, "invalid_request_error", "Missing required param: url.")
    
    # Parse enabled_events from form encoding
    enabled_events = data.get("enabled_events", ["*"])
    if isinstance(enabled_events, dict):
        enabled_events = list(enabled_events.values())
    elif isinstance(enabled_events, str):
        enabled_events = [enabled_events]
    
    wid = next_id("webhook_endpoint")
    ts = now_ts()
    endpoint = {
        "id": wid,
        "object": "webhook_endpoint",
        "url": url,
        "enabled_events": enabled_events,
        "status": "enabled",
        "secret": f"whsec_{uuid.uuid4().hex}",
        "created": ts,
        "livemode": False,
    }
    state["webhook_endpoints"][wid] = endpoint
    return JSONResponse(content=endpoint, status_code=200)


@app.get("/v1/webhook_endpoints/{we_id}")
async def get_webhook_endpoint(we_id: str):
    if we_id not in state["webhook_endpoints"]:
        return stripe_error(404, "invalid_request_error", f"No such webhook_endpoint: '{we_id}'")
    return state["webhook_endpoints"][we_id]


@app.delete("/v1/webhook_endpoints/{we_id}")
async def delete_webhook_endpoint(we_id: str):
    if we_id not in state["webhook_endpoints"]:
        return stripe_error(404, "invalid_request_error", f"No such webhook_endpoint: '{we_id}'")
    del state["webhook_endpoints"][we_id]
    return {"id": we_id, "object": "webhook_endpoint", "deleted": True}


@app.get("/v1/webhook_endpoints")
async def list_webhook_endpoints(request: Request):
    limit = int(request.query_params.get("limit", "10"))
    endpoints = list(state["webhook_endpoints"].values())[:limit]
    return stripe_list(endpoints, "/v1/webhook_endpoints")


async def dispatch_event(event_type: str, data: dict) -> None:
    """Dispatch webhook events to registered endpoints."""
    for endpoint in state["webhook_endpoints"].values():
        if endpoint["status"] != "enabled":
            continue
        events = endpoint["enabled_events"]
        if "*" not in events and event_type not in events:
            continue
        event = {
            "id": f"evt_{uuid.uuid4().hex[:14]}",
            "object": "event",
            "type": event_type,
            "data": {"object": data},
            "created": now_ts(),
            "livemode": False,
        }
        asyncio.create_task(_send_webhook(endpoint["url"], event))


async def _send_webhook(url: str, event: dict) -> None:
    try:
        async with httpx.AsyncClient() as client:
            await client.post(url, json=event, timeout=5.0)
    except Exception:
        pass


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8082))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
