"""Contract tests for Descope Authentication API (tokens, OTP, JWKS)."""

import httpx
import jwt
import uuid

SERVICE_URL = __import__("os").environ["DOUBLEAGENT_DESCOPE_URL"]


class TestAccessKeyExchange:
    def test_exchange_access_key(self, base_url, mgmt_headers):
        # Seed an access key
        httpx.post(
            f"{base_url}/_doubleagent/seed",
            json={
                "access_keys": [
                    {"id": "AK_test_key", "name": "ci-key", "userId": "U_svc", "roleNames": ["admin"]},
                ]
            },
        )

        resp = httpx.post(
            f"{base_url}/v1/auth/accesskey/exchange",
            json={"loginId": "AK_test_key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "sessionJwt" in data
        assert "refreshJwt" in data

    def test_exchange_invalid_key(self, base_url):
        resp = httpx.post(
            f"{base_url}/v1/auth/accesskey/exchange",
            json={"loginId": "nonexistent-key"},
        )
        assert resp.status_code == 401

    def test_session_jwt_verifiable_via_jwks(self, base_url, mgmt_headers):
        # Seed key
        httpx.post(
            f"{base_url}/_doubleagent/seed",
            json={"access_keys": [{"id": "AK_jwks_test", "name": "jwks-key"}]},
        )

        # Exchange
        exchange_resp = httpx.post(
            f"{base_url}/v1/auth/accesskey/exchange",
            json={"loginId": "AK_jwks_test"},
        )
        session_jwt = exchange_resp.json()["sessionJwt"]

        # Fetch JWKS
        jwks_resp = httpx.get(f"{base_url}/v2/keys/P_doubleagent")
        jwks_data = jwks_resp.json()
        assert len(jwks_data["keys"]) >= 1

        # Verify the JWT using the JWK
        key = jwks_data["keys"][0]
        from jwt.algorithms import RSAAlgorithm
        public_key = RSAAlgorithm.from_jwk(key)
        payload = jwt.decode(session_jwt, public_key, algorithms=["RS256"], options={"verify_aud": False})
        assert "sub" in payload
        assert "iss" in payload


class TestOTPFlow:
    def test_otp_signup_and_verify(self, base_url):
        login_id = f"otp-{uuid.uuid4().hex[:8]}@example.com"

        # Sign up
        resp = httpx.post(
            f"{base_url}/v1/auth/otp/sign-up/email",
            json={"loginId": login_id},
        )
        assert resp.json()["ok"] is True
        assert "maskedEmail" in resp.json()

        # Verify (fake accepts any code)
        verify_resp = httpx.post(
            f"{base_url}/v1/auth/otp/verify/email",
            json={"loginId": login_id, "code": "123456"},
        )
        assert verify_resp.json()["ok"] is True
        assert "sessionJwt" in verify_resp.json()
        assert verify_resp.json()["user"]["email"] == login_id

    def test_otp_signin(self, base_url, mgmt_headers):
        login_id = f"otp-in-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(
            f"{base_url}/v1/mgmt/user/create",
            json={"loginId": login_id, "email": login_id},
            headers=mgmt_headers,
        )

        resp = httpx.post(
            f"{base_url}/v1/auth/otp/sign-in/email",
            json={"loginId": login_id},
        )
        assert resp.json()["ok"] is True

    def test_otp_signin_nonexistent_user(self, base_url):
        resp = httpx.post(
            f"{base_url}/v1/auth/otp/sign-in/email",
            json={"loginId": "ghost@example.com"},
        )
        assert resp.status_code == 404

    def test_otp_signup_duplicate_rejected(self, base_url):
        login_id = f"otp-dup-{uuid.uuid4().hex[:8]}@example.com"
        httpx.post(f"{base_url}/v1/auth/otp/sign-up/email", json={"loginId": login_id})
        resp = httpx.post(f"{base_url}/v1/auth/otp/sign-up/email", json={"loginId": login_id})
        assert resp.status_code == 409
