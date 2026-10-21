"""Explicit, trusted service manifest loading."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Protocol

import yaml

from .sdk import Operation, ProviderRequest, ProviderResponse, ServiceContext, ServiceMetadata
from .sdk.models import host_key


class Service(Protocol):
    def classify(self, request: ProviderRequest) -> Operation: ...

    async def handle(
        self, operation: Operation, request: ProviderRequest, service_context: ServiceContext
    ) -> ProviderResponse: ...


class ServiceRegistry:
    def __init__(self, manifests: list[Path]) -> None:
        self.services: dict[str, tuple[ServiceMetadata, Service]] = {}
        self.hosts: dict[str, str] = {}
        for path in manifests:
            raw = yaml.safe_load(path.read_text())
            if not isinstance(raw, dict):
                raise ValueError(f"invalid service manifest: {path}")
            metadata = ServiceMetadata.model_validate(raw)
            if metadata.name in self.services:
                raise ValueError(f"duplicate service: {metadata.name}")
            module_name, separator, attribute = metadata.implementation.partition(":")
            if not separator or not module_name or not attribute:
                raise ValueError(f"invalid implementation entrypoint: {metadata.implementation}")
            service = getattr(importlib.import_module(module_name), attribute)()
            if not callable(getattr(service, "classify", None)) or not callable(
                getattr(service, "handle", None)
            ):
                raise ValueError(f"service {metadata.name} lacks classify or handle")
            for host in metadata.provider_hosts:
                if host in self.hosts:
                    raise ValueError(f"ambiguous managed host: {host}")
                self.hosts[host] = metadata.name
            self.services[metadata.name] = (metadata, service)

    def for_host(self, host: str) -> tuple[ServiceMetadata, Service] | None:
        name = self.hosts.get(host_key(host))
        return self.services[name] if name is not None else None

    def capabilities(self) -> dict[str, object]:
        return {
            "sdk_version": "v0",
            "services": [
                {
                    "name": metadata.name,
                    "recovery_policy_version": metadata.recovery_policy_version,
                    "provider_hosts": metadata.provider_hosts,
                    "supported_operations": metadata.supported_operations,
                }
                for metadata, _ in self.services.values()
            ],
        }
