"""
Auth0 Management & Authentication API Fake — DoubleAgent Service

Fakes both the Auth0 Management API (v2) and Authentication API:
- Users, Roles, Connections (CRUD via Management API)
- /oauth/token, /userinfo (Authentication flows)
- JWKS endpoint for local token verification
- OpenID Connect discovery
"""

import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import Response


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
    return jwt.encode(payload, _private_pem, algorithm="RS256", headers={"kid": _kid})


# =============================================================================
# State
# =============================================================================

state: dict[str, dict[str, Any]] = {
    "users": {},
    "roles": {},
    "connections": {},
}
counters: dict[str, int] = {}


def _next_id(prefix: str) -> str:
    counters[prefix] = counters.get(prefix, 0) + 1
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _initial_state() -> dict[str, dict[str, Any]]:
    return {"users": {}, "roles": {}, "connections": {}}


# =============================================================================
# Helpers
# =============================================================================

def _api_error(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"statusCode": status, "error": error, "message": message},
    )


def _get_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


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
    connections: list[dict[str, Any]] = []


# =============================================================================
# App
# =============================================================================

app = FastAPI(
    title="Auth0 Management & Authentication API Fake",
    description="DoubleAgent fake of the Auth0 APIs",
    version="1.0.0",
)


# =============================================================================
# /_doubleagent endpoints
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    global state, counters
    state = _initial_state()
    counters.clear()
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(data: SeedData):
    seeded: dict[str, int] = {}

    if data.users:
        for u in data.users:
            user_id = u.get("user_id") or f"auth0|{uuid.uuid4().hex[:24]}"
            now = _iso_now()
            state["users"][user_id] = {
                "user_id": user_id,
                "email": u.get("email", f"{user_id}@doubleagent.local"),
                "email_verified": u.get("email_verified", False),
                "name": u.get("name", ""),
                "nickname": u.get("nickname", ""),
                "given_name": u.get("given_name", ""),
                "family_name": u.get("family_name", ""),
                "connection": u.get("connection", "Username-Password-Authentication"),
                "blocked": u.get("blocked", False),
                "created_at": u.get("created_at", now),
                "updated_at": now,
                "user_metadata": u.get("user_metadata", {}),
                "app_metadata": u.get("app_metadata", {}),
                "identities": [{"connection": u.get("connection", "Username-Password-Authentication"),
                                "user_id": user_id.split("|")[-1], "provider": "auth0", "isSocial": False}],
            }
        seeded["users"] = len(data.users)

    if data.roles:
        for r in data.roles:
            role_id = r.get("id") or f"rol_{uuid.uuid4().hex[:24]}"
            state["roles"][role_id] = {
                "id": role_id,
                "name": r.get("name", ""),
                "description": r.get("description", ""),
            }
        seeded["roles"] = len(data.roles)

    if data.connections:
        for c in data.connections:
            conn_id = c.get("id") or f"con_{uuid.uuid4().hex[:24]}"
            state["connections"][conn_id] = {
                "id": conn_id,
                "name": c.get("name", ""),
                "strategy": c.get("strategy", "auth0"),
                "enabled_clients": c.get("enabled_clients", []),
            }
        seeded["connections"] = len(data.connections)

    return {"status": "ok", "seeded": seeded}


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
async def oauth_token(body: TokenRequest):
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
        for u in state["users"].values():
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
async def userinfo(authorization: Optional[str] = Header(None)):
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
    user = state["users"].get(sub)
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
    authorization: Optional[str] = Header(None),
    page: int = Query(default=0),
    per_page: int = Query(default=50),
    q: Optional[str] = Query(default=None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    users = list(state["users"].values())

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
    user = state["users"].get(user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")

    body = await request.json()
    role_ids = body.get("roles", [])

    existing = user.get("roles", [])
    existing.extend(role_ids)
    user["roles"] = list(set(existing))
    return Response(status_code=204)


@app.get("/api/v2/users/{user_id}/roles")
async def get_user_roles(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    user = state["users"].get(user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")

    role_ids = user.get("roles", [])
    roles = [state["roles"][rid] for rid in role_ids if rid in state["roles"]]
    return roles


# --- Generic user routes (after sub-resource routes) -------------------------

@app.get("/api/v2/users/{user_id}")
async def get_user(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    user = state["users"].get(user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")
    return user


@app.post("/api/v2/users")
async def create_user(
    body: CreateUserRequest,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")

    # Check duplicate email
    for u in state["users"].values():
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
    state["users"][user_id] = user
    return JSONResponse(status_code=201, content=user)


@app.patch("/api/v2/users/{user_id}")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    user = state["users"].get(user_id)
    if not user:
        return _api_error(404, "Not Found", f"User {user_id} not found")

    update_data = body.model_dump(exclude_none=True)
    user.update(update_data)
    user["updated_at"] = _iso_now()
    return user


@app.delete("/api/v2/users/{user_id}")
async def delete_user(
    user_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    if user_id not in state["users"]:
        return _api_error(404, "Not Found", f"User {user_id} not found")
    del state["users"][user_id]
    return Response(status_code=204)


# =============================================================================
# Management API: Roles
# =============================================================================

@app.get("/api/v2/roles")
async def list_roles(
    authorization: Optional[str] = Header(None),
    page: int = Query(default=0),
    per_page: int = Query(default=50),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    roles = list(state["roles"].values())
    start = page * per_page
    return roles[start : start + per_page]


@app.get("/api/v2/roles/{role_id}")
async def get_role(
    role_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    role = state["roles"].get(role_id)
    if not role:
        return _api_error(404, "Not Found", f"Role {role_id} not found")
    return role


@app.post("/api/v2/roles")
async def create_role(
    body: CreateRoleRequest,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")

    for r in state["roles"].values():
        if r.get("name") == body.name:
            return _api_error(409, "Conflict", "Role already exists.")

    role_id = f"rol_{uuid.uuid4().hex[:24]}"
    role = {"id": role_id, "name": body.name, "description": body.description or ""}
    state["roles"][role_id] = role
    return JSONResponse(status_code=200, content=role)


@app.delete("/api/v2/roles/{role_id}")
async def delete_role(
    role_id: str,
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    if role_id not in state["roles"]:
        return _api_error(404, "Not Found", f"Role {role_id} not found")
    del state["roles"][role_id]
    return JSONResponse(status_code=200, content=None)


# =============================================================================
# Management API: Connections
# =============================================================================

@app.get("/api/v2/connections")
async def list_connections(
    authorization: Optional[str] = Header(None),
):
    if not _get_bearer_token(authorization):
        return _api_error(401, "Unauthorized", "Missing bearer token")
    return list(state["connections"].values())


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8085))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
