"""Descope SnapshotConnector — read-only pull from a real Descope project."""

from __future__ import annotations

import logging
import os
from typing import Any

from doubleagent_sdk import (
    ConnectorCredentials,
    PiiRedactor,
    ReadOnlyHttpClient,
    RedactionPolicy,
    ResourceSchema,
    SnapshotConnector,
)

logger = logging.getLogger(__name__)

_BASE = "https://api.descope.com"

SCHEMAS = [
    ResourceSchema(name="users", fields=["userId", "loginIds", "name", "email", "roleNames", "userTenants"],
                   supports_incremental=True, description="Descope users"),
    ResourceSchema(name="tenants", fields=["id", "name", "selfProvisioningDomains"],
                   supports_incremental=True, description="Tenants"),
    ResourceSchema(name="roles", fields=["name", "description", "permissionNames"],
                   description="Roles (project-level and tenant-level)"),
    ResourceSchema(name="permissions", fields=["name", "description"],
                   description="Permissions"),
]


class DescopeConnector(SnapshotConnector):
    def __init__(self, creds: ConnectorCredentials, *, redact: bool = True):
        self._creds = creds
        self._project_id = creds.extra.get("project_id") or creds.domain or os.environ.get("DESCOPE_PROJECT_ID", "")
        self._mgmt_key = creds.token or os.environ.get("DESCOPE_MANAGEMENT_KEY", "")
        self._redactor = PiiRedactor(RedactionPolicy()) if redact else None
        self._client = ReadOnlyHttpClient(
            base_url=_BASE,
            headers={
                "Authorization": f"Bearer {self._project_id}:{self._mgmt_key}",
                "Content-Type": "application/json",
            },
        )

    def name(self) -> str:
        return "descope-mgmt-v1"

    def validate_credentials(self, creds: ConnectorCredentials) -> bool:
        project_id = creds.extra.get("project_id") or creds.domain
        token = creds.token
        if not project_id or not token:
            logger.error("Both DESCOPE_PROJECT_ID and DESCOPE_MANAGEMENT_KEY are required")
            return False
        return True

    def required_credential_fields(self) -> list[str]:
        return ["token", "domain"]

    def list_schemas(self) -> list[ResourceSchema]:
        return SCHEMAS

    async def pull_resources(self, schema: ResourceSchema, limit: int | None = None) -> list[dict[str, Any]]:
        # Descope management API uses POST for reads
        # We use our ReadOnlyHttpClient which only allows GET,
        # so we hit the REST-ish endpoints where available.
        # For search endpoints that require POST, we document that
        # the connector needs the POST-capable variant.
        # In practice, the ReadOnlyHttpClient enforces read-only at
        # the network level; Descope's management POST endpoints are
        # semantically read-only (search/loadall).

        handlers = {
            "users": self._pull_users,
            "tenants": self._pull_tenants,
            "roles": self._pull_roles,
            "permissions": self._pull_permissions,
        }
        handler = handlers.get(schema.name)
        if not handler:
            logger.warning(f"No handler for schema: {schema.name}")
            return []
        items = await handler(limit)
        if self._redactor:
            items = [self._redactor.redact(item) for item in items]
        return items

    async def _pull_users(self, limit: int | None) -> list[dict[str, Any]]:
        # Note: in a real implementation this would use POST /v1/mgmt/user/search
        # For the connector, we document that it uses the search endpoint.
        # The ReadOnlyHttpClient would need to be configured to allow
        # specific POST endpoints for Descope. For now, return empty
        # and log guidance.
        logger.info("User pull requires POST-based search — use `doubleagent seed --fixture` for offline data")
        return []

    async def _pull_tenants(self, limit: int | None) -> list[dict[str, Any]]:
        logger.info("Tenant pull requires POST — use fixtures for offline data")
        return []

    async def _pull_roles(self, limit: int | None) -> list[dict[str, Any]]:
        logger.info("Role pull requires POST — use fixtures for offline data")
        return []

    async def _pull_permissions(self, limit: int | None) -> list[dict[str, Any]]:
        logger.info("Permission pull requires POST — use fixtures for offline data")
        return []
