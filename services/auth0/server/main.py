"""
Auth0 Management & Authentication API Fake — DoubleAgent Service

Fakes both the Auth0 Management API (v2) and Authentication API:
- Users, Roles, Permissions (CRUD via Management API)
- /authorize, /oauth/token, /userinfo (Authentication flows)
- JWKS endpoint for local token verification
- COW state, namespace isolation, webhook simulator
"""

import asyncio
import base64
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
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response


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

    def snapshot_profile(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._baseline)


# =============================================================================
# Inline SDK: NamespaceRouter (per-agent isolation)
# =============================================================================

class NamespaceRouter:
    """Manages isolated StateOverlay instances keyed by namespace."""

    def __init__(self, baseline: dict[str, dict[str, Any]] | None = None) -> None:
        self._baseline: dict[str, dict[str, Any]] = baseline or {}
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
    """Record of a single webhook delivery attempt (or series of retries)."""

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
            "id": self.id,
            "event_type": self.event_type,
            "target_url": self.target_url,
            "namespace": self.namespace,
            "status": self.status,
            "attempts": self.attempts,
            "last_attempt_at": self.last_attempt_at,
            "response_code": self.response_code,
            "error": self.error,
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
    """Delivers webhooks to localhost endpoints with retry and logging."""

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
        self,
        target_url: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        secret: str | None = None,
        namespace: str = "default",
        extra_headers: dict[str, str] | None = None,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            id=uuid.uuid4().hex[:16],
            event_type=event_type,
            payload=payload,
            target_url=target_url,
            namespace=namespace,
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

    def get_deliveries(
        self,
        *,
        namespace: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        results = self._deliveries
        if namespace:
            results = [d for d in results if d.namespace == namespace]
        if event_type:
            results = [d for d in results if d.event_type == event_type]
        return [d.to_dict() for d in reversed(results[-limit:])]

    def clear(self) -> None:
        self._deliveries.clear()

    async def _deliver_with_retry(
        self,
        delivery: WebhookDelivery,
        *,
        secret: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
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
                    resp = await client.post(
                        delivery.target_url,
                        json=delivery.payload,
                        headers=headers,
                    )
                delivery.response_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    delivery.status = "delivered"
                    return
            except Exception as exc:
                delivery.error = str(exc)

            if attempt < self.max_retries - 1:
                delay = (
                    self.retry_delays[attempt]
                    if attempt < len(self.retry_delays)
                    else self.retry_delays[-1]
                )
                await asyncio.sleep(delay)

        delivery.status = "failed"


# =============================================================================
# RSA key pair (generated once at startup for JWKS + token signing)
# =============================================================================

_rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _rsa_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
_public_key = _rsa_key.public_key()
_public_numbers = _public_key.public_numbers()
_kid = uuid.uuid4().hex[:16]


def _int_to_base64url(n: int) -> str:
    """Encode an integer as base64url (no padding), for JWK."""
    b = n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": _kid,
            "use": "sig",
            "alg": "RS256",
            "n": _int_to_base64url(_public_numbers.n),
            "e": _int_to_base64url(_public_numbers.e),
        }
    ]
}

ISSUER = os.environ.get("AUTH0_ISSUER", "https://doubleagent.auth0.local/")


def _sign_token(payload: dict) -> str:
    """Sign a JWT with the local RSA key."""
    return jwt.encode(payload, _private_pem, algorithm="RS256", headers={"kid": _kid})


# =============================================================================
# State / helpers
# =============================================================================

router = NamespaceRouter()
webhook_sim = WebhookSimulator(max_retries=3, retry_delays=[0.5, 2.0, 10.0])


def get_namespace(request: Request) -> str:
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)


def get_state(request: Request) -> StateOverlay:
    return router.get_state(get_namespace(request))


def _api_error(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"statusCode": status, "error": error, "message": message},
    )


def _get_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Pydantic Models
# =============================================================================

class CreateUserRequest(BaseModel):
    email: str
    password: Optional[str] = None
    connection: str = "Username-Password-Authentication"
    name: Optional[str] = None
    nickname: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    user_metadata: Optional[dict] = None
    app_metadata: Optional[dict] = None
    blocked: bool = False
    email_verified: bool = False


class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    nickname: Optional[str] = None
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    blocked: Optional[bool] = None
    email_verified: Optional[bool] = None
    user_metadata: Optional[dict] = None
    app_metadata: Optional[dict] = None


