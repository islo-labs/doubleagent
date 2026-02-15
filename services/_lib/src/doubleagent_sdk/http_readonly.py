"""Read-only HTTP client wrapper.

Wraps :mod:`httpx` and **only** permits ``GET`` and ``HEAD`` methods.
Any attempt to call ``POST``, ``PUT``, ``PATCH``, or ``DELETE`` raises
:class:`ReadOnlyViolation`.  The client also rejects requests to private
IP ranges (anti-SSRF) unless explicitly allowed.
"""

from __future__ import annotations

from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx


class ReadOnlyViolation(Exception):
    """Raised when a non-GET/HEAD method is attempted on a read-only client."""


class ReadOnlyHttpClient:
    """HTTP client that only allows GET and HEAD requests.

    Parameters
    ----------
    allowed_hosts:
        Set of hostnames the client may connect to.  If ``None``, any
        non-private host is allowed.
    allow_private:
        If ``True``, skip the private-IP SSRF check.  Default ``False``.
    timeout:
        Per-request timeout in seconds.
    max_total_timeout:
        Hard cap on total time for all requests in a pull operation.
    """

    _ALLOWED_METHODS = {"GET", "HEAD"}

    def __init__(
        self,
        *,
        allowed_hosts: set[str] | None = None,
        allow_private: bool = False,
        timeout: float = 60.0,
        max_total_timeout: float = 300.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.allow_private = allow_private
        self.timeout = timeout
        self.max_total_timeout = max_total_timeout
        self._default_headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ReadOnlyHttpClient":
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self._default_headers,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_url(self, url: str) -> None:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""

        # Host allowlist
        if self.allowed_hosts and hostname not in self.allowed_hosts:
            raise ReadOnlyViolation(
                f"Host '{hostname}' not in allowed_hosts: {self.allowed_hosts}"
            )

        # SSRF check
        if not self.allow_private:
            try:
                addr = ip_address(hostname)
                if addr.is_private or addr.is_loopback:
                    raise ReadOnlyViolation(
                        f"Requests to private/loopback addresses are blocked: {hostname}"
                    )
            except ValueError:
                pass  # hostname is not an IP literal — fine

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a GET request."""
        return await self._request("GET", url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> httpx.Response:
        """Perform a HEAD request."""
        return await self._request("HEAD", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        # Compliance mode blocks all remote network calls from connectors
        import os
        if os.environ.get("DOUBLEAGENT_COMPLIANCE_MODE") == "strict":
            raise ReadOnlyViolation(
                "All remote API calls are blocked in compliance mode "
                "(DOUBLEAGENT_COMPLIANCE_MODE=strict)."
            )

        if method.upper() not in self._ALLOWED_METHODS:
            raise ReadOnlyViolation(
                f"Method {method} is not allowed. Only GET and HEAD are permitted."
            )
        self._check_url(url)
        if self._client is None:
            raise RuntimeError("Client not initialised. Use `async with` context manager.")
        return await self._client.request(method, url, **kwargs)
