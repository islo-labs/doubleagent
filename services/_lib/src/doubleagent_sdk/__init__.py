"""DoubleAgent SDK — shared library for fake services."""

from doubleagent_sdk.state_overlay import StateOverlay
from doubleagent_sdk.namespace import NamespaceRouter
from doubleagent_sdk.webhook_simulator import WebhookSimulator, WebhookDelivery
from doubleagent_sdk.connector import SnapshotConnector, ConnectorCredentials, ResourceSchema
from doubleagent_sdk.redactor import PiiRedactor, RedactionPolicy
from doubleagent_sdk.http_readonly import ReadOnlyHttpClient
from doubleagent_sdk.snapshot import SnapshotManifest, load_snapshot, save_snapshot, save_snapshot_incremental
from doubleagent_sdk.dual_target import (
    is_dual_target_enabled,
    compare_responses,
    readonly,
    is_readonly,
)
from doubleagent_sdk.airbyte_adapter import (
    AirbyteAdapter,
    AirbyteConnectorConfig,
    AirbyteCatalog,
    AirbyteMessage,
    AirbyteStream,
    parse_airbyte_output,
    group_records_by_stream,
)

__all__ = [
    "StateOverlay",
    "NamespaceRouter",
    "WebhookSimulator",
    "WebhookDelivery",
    "SnapshotConnector",
    "ConnectorCredentials",
    "ResourceSchema",
    "PiiRedactor",
    "RedactionPolicy",
    "ReadOnlyHttpClient",
    "SnapshotManifest",
    "load_snapshot",
    "save_snapshot",
    "save_snapshot_incremental",
    "is_dual_target_enabled",
    "compare_responses",
    "readonly",
    "is_readonly",
    "AirbyteAdapter",
    "AirbyteConnectorConfig",
    "AirbyteCatalog",
    "AirbyteMessage",
    "AirbyteStream",
    "parse_airbyte_output",
    "group_records_by_stream",
]
