"""Provider-neutral dispatch and capability binding."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from doubleagent.registry import ServiceRegistry
from doubleagent.sdk import (
    AuthorizationService,
    CursorStore,
    EvaluationConfig,
    IdentityRegistry,
    LazyReadCache,
    LogicalClock,
    OperationKind,
    OverlayStore,
    ProviderRequest,
    ProviderResponse,
    RegisteredTask,
    SearchStore,
    ServiceContext,
    TaskRegistrationClient,
    Telemetry,
    UpstreamTransport,
)
from doubleagent.sdk.models import host_key


class BoundUpstream:
    def __init__(
        self,
        transport: UpstreamTransport,
        hosts: tuple[str, ...],
        source_request_id: str | None = None,
    ) -> None:
        self._transport = transport
        self._hosts = frozenset(hosts)
        self._source_request_id = source_request_id

    def for_source(self, source_request_id: str) -> BoundUpstream:
        if not source_request_id:
            raise ValueError("source request ID is required")
        return BoundUpstream(self._transport, tuple(self._hosts), source_request_id)

    async def request(self, request: ProviderRequest) -> ProviderResponse:
        if host_key(request.host) not in self._hosts:
            raise ValueError("upstream target outside bound service hosts")
        if self._source_request_id is None:
            return await self._transport.request(request)
        return await self._transport.request(request, source_request_id=self._source_request_id)


class DeniedUpstream:
    async def request(self, request: ProviderRequest) -> ProviderResponse:
        raise PermissionError("virtual writes cannot use upstream transport")


@dataclass(frozen=True)
class Capabilities:
    upstream: UpstreamTransport
    overlay: OverlayStore
    identities: IdentityRegistry
    authorization: AuthorizationService
    cache: LazyReadCache
    cursors: CursorStore
    search: SearchStore
    clock: LogicalClock
    telemetry: Telemetry
    available: bool = True


class Runtime:
    def __init__(
        self,
        config: EvaluationConfig,
        task: RegisteredTask,
        registry: ServiceRegistry,
        capabilities: Capabilities,
    ) -> None:
        if task.task_id != config.task_id:
            raise ValueError("registered task does not match evaluation binding")
        self.config = config
        self.task = task
        self.registry = registry
        self._capabilities_available = capabilities.available and all(
            capability is not None and getattr(capability, "available", True)
            for capability in (
                capabilities.upstream,
                capabilities.overlay,
                capabilities.identities,
                capabilities.authorization,
                capabilities.cache,
                capabilities.cursors,
                capabilities.search,
                capabilities.clock,
                capabilities.telemetry,
            )
        )
        self._contexts = {
            name: ServiceContext(
                evaluation=config,
                task=task,
                upstream=BoundUpstream(capabilities.upstream, metadata.provider_hosts),
                overlay=capabilities.overlay,
                identities=capabilities.identities,
                authorization=capabilities.authorization,
                cache=capabilities.cache,
                cursors=capabilities.cursors,
                search=capabilities.search,
                clock=capabilities.clock,
                telemetry=capabilities.telemetry,
            )
            for name, (metadata, _) in registry.services.items()
        }

    @classmethod
    async def load(
        cls,
        config: EvaluationConfig,
        task_client: TaskRegistrationClient,
        registry: ServiceRegistry,
        capabilities: Capabilities,
    ) -> Runtime:
        return cls(config, await task_client.get_task(), registry, capabilities)

    async def dispatch(
        self, request: ProviderRequest, *, source_request_id: str | None = None
    ) -> ProviderResponse:
        entry = self.registry.for_host(request.host)
        if entry is None:
            return ProviderResponse(status=421, body=b"unknown managed service")
        metadata, service = entry
        try:
            operation = service.classify(request)
            if (
                operation.kind is OperationKind.UNSUPPORTED
                or operation.name not in metadata.supported_operations
            ):
                return ProviderResponse(status=501, body=b"unsupported operation")
            context = self._contexts[metadata.name]
            if source_request_id is not None:
                context = replace(context, upstream=context.upstream.for_source(source_request_id))
            if operation.kind is OperationKind.VIRTUAL_WRITE:
                context = replace(context, upstream=DeniedUpstream())
            response = await service.handle(operation, request, context)
            if not isinstance(response, ProviderResponse):
                raise TypeError("service did not return ProviderResponse")
            return response
        except Exception as exc:
            self._record_failure(metadata.name, exc)
            return ProviderResponse(status=502, body=b"managed service failed")

    def _record_failure(self, service: str, exc: Exception) -> None:
        context = self._contexts[service]
        context.telemetry.record(
            "managed_service_failure", {"service": service, "error_type": type(exc).__name__}
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ready" if self._capabilities_available else "unhealthy",
            "protocol_version": 1,
            "evaluation_id": self.config.evaluation_id,
            "bundle_version": self.config.bundle_version,
            **self.registry.capabilities(),
        }