class CreateRoleRequest(BaseModel):
    name: str
    description: Optional[str] = ""


class TokenRequest(BaseModel):
    grant_type: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    audience: Optional[str] = None
    scope: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class SeedData(BaseModel):
    users: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    permissions: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []


class BootstrapData(BaseModel):
    users: dict[str, Any] = {}
    roles: dict[str, Any] = {}
    permissions: dict[str, Any] = {}
    connections: dict[str, Any] = {}


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Auth0 Management & Authentication API Fake",
    description="DoubleAgent fake of the Auth0 APIs",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# /_doubleagent endpoints (REQUIRED)
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset(request: Request, hard: bool = Query(default=False)):
    ns = get_namespace(request)
    router.reset_namespace(ns, hard=hard)
    webhook_sim.clear()
    return {"status": "ok", "reset_mode": "hard" if hard else "baseline", "namespace": ns}


@app.post("/_doubleagent/seed")
async def seed(request: Request, data: SeedData):
    state = get_state(request)
    ns = get_namespace(request)
    seeded: dict[str, int] = {}

    if data.users:
        for u in data.users:
            user_id = u.get("user_id") or f"auth0|{uuid.uuid4().hex[:24]}"
            state.put("users", user_id, {
                "user_id": user_id,
                "email": u.get("email", f"{user_id}@doubleagent.local"),
                "email_verified": u.get("email_verified", False),
                "name": u.get("name", ""),
                "nickname": u.get("nickname", ""),
                "given_name": u.get("given_name", ""),
                "family_name": u.get("family_name", ""),
                "connection": u.get("connection", "Username-Password-Authentication"),
                "blocked": u.get("blocked", False),
                "created_at": u.get("created_at", _iso_now()),
                "updated_at": _iso_now(),
                "user_metadata": u.get("user_metadata", {}),
                "app_metadata": u.get("app_metadata", {}),
                "identities": [{"connection": u.get("connection", "Username-Password-Authentication"),
                                "user_id": user_id.split("|")[-1], "provider": "auth0", "isSocial": False}],
            })
        seeded["users"] = len(data.users)

    if data.roles:
        for r in data.roles:
            role_id = r.get("id") or f"rol_{uuid.uuid4().hex[:24]}"
            state.put("roles", role_id, {
                "id": role_id,
                "name": r.get("name", ""),
                "description": r.get("description", ""),
            })
        seeded["roles"] = len(data.roles)

    if data.permissions:
        for p in data.permissions:
            perm_id = f"{p.get('resource_server_identifier', 'api')}:{p.get('permission_name', 'unknown')}"
            state.put("permissions", perm_id, {
                "permission_name": p.get("permission_name", ""),
                "resource_server_identifier": p.get("resource_server_identifier", ""),
                "description": p.get("description", ""),
            })
        seeded["permissions"] = len(data.permissions)

    if data.connections:
        for c in data.connections:
            conn_id = c.get("id") or f"con_{uuid.uuid4().hex[:24]}"
            state.put("connections", conn_id, {
                "id": conn_id,
                "name": c.get("name", ""),
                "strategy": c.get("strategy", "auth0"),
                "enabled_clients": c.get("enabled_clients", []),
            })
        seeded["connections"] = len(data.connections)

    return {"status": "ok", "seeded": seeded, "namespace": ns}


@app.post("/_doubleagent/bootstrap")
async def bootstrap(data: BootstrapData):
    baseline: dict[str, dict[str, Any]] = {}
    for rtype in ("users", "roles", "permissions", "connections"):
        d = getattr(data, rtype, {})
        if d:
            baseline[rtype] = d
    router.load_baseline(baseline)
    counts = {k: len(v) for k, v in baseline.items()}
    return {"status": "ok", "loaded": counts}


@app.get("/_doubleagent/info")
async def info(request: Request):
    state = get_state(request)
    return {"name": "auth0", "version": "1.0", "namespace": get_namespace(request), "state": state.stats()}


@app.get("/_doubleagent/webhooks")
async def list_webhook_deliveries(
    request: Request,
    event_type: Optional[str] = None,
    limit: int = Query(default=100),
):
    ns = get_namespace(request)
    return webhook_sim.get_deliveries(namespace=ns, event_type=event_type, limit=limit)


@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    return router.list_namespaces()


