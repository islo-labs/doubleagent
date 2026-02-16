"""Entry point for ``doubleagent snapshot pull <service>`` (Airbyte connectors).

Invoked by the Rust CLI as::

    uv run python -m snapshot_pull \
        --service <service> --profile <profile> \
        --image <docker-image> \
        [--streams stream1,stream2] \
        [--config-env KEY=path.to.config ...] \
        [--stream-mapping airbyte_name=da_name ...] \
        [--seeding-json '{"seed_streams": [...]}'] \
        [--limit N] [--no-redact] [--incremental]

Uses PyAirbyte (pip-installable, no Docker needed).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from snapshot_pull.snapshot import save_snapshot, save_snapshot_incremental

logging.basicConfig(level=logging.INFO, format="  %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull a snapshot using an Airbyte source connector"
    )
    p.add_argument("--service", required=True)
    p.add_argument("--profile", default="default")
    p.add_argument("--image", required=True, help="Airbyte connector image name")
    p.add_argument("--streams", default="", help="Comma-separated Airbyte streams")
    p.add_argument("--config-env", nargs="*", default=[], help="ENV_VAR=dotted.config.path")
    p.add_argument("--stream-mapping", nargs="*", default=[], help="airbyte_name=da_name")
    p.add_argument("--seeding-json", default=None, help="JSON SeedingConfig")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-redact", action="store_true")
    p.add_argument("--incremental", action="store_true")
    return p.parse_args()


def parse_config_env(config_env_args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for mapping in config_env_args:
        if "=" not in mapping:
            continue
        env_var, config_path = mapping.split("=", 1)
        result[env_var] = config_path
    return result


def parse_stream_mapping(mapping_args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for mapping in mapping_args:
        if "=" not in mapping:
            continue
        ab_name, da_name = mapping.split("=", 1)
        result[ab_name] = da_name
    return result


def build_connector_config(config_env: dict[str, str]) -> dict[str, Any]:
    """Build Airbyte connector config JSON from env var mappings."""
    config: dict[str, Any] = {}
    for env_var, config_path in config_env.items():
        value = os.environ.get(env_var)
        if not value:
            logger.warning("Env var %s not set (mapped to %s)", env_var, config_path)
            continue
        _set_nested(config, config_path, value)
    return config


def _set_nested(d: dict[str, Any], dotted_path: str, value: Any) -> None:
    keys = dotted_path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def apply_stream_mapping(
    resources: dict[str, list[dict[str, Any]]],
    stream_mapping: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    if not stream_mapping:
        return resources
    return {stream_mapping.get(name, name): records for name, records in resources.items()}


def main() -> None:
    args = parse_args()

    config_env = parse_config_env(args.config_env)
    stream_mapping = parse_stream_mapping(args.stream_mapping)
    streams = [s.strip() for s in args.streams.split(",") if s.strip()]

    # Parse seeding config
    seeding_config = None
    if args.seeding_json:
        from snapshot_pull.smart_filter import SeedingConfig
        seeding_config = SeedingConfig.from_dict(json.loads(args.seeding_json))

    connector_config = build_connector_config(config_env)

    logger.info("Airbyte pull: %s → %s/%s", args.image, args.service, args.profile)

    # Pull via PyAirbyte
    from snapshot_pull.pyairbyte_backend import PyAirbyteBackend, image_to_connector_name

    connector_name = image_to_connector_name(args.image)
    logger.info("Using PyAirbyte backend: %s", connector_name)

    backend = PyAirbyteBackend(connector_name, connector_config)

    if not streams:
        streams = backend.discover_streams()

    # Narrow streams for smart seeding
    if seeding_config:
        needed = seeding_config.all_stream_names()
        streams = [s for s in streams if s in needed]
        logger.info("  Smart seeding: pulling %d streams", len(streams))

    # Build per-stream limits
    per_stream_limits: dict[str, int] = {}
    if seeding_config:
        for sc in seeding_config.seed_streams:
            if sc.limit is not None:
                per_stream_limits[sc.stream] = sc.limit
        if seeding_config.default_limit:
            for s in streams:
                if s not in per_stream_limits:
                    per_stream_limits[s] = seeding_config.default_limit

    resources = backend.pull_streams(
        streams,
        per_stream_limits=per_stream_limits if per_stream_limits else None,
        global_limit=args.limit,
    )

    if not resources:
        print("Warning: No records pulled. Check connector config and credentials.", file=sys.stderr)
        sys.exit(0)

    # Smart filtering
    if seeding_config:
        from snapshot_pull.smart_filter import apply_relational_filter
        before = sum(len(v) for v in resources.values())
        resources = apply_relational_filter(resources, seeding_config)
        after = sum(len(v) for v in resources.values())
        logger.info("  Smart filter: %d → %d records", before, after)

    # Stream name mapping
    resources = apply_stream_mapping(resources, stream_mapping)

    # PII redaction
    if not args.no_redact:
        from snapshot_pull.redactor import PiiRedactor
        redactor = PiiRedactor()
        for rtype, items in resources.items():
            redactor.redact_resources(items)

    # Save
    saver = save_snapshot_incremental if args.incremental else save_snapshot
    path = saver(
        service=args.service,
        profile=args.profile,
        resources=resources,
        connector_name=f"airbyte:{args.image}",
        redacted=not args.no_redact,
    )
    logger.info("  Snapshot saved to %s", path)

    total = sum(len(v) for v in resources.values())
    for rtype, items in sorted(resources.items()):
        logger.info("    %s: %d records", rtype, len(items))
    logger.info("  Done: %d records across %d streams", total, len(resources))


if __name__ == "__main__":
    main()
