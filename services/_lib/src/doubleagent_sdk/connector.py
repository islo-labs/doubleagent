"""Pluggable snapshot connector interface.

Each SaaS service can provide a connector that knows how to pull
read-only data from the real API.  The interface is intentionally
minimal — only read operations are exposed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectorCredentials:
    """Credentials for authenticating with a real SaaS API.

    Connectors declare which fields they require.  Credentials are
    sourced from env vars or OS keyring — never stored in snapshot files.
    """

    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    domain: str | None = None  # e.g., Auth0 tenant domain
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class ResourceSchema:
    """Describes a resource type that a connector can pull."""

    name: str  # e.g., "repos", "issues", "users"
    fields: list[str]  # field names included in the pull
    supports_incremental: bool = False  # can do delta / incremental pulls
    description: str = ""


class SnapshotConnector(ABC):
    """Abstract base class for read-only snapshot connectors.

    Implementations live in ``services/<name>/connector/`` and are
    discovered via the ``connector`` key in ``service.yaml``.
    """

    @abstractmethod
    def name(self) -> str:
        """Return the connector identifier, e.g. ``'github-rest-v3'``."""
        ...

    @abstractmethod
    def validate_credentials(self, creds: ConnectorCredentials) -> bool:
        """Validate that *creds* are sufficient for a read-only pull.

        Should also warn (via logging) if the token has write scopes
        where the API supports scope introspection.
        """
        ...

    @abstractmethod
    def required_credential_fields(self) -> list[str]:
        """Return the names of :class:`ConnectorCredentials` fields
        that must be populated (e.g. ``["token"]``)."""
        ...

    @abstractmethod
    def list_schemas(self) -> list[ResourceSchema]:
        """Return the resource types this connector can pull."""
        ...

    @abstractmethod
    async def pull_resources(
        self,
        schema: ResourceSchema,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Pull resources of the given type.  MUST be read-only (GET only).

        Parameters
        ----------
        schema:
            Which resource type to pull.
        limit:
            Maximum number of resources to return.  ``None`` means all.
        """
        ...

    async def pull_all(
        self,
        limit: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Pull all resource types.  Convenience wrapper over :meth:`pull_resources`."""
        result: dict[str, list[dict[str, Any]]] = {}
        for schema in self.list_schemas():
            result[schema.name] = await self.pull_resources(schema, limit=limit)
        return result
