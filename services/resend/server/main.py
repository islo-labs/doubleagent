"""
Resend Email API Fake - DoubleAgent Service

A high-fidelity fake of the Resend API for AI agent testing.
Built with FastAPI. The real API base is https://api.resend.com.

All endpoints return application/json with Content-Type: application/json.
All successful operations return HTTP 200 (Resend does not use 201/204).
Resource IDs are UUIDs.
"""

import os
import re
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# =============================================================================
# Constants
# =============================================================================

# The default valid API key used in fake mode (must match conftest.py)
DEFAULT_VALID_API_KEY = "re_fake_test_key_1234567890"


# =============================================================================
# Helpers
# =============================================================================

def _now() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _generate_id() -> str:
    """Generate a UUID matching Resend's ID format."""
    return str(uuid.uuid4())


def _ensure_list(value: Any) -> Optional[list]:
    """Convert a string or list to a list, or return None if value is falsy."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [value]


def _error_response(status_code: int, name: str, message: str) -> JSONResponse:
    """Return a Resend-style error response (top-level shape, NOT wrapped by FastAPI)."""
    return JSONResponse(
        status_code=status_code,
        content={
            "statusCode": status_code,
            "name": name,
            "message": message,
        },
    )


def _paginate(items: list, request: Request) -> dict:
    """
    Apply cursor-based pagination to a list of items.

    Reads `limit`, `after`, and `before` from query parameters.
    Returns a Resend-style list envelope: {"object": "list", "has_more": bool, "data": [...]}.
    """
    limit = int(request.query_params.get("limit", "20"))
    after = request.query_params.get("after")
    before = request.query_params.get("before")

    # Clamp limit
    limit = max(1, min(limit, 100))

    # Apply cursor-based pagination
    if after:
        found_idx = None
        for i, item in enumerate(items):
            if item["id"] == after:
                found_idx = i
                break
        if found_idx is not None:
            items = items[found_idx + 1:]
        else:
            items = []
    elif before:
        found_idx = None
        for i, item in enumerate(items):
            if item["id"] == before:
                found_idx = i
                break
        if found_idx is not None:
            items = items[:found_idx]
        else:
            items = []

    has_more = len(items) > limit
    page = items[:limit]

    return {
        "object": "list",
        "has_more": has_more,
        "data": page,
    }


# =============================================================================
# State
# =============================================================================

def _initial_state() -> dict[str, Any]:
    """Return a fresh initial state with empty collections."""
    return {
        "emails": OrderedDict(),
        "domains": OrderedDict(),
        "contacts": OrderedDict(),
        "templates": OrderedDict(),
        "api_keys": OrderedDict(),
        "webhooks": OrderedDict(),
        "idempotency_keys": {},
        "valid_api_key": DEFAULT_VALID_API_KEY,
    }


state: dict[str, Any] = _initial_state()


# =============================================================================
# App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    yield


app = FastAPI(title="Resend Fake", lifespan=lifespan)


# =============================================================================
# Auth middleware
# =============================================================================

class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate API key authentication.

    Checks the Authorization header on all non-control-plane requests.
    Returns Resend-style error responses for missing/invalid API keys.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip auth for control-plane endpoints and OPTIONS
        if request.url.path.startswith("/_doubleagent"):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")

        # Extract the bearer token
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]  # Strip "Bearer " prefix
        else:
            token = ""

        # Missing or empty API key → 401
        if not token or token.strip() == "":
            return JSONResponse(
                status_code=401,
                content={
                    "statusCode": 401,
                    "name": "missing_api_key",
                    "message": "Missing API Key",
                },
            )

        # Invalid API key → 400 (Resend quirk: invalid key returns 400, not 401/403)
        if token != state["valid_api_key"]:
            return JSONResponse(
                status_code=400,
                content={
                    "statusCode": 400,
                    "name": "validation_error",
                    "message": "API key is invalid",
                },
            )

        return await call_next(request)


app.add_middleware(AuthMiddleware)


# =============================================================================
# Control-plane endpoints
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    """Reset all state to initial empty state."""
    global state
    state = _initial_state()
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(request: Request):
    """Seed the fake with initial data."""
    body = await request.json()

    seeded: dict[str, Any] = {}

    # Seed each resource type if provided
    for resource_type in ["emails", "domains", "contacts", "templates", "api_keys", "webhooks"]:
        if resource_type in body:
            seeded[resource_type] = []
            for item in body[resource_type]:
                item_id = item.get("id", _generate_id())
                item["id"] = item_id
                state[resource_type][item_id] = item
                seeded[resource_type].append(item_id)

    return {"status": "ok", "seeded": seeded}


# =============================================================================
# Email endpoints
# =============================================================================


@app.post("/emails/batch")
async def send_batch_emails(request: Request):
    """
    POST /emails/batch — Send batch emails.

    Accepts a JSON array of email objects (same fields as single send).
    Returns {"data": [{"id": "uuid-1"}, {"id": "uuid-2"}, ...]}.
    No "object" field on the wrapper or items.
    """
    body = await request.json()
    now = _now()

    results = []
    for email_params in body:
        email_id = _generate_id()

        # Normalize fields
        to_field = email_params.get("to")
        if isinstance(to_field, str):
            to_field = [to_field]

        cc = _ensure_list(email_params.get("cc"))
        bcc = _ensure_list(email_params.get("bcc"))
        reply_to = _ensure_list(email_params.get("reply_to"))

        last_event = "delivered"

        email_record = {
            "object": "email",
            "id": email_id,
            "to": to_field,
            "from": email_params.get("from"),
            "created_at": now,
            "subject": email_params.get("subject"),
            "html": email_params.get("html"),
            "text": email_params.get("text"),
            "bcc": bcc,
            "cc": cc,
            "reply_to": reply_to,
            "last_event": last_event,
            "scheduled_at": None,
            "tags": email_params.get("tags"),
        }

        state["emails"][email_id] = email_record
        results.append({"id": email_id})

    return JSONResponse(content={"data": results})


@app.post("/emails")
async def send_email(request: Request):
    """
    POST /emails — Send an email.

    The real API returns only {"id": "uuid"} (no "object" field).
    Supports Idempotency-Key header for deduplication.
    Supports template-based sending via the "template" field.

    Validation order (verified against real API):
    1. `to` field checked first → 422 missing_required_field
    2. `html` or `text` → 422 validation_error (skipped if template provided)
    3. Then `subject`, `from`, etc. (skipped if template provides defaults)
    """
    body = await request.json()

    # Check if this is a template-based send
    template_ref = body.get("template")
    resolved_template = None

    if template_ref:
        # Look up the template by ID or alias
        tmpl_id = template_ref.get("id") or template_ref.get("alias")
        if tmpl_id:
            resolved_template = _resolve_template(tmpl_id)
            if resolved_template is None:
                return _error_response(404, "not_found", "Template not found")

    # Validate required fields (matching real API validation order)
    # 1. `to` is checked first
    if "to" not in body or body["to"] is None or body["to"] == "" or body["to"] == []:
        return _error_response(
            422,
            "missing_required_field",
            "Missing `to` field.",
        )

    # When a template is provided, skip html/text/subject validation
    # because those come from the template
    if not resolved_template:
        # 2. `html` or `text` required
        if not body.get("html") and not body.get("text"):
            return _error_response(
                422,
                "validation_error",
                "Missing `html` or `text` field.",
            )

        # 3. `subject` required
        if "subject" not in body or not body.get("subject"):
            return _error_response(
                422,
                "missing_required_field",
                "Missing `subject` field.",
            )

    # 4. `from` required
    if "from" not in body or not body.get("from"):
        return _error_response(
            422,
            "missing_required_field",
            "Missing `from` field.",
        )

    # Check for idempotency key
    idempotency_key = request.headers.get("idempotency-key")
    if idempotency_key and idempotency_key in state["idempotency_keys"]:
        # Return the same email id as before
        existing_id = state["idempotency_keys"][idempotency_key]
        return JSONResponse(content={"id": existing_id})

    email_id = _generate_id()
    now = _now()

    # Normalize `to` to always be a list
    to_field = body.get("to")
    if isinstance(to_field, str):
        to_field = [to_field]

    # Normalize cc, bcc, reply_to to lists or None
    cc = _ensure_list(body.get("cc"))
    bcc = _ensure_list(body.get("bcc"))
    reply_to = _ensure_list(body.get("reply_to"))

    # Resolve email fields: use template defaults, then apply overrides from body
    email_subject = body.get("subject")
    email_html = body.get("html")
    email_text = body.get("text")
    email_from = body.get("from")

    if resolved_template:
        template_vars = (template_ref.get("variables") or {}) if template_ref else {}

        # Use template defaults if not overridden in the send body
        if not email_subject:
            email_subject = resolved_template.get("subject", "")
        if not email_html:
            email_html = resolved_template.get("html", "")
        if not email_text:
            email_text = resolved_template.get("text")
        if not email_from:
            email_from = resolved_template.get("from", "")

        # Substitute variables in subject and html
        email_subject = _substitute_template_variables(email_subject, template_vars)
        email_html = _substitute_template_variables(email_html, template_vars)
        if email_text:
            email_text = _substitute_template_variables(email_text, template_vars)

    # Determine last_event based on whether the email is scheduled
    scheduled_at = body.get("scheduled_at")
    last_event = "scheduled" if scheduled_at else "delivered"

    # Store the full email object for later retrieval
    email_record = {
        "object": "email",
        "id": email_id,
        "to": to_field,
        "from": email_from,
        "created_at": now,
        "subject": email_subject,
        "html": email_html,
        "text": email_text,
        "bcc": bcc,
        "cc": cc,
        "reply_to": reply_to,
        "last_event": last_event,
        "scheduled_at": scheduled_at,
        "tags": body.get("tags"),
    }

    state["emails"][email_id] = email_record

    # Store idempotency key mapping
    if idempotency_key:
        state["idempotency_keys"][idempotency_key] = email_id

    # Send response returns only {"id": "uuid"} — no "object" field
    return JSONResponse(content={"id": email_id})


@app.get("/emails/{email_id}")
async def get_email(email_id: str):
    """
    GET /emails/{id} — Retrieve a single email.

    Returns the full email object with "object": "email".
    """
    email = state["emails"].get(email_id)
    if email is None:
        return _error_response(404, "not_found", "Email not found")

    return JSONResponse(content=email)


@app.get("/emails")
async def list_emails(request: Request):
    """
    GET /emails — List emails.

    Returns a paginated list envelope.
    List items include summary fields only (no html, text, or tags).
    """
    all_emails = list(state["emails"].values())

    # Build summary items (list items exclude html, text, tags per API docs)
    summary_items = []
    for email in all_emails:
        summary = {
            "id": email["id"],
            "to": email["to"],
            "from": email["from"],
            "created_at": email["created_at"],
            "subject": email["subject"],
            "bcc": email.get("bcc"),
            "cc": email.get("cc"),
            "reply_to": email.get("reply_to"),
            "last_event": email.get("last_event", "delivered"),
            "scheduled_at": email.get("scheduled_at"),
        }
        summary_items.append(summary)

    result = _paginate(summary_items, request)
    return JSONResponse(content=result)


@app.patch("/emails/{email_id}")
async def update_email(email_id: str, request: Request):
    """
    PATCH /emails/{id} — Update (reschedule) an email.

    Primarily used to update scheduled_at for scheduled emails.
    Returns {"object": "email", "id": "..."}.
    """
    email = state["emails"].get(email_id)
    if email is None:
        return _error_response(404, "not_found", "Email not found")

    body = await request.json()

    # Update mutable fields
    if "scheduled_at" in body:
        email["scheduled_at"] = body["scheduled_at"]

    return JSONResponse(content={"object": "email", "id": email_id})


@app.post("/emails/{email_id}/cancel")
async def cancel_email(email_id: str):
    """
    POST /emails/{id}/cancel — Cancel a scheduled email.

    Sets last_event to "canceled".
    Returns {"object": "email", "id": "..."}.
    """
    email = state["emails"].get(email_id)
    if email is None:
        return _error_response(404, "not_found", "Email not found")

    email["last_event"] = "canceled"

    return JSONResponse(content={"object": "email", "id": email_id})


# =============================================================================
# Domain helpers
# =============================================================================

def _generate_domain_records(domain_name: str, region: str) -> list[dict]:
    """
    Generate realistic DNS records for a domain.

    Returns a list of DNS records matching the real Resend API structure.
    Each record has: record, name, type, value, ttl, status, and optionally priority.
    """
    custom_return_path = "send"
    records = [
        {
            "record": "SPF",
            "name": f"{custom_return_path}.{domain_name}",
            "type": "MX",
            "value": f"feedback-smtp.{region}.amazonses.com",
            "ttl": "Auto",
            "status": "not_started",
            "priority": 10,
        },
        {
            "record": "SPF",
            "name": f"{custom_return_path}.{domain_name}",
            "type": "TXT",
            "value": "v=spf1 include:amazonses.com ~all",
            "ttl": "Auto",
            "status": "not_started",
        },
        {
            "record": "DKIM",
            "name": f"resend._domainkey.{domain_name}",
            "type": "CNAME",
            "value": f"resend.{domain_name}.dkim.amazonses.com",
            "ttl": "Auto",
            "status": "not_started",
        },
    ]
    return records


# =============================================================================
# Domain endpoints
# =============================================================================


@app.post("/domains")
async def create_domain(request: Request):
    """
    POST /domains — Create a domain.

    Returns the full domain object including DNS records.
    All successful operations return HTTP 200.
    """
    body = await request.json()

    domain_id = _generate_id()
    now = _now()
    domain_name = body.get("name", "")
    region = body.get("region", "us-east-1")

    records = _generate_domain_records(domain_name, region)

    domain = {
        "id": domain_id,
        "name": domain_name,
        "created_at": now,
        "status": "not_started",
        "region": region,
        "records": records,
    }

    state["domains"][domain_id] = domain

    return JSONResponse(content=domain)


@app.get("/domains")
async def list_domains(request: Request):
    """
    GET /domains — List domains.

    Returns a paginated list envelope.
    List items do NOT include the records array.
    """
    all_domains = list(state["domains"].values())

    # Build summary items (list items exclude records per API docs)
    summary_items = []
    for domain in all_domains:
        summary = {
            "id": domain["id"],
            "name": domain["name"],
            "status": domain.get("status", "not_started"),
            "created_at": domain["created_at"],
            "region": domain.get("region", "us-east-1"),
        }
        summary_items.append(summary)

    result = _paginate(summary_items, request)
    return JSONResponse(content=result)


@app.post("/domains/{domain_id}/verify")
async def verify_domain(domain_id: str):
    """
    POST /domains/{domain_id}/verify — Trigger domain verification.

    Returns {"object": "domain", "id": "..."}.
    """
    domain = state["domains"].get(domain_id)
    if domain is None:
        return _error_response(404, "not_found", "Domain not found")

    return JSONResponse(content={"object": "domain", "id": domain_id})


@app.get("/domains/{domain_id}")
async def get_domain(domain_id: str):
    """
    GET /domains/{domain_id} — Retrieve a single domain.

    Returns the full domain object with "object": "domain" and records array.
    """
    domain = state["domains"].get(domain_id)
    if domain is None:
        return _error_response(404, "not_found", "Domain not found")

    # Build response with object field (GET response includes object field)
    response = {
        "object": "domain",
        "id": domain["id"],
        "name": domain["name"],
        "status": domain.get("status", "not_started"),
        "created_at": domain["created_at"],
        "region": domain.get("region", "us-east-1"),
        "records": domain.get("records", []),
    }

    return JSONResponse(content=response)


@app.patch("/domains/{domain_id}")
async def update_domain(domain_id: str, request: Request):
    """
    PATCH /domains/{domain_id} — Update a domain.

    Supports updating tracking settings (openTracking, clickTracking, tls, capabilities).
    Returns {"object": "domain", "id": "..."}.
    """
    domain = state["domains"].get(domain_id)
    if domain is None:
        return _error_response(404, "not_found", "Domain not found")

    body = await request.json()

    # Update mutable fields
    if "openTracking" in body or "open_tracking" in body:
        domain["open_tracking"] = body.get("openTracking", body.get("open_tracking"))
    if "clickTracking" in body or "click_tracking" in body:
        domain["click_tracking"] = body.get("clickTracking", body.get("click_tracking"))
    if "tls" in body:
        domain["tls"] = body["tls"]
    if "capabilities" in body:
        domain["capabilities"] = body["capabilities"]

    return JSONResponse(content={"object": "domain", "id": domain_id})


@app.delete("/domains/{domain_id}")
async def delete_domain(domain_id: str):
    """
    DELETE /domains/{domain_id} — Delete a domain.

    Hard-deletes the domain (Resend does NOT soft-delete).
    Returns {"object": "domain", "id": "...", "deleted": true}.
    """
    domain = state["domains"].get(domain_id)
    if domain is None:
        return _error_response(404, "not_found", "Domain not found")

    # Hard-delete: remove from state
    del state["domains"][domain_id]

    return JSONResponse(content={
        "object": "domain",
        "id": domain_id,
        "deleted": True,
    })


# =============================================================================
# Contact helpers
# =============================================================================

def _find_contact_by_email(email: str) -> Optional[dict]:
    """Find a contact by email address. Returns the contact dict or None."""
    for contact in state["contacts"].values():
        if contact.get("email") == email:
            return contact
    return None


def _is_uuid(value: str) -> bool:
    """Check if a string looks like a UUID."""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _resolve_contact(id_or_email: str) -> Optional[dict]:
    """
    Resolve a contact by UUID or email address.

    The Resend API accepts either a UUID or email as the path parameter
    for GET /contacts/{id_or_email}.
    """
    # Try as UUID first (direct lookup is O(1))
    contact = state["contacts"].get(id_or_email)
    if contact is not None:
        return contact

    # Try as email address
    return _find_contact_by_email(id_or_email)


# =============================================================================
# Contact endpoints
# =============================================================================


@app.post("/contacts")
async def create_contact(request: Request):
    """
    POST /contacts — Create a contact.

    Returns {"object": "contact", "id": "uuid"} (HTTP 200).
    """
    body = await request.json()

    contact_id = _generate_id()
    now = _now()

    contact = {
        "object": "contact",
        "id": contact_id,
        "email": body.get("email", ""),
        "first_name": body.get("first_name", ""),
        "last_name": body.get("last_name", ""),
        "created_at": now,
        "unsubscribed": body.get("unsubscribed", False),
        "properties": body.get("properties", {}),
    }

    state["contacts"][contact_id] = contact

    return JSONResponse(content={
        "object": "contact",
        "id": contact_id,
    })


@app.get("/contacts")
async def list_contacts(request: Request):
    """
    GET /contacts — List contacts.

    Returns a paginated list envelope.
    """
    all_contacts = list(state["contacts"].values())

    # Build summary items for list
    summary_items = []
    for contact in all_contacts:
        summary = {
            "id": contact["id"],
            "email": contact.get("email", ""),
            "first_name": contact.get("first_name", ""),
            "last_name": contact.get("last_name", ""),
            "created_at": contact["created_at"],
            "unsubscribed": contact.get("unsubscribed", False),
        }
        summary_items.append(summary)

    result = _paginate(summary_items, request)
    return JSONResponse(content=result)


@app.get("/contacts/{id_or_email:path}")
async def get_contact(id_or_email: str):
    """
    GET /contacts/{id_or_email} — Retrieve a single contact.

    Accepts either UUID or email address as path parameter.
    Returns the full contact object with "object": "contact".
    """
    contact = _resolve_contact(id_or_email)
    if contact is None:
        return _error_response(404, "not_found", "Contact not found")

    response = {
        "object": "contact",
        "id": contact["id"],
        "email": contact.get("email", ""),
        "first_name": contact.get("first_name", ""),
        "last_name": contact.get("last_name", ""),
        "created_at": contact["created_at"],
        "unsubscribed": contact.get("unsubscribed", False),
        "properties": contact.get("properties", {}),
    }

    return JSONResponse(content=response)


@app.patch("/contacts/{id_or_email:path}")
async def update_contact(id_or_email: str, request: Request):
    """
    PATCH /contacts/{id_or_email} — Update a contact.

    Accepts either UUID or email as path parameter.
    Returns {"object": "contact", "id": "..."}.
    """
    contact = _resolve_contact(id_or_email)
    if contact is None:
        return _error_response(404, "not_found", "Contact not found")

    body = await request.json()

    # Update mutable fields
    if "first_name" in body:
        contact["first_name"] = body["first_name"]
    if "last_name" in body:
        contact["last_name"] = body["last_name"]
    if "unsubscribed" in body:
        contact["unsubscribed"] = body["unsubscribed"]
    if "email" in body:
        contact["email"] = body["email"]
    if "properties" in body:
        contact["properties"] = body["properties"]

    return JSONResponse(content={
        "object": "contact",
        "id": contact["id"],
    })


@app.delete("/contacts/{id_or_email:path}")
async def delete_contact(id_or_email: str):
    """
    DELETE /contacts/{id_or_email} — Delete a contact.

    Hard-deletes the contact (Resend does NOT soft-delete).
    Returns {"object": "contact", "contact": "<uuid>", "deleted": true}.
    Note: Uses "contact" field (not "id") for the deleted contact's UUID.
    """
    contact = _resolve_contact(id_or_email)
    if contact is None:
        return _error_response(404, "not_found", "Contact not found")

    contact_id = contact["id"]

    # Hard-delete: remove from state
    del state["contacts"][contact_id]

    return JSONResponse(content={
        "object": "contact",
        "contact": contact_id,
        "deleted": True,
    })


# =============================================================================
# Template helpers
# =============================================================================


def _resolve_template(id_or_alias: str) -> Optional[dict]:
    """
    Resolve a template by UUID or alias.

    The Resend API accepts either a UUID or alias as the path parameter
    for GET /templates/{id_or_alias}, POST /templates/{id_or_alias}/publish, etc.
    """
    # Try direct UUID lookup first (O(1))
    template = state["templates"].get(id_or_alias)
    if template is not None:
        return template

    # Try alias lookup (linear scan)
    for tmpl in state["templates"].values():
        if tmpl.get("alias") == id_or_alias:
            return tmpl

    return None


def _substitute_template_variables(text: str, variables: dict) -> str:
    """
    Substitute triple-brace {{{VAR}}} placeholders with variable values.

    Resend uses {{{variable_name}}} syntax (Mustache-style unescaped).
    """
    if not text:
        return text

    def replace_var(match):
        var_name = match.group(1)
        return variables.get(var_name, match.group(0))

    # Match {{{...}}} patterns
    return re.sub(r"\{\{\{(\w+)\}\}\}", replace_var, text)


# =============================================================================
# Template endpoints
# =============================================================================


@app.post("/templates")
async def create_template(request: Request):
    """
    POST /templates — Create a template.

    Returns {"id": "uuid", "object": "template"} (HTTP 200).
    """
    body = await request.json()

    template_id = _generate_id()
    now = _now()

    # Build variables with IDs and timestamps
    variables = []
    for var in body.get("variables", []):
        variable = {
            "id": _generate_id(),
            "key": var.get("key", ""),
            "type": var.get("type", "string"),
            "fallback_value": var.get("fallback_value"),
            "created_at": now,
            "updated_at": now,
        }
        variables.append(variable)

    template = {
        "object": "template",
        "id": template_id,
        "current_version_id": _generate_id(),
        "alias": body.get("alias"),
        "name": body.get("name", ""),
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "published_at": None,
        "from": body.get("from"),
        "subject": body.get("subject"),
        "reply_to": body.get("reply_to"),
        "html": body.get("html", ""),
        "text": body.get("text"),
        "variables": variables,
        "has_unpublished_versions": False,
    }

    state["templates"][template_id] = template

    return JSONResponse(content={
        "id": template_id,
        "object": "template",
    })


@app.get("/templates")
async def list_templates(request: Request):
    """
    GET /templates — List templates.

    Returns a paginated list envelope.
    List items include summary fields only (no html, text, variables, from, subject, etc).
    """
    all_templates = list(state["templates"].values())

    # Build summary items (list items exclude html, text, variables, from, subject per API docs)
    summary_items = []
    for template in all_templates:
        summary = {
            "id": template["id"],
            "name": template.get("name", ""),
            "status": template.get("status", "draft"),
            "published_at": template.get("published_at"),
            "created_at": template["created_at"],
            "updated_at": template["updated_at"],
            "alias": template.get("alias"),
        }
        summary_items.append(summary)

    result = _paginate(summary_items, request)
    return JSONResponse(content=result)


@app.post("/templates/{template_id}/publish")
async def publish_template(template_id: str):
    """
    POST /templates/{id_or_alias}/publish — Publish a template.

    Accepts either UUID or alias as path parameter.
    Sets status to "published" and sets published_at timestamp.
    Returns {"id": "...", "object": "template"}.
    """
    template = _resolve_template(template_id)
    if template is None:
        return _error_response(404, "not_found", "Template not found")

    template["status"] = "published"
    template["published_at"] = _now()
    template["updated_at"] = _now()

    return JSONResponse(content={
        "id": template["id"],
        "object": "template",
    })


@app.post("/templates/{template_id}/duplicate")
async def duplicate_template(template_id: str):
    """
    POST /templates/{id_or_alias}/duplicate — Duplicate a template.

    Accepts either UUID or alias as path parameter.
    Creates a copy of the template with a new ID.
    Returns {"object": "template", "id": "new-uuid"}.
    """
    template = _resolve_template(template_id)
    if template is None:
        return _error_response(404, "not_found", "Template not found")

    new_id = _generate_id()
    now = _now()

    # Deep copy the template with a new ID
    new_template = {
        "object": "template",
        "id": new_id,
        "current_version_id": _generate_id(),
        "alias": template.get("alias"),
        "name": template.get("name", ""),
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "published_at": None,
        "from": template.get("from"),
        "subject": template.get("subject"),
        "reply_to": template.get("reply_to"),
        "html": template.get("html", ""),
        "text": template.get("text"),
        "variables": [
            {
                "id": _generate_id(),
                "key": v.get("key", ""),
                "type": v.get("type", "string"),
                "fallback_value": v.get("fallback_value"),
                "created_at": now,
                "updated_at": now,
            }
            for v in template.get("variables", [])
        ],
        "has_unpublished_versions": False,
    }

    state["templates"][new_id] = new_template

    return JSONResponse(content={
        "object": "template",
        "id": new_id,
    })


@app.get("/templates/{template_id}")
async def get_template(template_id: str):
    """
    GET /templates/{id_or_alias} — Retrieve a single template.

    Accepts either UUID or alias as path parameter.
    Returns the full template object with "object": "template".
    """
    template = _resolve_template(template_id)
    if template is None:
        return _error_response(404, "not_found", "Template not found")

    return JSONResponse(content=template)


@app.patch("/templates/{template_id}")
async def update_template(template_id: str, request: Request):
    """
    PATCH /templates/{id_or_alias} — Update a template.

    Accepts either UUID or alias as path parameter.
    The SDK strips the 'id' field from the request body before sending.
    Returns {"id": "...", "object": "template"}.
    """
    template = _resolve_template(template_id)
    if template is None:
        return _error_response(404, "not_found", "Template not found")

    body = await request.json()

    # Update mutable fields
    if "name" in body:
        template["name"] = body["name"]
    if "html" in body:
        template["html"] = body["html"]
    if "text" in body:
        template["text"] = body["text"]
    if "subject" in body:
        template["subject"] = body["subject"]
    if "from" in body:
        template["from"] = body["from"]
    if "reply_to" in body:
        template["reply_to"] = body["reply_to"]
    if "alias" in body:
        template["alias"] = body["alias"]
    if "variables" in body:
        now = _now()
        template["variables"] = [
            {
                "id": _generate_id(),
                "key": v.get("key", ""),
                "type": v.get("type", "string"),
                "fallback_value": v.get("fallback_value"),
                "created_at": now,
                "updated_at": now,
            }
            for v in body["variables"]
        ]

    template["updated_at"] = _now()

    return JSONResponse(content={
        "id": template["id"],
        "object": "template",
    })


@app.delete("/templates/{template_id}")
async def delete_template(template_id: str):
    """
    DELETE /templates/{id_or_alias} — Delete a template.

    Accepts either UUID or alias as path parameter.
    Hard-deletes the template (Resend does NOT soft-delete).
    Returns {"object": "template", "id": "...", "deleted": true}.
    """
    template = _resolve_template(template_id)
    if template is None:
        return _error_response(404, "not_found", "Template not found")

    actual_id = template["id"]

    # Hard-delete: remove from state
    del state["templates"][actual_id]

    return JSONResponse(content={
        "object": "template",
        "id": actual_id,
        "deleted": True,
    })


# =============================================================================
# API Key helpers
# =============================================================================

def _generate_token() -> str:
    """Generate a fake API key token starting with 're_'."""
    return f"re_{uuid.uuid4().hex}"


# =============================================================================
# API Key endpoints
# =============================================================================


@app.post("/api-keys")
async def create_api_key(request: Request):
    """
    POST /api-keys — Create an API key.

    Returns {"id": "uuid", "token": "re_..."} (HTTP 200).
    No "object" field in the response.
    Token is only returned on creation.
    """
    body = await request.json()

    api_key_id = _generate_id()
    now = _now()
    token = _generate_token()

    api_key = {
        "id": api_key_id,
        "name": body.get("name", ""),
        "created_at": now,
        "permission": body.get("permission", "full_access"),
        "domain_id": body.get("domain_id"),
    }

    state["api_keys"][api_key_id] = api_key

    # Create response: only id and token (no "object" field)
    return JSONResponse(content={
        "id": api_key_id,
        "token": token,
    })


@app.get("/api-keys")
async def list_api_keys(request: Request):
    """
    GET /api-keys — List API keys.

    Returns a paginated list envelope.
    Listed keys do NOT include the token value.
    """
    all_keys = list(state["api_keys"].values())

    # Build summary items (list items exclude token per API docs)
    summary_items = []
    for key in all_keys:
        summary = {
            "id": key["id"],
            "name": key.get("name", ""),
            "created_at": key["created_at"],
        }
        summary_items.append(summary)

    result = _paginate(summary_items, request)
    return JSONResponse(content=result)


@app.delete("/api-keys/{api_key_id}")
async def delete_api_key(api_key_id: str):
    """
    DELETE /api-keys/{api_key_id} — Delete an API key.

    Hard-deletes the API key. Returns empty body (the SDK returns None).
    The real API returns HTTP 200 with empty body.

    We return JSON null so json.loads() succeeds and the SDK's perform()
    returns None as expected.
    """
    # Remove from state if it exists (no error if not found, matching real API behavior)
    if api_key_id in state["api_keys"]:
        del state["api_keys"][api_key_id]

    # Return JSON null — json.loads("null") → None, which is what the SDK expects
    return JSONResponse(content=None)


# =============================================================================
# Webhook helpers
# =============================================================================

def _generate_signing_secret() -> str:
    """Generate a fake webhook signing secret starting with 'whsec_'."""
    return f"whsec_{uuid.uuid4().hex}"


# =============================================================================
# Webhook endpoints
# =============================================================================


@app.post("/webhooks")
async def create_webhook(request: Request):
    """
    POST /webhooks — Create a webhook.

    Returns {"object": "webhook", "id": "uuid", "signing_secret": "whsec_..."} (HTTP 200).
    """
    body = await request.json()

    webhook_id = _generate_id()
    now = _now()
    signing_secret = _generate_signing_secret()

    webhook = {
        "object": "webhook",
        "id": webhook_id,
        "created_at": now,
        "status": "enabled",
        "endpoint": body.get("endpoint", ""),
        "events": body.get("events", []),
        "signing_secret": signing_secret,
    }

    state["webhooks"][webhook_id] = webhook

    return JSONResponse(content={
        "object": "webhook",
        "id": webhook_id,
        "signing_secret": signing_secret,
    })


@app.get("/webhooks")
async def list_webhooks(request: Request):
    """
    GET /webhooks — List webhooks.

    Returns a paginated list envelope.
    List items do NOT include signing_secret.
    """
    all_webhooks = list(state["webhooks"].values())

    # Build summary items (list items exclude signing_secret per API docs)
    summary_items = []
    for webhook in all_webhooks:
        summary = {
            "id": webhook["id"],
            "created_at": webhook["created_at"],
            "status": webhook.get("status", "enabled"),
            "endpoint": webhook.get("endpoint", ""),
            "events": webhook.get("events", []),
        }
        summary_items.append(summary)

    result = _paginate(summary_items, request)
    return JSONResponse(content=result)


@app.get("/webhooks/{webhook_id}")
async def get_webhook(webhook_id: str):
    """
    GET /webhooks/{webhook_id} — Retrieve a single webhook.

    Returns the full webhook object with "object": "webhook" and signing_secret.
    """
    webhook = state["webhooks"].get(webhook_id)
    if webhook is None:
        return _error_response(404, "not_found", "Webhook not found")

    return JSONResponse(content={
        "object": "webhook",
        "id": webhook["id"],
        "created_at": webhook["created_at"],
        "status": webhook.get("status", "enabled"),
        "endpoint": webhook.get("endpoint", ""),
        "events": webhook.get("events", []),
        "signing_secret": webhook.get("signing_secret", ""),
    })


@app.patch("/webhooks/{webhook_id}")
async def update_webhook(webhook_id: str, request: Request):
    """
    PATCH /webhooks/{webhook_id} — Update a webhook.

    The SDK sends full params including webhook_id in the body.
    Supports updating endpoint, events, and status.
    Returns {"object": "webhook", "id": "..."}.
    """
    webhook = state["webhooks"].get(webhook_id)
    if webhook is None:
        return _error_response(404, "not_found", "Webhook not found")

    body = await request.json()

    # Update mutable fields
    if "endpoint" in body:
        webhook["endpoint"] = body["endpoint"]
    if "events" in body:
        webhook["events"] = body["events"]
    if "status" in body:
        webhook["status"] = body["status"]

    return JSONResponse(content={
        "object": "webhook",
        "id": webhook_id,
    })


@app.delete("/webhooks/{webhook_id}")
async def delete_webhook(webhook_id: str):
    """
    DELETE /webhooks/{webhook_id} — Delete a webhook.

    Hard-deletes the webhook (Resend does NOT soft-delete).
    Returns {"object": "webhook", "id": "...", "deleted": true}.
    """
    webhook = state["webhooks"].get(webhook_id)
    if webhook is None:
        return _error_response(404, "not_found", "Webhook not found")

    # Hard-delete: remove from state
    del state["webhooks"][webhook_id]

    return JSONResponse(content={
        "object": "webhook",
        "id": webhook_id,
        "deleted": True,
    })


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
