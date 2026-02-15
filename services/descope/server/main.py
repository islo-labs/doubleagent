"""
Descope Authentication & User Management API Fake — DoubleAgent Service

Fakes the Descope Management API and Authentication API:
- Users, Tenants, Roles, Permissions (Management API via POST /v1/mgmt/...)
- Access key exchange, OTP simulation (Auth API via POST /v1/auth/...)
- JWKS endpoint at /v2/keys/{project_id}
- COW state, namespace isolation, webhook simulator

Descope API quirks vs Auth0:
- Almost all endpoints are POST (even reads like "load user")
- Auth uses Bearer with project_id for management, access keys for M2M
- Tenants are first-class; roles can be tenant-scoped
- User IDs are Descope-generated (U...) not provider-prefixed
"""

import base64
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response

from doubleagent_sdk import NamespaceRouter, StateOverlay, WebhookSimulator
from doubleagent_sdk.namespace import DEFAULT_NAMESPACE, NAMESPACE_HEADER

# =============================================================================
# RSA key pair (generated once at startup)
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

PROJECT_ID = os.environ.get("DESCOPE_PROJECT_ID", "P_doubleagent")
ISSUER = f"https://api.descope.com/{PROJECT_ID}"


def _int_to_base64url(n: int) -> str:
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


def _sign_token(payload: dict) -> str:
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


def _descope_error(status: int, error_code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": False, "errorCode": error_code, "errorDescription": message, "errorMessage": message},
    )


def _ok_response(data: dict | list | None = None) -> dict:
    if data is None:
        return {"ok": True}
    return {"ok": True, **data} if isinstance(data, dict) else {"ok": True, "data": data}


def _get_bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _gen_user_id() -> str:
    return f"U{uuid.uuid4().hex[:24]}"


def _gen_tenant_id() -> str:
    return f"T{uuid.uuid4().hex[:16]}"


# =============================================================================
# Pydantic Models
# =============================================================================

class SeedData(BaseModel):
    users: list[dict[str, Any]] = []
    tenants: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []
    permissions: list[dict[str, Any]] = []
    access_keys: list[dict[str, Any]] = []


class BootstrapData(BaseModel):
    users: dict[str, Any] = {}
    tenants: dict[str, Any] = {}
    roles: dict[str, Any] = {}
    permissions: dict[str, Any] = {}
    access_keys: dict[str, Any] = {}


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Descope API Fake",
    description="DoubleAgent fake of the Descope Authentication & Management APIs",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# /_doubleagent control plane
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
            uid = u.get("userId") or _gen_user_id()
            state.put("users", uid, _build_user(uid, u))
        seeded["users"] = len(data.users)

    if data.tenants:
        for t in data.tenants:
            tid = t.get("id") or _gen_tenant_id()
            state.put("tenants", tid, {
                "id": tid,
                "name": t.get("name", tid),
                "selfProvisioningDomains": t.get("selfProvisioningDomains", []),
                "customAttributes": t.get("customAttributes", {}),
            })
        seeded["tenants"] = len(data.tenants)

    if data.roles:
        for r in data.roles:
            name = r.get("name", "")
            state.put("roles", name, {
                "name": name,
                "description": r.get("description", ""),
                "permissionNames": r.get("permissionNames", []),
                "tenantId": r.get("tenantId", ""),
            })
        seeded["roles"] = len(data.roles)

    if data.permissions:
        for p in data.permissions:
            name = p.get("name", "")
            state.put("permissions", name, {
                "name": name,
                "description": p.get("description", ""),
            })
        seeded["permissions"] = len(data.permissions)

    if data.access_keys:
        for ak in data.access_keys:
            kid = ak.get("id") or f"AK{uuid.uuid4().hex[:20]}"
            state.put("access_keys", kid, {
                "id": kid,
                "name": ak.get("name", ""),
                "userId": ak.get("userId", ""),
                "tenantId": ak.get("tenantId", ""),
                "roleNames": ak.get("roleNames", []),
                "createdTime": int(time.time()),
                "expireTime": ak.get("expireTime", 0),
                "status": "active",
            })
        seeded["access_keys"] = len(data.access_keys)

    return {"status": "ok", "seeded": seeded, "namespace": ns}


