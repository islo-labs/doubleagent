"""Airbyte Protocol adapter for DoubleAgent.

Wraps any existing Airbyte source connector (Docker image) and converts
its output into DoubleAgent snapshots.  This gives DoubleAgent instant
access to 300+ Airbyte source connectors (Salesforce, HubSpot, Jira,
Stripe, etc.) without writing custom connector code.

Airbyte Protocol v1 overview:
- Connectors are Docker images that read from stdin and write JSONL to stdout
- ``spec``    → returns JSON schema for the connector's config
- ``check``   → validates credentials
- ``discover`` → returns catalog of available streams
- ``read``    → emits AirbyteMessage records (RECORD, STATE, LOG)

Usage::

    adapter = AirbyteAdapter(
        image="airbyte/source-github:latest",
        config={"credentials": {"personal_access_token": "ghp_..."},
                "repositories": ["myorg/myrepo"]},
    )

    # Discover available streams
    catalog = await adapter.discover()

    # Pull selected streams as a DoubleAgent snapshot
    resources = await adapter.read(streams=["repositories", "issues"])
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from doubleagent_sdk.connector import (
    ConnectorCredentials,
    ResourceSchema,
    SnapshotConnector,
)
from doubleagent_sdk.redactor import PiiRedactor, RedactionPolicy

logger = logging.getLogger(__name__)


# =============================================================================
# Airbyte Protocol message types
# =============================================================================

@dataclass
class AirbyteMessage:
    """A single line from an Airbyte connector's JSONL output."""

    type: str  # RECORD, STATE, LOG, SPEC, CATALOG, CONNECTION_STATUS, TRACE
    record: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    log: dict[str, Any] | None = None
    spec: dict[str, Any] | None = None
    catalog: dict[str, Any] | None = None
    connectionStatus: dict[str, Any] | None = None
    trace: dict[str, Any] | None = None

    @classmethod
    def from_line(cls, line: str) -> "AirbyteMessage | None":
        """Parse a single JSONL line into an AirbyteMessage.

        Returns None for non-JSON or unrecognized lines (connectors
        sometimes emit non-protocol log lines).
        """
        line = line.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Skipping non-JSON line: %s", line[:120])
            return None

        msg_type = data.get("type", "")
        if not msg_type:
            return None

        return cls(
            type=msg_type,
            record=data.get("record"),
            state=data.get("state"),
            log=data.get("log"),
            spec=data.get("spec"),
            catalog=data.get("catalog"),
            connectionStatus=data.get("connectionStatus"),
            trace=data.get("trace"),
        )


@dataclass
class AirbyteStream:
    """Metadata about a stream from the Airbyte catalog."""

    name: str
    json_schema: dict[str, Any] = field(default_factory=dict)
    supported_sync_modes: list[str] = field(default_factory=list)
    source_defined_cursor: bool = False
    default_cursor_field: list[str] = field(default_factory=list)
    source_defined_primary_key: list[list[str]] = field(default_factory=list)
    namespace: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AirbyteStream":
        return cls(
            name=data.get("name", ""),
            json_schema=data.get("json_schema", {}),
            supported_sync_modes=data.get("supported_sync_modes", ["full_refresh"]),
            source_defined_cursor=data.get("source_defined_cursor", False),
            default_cursor_field=data.get("default_cursor_field", []),
            source_defined_primary_key=data.get("source_defined_primary_key", []),
            namespace=data.get("namespace"),
        )


@dataclass
class AirbyteCatalog:
    """The catalog returned by an Airbyte connector's ``discover`` command."""

    streams: list[AirbyteStream] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AirbyteCatalog":
        raw_streams = data.get("streams", [])
        return cls(
            streams=[AirbyteStream.from_dict(s.get("stream", s)) for s in raw_streams]
        )

    def stream_names(self) -> list[str]:
        return [s.name for s in self.streams]

    def get_stream(self, name: str) -> AirbyteStream | None:
        for s in self.streams:
            if s.name == name:
                return s
        return None


