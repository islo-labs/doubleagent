"""Buffered provider HTTP transports for local and hosted DoubleAgent runtimes."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import httpx

from doubleagent.runtime.protocol import (
    PROTOCOL_VERSION,
    FrameTooLargeError,
    modified_read_to_wire,
    read_frame,
    response_from_wire,
    write_frame,
)

from .models import ProviderRequest, ProviderResponse, host_key


class TransportErrorCode(StrEnum):
    INVALID_TARGET = "invalid_target"
    CREDENTIAL_UNAVAILABLE = "credential_unavailable"
    CONNECT_FAILURE = "connect_failure"
    TIMEOUT = "timeout"
    RESPONSE_TOO_LARGE = "response_too_large"
    CANCELLED = "cancelled"


class TransportError(Exception):
    """Stable, secret-free error surface. The original exception is never retained."""

    def __init__(self, code: TransportErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class TransportCancelledError(asyncio.CancelledError):
    """Typed cancellation that still propagates through asyncio cancellation handling."""

    code = TransportErrorCode.CANCELLED

    def __init__(self) -> None:
        super().__init__(self.code.value)


@dataclass(frozen=True)
class Credential:
    strategy: str
    value: str
    username: str = ""
    header: str = ""

    def __post_init__(self) -> None:
        if self.strategy not in {"bearer", "basic", "custom_header"}:
            raise ValueError("unsupported credential strategy")
        if not self.value or "\r" in self.value or "\n" in self.value:
            raise ValueError("invalid credential")
        if self.strategy == "custom_header" and not _safe_credential_header(self.header):
            raise ValueError("unsafe credential header")
        if self.strategy == "basic" and (
            ":" in self.username or "\r" in self.username or "\n" in self.username
        ):
            raise ValueError("invalid basic username")


class CredentialProvider(Protocol):
    def get(self) -> Credential: ...


@dataclass(frozen=True)
class StaticCredentialProvider:
    credential: Credential

    def get(self) -> Credential:
        return self.credential


@dataclass(frozen=True)
class EnvironmentCredentialProvider:
    strategy: str
    variable: str
    username_variable: str = ""
    header: str = ""

    def get(self) -> Credential:
        value = os.environ.get(self.variable)
        if not value:
            raise TransportError(TransportErrorCode.CREDENTIAL_UNAVAILABLE)
        try:
            return Credential(
                self.strategy,
                value,
                os.environ.get(self.username_variable, "") if self.username_variable else "",
                self.header,
            )
        except ValueError:
            raise TransportError(TransportErrorCode.CREDENTIAL_UNAVAILABLE) from None


@dataclass(frozen=True)
class TransportBinding:
    provider_key: str
    provider_account: str
    allowed_hosts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.provider_key or not self.provider_account or not self.allowed_hosts:
            raise ValueError("provider binding is required")
        object.__setattr__(self, "allowed_hosts", tuple(self.allowed_hosts))
        if len(set(self.allowed_hosts)) != len(self.allowed_hosts):
            raise ValueError("allowed authorities must be unique")
        for authority in self.allowed_hosts:
            hostname = host_key(authority)
            port = authority.rpartition(":")[2] if ":" in authority else None
            canonical = hostname if port is None else f"{hostname}:{int(port)}"
            if authority != canonical:
                raise ValueError("allowed authorities must be canonical")


_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "authorization",
    "cookie",
    "cookie2",
    "set-cookie",
    "content-length",
    "expect",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-access-token",
}
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _protected_header(name: str) -> bool:
    lower = name.lower()
    return lower in _HOP_HEADERS or lower.startswith(("x-islo-", "x-original-", "proxy-"))


def _safe_credential_header(name: str) -> bool:
    return bool(_TOKEN.fullmatch(name)) and not _protected_header(name)


def _safe_headers(request: ProviderRequest) -> list[tuple[str, str]]:
    connection_tokens = {
        part.strip().lower()
        for name, value in request.headers
        if name.lower() == "connection"
        for part in value.split(",")
    }
    safe = []
    for name, value in request.headers:
        if not _TOKEN.fullmatch(name) or any(char in value for char in "\r\n\x00"):
            raise TransportError(TransportErrorCode.INVALID_TARGET)
        if not _protected_header(name) and name.lower() not in connection_tokens:
            safe.append((name, value))
    return safe


def _target(request: ProviderRequest, binding: TransportBinding, local_test: bool) -> str:
    try:
        hostname = host_key(request.host)
    except ValueError:
        raise TransportError(TransportErrorCode.INVALID_TARGET) from None
    if request.scheme != "https" and not (local_test and request.scheme == "http"):
        raise TransportError(TransportErrorCode.INVALID_TARGET)
    port_text = request.host.rpartition(":")[2] if ":" in request.host else None
    if port_text is not None and port_text != str(int(port_text)):
        raise TransportError(TransportErrorCode.INVALID_TARGET)
    default_port = 443 if request.scheme == "https" else 80
    port = int(port_text) if port_text is not None else None
    explicitly_bound = port is not None and f"{hostname}:{port}" in binding.allowed_hosts
    default_bound = hostname in binding.allowed_hosts and (port is None or port == default_port)
    if not (explicitly_bound or default_bound):
        raise TransportError(TransportErrorCode.INVALID_TARGET)
    if not re.fullmatch(r"[A-Z]+", request.method.upper()) or not request.method.isascii():
        raise TransportError(TransportErrorCode.INVALID_TARGET)
    if any(char in request.raw_target for char in "\r\n\x00") or request.raw_target.startswith(
        "//"
    ):
        raise TransportError(TransportErrorCode.INVALID_TARGET)
    return f"{request.scheme}://{request.host}{request.raw_target}"


def _event(
    binding: TransportBinding,
    request: ProviderRequest,
    request_id: str,
    status: int | None,
    outcome: str,
    start: float,
    record: Callable[[str, Mapping[str, str]], None] | None,
) -> None:
    if record is None:
        return
    try:
        record(
            "upstream_transport",
            {
                "provider_key": binding.provider_key,
                "host": host_key(request.host),
                "path": "/"
                + "/".join(
                    "{segment}" for segment in request.path.strip("/").split("/") if segment
                ),
                "method": request.method if re.fullmatch(r"[A-Za-z]+", request.method) else "?",
                "status": str(status) if status is not None else "",
                "duration_ms": str(round((time.monotonic() - start) * 1000)),
                "outcome": outcome,
                "request_id": request_id,
            },
        )
    except Exception:
        # Telemetry failure must not change the provider transport result.
        pass


def _reject_redirect(status: int, headers: tuple[tuple[str, str], ...]) -> None:
    if 300 <= status < 400 and any(name.lower() == "location" for name, _value in headers):
        raise TransportError(TransportErrorCode.INVALID_TARGET)


class DirectTokenTransport:
    def __init__(
        self,
        binding: TransportBinding,
        credentials: CredentialProvider,
        *,
        local_test: bool = False,
        connect_timeout: float = 10,
        total_timeout: float = 30,
        response_limit: int = 10 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
        record: Callable[[str, Mapping[str, str]], None] | None = None,
    ) -> None:
        if connect_timeout <= 0 or total_timeout <= 0 or response_limit <= 0:
            raise ValueError("transport limits must be positive")
        self.binding = binding
        self.credentials = credentials
        self.local_test = local_test
        self.response_limit = response_limit
        self.total_timeout = total_timeout
        self.record = record
        self._own_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(total_timeout, connect=connect_timeout),
            follow_redirects=False,
            trust_env=False,
        )

    async def aclose(self) -> None:
        if self._own_client:
            await self.client.aclose()

    async def request(
        self, request: ProviderRequest, *, source_request_id: str | None = None
    ) -> ProviderResponse:
        request_id = source_request_id or uuid.uuid4().hex
        start = time.monotonic()
        status = None
        outcome = "ok"
        try:
            url = _target(request, self.binding, self.local_test)
            headers = _safe_headers(request)
            try:
                credential = self.credentials.get()
            except TransportError:
                raise
            except Exception:
                raise TransportError(TransportErrorCode.CREDENTIAL_UNAVAILABLE) from None
            if credential.strategy == "bearer":
                headers.append(("Authorization", f"Bearer {credential.value}"))
            elif credential.strategy == "basic":
                import base64

                raw = f"{credential.username}:{credential.value}".encode()
                headers.append(("Authorization", "Basic " + base64.b64encode(raw).decode()))
            else:
                headers = [pair for pair in headers if pair[0].lower() != credential.header.lower()]
                headers.append((credential.header, credential.value))
            async with asyncio.timeout(self.total_timeout):
                async with self.client.stream(
                    request.method,
                    url,
                    headers=headers,
                    content=request.body,
                    follow_redirects=False,
                ) as response:
                    status = response.status_code
                    _reject_redirect(status, tuple(response.headers.multi_items()))
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > self.response_limit:
                            raise TransportError(TransportErrorCode.RESPONSE_TOO_LARGE)
                    return ProviderResponse(
                        status=status,
                        headers=tuple(response.headers.multi_items()),
                        body=bytes(body),
                    )
        except asyncio.CancelledError:
            outcome = TransportErrorCode.CANCELLED.value
            raise TransportCancelledError() from None
        except TransportError as exc:
            outcome = exc.code.value
            raise
        except httpx.TimeoutException:
            outcome = TransportErrorCode.TIMEOUT.value
            raise TransportError(TransportErrorCode.TIMEOUT) from None
        except TimeoutError:
            outcome = TransportErrorCode.TIMEOUT.value
            raise TransportError(TransportErrorCode.TIMEOUT) from None
        except (httpx.TransportError, httpx.InvalidURL, ValueError):
            outcome = TransportErrorCode.CONNECT_FAILURE.value
            raise TransportError(TransportErrorCode.CONNECT_FAILURE) from None
        finally:
            _event(self.binding, request, request_id, status, outcome, start, self.record)


class RouterBackedTransport:
    """Python side of the isolated runtime-to-router modified-read socket."""

    def __init__(
        self,
        binding: TransportBinding,
        socket_path: Path,
        *,
        local_test: bool = False,
        connect_timeout: float = 10,
        total_timeout: float = 30,
        response_limit: int = 10 * 1024 * 1024,
        record: Callable[[str, Mapping[str, str]], None] | None = None,
    ) -> None:
        self.binding = binding
        self.socket_path = socket_path
        self.local_test = local_test
        self.connect_timeout = connect_timeout
        self.total_timeout = total_timeout
        self.response_limit = response_limit
        self.record = record

    async def request(
        self, request: ProviderRequest, *, source_request_id: str | None = None
    ) -> ProviderResponse:
        request_id = uuid.uuid4().hex
        start = time.monotonic()
        status = None
        outcome = "ok"
        writer = None
        try:
            if not source_request_id:
                raise TransportError(TransportErrorCode.INVALID_TARGET)
            _target(request, self.binding, self.local_test)
            safe_request = request.model_copy(update={"headers": tuple(_safe_headers(request))})
            async with asyncio.timeout(self.total_timeout):
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(str(self.socket_path)), self.connect_timeout
                )
                try:
                    await write_frame(
                        writer, modified_read_to_wire(request_id, source_request_id, safe_request)
                    )
                except FrameTooLargeError:
                    raise TransportError(TransportErrorCode.INVALID_TARGET) from None
                frame = await read_frame(reader)
            if (
                frame.get("version") != PROTOCOL_VERSION
                or frame.get("kind") != "raw_response"
                or frame.get("request_id") != request_id
            ):
                raise TransportError(TransportErrorCode.CONNECT_FAILURE)
            response = response_from_wire(frame["response"])
            status = response.status
            _reject_redirect(status, response.headers)
            if len(response.body) > self.response_limit:
                raise TransportError(TransportErrorCode.RESPONSE_TOO_LARGE)
            return response
        except asyncio.CancelledError:
            outcome = TransportErrorCode.CANCELLED.value
            raise TransportCancelledError() from None
        except TimeoutError:
            outcome = TransportErrorCode.TIMEOUT.value
            raise TransportError(TransportErrorCode.TIMEOUT) from None
        except TransportError as exc:
            outcome = exc.code.value
            raise
        except FrameTooLargeError:
            outcome = TransportErrorCode.RESPONSE_TOO_LARGE.value
            raise TransportError(TransportErrorCode.RESPONSE_TOO_LARGE) from None
        except (OSError, ValueError, KeyError, TypeError, asyncio.IncompleteReadError):
            outcome = TransportErrorCode.CONNECT_FAILURE.value
            raise TransportError(TransportErrorCode.CONNECT_FAILURE) from None
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            _event(self.binding, request, request_id, status, outcome, start, self.record)


class RecordingTransport:
    def __init__(
        self, response: ProviderResponse | Callable[[ProviderRequest], ProviderResponse]
    ) -> None:
        self.response = response
        self.requests: list[tuple[ProviderRequest, str | None]] = []

    async def request(
        self, request: ProviderRequest, *, source_request_id: str | None = None
    ) -> ProviderResponse:
        self.requests.append((request, source_request_id))
        return self.response(request) if callable(self.response) else self.response


class MockTransport:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[ProviderRequest] = []

    async def request(
        self, request: ProviderRequest, *, source_request_id: str | None = None
    ) -> ProviderResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("mock transport has no response")
        return self.responses.pop(0)
