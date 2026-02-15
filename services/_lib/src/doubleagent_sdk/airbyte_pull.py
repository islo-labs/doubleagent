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
        [--limit N] [--no-redact] [--incremental]

This script:
1. Builds the Airbyte connector config from env vars.
2. Runs ``discover`` → ``read`` via Docker.
3. Parses JSONL output, groups by stream.
4. Applies PII redaction (unless --no-redact).
5. Saves as a DoubleAgent snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from doubleagent_sdk.airbyte_adapter import (
    AirbyteAdapter,
    AirbyteConnectorConfig,
    _check_docker,
)
from doubleagent_sdk.snapshot import save_snapshot, save_snapshot_incremental

logging.basicConfig(level=logging.INFO, format="  %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull a snapshot using an Airbyte source connector"
    )
    p.add_argument("--service", required=True, help="DoubleAgent service name")
    p.add_argument("--profile", default="default", help="Snapshot profile name")
    p.add_argument("--image", required=True, help="Docker image (e.g., airbyte/source-github:latest)")
    p.add_argument(
        "--streams",
        default="",
        help="Comma-separated list of Airbyte streams to pull (empty = all)",
    )
    p.add_argument(
        "--config-env",
        nargs="*",
        default=[],
        help="Config env mappings: ENV_VAR=dotted.config.path (e.g., GITHUB_TOKEN=credentials.personal_access_token)",
    )
    p.add_argument(
        "--stream-mapping",
        nargs="*",
        default=[],
        help="Stream name mappings: airbyte_name=doubleagent_name (e.g., repositories=repos)",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-redact", action="store_true")
    p.add_argument("--incremental", action="store_true")
    p.add_argument(
        "--service-yaml",
        default=None,
        help="Path to service.yaml to read Airbyte config from (alternative to CLI args)",
    )
    return p.parse_args()


def load_config_from_service_yaml(path: str) -> AirbyteConnectorConfig | None:
    """Load Airbyte connector config from a service.yaml file."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # Fall back to reading the YAML manually for simple cases
        return None

    with open(path) as f:
        data = yaml.safe_load(f)

    connector = data.get("connector", {})
    if connector.get("type") != "airbyte":
        return None

    return AirbyteConnectorConfig.from_dict(connector)


def config_from_args(args: argparse.Namespace) -> AirbyteConnectorConfig:
    """Build AirbyteConnectorConfig from CLI arguments."""
    streams = [s.strip() for s in args.streams.split(",") if s.strip()]

    config_env: dict[str, str] = {}
    for mapping in args.config_env:
        if "=" not in mapping:
            logger.warning("Ignoring invalid config-env mapping: %s", mapping)
            continue
        env_var, config_path = mapping.split("=", 1)
        config_env[env_var] = config_path

    stream_mapping: dict[str, str] = {}
    for mapping in args.stream_mapping:
        if "=" not in mapping:
            logger.warning("Ignoring invalid stream-mapping: %s", mapping)
            continue
        ab_name, da_name = mapping.split("=", 1)
        stream_mapping[ab_name] = da_name

    return AirbyteConnectorConfig(
        image=args.image,
        streams=streams,
        config_env=config_env,
        stream_mapping=stream_mapping,
    )


async def main() -> None:
    args = parse_args()

    # Pre-check Docker
    if not _check_docker():
        print(
            "Error: Docker is not available.\n"
            "Airbyte connectors require Docker to run.\n"
            "Install Docker: https://docs.docker.com/get-docker/",
            file=sys.stderr,
        )
        sys.exit(1)

    # Build config
    airbyte_config: AirbyteConnectorConfig | None = None
    if args.service_yaml:
        airbyte_config = load_config_from_service_yaml(args.service_yaml)

    if not airbyte_config:
        airbyte_config = config_from_args(args)

    if not airbyte_config.image:
        print("Error: --image is required", file=sys.stderr)
        sys.exit(1)

    # Log what we're doing
    logger.info("Airbyte pull: %s → %s/%s", airbyte_config.image, args.service, args.profile)
    if airbyte_config.streams:
        logger.info("  Streams: %s", ", ".join(airbyte_config.streams))
    else:
        logger.info("  Streams: all (will discover)")

    # Create adapter
    adapter = AirbyteAdapter(
        airbyte_config,
        redact=not args.no_redact,
    )

    # Load state for incremental
    state_path = _state_file(args.service, args.profile)
    if args.incremental and state_path.exists():
        logger.info("  Loading state for incremental sync...")
        state = json.loads(state_path.read_text())
        adapter.load_state(state)

    # Pull
    logger.info("  Pulling resources (limit=%s)...", args.limit or "all")
    try:
        resources = await adapter.pull_all(limit=args.limit)
    except Exception as exc:
        print(f"Error during Airbyte pull: {exc}", file=sys.stderr)
        sys.exit(1)

    if not resources:
        print("Warning: No records pulled. Check connector config and credentials.", file=sys.stderr)
        sys.exit(0)

    # Save state for future incremental
    final_state = adapter.get_state()
    if final_state:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(final_state, indent=2))
        logger.info("  State saved for incremental sync")

    # Save snapshot
    saver = save_snapshot_incremental if args.incremental else save_snapshot
    path = saver(
        service=args.service,
        profile=args.profile,
        resources=resources,
        connector_name=adapter.name(),
        redacted=not args.no_redact,
    )
    logger.info("  Snapshot saved to %s", path)

    # Summary
    total = sum(len(v) for v in resources.values())
    logger.info(
        "  Done: %d records across %d streams",
        total,
        len(resources),
    )


def _state_file(service: str, profile: str) -> Path:
    """Path to the Airbyte state file for incremental syncs."""
    from doubleagent_sdk.snapshot import snapshot_dir
    return snapshot_dir(service, profile) / ".airbyte_state.json"


if __name__ == "__main__":
    asyncio.run(main())
