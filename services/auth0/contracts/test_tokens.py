"""
Contract tests for Auth0 Authentication API: token issuance, JWKS, userinfo.
"""

import httpx
import jwt
import uuid
from jwt import PyJWKClient

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_AUTH0_URL"]


class TestClientCredentials:
    def test_client_credentials_returns_access_token(self, base_url):
        resp = httpx.post(
            f"{base_url}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": "my-app",
                "client_secret": "secret",
                "audience": "https://api.example.com",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"

    def test_token_verifiable_via_jwks(self, base_url):
        # Get token
        token_resp = httpx.post(
            f"{base_url}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": "my-app",
                "client_secret": "secret",
                "audience": "https://api.example.com",
            },
        )
        access_token = token_resp.json()["access_token"]

        # Get JWKS
        jwks_resp = httpx.get(f"{base_url}/.well-known/jwks.json")
        assert jwks_resp.status_code == 200
        jwks_data = jwks_resp.json()
        assert len(jwks_data["keys"]) >= 1

        # Verify token with JWKS
        jwk_client = PyJWKClient(f"{base_url}/.well-known/jwks.json")
        signing_key = jwk_client.get_signing_key_from_jwt(access_token)
        decoded = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["RS256"],
            audience="https://api.example.com",
        )
        assert decoded["sub"] == "my-app@clients"


class TestROPCFlow:
    def test_password_grant_with_seeded_user(self, base_url, mgmt_headers):
        # Seed a user first
        email = f"ropc-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication", "name": "Test User"},
            headers=mgmt_headers,
        )

        # Get token via ROPC
        resp = httpx.post(
            f"{base_url}/oauth/token",
            json={
                "grant_type": "password",
                "client_id": "my-app",
                "username": email,
                "password": "fake-password",
                "audience": "https://api.example.com",
                "scope": "openid profile email",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "id_token" in data

    def test_password_grant_wrong_email_fails(self, base_url):
        resp = httpx.post(
            f"{base_url}/oauth/token",
            json={
                "grant_type": "password",
                "client_id": "my-app",
                "username": "nonexistent@example.com",
                "password": "whatever",
            },
        )
        assert resp.status_code == 403


class TestUserinfo:
    def test_userinfo_with_valid_token(self, base_url, mgmt_headers):
        # Seed user
        email = f"info-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(
            f"{base_url}/api/v2/users",
            json={"email": email, "connection": "Username-Password-Authentication", "name": "Info User"},
            headers=mgmt_headers,
        )

        # Get token
        token_resp = httpx.post(
            f"{base_url}/oauth/token",
            json={
                "grant_type": "password",
                "client_id": "my-app",
                "username": email,
                "password": "pw",
            },
        )
        access_token = token_resp.json()["access_token"]

        # Call userinfo
        resp = httpx.get(
            f"{base_url}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == email


class TestOpenIDConfiguration:
    def test_openid_config_endpoint(self, base_url):
        resp = httpx.get(f"{base_url}/.well-known/openid-configuration")
        assert resp.status_code == 200
        data = resp.json()
        assert "issuer" in data
        assert "jwks_uri" in data
        assert "token_endpoint" in data