@dataclass
class AirbyteConnectorConfig:
    """Configuration for an Airbyte-based connector in service.yaml.

    Example service.yaml::

        connector:
          type: airbyte
          image: airbyte/source-github:latest
          streams:
            - repositories
            - issues
            - pull_requests
          config_env:
            GITHUB_TOKEN: credentials.personal_access_token
            GITHUB_REPOS: repositories
          stream_mapping:
            repositories: repos
            pull_requests: pulls
    """

    image: str
    streams: list[str] = field(default_factory=list)
    config_env: dict[str, str] = field(default_factory=dict)
    stream_mapping: dict[str, str] = field(default_factory=dict)
    docker_args: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AirbyteConnectorConfig":
        return cls(
            image=data.get("image", ""),
            streams=data.get("streams", []),
            config_env=data.get("config_env", {}),
            stream_mapping=data.get("stream_mapping", {}),
            docker_args=data.get("docker_args", []),
        )

    def build_connector_config(self) -> dict[str, Any]:
        """Build the Airbyte connector config JSON from env vars.

        Uses ``config_env`` to map environment variables to nested config
        paths.  For example::

            config_env:
              GITHUB_TOKEN: credentials.personal_access_token

        With ``GITHUB_TOKEN=ghp_xxx``, produces::

            {"credentials": {"personal_access_token": "ghp_xxx"}}
        """
        config: dict[str, Any] = {}
        for env_var, config_path in self.config_env.items():
            value = os.environ.get(env_var)
            if not value:
                logger.warning("Env var %s not set (mapped to %s)", env_var, config_path)
                continue
            _set_nested(config, config_path, value)
        return config

    def map_stream_name(self, airbyte_name: str) -> str:
        """Map an Airbyte stream name to a DoubleAgent resource type."""
        return self.stream_mapping.get(airbyte_name, airbyte_name)


