"""Webhook delivery simulator with retry, HMAC signatures, and audit log.

Replaces fire-and-forget webhook delivery with a production-grade
simulator that supports:

- Configurable retry with exponential backoff
- HMAC-SHA256 signature generation (``X-Hub-Signature-256``)
- Localhost-only delivery allowlist (hardened default)
- Queryable delivery log via ``/_doubleagent/webhooks``
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class WebhookDelivery:
    """Record of a single webhook delivery attempt (or series of retries)."""

    id: str
    event_type: str
    payload: dict[str, Any]
    target_url: str
    namespace: str
    status: str = "pending"  # pending | delivered | failed
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


# ---------------------------------------------------------------------------
# Allowlist helpers
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _is_target_allowed(url: str, allowed_hosts: set[str]) -> bool:
    """Check if *url* resolves to an allowed host."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if hostname in allowed_hosts:
        return True
    # Also allow any private/loopback IP
    try:
        addr = ip_address(hostname)
        return addr.is_loopback or addr.is_private
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------

def _compute_signature(payload: dict[str, Any], secret: str | None) -> str | None:
    """Compute HMAC-SHA256 signature for *payload*.  Returns None if no secret."""
    if not secret:
        return None
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        """Schedule delivery of a webhook.  Returns the delivery record."""
        delivery = WebhookDelivery(
            id=uuid.uuid4().hex[:16],
            event_type=event_type,
            payload=payload,
            target_url=target_url,
            namespace=namespace,
        )
        self._deliveries.append(delivery)

        # Check allowlist
        if not _is_target_allowed(target_url, self.allowed_hosts):
            delivery.status = "failed"
            delivery.error = f"target host not in allowlist: {urlparse(target_url).hostname}"
            return delivery

        # Fire in background
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
        """Query the delivery log.  Most recent first."""
        results = self._deliveries
        if namespace:
            results = [d for d in results if d.namespace == namespace]
        if event_type:
            results = [d for d in results if d.event_type == event_type]
        return [d.to_dict() for d in reversed(results[-limit:])]

    def clear(self) -> None:
        """Clear the delivery log."""
        self._deliveries.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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

            # Retry with backoff
            if attempt < self.max_retries - 1:
                delay = (
                    self.retry_delays[attempt]
                    if attempt < len(self.retry_delays)
                    else self.retry_delays[-1]
                )
                await asyncio.sleep(delay)

        delivery.status = "failed"
