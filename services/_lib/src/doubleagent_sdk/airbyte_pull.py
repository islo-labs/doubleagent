#!/usr/bin/env python3
"""Generic entry point for ``doubleagent snapshot pull <service>`` when the
service uses an Airbyte connector.

Invoked by the Rust CLI as::

    uv run python -m doubleagent_sdk.airbyte_pull \\
        --service <service> --profile <profile> \\
        --image <docker-image> \\
        [--streams stream1,stream2] \\
        [--config-env KEY=path.to.config ...] \\
        [--stream-mapping airbyte_name=da_name ...] \\
        [--seeding-json '{"seed_streams": [...]}'] \\
        [--backend pyairbyte|docker] \\
        [--limit N] [--no-redact] [--incremental]

Supports two backends:
- **pyairbyte** (default): Uses PyAirbyte pip packages. No Docker needed.
- **docker**: Uses the existing AirbyteAdapter with Docker subprocess.

When ``--seeding-json`` is provided, applies smart relational filtering
after pulling records. See :mod:`smart_filter` for details.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from doubleagent_sdk.snapshot import save_snapshot, save_snapshot_incremental

logging.basicConfig(level=logging.INFO, format="  %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull a snapshot using an Airbyte source connector"
    )
    p.add_argument("--service", required=True, help="DoubleAgent service name")
    p.add_argument("--profile", default="default", help="Snapshot profile name")
    p.add_argument("--image", required=True, help="Docker image (e.g., airbyte/source-jira:latest)")
    p.add_argument(
        "--streams",
        default="",
        help="Comma-separated list of Airbyte streams to pull (empty = all)",
    )
    p.add_argument(
        "--config-env",
        nargs="*",
        default=[],
        help="Config env mappings: ENV_VAR=dotted.config.path",
    )
    p.add_argument(
        "--stream-mapping",
        nargs="*",
        default=[],
        help="Stream name mappings: airbyte_name=doubleagent_name",
    )
    p.add_argument(
        "--seeding-json",
        default=None,
        help="JSON-encoded SeedingConfig from service.yaml seeding block",
    )
    p.add_argument(
        "--backend",
        choices=["pyairbyte", "docker"],
        default="pyairbyte",
        help="Backend: pyairbyte (default, no Docker) or docker",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-redact", action="store_true")
    p.add_argument("--incremental", action="store_true")
    return p.parse_args()


# =============================================================================
# Config builders
# =============================================================================


def parse_config_env(config_env_args: list[str]) -> dict[str, str]:
    """Parse --config-env args into {env_var: config_path} mapping."""
    result: dict[str, str] = {}
    for mapping in config_env_args:
        if "=" not in mapping:
            logger.warning("Ignoring invalid config-env mapping: %s", mapping)
            continue
        env_var, config_path = mapping.split("=", 1)
        result[env_var] = config_path
    return result


def parse_stream_mapping(mapping_args: list[str]) -> dict[str, str]:
    """Parse --stream-mapping args into {airbyte_name: da_name}."""
    result: dict[str, str] = {}
    for mapping in mapping_args:
        if "=" not in mapping:
            logger.warning("Ignoring invalid stream-mapping: %s", mapping)
            continue
        ab_name, da_name = mapping.split("=", 1)
        result[ab_name] = da_name
    return result


def build_connector_config(config_env: dict[str, str]) -> dict[str, Any]:
    """Build the Airbyte connector config JSON from env var mappings.

    Each entry maps an env var name to a dotted config path.
    E.g., ``{"JIRA_API_TOKEN": "api_token"}`` with ``JIRA_API_TOKEN=xyz``
    produces ``{"api_token": "xyz"}``.
    """
    import os

    config: dict[str, Any] = {}
    for env_var, config_path in config_env.items():
        value = os.environ.get(env_var)
        if not value:
            logger.warning("Env var %s not set (mapped to %s)", env_var, config_path)
            continue
        _set_nested(config, config_path, value)
    return config


def _set_nested(d: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a value in a nested dict using a dotted path."""
    keys = dotted_path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def apply_stream_mapping(
    resources: dict[str, list[dict[str, Any]]],
    stream_mapping: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Rename resource keys according to stream_mapping."""
    if not stream_mapping:
        return resources
    result: dict[str, list[dict[str, Any]]] = {}
    for name, records in resources.items():
        mapped = stream_mapping.get(name, name)
        result[mapped] = records
    return result


# =============================================================================
# Backend: PyAirbyte
# =============================================================================


def pull_with_pyairbyte(
    args: argparse.Namespace,
    connector_config: dict[str, Any],
    streams: list[str],
    seeding_config: Any | None,
) -> dict[str, list[dict[str, Any]]]:
    """Pull data using the PyAirbyte backend (no Docker)."""
    from doubleagent_sdk.pyairbyte_backend import PyAirbyteBackend, image_to_connector_name

    connector_name = image_to_connector_name(args.image)
    logger.info("Using PyAirbyte backend: %s", connector_name)

    backend = PyAirbyteBackend(connector_name, connector_config)

    # Discover streams if none specified
    if not streams:
        streams = backend.discover_streams()

    # If smart seeding, narrow to only the streams we need
    if seeding_config:
        needed = seeding_config.all_stream_names()
        streams = [s for s in streams if s in needed]
        logger.info("  Smart seeding: pulling %d streams", len(streams))

    # Build per-stream limits from seeding config
    per_stream_limits: dict[str, int] = {}
    if seeding_config:
        for sc in seeding_config.seed_streams:
            if sc.limit is not None:
                per_stream_limits[sc.stream] = sc.limit
        # For child-only streams, use default_limit as a safety cap
        if seeding_config.default_limit:
            for s in streams:
                if s not in per_stream_limits:
                    per_stream_limits[s] = seeding_config.default_limit

    return backend.pull_streams(
        streams,
        per_stream_limits=per_stream_limits if per_stream_limits else None,
        global_limit=args.limit,
    )


# =============================================================================
# Backend: Docker
# =============================================================================


async def pull_with_docker(
    args: argparse.Namespace,
    config_env: dict[str, str],
    streams: list[str],
    stream_mapping: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Pull data using the Docker-based AirbyteAdapter."""
    from doubleagent_sdk.airbyte_adapter import (
        AirbyteAdapter,
        AirbyteConnectorConfig,
        _check_docker,
    )

    if not _check_docker():
        print(
            "Error: Docker is not available.\n"
            "Airbyte Docker backend requires Docker to run.\n"
            "Install Docker or use --backend pyairbyte.",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info("Using Docker backend: %s", args.image)

    airbyte_config = AirbyteConnectorConfig(
        image=args.image,
        streams=streams,
        config_env=config_env,
        stream_mapping=stream_mapping,
    )

    adapter = AirbyteAdapter(airbyte_config, redact=False)  # redaction done separately

    # Load state for incremental
    state_path = _state_file(args.service, args.profile)
    if args.incremental and state_path.exists():
        logger.info("  Loading state for incremental sync...")
        state = json.loads(state_path.read_text())
        adapter.load_state(state)

    resources = await adapter.pull_all(limit=args.limit)

    # Save state for future incremental
    final_state = adapter.get_state()
    if final_state:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(final_state, indent=2))
        logger.info("  State saved for incremental sync")

    return resources


# =============================================================================
# Main
# =============================================================================


async def main() -> None:
    args = parse_args()

    # Parse inputs
    config_env = parse_config_env(args.config_env)
    stream_mapping = parse_stream_mapping(args.stream_mapping)
    streams = [s.strip() for s in args.streams.split(",") if s.strip()]

    # Parse seeding config
    seeding_config = None
    if args.seeding_json:
        from doubleagent_sdk.smart_filter import SeedingConfig
        seeding_config = SeedingConfig.from_dict(json.loads(args.seeding_json))

    # Build connector config from env vars
    connector_config = build_connector_config(config_env)

    # Log what we're doing
    logger.info(
        "Airbyte pull: %s → %s/%s (backend=%s)",
        args.image, args.service, args.profile, args.backend,
    )

    # Pull records using chosen backend
    if args.backend == "pyairbyte":
        try:
            resources = pull_with_pyairbyte(
                args, connector_config, streams, seeding_config,
            )
        except ImportError as exc:
            logger.error("%s", exc)
            logger.info("Falling back to Docker backend...")
            resources = await pull_with_docker(
                args, config_env, streams, stream_mapping,
            )
    else:
        resources = await pull_with_docker(
            args, config_env, streams, stream_mapping,
        )

    if not resources:
        print(
            "Warning: No records pulled. Check connector config and credentials.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Apply smart filtering
    if seeding_config:
        from doubleagent_sdk.smart_filter import apply_relational_filter
        before = sum(len(v) for v in resources.values())
        resources = apply_relational_filter(resources, seeding_config)
        after = sum(len(v) for v in resources.values())
        logger.info("  Smart filter: %d → %d records", before, after)

    # Apply stream name mapping
    resources = apply_stream_mapping(resources, stream_mapping)

    # Apply PII redaction
    if not args.no_redact:
        from doubleagent_sdk.redactor import PiiRedactor
        redactor = PiiRedactor()
        for rtype, items in resources.items():
            redactor.redact_resources(items)

    # Save snapshot
    saver = save_snapshot_incremental if args.incremental else save_snapshot
    path = saver(
        service=args.service,
        profile=args.profile,
        resources=resources,
        connector_name=f"airbyte:{args.image}",
        redacted=not args.no_redact,
    )
    logger.info("  Snapshot saved to %s", path)

    # Summary
    total = sum(len(v) for v in resources.values())
    for rtype, items in sorted(resources.items()):
        logger.info("    %s: %d records", rtype, len(items))
    logger.info("  Done: %d records across %d streams", total, len(resources))


def _state_file(service: str, profile: str) -> Path:
    """Path to the Airbyte state file for incremental syncs."""
    from doubleagent_sdk.snapshot import snapshot_dir
    return snapshot_dir(service, profile) / ".airbyte_state.json"


if __name__ == "__main__":
    asyncio.run(main())
