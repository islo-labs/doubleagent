"""CLI entry point for Airbyte-based snapshot pulls."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from snapshot_pull.redactor import PiiRedactor
from snapshot_pull.smart_filter import SeedingConfig, apply_relational_filter
from snapshot_pull.snapshot import save_snapshot

logging.basicConfig(level=logging.INFO, format="  %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull snapshot data from Airbyte connector")
    parser.add_argument("--service", required=True)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--image", required=True, help="airbyte/source-xxx image")
    parser.add_argument("--streams", default="", help="Comma-separated stream names")
    parser.add_argument("--config-env", action="append", default=[], help="ENV=path.to.key")
    parser.add_argument(
        "--stream-mapping",
        action="append",
        default=[],
        help="stream_name=resource_name",
    )
    parser.add_argument("--seeding-json", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--backend", default="pyairbyte")
    parser.add_argument("--no-redact", action="store_true")
    parser.add_argument("--incremental", action="store_true")
    return parser.parse_args()


def parse_mappings(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        mapping[key.strip()] = value.strip()
    return mapping


def set_nested(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    keys = dotted_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def build_connector_config(config_env: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    config: dict[str, Any] = {}
    missing: list[str] = []
    for env_var, config_path in config_env.items():
        value = os.environ.get(env_var)
        if value is None or value.strip() == "":
            missing.append(env_var)
            continue
        set_nested(config, config_path, value)
    return config, missing


def build_limits(config: SeedingConfig) -> dict[str, int]:
    limits: dict[str, int] = {}
    for seed in config.seed_streams:
        if seed.limit is not None:
            limits[seed.stream] = seed.limit
    if config.default_limit is not None:
        for stream in config.all_stream_names():
            limits.setdefault(stream, config.default_limit)
    return limits


def map_streams(
    resources: dict[str, list[dict[str, Any]]],
    stream_mapping: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    mapped: dict[str, list[dict[str, Any]]] = {}
    for stream_name, rows in resources.items():
        resource_name = stream_mapping.get(stream_name, stream_name)
        mapped.setdefault(resource_name, []).extend(rows)
    return mapped


def main() -> None:
    args = parse_args()
    if args.backend != "pyairbyte":
        raise SystemExit(
            f"Unsupported backend '{args.backend}'. Supported backends: pyairbyte"
        )

    config_env = parse_mappings(args.config_env)
    stream_mapping = parse_mappings(args.stream_mapping)
    connector_config, missing_env = build_connector_config(config_env)
    if missing_env:
        raise SystemExit(
            f"Missing required connector env vars: {', '.join(sorted(set(missing_env)))}"
        )

    from snapshot_pull.pyairbyte_backend import PyAirbyteBackend, image_to_connector_name

    connector_name = image_to_connector_name(args.image)
    backend = PyAirbyteBackend(connector_name, connector_config)

    selected_streams = [s.strip() for s in args.streams.split(",") if s.strip()]
    if not selected_streams:
        selected_streams = backend.discover_streams()

    seeding_config: SeedingConfig | None = None
    if args.seeding_json:
        seeding_config = SeedingConfig.from_dict(json.loads(args.seeding_json))
        needed_streams = seeding_config.all_stream_names()
        selected_streams = [s for s in selected_streams if s in needed_streams]

    limits = build_limits(seeding_config) if seeding_config is not None else None
    resources = backend.pull_streams(
        selected_streams,
        per_stream_limits=limits,
        global_limit=args.limit,
    )
    if not resources:
        logger.warning("No records pulled")
        return

    if seeding_config is not None:
        before = sum(len(rows) for rows in resources.values())
        resources = apply_relational_filter(resources, seeding_config)
        after = sum(len(rows) for rows in resources.values())
        logger.info("  relational filter: %d -> %d records", before, after)

    resources = map_streams(resources, stream_mapping)

    if not args.no_redact:
        redactor = PiiRedactor()
        resources = {
            resource: redactor.redact_resources(rows)
            for resource, rows in resources.items()
        }

    snapshot_path = save_snapshot(
        service=args.service,
        profile=args.profile,
        resources=resources,
        connector_name=f"airbyte:{args.image}",
        redacted=not args.no_redact,
        incremental=args.incremental,
    )

    total = sum(len(rows) for rows in resources.values())
    logger.info("  snapshot saved: %s", snapshot_path)
    logger.info("  total records: %d", total)
    for resource_name in sorted(resources):
        logger.info("    %s: %d", resource_name, len(resources[resource_name]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