def _set_nested(d: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a value in a nested dict using a dotted path.

    ``_set_nested({}, "a.b.c", 42)`` → ``{"a": {"b": {"c": 42}}}``
    """
    keys = dotted_path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


# =============================================================================
# Docker runner
# =============================================================================

def _check_docker() -> bool:
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_docker(
    image: str,
    command: str,
    *,
    config_path: str | None = None,
    catalog_path: str | None = None,
    state_path: str | None = None,
    extra_args: list[str] | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    """Run an Airbyte connector Docker command.

    Parameters
    ----------
    image:
        Docker image name (e.g., ``airbyte/source-github:latest``).
    command:
        Airbyte command: ``spec``, ``check``, ``discover``, or ``read``.
    config_path:
        Path to the config JSON file (mounted into container).
    catalog_path:
        Path to the configured catalog JSON (for ``read``).
    state_path:
        Path to the state JSON (for incremental ``read``).
    extra_args:
        Additional Docker args (e.g., network settings).
    timeout:
        Timeout in seconds for the Docker run.
    """
    docker_cmd = [
        "docker", "run", "--rm",
        "-i",
    ]

    # Mount files into the container
    mounts: list[str] = []
    connector_args = [command]

    if config_path:
        mounts.extend(["-v", f"{config_path}:/tmp/config.json:ro"])
        connector_args.extend(["--config", "/tmp/config.json"])

    if catalog_path:
        mounts.extend(["-v", f"{catalog_path}:/tmp/catalog.json:ro"])
        connector_args.extend(["--catalog", "/tmp/catalog.json"])

    if state_path:
        mounts.extend(["-v", f"{state_path}:/tmp/state.json:ro"])
        connector_args.extend(["--state", "/tmp/state.json"])

    if extra_args:
        docker_cmd.extend(extra_args)

    full_cmd = docker_cmd + mounts + [image] + connector_args

    logger.debug("Running: %s", " ".join(full_cmd))

    return subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_airbyte_output(stdout: str) -> list[AirbyteMessage]:
    """Parse JSONL output from an Airbyte connector into messages."""
    messages: list[AirbyteMessage] = []
    for line in stdout.splitlines():
        msg = AirbyteMessage.from_line(line)
        if msg:
            messages.append(msg)
    return messages


def group_records_by_stream(
    messages: list[AirbyteMessage],
    stream_mapping: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Group RECORD messages by stream name.

    Parameters
    ----------
    messages:
        Parsed AirbyteMessages.
    stream_mapping:
        Optional mapping from Airbyte stream names to DoubleAgent
        resource types.
    """
    mapping = stream_mapping or {}
    resources: dict[str, list[dict[str, Any]]] = {}

    for msg in messages:
        if msg.type != "RECORD" or not msg.record:
            continue
        stream = msg.record.get("stream", "unknown")
        data = msg.record.get("data", {})
        mapped_name = mapping.get(stream, stream)
        resources.setdefault(mapped_name, []).append(data)

    return resources


def extract_catalog(messages: list[AirbyteMessage]) -> AirbyteCatalog | None:
    """Extract the catalog from discover output."""
    for msg in messages:
        if msg.type == "CATALOG" and msg.catalog:
            return AirbyteCatalog.from_dict(msg.catalog)
    return None


def extract_state(messages: list[AirbyteMessage]) -> dict[str, Any] | None:
    """Extract the last state message (for incremental syncs)."""
    last_state = None
    for msg in messages:
        if msg.type == "STATE" and msg.state:
            last_state = msg.state
    return last_state


def build_configured_catalog(
    catalog: AirbyteCatalog,
    selected_streams: list[str] | None = None,
) -> dict[str, Any]:
    """Build a configured catalog JSON for the ``read`` command.

    Selects only the specified streams (or all if None).  Uses
    ``full_refresh | overwrite`` sync mode.
    """
    streams_config = []
    for stream in catalog.streams:
        if selected_streams and stream.name not in selected_streams:
            continue
        streams_config.append({
            "stream": {
                "name": stream.name,
                "json_schema": stream.json_schema,
                "supported_sync_modes": stream.supported_sync_modes,
            },
            "sync_mode": "full_refresh",
            "destination_sync_mode": "overwrite",
        })
    return {"streams": streams_config}


# =============================================================================
# AirbyteAdapter — the main class
# =============================================================================

class AirbyteAdapter(SnapshotConnector):
    """Adapter that wraps an Airbyte source connector Docker image.

    Implements the :class:`SnapshotConnector` interface so it plugs
    into the same ``snapshot pull`` workflow as native connectors.

    Parameters
    ----------
    airbyte_config:
        Configuration specifying the Docker image, streams, and env
        variable mapping.
    creds:
        Credentials (used to build the Airbyte config JSON).
    redact:
        Whether to apply PII redaction to pulled data.
    timeout:
        Docker run timeout in seconds.
    """

    def __init__(
        self,
        airbyte_config: AirbyteConnectorConfig,
        creds: ConnectorCredentials | None = None,
        *,
        redact: bool = True,
        timeout: int = 600,
    ) -> None:
        self._config = airbyte_config
        self._creds = creds
        self._redactor = PiiRedactor(RedactionPolicy()) if redact else None
        self._timeout = timeout
        self._catalog: AirbyteCatalog | None = None
        self._last_state: dict[str, Any] | None = None

    # -- SnapshotConnector interface ----------------------------------------

    def name(self) -> str:
        return f"airbyte:{self._config.image}"

    def required_credential_fields(self) -> list[str]:
        # Determined by the Airbyte connector's spec
        return list(self._config.config_env.keys())

    def validate_credentials(self, creds: ConnectorCredentials) -> bool:
        """Run the Airbyte ``check`` command to validate credentials."""
        if not _check_docker():
            logger.error("Docker is not available. Airbyte connectors require Docker.")
            return False

        connector_config = self._config.build_connector_config()
        if not connector_config:
            logger.error("No config could be built from env vars. Check config_env mapping.")
            return False

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(connector_config, f)
            config_path = f.name

        try:
            result = _run_docker(
                self._config.image,
                "check",
                config_path=config_path,
                extra_args=self._config.docker_args,
                timeout=self._timeout,
            )
            messages = parse_airbyte_output(result.stdout)
            for msg in messages:
                if msg.type == "CONNECTION_STATUS" and msg.connectionStatus:
                    status = msg.connectionStatus.get("status", "")
                    if status == "SUCCEEDED":
                        logger.info("Airbyte check succeeded for %s", self._config.image)
                        return True
                    else:
                        logger.error(
                            "Airbyte check failed: %s",
                            msg.connectionStatus.get("message", "unknown error"),
                        )
                        return False

            # If we got stderr but no status message
            if result.returncode != 0:
                logger.error("Airbyte check failed (exit %d): %s", result.returncode, result.stderr[:500])
                return False

            return True
        finally:
            os.unlink(config_path)

    def list_schemas(self) -> list[ResourceSchema]:
        """Run ``discover`` if needed and return available streams as schemas."""
        if self._catalog is None:
            self._catalog = self._discover_sync()

        if not self._catalog:
            return []

        schemas = []
        for stream in self._catalog.streams:
            if self._config.streams and stream.name not in self._config.streams:
                continue
            mapped_name = self._config.map_stream_name(stream.name)
            fields = list(stream.json_schema.get("properties", {}).keys())
            schemas.append(ResourceSchema(
                name=mapped_name,
                fields=fields[:20],  # cap field list for display
                supports_incremental="incremental" in stream.supported_sync_modes,
                description=f"Airbyte stream: {stream.name}",
            ))
        return schemas

    async def pull_resources(
        self,
        schema: ResourceSchema,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Pull resources for a single stream.

        Note: Airbyte connectors read all configured streams at once,
        so this defers to :meth:`pull_all` internally.
        """
        all_resources = await self.pull_all(limit=limit)
        return all_resources.get(schema.name, [])

    async def pull_all(
        self,
        limit: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Run the Airbyte ``read`` command and return all resources."""
        # Ensure we have a catalog
        if self._catalog is None:
            self._catalog = self._discover_sync()
        if not self._catalog:
            raise RuntimeError(f"Could not discover catalog for {self._config.image}")

        connector_config = self._config.build_connector_config()

        # Write config and catalog to temp files
        config_fd = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        catalog_fd = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)

        try:
            json.dump(connector_config, config_fd)
            config_fd.close()

            configured_catalog = build_configured_catalog(
                self._catalog,
                selected_streams=self._config.streams or None,
            )
            json.dump(configured_catalog, catalog_fd)
            catalog_fd.close()

            # Optional state for incremental
            state_path = None
            if self._last_state:
                state_fd = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
                json.dump(self._last_state, state_fd)
                state_fd.close()
                state_path = state_fd.name

            logger.info("Running Airbyte read: %s (%d streams)...",
                        self._config.image, len(configured_catalog["streams"]))

            result = _run_docker(
                self._config.image,
                "read",
                config_path=config_fd.name,
                catalog_path=catalog_fd.name,
                state_path=state_path,
                extra_args=self._config.docker_args,
                timeout=self._timeout,
            )

            if result.returncode != 0:
                # Log stderr but still try to parse partial output
                logger.warning("Airbyte read exited with code %d", result.returncode)
                if result.stderr:
                    logger.warning("stderr: %s", result.stderr[:1000])

            messages = parse_airbyte_output(result.stdout)
            _log_airbyte_messages(messages)

            # Save state for future incremental pulls
            self._last_state = extract_state(messages)

            # Group records
            resources = group_records_by_stream(
                messages,
                stream_mapping=self._config.stream_mapping,
            )

            # Apply limit
            if limit:
                resources = {k: v[:limit] for k, v in resources.items()}

            # Redact PII
            if self._redactor:
                for rtype, items in resources.items():
                    self._redactor.redact_resources(items)

            for rtype, items in resources.items():
                logger.info("  %s: %d records", rtype, len(items))

            return resources

        finally:
            os.unlink(config_fd.name)
            os.unlink(catalog_fd.name)
            if state_path:
                os.unlink(state_path)

    # -- Internal -----------------------------------------------------------

    def _discover_sync(self) -> AirbyteCatalog | None:
        """Run ``discover`` synchronously and return the catalog."""
        connector_config = self._config.build_connector_config()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(connector_config, f)
            config_path = f.name

        try:
            logger.info("Discovering streams for %s...", self._config.image)
            result = _run_docker(
                self._config.image,
                "discover",
                config_path=config_path,
                extra_args=self._config.docker_args,
                timeout=self._timeout,
            )

            if result.returncode != 0:
                logger.error("Discover failed (exit %d): %s", result.returncode, result.stderr[:500])
                return None

            messages = parse_airbyte_output(result.stdout)
            catalog = extract_catalog(messages)

            if catalog:
                logger.info("Discovered %d streams: %s",
                            len(catalog.streams),
                            ", ".join(catalog.stream_names()))
            else:
                logger.error("No catalog found in discover output")

            return catalog
        finally:
            os.unlink(config_path)

    def get_state(self) -> dict[str, Any] | None:
        """Return the last state from a read operation (for incremental)."""
        return self._last_state

    def load_state(self, state: dict[str, Any]) -> None:
        """Load state from a previous run (for incremental pulls)."""
        self._last_state = state


def _log_airbyte_messages(messages: list[AirbyteMessage]) -> None:
    """Log notable Airbyte messages (errors, warnings)."""
    for msg in messages:
        if msg.type == "LOG" and msg.log:
            level = msg.log.get("level", "INFO").upper()
            text = msg.log.get("message", "")
            if level in ("ERROR", "FATAL"):
                logger.error("Airbyte: %s", text)
            elif level == "WARN":
                logger.warning("Airbyte: %s", text)
            else:
                logger.debug("Airbyte: %s", text)
        elif msg.type == "TRACE" and msg.trace:
            trace_type = msg.trace.get("type", "")
            if trace_type == "ERROR":
                error = msg.trace.get("error", {})
                logger.error("Airbyte trace error: %s", error.get("message", ""))
