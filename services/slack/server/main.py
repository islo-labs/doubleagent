"""
Slack Web API Fake — DoubleAgent Service

A high-fidelity fake of the Slack Web API for AI agent testing.
Copy-on-write state, per-agent namespace isolation, and webhook
delivery with retry + HMAC.

Slack API Notes:
- Most endpoints use POST with form data or JSON body
- Responses always include "ok": true/false
- Errors include "error" field with error code
"""

import asyncio
import copy
import hashlib
import hmac
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Form, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# =============================================================================
# Inline SDK: StateOverlay (copy-on-write state)
# =============================================================================

NAMESPACE_HEADER = "X-DoubleAgent-Namespace"
DEFAULT_NAMESPACE = "default"


class StateOverlay:
    """Copy-on-write state: reads fall through to baseline, writes go to overlay."""

    def __init__(self, baseline: dict[str, dict[str, Any]] | None = None) -> None:
        self._baseline: dict[str, dict[str, Any]] = baseline or {}
        self._overlay: dict[str, dict[str, Any]] = {}
        self._tombstones: set[str] = set()
        self._counters: dict[str, int] = {}

    def next_id(self, resource_type: str) -> int:
        if resource_type not in self._counters:
            max_id = 0
            for store in (self._baseline, self._overlay):
                for rid in store.get(resource_type, {}):
                    try:
                        max_id = max(max_id, int(rid))
                    except (ValueError, TypeError):
                        pass
            self._counters[resource_type] = max_id
        self._counters[resource_type] += 1
        return self._counters[resource_type]

    def get(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        key = f"{resource_type}:{resource_id}"
        if key in self._tombstones:
            return None
        obj = self._overlay.get(resource_type, {}).get(resource_id)
        if obj is not None:
            return obj
        baseline_obj = self._baseline.get(resource_type, {}).get(resource_id)
        if baseline_obj is not None:
            return copy.deepcopy(baseline_obj)
        return None

    def put(self, resource_type: str, resource_id: str, obj: dict[str, Any]) -> None:
        self._overlay.setdefault(resource_type, {})[resource_id] = obj
        self._tombstones.discard(f"{resource_type}:{resource_id}")

    def delete(self, resource_type: str, resource_id: str) -> bool:
        key = f"{resource_type}:{resource_id}"
        existed = self.get(resource_type, resource_id) is not None
        self._overlay.get(resource_type, {}).pop(resource_id, None)
        self._tombstones.add(key)
        return existed

    def list_all(
        self,
        resource_type: str,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        merged: dict[str, Any] = {
            k: copy.deepcopy(v)
            for k, v in self._baseline.get(resource_type, {}).items()
        }
        merged.update(self._overlay.get(resource_type, {}))
        items = [
            v
            for k, v in merged.items()
            if f"{resource_type}:{k}" not in self._tombstones
        ]
        if filter_fn:
            items = [i for i in items if filter_fn(i)]
        return items

    def count(self, resource_type: str) -> int:
        return len(self.list_all(resource_type))

    def reset(self) -> None:
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def reset_hard(self) -> None:
        self._baseline.clear()
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def load_baseline(self, data: dict[str, dict[str, Any]]) -> None:
        self._baseline = data
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def seed(self, data: dict[str, dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rtype, resources in data.items():
            for rid, obj in resources.items():
                self.put(rtype, rid, obj)
            counts[rtype] = len(resources)
        return counts

    def resource_types(self) -> set[str]:
        return set(self._baseline.keys()) | set(self._overlay.keys())

    def stats(self) -> dict[str, Any]:
        return {
            "baseline_types": {k: len(v) for k, v in self._baseline.items()},
            "overlay_types": {k: len(v) for k, v in self._overlay.items()},
            "tombstone_count": len(self._tombstones),
            "has_baseline": bool(self._baseline),
        }


# =============================================================================
# Inline SDK: NamespaceRouter (per-agent isolation)
# =============================================================================

class NamespaceRouter:
    """Manages isolated StateOverlay instances keyed by namespace."""

    def __init__(self) -> None:
        self._baseline: dict[str, dict[str, Any]] = {}
        self._namespaces: dict[str, StateOverlay] = {}

    def get_state(self, namespace: str | None = None) -> StateOverlay:
        ns = namespace or DEFAULT_NAMESPACE
        if ns not in self._namespaces:
            self._namespaces[ns] = StateOverlay(baseline=self._baseline)
        return self._namespaces[ns]

    def load_baseline(self, data: dict[str, dict[str, Any]]) -> None:
        self._baseline = data
        for overlay in self._namespaces.values():
            overlay.load_baseline(data)

    def reset_namespace(self, namespace: str | None = None, *, hard: bool = False) -> None:
        ns = namespace or DEFAULT_NAMESPACE
        if ns in self._namespaces:
            if hard:
                self._namespaces[ns].reset_hard()
            else:
                self._namespaces[ns].reset()

    def reset_all(self, *, hard: bool = False) -> None:
        for ns in list(self._namespaces):
            self.reset_namespace(ns, hard=hard)

    def list_namespaces(self) -> list[dict[str, Any]]:
        result = []
        for ns, overlay in self._namespaces.items():
            stats = overlay.stats()
            result.append({"namespace": ns, **stats})
        return result

    def delete_namespace(self, namespace: str) -> bool:
        return self._namespaces.pop(namespace, None) is not None


# =============================================================================
# Inline SDK: WebhookSimulator (delivery with retry + HMAC)
# =============================================================================

@dataclass
class WebhookDelivery:
    id: str
    event_type: str
    payload: dict[str, Any]
    target_url: str
    namespace: str
    status: str = "pending"
    attempts: int = 0
    last_attempt_at: float | None = None
    response_code: int | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "event_type": self.event_type,
            "target_url": self.target_url, "namespace": self.namespace,
            "status": self.status, "attempts": self.attempts,
            "last_attempt_at": self.last_attempt_at,
            "response_code": self.response_code, "error": self.error,
            "created_at": self.created_at,
        }


_DEFAULT_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _is_target_allowed(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if hostname in allowed_hosts:
        return True
    try:
        addr = ip_address(hostname)
        return addr.is_loopback or addr.is_private
    except ValueError:
        return False


def _compute_signature(payload: dict[str, Any], secret: str | None) -> str | None:
    if not secret:
        return None
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class WebhookSimulator:
    def __init__(
        self,
        max_retries: int = 3,
        retry_delays: list[float] | None = None,
        allowed_hosts: set[str] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.max_retries = max_retries
        self.retry_delays = retry_delays or [1.0, 5.0, 30.0]
        self.allowed_hosts = allowed_hosts or _DEFAULT_ALLOWED_HOSTS
        self.timeout = timeout
        self._deliveries: list[WebhookDelivery] = []

    async def deliver(
        self, target_url: str, event_type: str, payload: dict[str, Any], *,
        secret: str | None = None, namespace: str = "default",
        extra_headers: dict[str, str] | None = None,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            id=uuid.uuid4().hex[:16], event_type=event_type,
            payload=payload, target_url=target_url, namespace=namespace,
        )
        self._deliveries.append(delivery)
        if not _is_target_allowed(target_url, self.allowed_hosts):
            delivery.status = "failed"
            delivery.error = f"target host not in allowlist: {urlparse(target_url).hostname}"
            return delivery
        asyncio.create_task(
            self._deliver_with_retry(delivery, secret=secret, extra_headers=extra_headers)
        )
        return delivery

    def get_deliveries(self, *, namespace: str | None = None,
                       event_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        results = self._deliveries
        if namespace:
            results = [d for d in results if d.namespace == namespace]
        if event_type:
            results = [d for d in results if d.event_type == event_type]
        return [d.to_dict() for d in reversed(results[-limit:])]

    def clear(self) -> None:
        self._deliveries.clear()

    async def _deliver_with_retry(self, delivery: WebhookDelivery, *,
                                  secret: str | None = None,
                                  extra_headers: dict[str, str] | None = None) -> None:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-DoubleAgent-Delivery": delivery.id,
            "X-DoubleAgent-Namespace": delivery.namespace,
        }
        sig = _compute_signature(delivery.payload, secret)
        if sig:
            headers["X-Hub-Signature-256"] = sig
        if extra_headers:
            headers.update(extra_headers)
        for attempt in range(self.max_retries):
            delivery.attempts = attempt + 1
            delivery.last_attempt_at = time.time()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(delivery.target_url, json=delivery.payload, headers=headers)
                delivery.response_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    delivery.status = "delivered"
                    return
            except Exception as exc:
                delivery.error = str(exc)
            if attempt < self.max_retries - 1:
                delay = self.retry_delays[attempt] if attempt < len(self.retry_delays) else self.retry_delays[-1]
                await asyncio.sleep(delay)
        delivery.status = "failed"


# =============================================================================
# Helpers
# =============================================================================

def get_namespace(request: Request) -> str:
    """Extract namespace from request header."""
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)


def get_state(request: Request) -> StateOverlay:
    """Get the state overlay for the current request's namespace."""
    return ns_router.get_state(get_namespace(request))


def slack_error(error_code: str) -> JSONResponse:
    """Return Slack-style error response."""
    return JSONResponse({"ok": False, "error": error_code})


def get_auth_token(authorization: Optional[str]) -> Optional[str]:
    """Extract token from Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


# =============================================================================
# State (namespace-aware)
# =============================================================================

ns_router = NamespaceRouter()
webhook_sim = WebhookSimulator(max_retries=3, retry_delays=[0.5, 2.0, 10.0])

DEFAULT_USER = {
    "id": "U00000001",
    "team_id": "T00000001",
    "name": "doubleagent",
    "real_name": "DoubleAgent Bot",
    "is_bot": False,
}

DEFAULT_BOT = {
    "id": "B00000001",
    "name": "doubleagent-bot",
    "app_id": "A00000001",
}

_ts_counter: int = 1700000000


def _next_ts() -> str:
    global _ts_counter
    _ts_counter += 1
    return f"{_ts_counter}.000000"


_channel_counter: int = 0


def _next_channel_id() -> str:
    global _channel_counter
    _channel_counter += 1
    return f"C{_channel_counter:08d}"


_user_counter: int = 0


def _next_user_id() -> str:
    global _user_counter
    _user_counter += 1
    return f"U{_user_counter:08d}"


# =============================================================================
# Pydantic Models
# =============================================================================

class SeedData(BaseModel):
    users: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []


class BootstrapData(BaseModel):
    """Data sent by CLI to load a snapshot baseline."""
    channels: dict[str, Any] = {}
    users: dict[str, Any] = {}
    messages: dict[str, Any] = {}


class PostMessageRequest(BaseModel):
    channel: str
    text: Optional[str] = None
    blocks: Optional[list[dict]] = None
    thread_ts: Optional[str] = None


class UpdateMessageRequest(BaseModel):
    channel: str
    ts: str
    text: Optional[str] = None


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Slack Web API Fake",
    description="DoubleAgent fake of the Slack Web API",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# /_doubleagent endpoints (REQUIRED)
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    """Health check — REQUIRED."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset(request: Request, hard: bool = Query(default=False)):
    """Reset state — REQUIRED.

    Without ``?hard=true``, resets to snapshot baseline.
    With ``?hard=true``, resets to empty (ignores snapshot).
    """
    ns = get_namespace(request)
    ns_router.reset_namespace(ns, hard=hard)
    webhook_sim.clear()
    mode = "hard (empty)" if hard else "baseline"
    return {"status": "ok", "reset_mode": mode, "namespace": ns}


@app.post("/_doubleagent/seed")
async def seed(request: Request, data: SeedData):
    """Seed state from JSON — REQUIRED.

    Merges into overlay; snapshot baseline is preserved beneath.
    """
    state = get_state(request)
    ns = get_namespace(request)
    seeded: dict[str, int] = {}

    if data.users:
        for u in data.users:
            user_id = u.get("id") or _next_user_id()
            state.put("users", user_id, {
                "id": user_id,
                "team_id": u.get("team_id", "T00000001"),
                "name": u.get("name", f"user{user_id}"),
                "real_name": u.get("real_name", ""),
                "is_bot": u.get("is_bot", False),
                "is_admin": u.get("is_admin", False),
            })
        seeded["users"] = len(data.users)

    if data.channels:
        for c in data.channels:
            channel_id = c.get("id") or _next_channel_id()
            state.put("channels", channel_id, {
                "id": channel_id,
                "name": c.get("name", f"channel-{channel_id}"),
                "is_channel": True,
                "is_private": c.get("is_private", False),
                "is_archived": c.get("is_archived", False),
                "created": int(time.time()),
                "creator": c.get("creator", DEFAULT_USER["id"]),
                "topic": {"value": c.get("topic", ""), "creator": "", "last_set": 0},
                "purpose": {"value": c.get("purpose", ""), "creator": "", "last_set": 0},
                "num_members": c.get("num_members", 1),
            })
            # Initialize empty message list for the channel
            state.put("messages", channel_id, {"channel_id": channel_id, "messages": []})
        seeded["channels"] = len(data.channels)

    if data.messages:
        for m in data.messages:
            # Resolve channel by name if not an ID
            channel_id = m.get("channel")
            if channel_id and not channel_id.startswith("C"):
                # Look up channel by name
                for ch in state.list_all("channels"):
                    if ch["name"] == channel_id:
                        channel_id = ch["id"]
                        break
            if channel_id:
                ts = _next_ts()
                msg = {
                    "type": "message",
                    "ts": ts,
                    "user": m.get("user", DEFAULT_USER["id"]),
                    "text": m.get("text", ""),
                    "channel": channel_id,
                }
                msg_store = state.get("messages", channel_id)
                if msg_store is None:
                    msg_store = {"channel_id": channel_id, "messages": []}
                msg_store["messages"].append(msg)
                state.put("messages", channel_id, msg_store)
        seeded["messages"] = len(data.messages)

    return {"status": "ok", "seeded": seeded, "namespace": ns}


@app.post("/_doubleagent/bootstrap")
async def bootstrap(data: BootstrapData):
    """Load snapshot baseline.  Called by CLI on ``start --snapshot``.

    Replaces the shared baseline for all namespaces.
    """
    baseline: dict[str, dict[str, Any]] = {}
    for rtype in ("channels", "users", "messages"):
        d = getattr(data, rtype, {})
        if d:
            baseline[rtype] = d
    ns_router.load_baseline(baseline)
    counts = {k: len(v) for k, v in baseline.items()}
    return {"status": "ok", "loaded": counts}


@app.get("/_doubleagent/info")
async def info(request: Request):
    """Service info — OPTIONAL."""
    state = get_state(request)
    return {
        "name": "slack",
        "version": "1.0",
        "namespace": get_namespace(request),
        "state": state.stats(),
    }


@app.get("/_doubleagent/webhooks")
async def list_webhook_deliveries(
    request: Request,
    event_type: Optional[str] = None,
    limit: int = Query(default=100),
):
    """Query the webhook delivery log."""
    ns = get_namespace(request)
    return webhook_sim.get_deliveries(namespace=ns, event_type=event_type, limit=limit)


@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    """List active namespaces and their state sizes."""
    return ns_router.list_namespaces()


# =============================================================================
# Auth endpoints
# =============================================================================

@app.post("/auth.test")
async def auth_test(authorization: Optional[str] = Header(None)):
    """Test authentication."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    return {
        "ok": True,
        "url": "https://doubleagent.slack.com/",
        "team": "DoubleAgent",
        "user": DEFAULT_USER["name"],
        "team_id": "T00000001",
        "user_id": DEFAULT_USER["id"],
        "bot_id": DEFAULT_BOT["id"],
    }


# =============================================================================
# User endpoints
# =============================================================================

@app.post("/users.list")
async def users_list(
    request: Request,
    authorization: Optional[str] = Header(None),
    cursor: Optional[str] = Form(None),
    limit: int = Form(100),
):
    """List users in workspace."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    users = state.list_all("users")
    if not users:
        users = [DEFAULT_USER]

    return {
        "ok": True,
        "members": users,
        "response_metadata": {"next_cursor": ""},
    }


@app.post("/users.info")
async def users_info(
    request: Request,
    authorization: Optional[str] = Header(None),
    user: str = Form(...),
):
    """Get user info."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    user_obj = state.get("users", user)
    if user_obj:
        return {"ok": True, "user": user_obj}

    if user == DEFAULT_USER["id"]:
        return {"ok": True, "user": DEFAULT_USER}

    return slack_error("user_not_found")


# =============================================================================
# Conversation/Channel endpoints
# =============================================================================

@app.post("/conversations.list")
async def conversations_list(
    request: Request,
    authorization: Optional[str] = Header(None),
    types: str = Form("public_channel"),
    cursor: Optional[str] = Form(None),
    limit: int = Form(100),
):
    """List conversations/channels."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    channels = state.list_all("channels")

    return {
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": ""},
    }


@app.post("/conversations.create")
async def conversations_create(
    request: Request,
    authorization: Optional[str] = Header(None),
    name: str = Form(...),
    is_private: bool = Form(False),
):
    """Create a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)

    # Check for duplicate name
    for ch in state.list_all("channels"):
        if ch["name"] == name:
            return slack_error("name_taken")

    channel_id = _next_channel_id()
    channel = {
        "id": channel_id,
        "name": name,
        "is_channel": not is_private,
        "is_private": is_private,
        "is_archived": False,
        "created": int(time.time()),
        "creator": DEFAULT_USER["id"],
        "topic": {"value": "", "creator": "", "last_set": 0},
        "purpose": {"value": "", "creator": "", "last_set": 0},
        "num_members": 1,
    }
    state.put("channels", channel_id, channel)
    state.put("messages", channel_id, {"channel_id": channel_id, "messages": []})

    # Dispatch event
    await _dispatch_event(request, "channel_created", {"channel": channel})

    return {"ok": True, "channel": channel}


@app.post("/conversations.info")
async def conversations_info(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
):
    """Get channel info."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    return {"ok": True, "channel": ch}


@app.post("/conversations.archive")
async def conversations_archive(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
):
    """Archive a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    ch["is_archived"] = True
    state.put("channels", channel, ch)
    return {"ok": True}


@app.post("/conversations.unarchive")
async def conversations_unarchive(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
):
    """Unarchive a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    ch["is_archived"] = False
    state.put("channels", channel, ch)
    return {"ok": True}


@app.post("/conversations.setTopic")
async def conversations_set_topic(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    topic: str = Form(...),
):
    """Set channel topic."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    ch["topic"] = {
        "value": topic,
        "creator": DEFAULT_USER["id"],
        "last_set": int(time.time()),
    }
    state.put("channels", channel, ch)
    return {"ok": True, "topic": topic}


@app.post("/conversations.setPurpose")
async def conversations_set_purpose(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    purpose: str = Form(...),
):
    """Set channel purpose."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    ch["purpose"] = {
        "value": purpose,
        "creator": DEFAULT_USER["id"],
        "last_set": int(time.time()),
    }
    state.put("channels", channel, ch)
    return {"ok": True, "purpose": purpose}


async def _conversations_history_impl(
    request: Request,
    authorization: Optional[str],
    channel: str,
    cursor: Optional[str],
    limit: int,
):
    """Implementation for conversation history (shared by GET and POST)."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    msg_store = state.get("messages", channel)
    messages = msg_store["messages"] if msg_store else []

    return {
        "ok": True,
        "messages": messages[-limit:],
        "has_more": len(messages) > limit,
        "response_metadata": {"next_cursor": ""},
    }


@app.get("/conversations.history")
async def conversations_history_get(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Query(...),
    cursor: Optional[str] = Query(None),
    limit: int = Query(100),
):
    """Get conversation history (GET method - per API docs)."""
    return await _conversations_history_impl(request, authorization, channel, cursor, limit)


@app.post("/conversations.history")
async def conversations_history_post(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    cursor: Optional[str] = Form(None),
    limit: int = Form(100),
):
    """Get conversation history (POST method - for SDK compatibility)."""
    return await _conversations_history_impl(request, authorization, channel, cursor, limit)


# =============================================================================
# Message endpoints
# =============================================================================

@app.post("/chat.postMessage")
async def chat_post_message(
    request: Request,
    msg: PostMessageRequest,
    authorization: Optional[str] = Header(None),
):
    """Post a message to a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", msg.channel)
    if not ch:
        return slack_error("channel_not_found")

    if not msg.text and not msg.blocks:
        return slack_error("no_text")

    ts = _next_ts()
    message = {
        "type": "message",
        "ts": ts,
        "user": DEFAULT_USER["id"],
        "text": msg.text or "",
        "channel": msg.channel,
    }

    if msg.thread_ts:
        message["thread_ts"] = msg.thread_ts

    if msg.blocks:
        message["blocks"] = msg.blocks

    msg_store = state.get("messages", msg.channel)
    if msg_store is None:
        msg_store = {"channel_id": msg.channel, "messages": []}
    msg_store["messages"].append(message)
    state.put("messages", msg.channel, msg_store)

    # Dispatch event
    await _dispatch_event(request, "message", {
        "channel": msg.channel,
        "user": DEFAULT_USER["id"],
        "text": msg.text or "",
        "ts": ts,
    })

    return {
        "ok": True,
        "channel": msg.channel,
        "ts": ts,
        "message": message,
    }


@app.post("/chat.update")
async def chat_update(
    request: Request,
    msg: UpdateMessageRequest,
    authorization: Optional[str] = Header(None),
):
    """Update a message."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", msg.channel)
    if not ch:
        return slack_error("channel_not_found")

    msg_store = state.get("messages", msg.channel)
    messages = msg_store["messages"] if msg_store else []
    for m in messages:
        if m["ts"] == msg.ts:
            if msg.text:
                m["text"] = msg.text
            m["edited"] = {"user": DEFAULT_USER["id"], "ts": _next_ts()}
            if msg_store:
                state.put("messages", msg.channel, msg_store)
            return {"ok": True, "channel": msg.channel, "ts": msg.ts, "text": msg.text}

    return slack_error("message_not_found")


@app.post("/chat.delete")
async def chat_delete(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    ts: str = Form(...),
):
    """Delete a message."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    msg_store = state.get("messages", channel)
    messages = msg_store["messages"] if msg_store else []
    for i, m in enumerate(messages):
        if m["ts"] == ts:
            del messages[i]
            if msg_store:
                state.put("messages", channel, msg_store)
            return {"ok": True, "channel": channel, "ts": ts}

    return slack_error("message_not_found")


@app.post("/reactions.add")
async def reactions_add(
    request: Request,
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    timestamp: str = Form(...),
    name: str = Form(...),
):
    """Add a reaction to a message."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")

    state = get_state(request)
    ch = state.get("channels", channel)
    if not ch:
        return slack_error("channel_not_found")

    msg_store = state.get("messages", channel)
    messages = msg_store["messages"] if msg_store else []
    for m in messages:
        if m["ts"] == timestamp:
            if "reactions" not in m:
                m["reactions"] = []
            m["reactions"].append({
                "name": name,
                "users": [DEFAULT_USER["id"]],
                "count": 1,
            })
            if msg_store:
                state.put("messages", channel, msg_store)
            return {"ok": True}

    return slack_error("message_not_found")


# =============================================================================
# Events/Webhooks
# =============================================================================

async def _dispatch_event(request: Request, event_type: str, payload: dict) -> None:
    """Dispatch events to registered webhooks via the WebhookSimulator."""
    ns = get_namespace(request)
    state = get_state(request)
    webhooks = state.list_all("webhooks")

    for webhook in webhooks:
        if not webhook.get("active", True):
            continue

        event_data = {
            "type": event_type,
            "event": payload,
            "team_id": "T00000001",
            "event_time": int(time.time()),
        }

        await webhook_sim.deliver(
            target_url=webhook["url"],
            event_type=event_type,
            payload=event_data,
            namespace=ns,
        )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8083))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
