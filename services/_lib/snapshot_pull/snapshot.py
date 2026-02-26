"""Snapshot writer for Airbyte pull results."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any


@dataclass
class SnapshotManifest:
    service: str
    profile: str
    version: int = 1
    pulled_at: float = field(default_factory=lambda: time.time())
    connector: str = ""
    redacted: bool = True
    resource_counts: dict[str, int] = field(default_factory=dict)


def default_snapshots_dir() -> Path:
    base = os.environ.get("DOUBLEAGENT_SNAPSHOTS_DIR")
    if base:
        return Path(base)
    return Path.home() / ".doubleagent" / "snapshots"


def snapshot_dir(service: str, profile: str) -> Path:
    return default_snapshots_dir() / service / profile


def _record_id(record: dict[str, Any], fallback_index: int) -> str:
    rid = record.get("id")
    if rid is None:
        return f"idx-{fallback_index}"
    return str(rid)


def _merge_records(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}

    for idx, row in enumerate(existing):
        merged[_record_id(row, idx)] = row
    for idx, row in enumerate(incoming):
        merged[_record_id(row, idx)] = row

    return list(merged.values())


def _load_resource_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _load_seed_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, list)}
    return {}


def save_snapshot(
    *,
    service: str,
    profile: str,
    resources: dict[str, list[dict[str, Any]]],
    connector_name: str,
    redacted: bool,
    incremental: bool = False,
) -> Path:
    sdir = snapshot_dir(service, profile)
    sdir.mkdir(parents=True, exist_ok=True)

    merged_resources: dict[str, list[dict[str, Any]]] = {}
    for resource_name, rows in resources.items():
        resource_path = sdir / f"{resource_name}.json"
        existing_rows = _load_resource_file(resource_path) if incremental else []
        merged_rows = _merge_records(existing_rows, rows) if incremental else rows
        merged_resources[resource_name] = merged_rows
        resource_path.write_text(json.dumps(merged_rows, indent=2, default=str))

    seed_path = sdir / "seed.json"
    existing_seed = _load_seed_file(seed_path) if incremental else {}
    for resource_name, rows in merged_resources.items():
        existing_seed[resource_name] = rows
    seed_path.write_text(json.dumps(existing_seed, indent=2, default=str))

    manifest = SnapshotManifest(
        service=service,
        profile=profile,
        connector=connector_name,
        redacted=redacted,
        resource_counts={k: len(v) for k, v in existing_seed.items()},
    )
    (sdir / "manifest.json").write_text(json.dumps(asdict(manifest), indent=2))

    return sdir