@app.post("/_doubleagent/bootstrap")
async def bootstrap(data: BootstrapData):
    baseline: dict[str, dict[str, Any]] = {}
    for rtype in ("users", "tenants", "roles", "permissions", "access_keys"):
        d = getattr(data, rtype, {})
        if d:
            baseline[rtype] = d
    router.load_baseline(baseline)
    counts = {k: len(v) for k, v in baseline.items()}
    return {"status": "ok", "loaded": counts}


@app.get("/_doubleagent/info")
async def info(request: Request):
    state = get_state(request)
    return {"name": "descope", "version": "1.0", "namespace": get_namespace(request), "state": state.stats()}


@app.get("/_doubleagent/webhooks")
async def list_webhook_deliveries(request: Request, event_type: Optional[str] = None, limit: int = 100):
    return webhook_sim.get_deliveries(namespace=get_namespace(request), event_type=event_type, limit=limit)


@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    return router.list_namespaces()


# =============================================================================
# JWKS
# =============================================================================

@app.get("/v2/keys/{project_id}")
async def jwks_endpoint(project_id: str):
    return JWKS


# =============================================================================
# Auth API: Access Key Exchange (M2M)
# =============================================================================

@app.post("/v1/auth/accesskey/exchange")
async def access_key_exchange(request: Request):
    body = await request.json()
    access_key = body.get("loginId", "")

    state = get_state(request)
    ak = state.get("access_keys", access_key)
    if not ak:
        # Also search by name
        for k in state.list_all("access_keys"):
            if k.get("name") == access_key or k.get("id") == access_key:
                ak = k
                break
    if not ak:
        return _descope_error(401, "E062108", "Access key not found or inactive")

    now = int(time.time())
    token_payload = {
        "iss": ISSUER,
        "sub": ak.get("userId", ak["id"]),
        "iat": now,
        "exp": now + 86400,
        "tenants": {},
        "permissions": [],
        "roles": ak.get("roleNames", []),
    }
    # Add tenant-scoped permissions if tenant is specified
    if ak.get("tenantId"):
        token_payload["tenants"] = {
            ak["tenantId"]: {"roles": ak.get("roleNames", []), "permissions": []}
        }

    session_jwt = _sign_token(token_payload)
    return _ok_response({
        "sessionJwt": session_jwt,
        "refreshJwt": _sign_token({**token_payload, "exp": now + 86400 * 30}),
        "cookieDomain": "",
        "cookiePath": "/",
        "cookieMaxAge": 86400,
        "cookieExpiration": now + 86400,
    })


# =============================================================================
# Auth API: OTP (simulated -- always succeeds)
# =============================================================================

@app.post("/v1/auth/otp/sign-up/email")
async def otp_signup_email(request: Request):
    body = await request.json()
    login_id = body.get("loginId", "")
    state = get_state(request)

    # Create user if not exists
    existing = None
    for u in state.list_all("users"):
        if u.get("email") == login_id or u.get("loginIds", [None])[0] == login_id:
            existing = u
            break

    if existing:
        return _descope_error(409, "E062107", "User already exists")

    uid = _gen_user_id()
    user = _build_user(uid, {"email": login_id, "loginId": login_id, **(body.get("user") or {})})
    state.put("users", uid, user)

    # In the fake, OTP is "sent" immediately -- the code is always "123456"
    return _ok_response({"maskedEmail": _mask_email(login_id), "pendingRef": uuid.uuid4().hex})


@app.post("/v1/auth/otp/sign-in/email")
async def otp_signin_email(request: Request):
    body = await request.json()
    login_id = body.get("loginId", "")
    state = get_state(request)

    user = _find_user_by_login(state, login_id)
    if not user:
        return _descope_error(404, "E062108", "User not found")

    return _ok_response({"maskedEmail": _mask_email(login_id), "pendingRef": uuid.uuid4().hex})


