"""Trusted Sandbox B runtime process entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

import uvicorn
from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictStr, field_validator

from doubleagent.registry import ServiceRegistry
from doubleagent.sdk import EvaluationConfig, RegisteredTask

from .asgi import create_app
from .core import Capabilities, Runtime
from .server import RuntimeServer


class UnavailableCapability:
    """Fail closed until the owning subsystem supplies a bound implementation."""

    available = False

    async def request(self, request: Any) -> Any:
        raise RuntimeError("upstream transport is not configured")

    async def get(self, key: str) -> Any:
        raise RuntimeError("state capability is not configured")

    async def put(self, key: str, value: Any) -> None:
        raise RuntimeError("state capability is not configured")

    async def resolve(self, alias: str) -> Any:
        raise RuntimeError("identity registry is not configured")

    async def authorize(self, operation: Any, request: Any) -> None:
        raise RuntimeError("authorization is not configured")

    async def tick(self) -> int:
        raise RuntimeError("logical clock is not configured")

    def record(self, event: str, attributes: Any) -> None:
        pass


class TrustedModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class RegisteredTaskLaunch(TrustedModel):
    task_id: StrictStr
    task_payload: dict[str, Any]
    registration_payload: dict[str, Any]
    source_links: list[StrictStr]

    @field_validator("task_id")
    @classmethod
    def valid_task_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task_id is required")
        return value


class Launch(TrustedModel):
    evaluation_id: StrictStr
    task_id: StrictStr
    cutoff_at: AwareDatetime
    bundle_version: StrictStr
    registered_task: RegisteredTaskLaunch
    service_manifests: list[StrictStr]

    @field_validator("evaluation_id", "task_id", "bundle_version")
    @classmethod
    def nonempty_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("launch identifier is required")
        return value

    @field_validator("service_manifests")
    @classmethod
    def valid_manifests(cls, values: list[str]) -> list[str]:
        if not values or any(not Path(value).is_absolute() for value in values):
            raise ValueError("service manifests must be nonempty absolute paths")
        return values


def load_runtime(path: Path) -> Runtime:
    """Load one trusted evaluation bundle; no untrusted request can select another task."""
    data = Launch.model_validate_json(path.read_text())
    config = EvaluationConfig(
        evaluation_id=data.evaluation_id,
        task_id=data.task_id,
        cutoff_at=data.cutoff_at,
        bundle_version=data.bundle_version,
    )
    task_data = data.registered_task
    task = RegisteredTask(
        task_id=task_data.task_id,
        task_payload=task_data.task_payload,
        registration_payload=task_data.registration_payload,
        source_links=tuple(task_data.source_links),
    )
    registry = ServiceRegistry([Path(item) for item in data.service_manifests])
    unavailable = UnavailableCapability()
    capabilities = Capabilities(
        upstream=unavailable,
        overlay=unavailable,
        identities=unavailable,
        authorization=unavailable,
        cache=unavailable,
        cursors=unavailable,
        search=unavailable,
        clock=unavailable,
        telemetry=unavailable,
        available=False,
    )
    return Runtime(config, task, registry, capabilities)


async def run(config_path: Path, runtime_socket: Path, health_socket: Path) -> None:
    runtime = load_runtime(config_path)
    server = RuntimeServer(runtime, runtime_socket)
    await server.start()
    try:
        web = uvicorn.Server(
            uvicorn.Config(create_app(runtime), uds=str(health_socket), log_level="info")
        )
        await web.serve()
    finally:
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="DoubleAgent trusted runtime")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime-socket", type=Path, required=True)
    parser.add_argument("--health-socket", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    asyncio.run(run(args.config, args.runtime_socket, args.health_socket))


if __name__ == "__main__":
    main()
