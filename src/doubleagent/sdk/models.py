"""Provider-neutral, buffered request and response contracts for SDK v0."""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SDK_VERSION = "v0"


def host_key(authority: str) -> str:
    """Return the DNS routing key while leaving the request authority untouched."""
    if not authority or not authority.isascii() or any(c in authority for c in "/@?#\\ \t\r\n"):
        raise ValueError("invalid host authority")
    hostname = authority
    if ":" in authority:
        hostname, separator, port = authority.rpartition(":")
        if not separator or not port.isascii() or not port.isdecimal():
            raise ValueError("invalid host authority port")
        if not 1 <= int(port) <= 65535:
            raise ValueError("invalid host authority port")
    if len(hostname) > 253:
        raise ValueError("invalid hostname")
    labels = hostname.split(".")
    if any(
        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("invalid hostname")
    return hostname.lower()


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OperationKind(StrEnum):
    READ = "READ"
    VIRTUAL_WRITE = "VIRTUAL_WRITE"
    SEARCH = "SEARCH"
    AUTHENTICATION = "AUTHENTICATION"
    UNSUPPORTED = "UNSUPPORTED"


class Operation(FrozenModel):
    name: str
    kind: OperationKind


class ProviderRequest(FrozenModel):
    method: str
    scheme: str = "https"
    host: str
    path: str
    raw_target: str = ""
    query: tuple[tuple[str, str], ...] = ()
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""

    @model_validator(mode="after")
    def target_matches_path(self) -> ProviderRequest:
        if self.scheme not in ("http", "https"):
            raise ValueError("unsupported request scheme")
        target = self.raw_target or self.path + ("?" + urlencode(self.query) if self.query else "")
        if target.split("?", 1)[0] != self.path or "#" in target:
            raise ValueError("raw target must contain the original path")
        object.__setattr__(self, "raw_target", target)
        return self

    @field_validator("host")
    @classmethod
    def valid_authority(cls, host: str) -> str:
        host_key(host)
        return host

    @field_validator("path")
    @classmethod
    def absolute_path(cls, path: str) -> str:
        if not path.startswith("/"):
            raise ValueError("path must start with /")
        return path


class ProviderResponse(FrozenModel):
    status: int = Field(ge=100, le=599)
    headers: tuple[tuple[str, str], ...] = ()
    body: bytes = b""


class ServiceMetadata(FrozenModel):
    name: str
    sdk_version: str
    recovery_policy_version: str
    provider_hosts: tuple[str, ...]
    routing_priority: int = 0
    supported_operations: tuple[str, ...]
    implementation: str

    @field_validator("sdk_version")
    @classmethod
    def supported_sdk(cls, version: str) -> str:
        if version != SDK_VERSION:
            raise ValueError(f"unsupported SDK version: {version}")
        return version

    @field_validator("provider_hosts")
    @classmethod
    def valid_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        if not hosts or len(set(hosts)) != len(hosts):
            raise ValueError("provider_hosts must be nonempty and unique")
        for host in hosts:
            if host_key(host) != host:
                raise ValueError("provider_hosts must be canonical lowercase hostnames")
        return hosts

    @field_validator("supported_operations")
    @classmethod
    def valid_operations(cls, operations: tuple[str, ...]) -> tuple[str, ...]:
        if not operations or len(set(operations)) != len(operations):
            raise ValueError("supported_operations must be nonempty and unique")
        return operations