@app.post("/v1/auth/otp/verify/email")
async def otp_verify_email(request: Request):
    body = await request.json()
    login_id = body.get("loginId", "")
    code = body.get("code", "")

    # The fake accepts any code (or specifically "123456")
    state = get_state(request)
    user = _find_user_by_login(state, login_id)
    if not user:
        return _descope_error(404, "E062108", "User not found")

    now = int(time.time())
    session = _build_session_token(user, now)
    return _ok_response(session)


# =============================================================================
# Management API: Users
# =============================================================================

@app.post("/v1/mgmt/user/create")
async def mgmt_create_user(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    login_id = body.get("loginId", body.get("email", ""))
    email = body.get("email", login_id)

    # Duplicate check
    for u in state.list_all("users"):
        if login_id in u.get("loginIds", []) or u.get("email") == email:
            return _descope_error(409, "E062107", "User already exists")

    uid = _gen_user_id()
    user = _build_user(uid, {**body, "email": email, "loginId": login_id})
    state.put("users", uid, user)

    await _dispatch_event(request, "user.created", {"user": user})
    return _ok_response({"user": user})


@app.post("/v1/mgmt/user/load")
async def mgmt_load_user(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    user_id = body.get("userId", "")
    login_id = body.get("loginId", "")

    if user_id:
        user = state.get("users", user_id)
    elif login_id:
        user = _find_user_by_login(state, login_id)
    else:
        return _descope_error(400, "E062101", "Must provide userId or loginId")

    if not user:
        return _descope_error(404, "E062108", "User not found")
    return _ok_response({"user": user})


@app.post("/v1/mgmt/user/search")
async def mgmt_search_users(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    limit = body.get("limit", 100)
    page = body.get("page", 0)
    tenant_ids = body.get("tenantIds", [])
    role_names = body.get("roleNames", [])

    users = state.list_all("users")

    if tenant_ids:
        users = [u for u in users if any(t in u.get("userTenants", []) for t in tenant_ids)]
    if role_names:
        users = [u for u in users if any(r in u.get("roleNames", []) for r in role_names)]

    total = len(users)
    start = page * limit
    return _ok_response({"users": users[start:start + limit], "total": total})


@app.post("/v1/mgmt/user/update")
async def mgmt_update_user(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    user_id = body.get("userId", "")
    login_id = body.get("loginId", "")

    if user_id:
        user = state.get("users", user_id)
    elif login_id:
        user = _find_user_by_login(state, login_id)
    else:
        return _descope_error(400, "E062101", "Must provide userId or loginId")

    if not user:
        return _descope_error(404, "E062108", "User not found")

    # Apply updates
    for field in ("name", "email", "phone", "displayName", "givenName", "familyName"):
        if field in body:
            user[field] = body[field]
    if "customAttributes" in body:
        user["customAttributes"] = body["customAttributes"]
    if "roleNames" in body:
        user["roleNames"] = body["roleNames"]
    if "tenants" in body:
        user["userTenants"] = [t.get("tenantId", t) if isinstance(t, dict) else t for t in body["tenants"]]

    state.put("users", user["userId"], user)
    await _dispatch_event(request, "user.updated", {"user": user})
    return _ok_response({"user": user})


@app.post("/v1/mgmt/user/delete")
async def mgmt_delete_user(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    user_id = body.get("userId", "")
    login_id = body.get("loginId", "")

    if user_id:
        user = state.get("users", user_id)
    elif login_id:
        user = _find_user_by_login(state, login_id)
        user_id = user["userId"] if user else ""
    else:
        return _descope_error(400, "E062101", "Must provide userId or loginId")

    if not user:
        return _descope_error(404, "E062108", "User not found")

    state.delete("users", user_id)
    return _ok_response()


@app.post("/v1/mgmt/user/addrole")
async def mgmt_add_role_to_user(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    user_id = body.get("userId", "")
    login_id = body.get("loginId", "")
    role_names = body.get("roleNames", [])
    tenant_id = body.get("tenantId", "")

    if user_id:
        user = state.get("users", user_id)
    elif login_id:
        user = _find_user_by_login(state, login_id)
    else:
        return _descope_error(400, "E062101", "Must provide userId or loginId")

    if not user:
        return _descope_error(404, "E062108", "User not found")

    existing = set(user.get("roleNames", []))
    existing.update(role_names)
    user["roleNames"] = list(existing)

    if tenant_id and tenant_id not in user.get("userTenants", []):
        user.setdefault("userTenants", []).append(tenant_id)

    state.put("users", user["userId"], user)
    return _ok_response()


@app.post("/v1/mgmt/user/addtenant")
async def mgmt_add_tenant_to_user(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    user_id = body.get("userId", "")
    login_id = body.get("loginId", "")
    tenant_id = body.get("tenantId", "")

    if user_id:
        user = state.get("users", user_id)
    elif login_id:
        user = _find_user_by_login(state, login_id)
    else:
        return _descope_error(400, "E062101", "Must provide userId or loginId")

    if not user:
        return _descope_error(404, "E062108", "User not found")

    tenants = set(user.get("userTenants", []))
    tenants.add(tenant_id)
    user["userTenants"] = list(tenants)
    state.put("users", user["userId"], user)
    return _ok_response()


# =============================================================================
# Management API: Tenants
# =============================================================================

@app.post("/v1/mgmt/tenant/create")
async def mgmt_create_tenant(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    tid = body.get("id") or _gen_tenant_id()
    name = body.get("name", tid)

    if state.get("tenants", tid):
        return _descope_error(409, "E062305", "Tenant already exists")

    tenant = {
        "id": tid,
        "name": name,
        "selfProvisioningDomains": body.get("selfProvisioningDomains", []),
        "customAttributes": body.get("customAttributes", {}),
    }
    state.put("tenants", tid, tenant)
    return _ok_response({"id": tid})


@app.post("/v1/mgmt/tenant/load")
async def mgmt_load_tenant(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    tid = body.get("id", "")
    tenant = state.get("tenants", tid)
    if not tenant:
        return _descope_error(404, "E062306", "Tenant not found")
    return _ok_response({"tenant": tenant})


@app.post("/v1/mgmt/tenant/loadall")
async def mgmt_load_all_tenants(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    state = get_state(request)
    return _ok_response({"tenants": state.list_all("tenants")})


@app.post("/v1/mgmt/tenant/update")
async def mgmt_update_tenant(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    tid = body.get("id", "")
    tenant = state.get("tenants", tid)
    if not tenant:
        return _descope_error(404, "E062306", "Tenant not found")

    if "name" in body:
        tenant["name"] = body["name"]
    if "selfProvisioningDomains" in body:
        tenant["selfProvisioningDomains"] = body["selfProvisioningDomains"]
    if "customAttributes" in body:
        tenant["customAttributes"] = body["customAttributes"]

    state.put("tenants", tid, tenant)
    return _ok_response()


@app.post("/v1/mgmt/tenant/delete")
async def mgmt_delete_tenant(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    tid = body.get("id", "")
    if not state.get("tenants", tid):
        return _descope_error(404, "E062306", "Tenant not found")
    state.delete("tenants", tid)
    return _ok_response()


# =============================================================================
# Management API: Roles
# =============================================================================

@app.post("/v1/mgmt/role/create")
async def mgmt_create_role(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    name = body.get("name", "")
    if state.get("roles", name):
        return _descope_error(409, "E062205", "Role already exists")

    role = {
        "name": name,
        "description": body.get("description", ""),
        "permissionNames": body.get("permissionNames", []),
        "tenantId": body.get("tenantId", ""),
    }
    state.put("roles", name, role)
    return _ok_response()


@app.post("/v1/mgmt/role/loadall")
async def mgmt_load_all_roles(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    state = get_state(request)
    return _ok_response({"roles": state.list_all("roles")})


@app.post("/v1/mgmt/role/delete")
async def mgmt_delete_role(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    name = body.get("name", "")
    if not state.get("roles", name):
        return _descope_error(404, "E062206", "Role not found")
    state.delete("roles", name)
    return _ok_response()


# =============================================================================
# Management API: Permissions
# =============================================================================

@app.post("/v1/mgmt/permission/create")
async def mgmt_create_permission(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    name = body.get("name", "")
    state.put("permissions", name, {
        "name": name,
        "description": body.get("description", ""),
    })
    return _ok_response()


@app.post("/v1/mgmt/permission/loadall")
async def mgmt_load_all_permissions(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    state = get_state(request)
    return _ok_response({"permissions": state.list_all("permissions")})


# =============================================================================
# Management API: Access Keys
# =============================================================================

@app.post("/v1/mgmt/accesskey/create")
async def mgmt_create_access_key(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    kid = f"AK{uuid.uuid4().hex[:20]}"
    cleartext = f"dsk_{uuid.uuid4().hex}"  # simulated cleartext key
    ak = {
        "id": kid,
        "name": body.get("name", ""),
        "userId": body.get("userId", ""),
        "tenantId": body.get("tenantId", ""),
        "roleNames": body.get("roleNames", []),
        "createdTime": int(time.time()),
        "expireTime": body.get("expireTime", 0),
        "status": "active",
    }
    state.put("access_keys", kid, ak)
    return _ok_response({"key": {**ak, "cleartext": cleartext}})


@app.post("/v1/mgmt/accesskey/search")
async def mgmt_search_access_keys(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    keys = state.list_all("access_keys")
    tenant_ids = body.get("tenantIds", [])
    if tenant_ids:
        keys = [k for k in keys if k.get("tenantId") in tenant_ids]
    return _ok_response({"keys": keys})


@app.post("/v1/mgmt/accesskey/delete")
async def mgmt_delete_access_key(request: Request, authorization: Optional[str] = Header(None)):
    if not _get_bearer(authorization):
        return _descope_error(401, "E011001", "Unauthorized")
    body = await request.json()
    state = get_state(request)

    kid = body.get("id", "")
    if not state.get("access_keys", kid):
        return _descope_error(404, "E062401", "Access key not found")
    state.delete("access_keys", kid)
    return _ok_response()


# =============================================================================
# Internal helpers
# =============================================================================

def _build_user(uid: str, data: dict) -> dict:
    login_id = data.get("loginId", data.get("email", ""))
    return {
        "userId": uid,
        "loginIds": [login_id] if login_id else [],
        "name": data.get("name", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "verifiedEmail": data.get("verifiedEmail", False),
        "verifiedPhone": data.get("verifiedPhone", False),
        "displayName": data.get("displayName", data.get("name", "")),
        "givenName": data.get("givenName", ""),
        "familyName": data.get("familyName", ""),
        "roleNames": data.get("roleNames", []),
        "userTenants": data.get("userTenants", []),
        "customAttributes": data.get("customAttributes", {}),
        "status": "enabled",
        "createdTime": int(time.time()),
        "picture": data.get("picture", ""),
    }


def _find_user_by_login(state: StateOverlay, login_id: str) -> dict | None:
    for u in state.list_all("users"):
        if login_id in u.get("loginIds", []):
            return u
        if u.get("email") == login_id:
            return u
    return None


def _build_session_token(user: dict, now: int) -> dict:
    token_payload = {
        "iss": ISSUER,
        "sub": user["userId"],
        "iat": now,
        "exp": now + 86400,
        "tenants": {t: {"roles": user.get("roleNames", []), "permissions": []}
                    for t in user.get("userTenants", [])},
        "roles": user.get("roleNames", []),
        "permissions": [],
        "email": user.get("email", ""),
    }
    return {
        "sessionJwt": _sign_token(token_payload),
        "refreshJwt": _sign_token({**token_payload, "exp": now + 86400 * 30}),
        "user": user,
        "firstSeen": False,
    }


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"**@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


async def _dispatch_event(request: Request, event_type: str, payload: dict) -> None:
    state = get_state(request)
    ns = get_namespace(request)
    for wh in state.list_all("webhooks"):
        if wh.get("active", True):
            await webhook_sim.deliver(
                target_url=wh["url"], event_type=event_type, payload=payload, namespace=ns,
            )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8087))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