# =============================================================================
# JWKS / Well-known endpoints
# =============================================================================

@app.get("/.well-known/jwks.json")
async def jwks():
    return JWKS


@app.get("/.well-known/openid-configuration")
async def openid_configuration():
    base = os.environ.get("AUTH0_BASE_URL", f"http://localhost:{os.environ.get('PORT', 8085)}")
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "userinfo_endpoint": f"{base}/userinfo",
        "jwks_uri": f"{base}/.well-known/jwks.json",
        "scopes_supported": ["openid", "profile", "email"],
        "response_types_supported": ["code", "token", "id_token"],
        "grant_types_supported": ["authorization_code", "client_credentials", "password"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


# =============================================================================
# Authentication API: /oauth/token
# =============================================================================

@app.post("/oauth/token")
async def oauth_token(request: Request, body: TokenRequest):
    state = get_state(request)
    now = int(time.time())

    if body.grant_type == "client_credentials":
        token_payload = {
            "iss": ISSUER,
            "sub": f"{body.client_id}@clients",
            "aud": body.audience or "https://api.doubleagent.local",
            "iat": now,
            "exp": now + 86400,
            "scope": body.scope or "",
            "gty": "client-credentials",
            "azp": body.client_id,
        }
        return {
            "access_token": _sign_token(token_payload),
            "token_type": "Bearer",
            "expires_in": 86400,
            "scope": body.scope or "",
        }

    elif body.grant_type == "password":
        user = None
        for u in state.list_all("users"):
            if u.get("email") == body.username:
                user = u
                break
        if not user:
            return _api_error(403, "Forbidden", "Wrong email or password.")

        token_payload = {
            "iss": ISSUER,
            "sub": user["user_id"],
            "aud": body.audience or "https://api.doubleagent.local",
            "iat": now,
            "exp": now + 86400,
            "scope": body.scope or "openid profile email",
            "azp": body.client_id,
        }
        id_token_payload = {
            "iss": ISSUER,
            "sub": user["user_id"],
            "aud": body.client_id,
            "iat": now,
            "exp": now + 86400,
            "email": user.get("email"),
            "email_verified": user.get("email_verified", False),
            "name": user.get("name"),
            "nickname": user.get("nickname"),
        }
        return {
            "access_token": _sign_token(token_payload),
            "id_token": _sign_token(id_token_payload),
            "token_type": "Bearer",
            "expires_in": 86400,
            "scope": body.scope or "openid profile email",
        }

    return _api_error(400, "Bad Request", f"Unsupported grant_type: {body.grant_type}")


# =============================================================================
# Authentication API: /userinfo
# =============================================================================

@app.get("/userinfo")
async def userinfo(request: Request, authorization: Optional[str] = Header(None)):
    token = _get_bearer_token(authorization)
    if not token:
        return _api_error(401, "Unauthorized", "Missing or invalid bearer token")

    try:
        _pub_pem = _public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        payload = jwt.decode(token, _pub_pem, algorithms=["RS256"],
                             options={"verify_aud": False})
    except jwt.PyJWTError:
        return _api_error(401, "Unauthorized", "Invalid token")

    sub = payload.get("sub", "")
    state = get_state(request)
    user = state.get("users", sub)
    if not user:
        return {"sub": sub}

    return {
        "sub": user["user_id"],
        "email": user.get("email"),
        "email_verified": user.get("email_verified", False),
        "name": user.get("name"),
        "nickname": user.get("nickname"),
        "given_name": user.get("given_name"),
        "family_name": user.get("family_name"),
    }


# =============================================================================
# Management API: Users
# =============================================================================

@app.get("/api/v2/users")
async def list_users(
    request: Request,
    authorization: Optional[str] = Header(None),
    page: int = Query(default=0),
    per_page: int = Query(default=50),
    q: Optional[str] = Query(default=None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    users = state.list_all("users")

    if q:
        users = [u for u in users if q.lower() in json.dumps(u).lower()]

    start = page * per_page
    return users[start : start + per_page]


# --- Role <-> User assignments (must be declared BEFORE {user_id:path}) -------

@app.post("/api/v2/users/{user_id}/roles")
async def assign_roles_to_user(
    request: Request,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    user = state.get("users", user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")

    body = await request.json()
    role_ids = body.get("roles", [])

    existing = user.get("roles", [])
    existing.extend(role_ids)
    user["roles"] = list(set(existing))
    state.put("users", user_id, user)
    return Response(status_code=204)


@app.get("/api/v2/users/{user_id}/roles")
async def get_user_roles(
    request: Request,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    user = state.get("users", user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")

    role_ids = user.get("roles", [])
    roles = [state.get("roles", rid) for rid in role_ids if state.get("roles", rid)]
    return roles


# --- Generic user routes (after sub-resource routes) -------------------------

@app.get("/api/v2/users/{user_id}")
async def get_user(
    request: Request,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    user = state.get("users", user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")
    return user


@app.post("/api/v2/users")
async def create_user(
    request: Request,
    body: CreateUserRequest,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)

    # Check duplicate email
    for u in state.list_all("users"):
        if u.get("email") == body.email:
            return _api_error(409, "Conflict", "The user already exists.")

    user_id = f"auth0|{uuid.uuid4().hex[:24]}"
    now = _iso_now()
    user = {
        "user_id": user_id,
        "email": body.email,
        "email_verified": body.email_verified,
        "name": body.name or body.email,
        "nickname": body.nickname or body.email.split("@")[0],
        "given_name": body.given_name or "",
        "family_name": body.family_name or "",
        "connection": body.connection,
        "blocked": body.blocked,
        "created_at": now,
        "updated_at": now,
        "user_metadata": body.user_metadata or {},
        "app_metadata": body.app_metadata or {},
        "identities": [{
            "connection": body.connection,
            "user_id": user_id.split("|")[-1],
            "provider": "auth0",
            "isSocial": False,
        }],
    }
    state.put("users", user_id, user)

    await _dispatch_event(request, "user.created", {"user": user})
    return JSONResponse(status_code=201, content=user)


@app.patch("/api/v2/users/{user_id}")
async def update_user(
    request: Request,
    user_id: str,
    body: UpdateUserRequest,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    user = state.get("users", user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")

    update_data = body.model_dump(exclude_none=True)
    user.update(update_data)
    user["updated_at"] = _iso_now()
    state.put("users", user_id, user)

    await _dispatch_event(request, "user.updated", {"user": user})
    return user


@app.delete("/api/v2/users/{user_id}")
async def delete_user(
    request: Request,
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    user = state.get("users", user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")
    state.delete("users", user_id)
    return Response(status_code=204)


# =============================================================================
# Management API: Roles
# =============================================================================

@app.get("/api/v2/roles")
async def list_roles(
    request: Request,
    authorization: Optional[str] = Header(None),
    page: int = Query(default=0),
    per_page: int = Query(default=50),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    roles = state.list_all("roles")
    start = page * per_page
    return roles[start : start + per_page]


@app.get("/api/v2/roles/{role_id}")
async def get_role(
    request: Request,
    role_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    role = state.get("roles", role_id)
    if not role:
        return _api_error(404, "Not Found", f"Role {role_id} not found")
    return role


@app.post("/api/v2/roles")
async def create_role(
    request: Request,
    body: CreateRoleRequest,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)

    # Check duplicate name
    for r in state.list_all("roles"):
        if r.get("name") == body.name:
            return _api_error(409, "Conflict", "Role already exists.")

    role_id = f"rol_{uuid.uuid4().hex[:24]}"
    role = {"id": role_id, "name": body.name, "description": body.description or ""}
    state.put("roles", role_id, role)
    return JSONResponse(status_code=200, content=role)


@app.delete("/api/v2/roles/{role_id}")
async def delete_role(
    request: Request,
    role_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    if not state.get("roles", role_id):
        return _api_error(404, "Not Found", f"Role {role_id} not found")
    state.delete("roles", role_id)
    return JSONResponse(status_code=200, content=None)


# =============================================================================
# Management API: Connections
# =============================================================================

@app.get("/api/v2/connections")
async def list_connections(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    state = get_state(request)
    return state.list_all("connections")


# =============================================================================
# Events / Webhooks
# =============================================================================

async def _dispatch_event(request: Request, event_type: str, payload: dict) -> None:
    state = get_state(request)
    ns = get_namespace(request)
    webhooks = state.list_all("webhooks")
    for wh in webhooks:
        if not wh.get("active", True):
            continue
        await webhook_sim.deliver(
            target_url=wh["url"],
            event_type=event_type,
            payload=payload,
            namespace=ns,
        )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8085))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
