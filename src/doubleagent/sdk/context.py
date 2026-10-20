"""Immutable task data and evaluation-bound capability interfaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .models import Operation, ProviderRequest, ProviderResponse


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class RegisteredTask:
    task_id: str
    task_payload: Mapping[str, Any]
    registration_payload: Mapping[str, Any]
    source_links: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_payload", freeze(dict(self.task_payload)))
        object.__setattr__(self, "registration_payload", freeze(dict(self.registration_payload)))
        object.__setattr__(self, "source_links", tuple(self.source_links))


@dataclass(frozen=True)
class EvaluationConfig:
    evaluation_id: str
    task_id: str
    cutoff_at: datetime
    bundle_version: str

    def __post_init__(self) -> None:
        if not self.evaluation_id or not self.task_id or not self.bundle_version:
            raise ValueError("evaluation, task, and bundle identifiers are required")
        if self.cutoff_at.tzinfo is None:
            raise ValueError("cutoff_at must be timezone-aware")


class UpstreamTransport(Protocol):
    async def request(
        self, request: ProviderRequest, *, source_request_id: str | None = None
    ) -> ProviderResponse: ...


class TaskRegistrationClient(Protocol):
    async def get_task(self) -> RegisteredTask: ...


class OverlayStore(Protocol):
    async def get(self, key: str) -> Any: ...

    async def put(self, key: str, value: Any) -> None: ...


class IdentityRegistry(Protocol):
    async def resolve(self, alias: str) -> str | None: ...


class AuthorizationService(Protocol):
    async def authorize(self, operation: Operation, request: ProviderRequest) -> None: ...


class LazyReadCache(Protocol):
    async def get(self, key: str) -> ProviderResponse | None: ...

    async def put(self, key: str, response: ProviderResponse) -> None: ...


class CursorStore(Protocol):
    async def get(self, cursor: str) -> Any: ...


class SearchStore(Protocol):
    async def get(self, session: str) -> Any: ...


class LogicalClock(Protocol):
    async def tick(self) -> int: ...


class Telemetry(Protocol):
    def record(self, event: str, attributes: Mapping[str, str]) -> None: ...


class ServiceStateDefinition(Protocol):
    """Service-owned typed state hook; implementation belongs to the overlay subsystem."""

    service_name: str
    state_schema_version: str

    def initialize_schema(self, connection: Any) -> None: ...

    def validate_schema(self, connection: Any) -> None: ...

    def repository(self, transaction: Any) -> Any: ...


@dataclass(frozen=True)
class ServiceContext:
    evaluation: EvaluationConfig
    task: RegisteredTask
    upstream: UpstreamTransport
    overlay: OverlayStore
    identities: IdentityRegistry
    authorization: AuthorizationService
    cache: LazyReadCache
    cursors: CursorStore
    search: SearchStore
    clock: LogicalClock
    telemetry: Telemetry
