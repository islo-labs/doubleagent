"""Snapshot storage: manifest, load, and save helpers.

Snapshots are stored as JSON files under
``~/.doubleagent/snapshots/<service>/<profile>/``:

    manifest.json        — metadata (service, version, timestamps, counts)
    repos.json           — array of resource objects
    issues.json
    ...
"""

from __future__ import annotations

import json
import hashlib
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class SnapshotManifest:
    service: str
    profile: str
    version: int = 1
    pulled_at: float = field(default_factory=time.time)
    connector: str = ""
    redacted: bool = True
    resource_counts: dict[str, int] = field(default_factory=dict)
    source_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SnapshotManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def default_snapshots_dir() -> Path:
    base = os.environ.get("DOUBLEAGENT_SNAPSHOTS_DIR")
    if base:
        return Path(base)
    return Path.home() / ".doubleagent" / "snapshots"


def snapshot_dir(service: str, profile: str) -> Path:
    return default_snapshots_dir() / service / profile


def save_snapshot(
    service: str,
    profile: str,
    resources: dict[str, list[dict[str, Any]]],
    *,
    connector_name: str = "",
    redacted: bool = True,
) -> Path:
    sdir = snapshot_dir(service, profile)
    sdir.mkdir(parents=True, exist_ok=True)

    resource_counts: dict[str, int] = {}
    all_bytes = b""
    for rtype, items in resources.items():
        data = json.dumps(items, indent=2, sort_keys=True, default=str)
        (sdir / f"{rtype}.json").write_text(data)
        resource_counts[rtype] = len(items)
        all_bytes += data.encode()

    source_hash = f"sha256:{hashlib.sha256(all_bytes).hexdigest()}"

    manifest = SnapshotManifest(
        service=service,
        profile=profile,
        connector=connector_name,
        redacted=redacted,
        resource_counts=resource_counts,
        source_hash=source_hash,
    )
    manifest_data = json.dumps(manifest.to_dict(), indent=2, default=str)
    (sdir / "manifest.json").write_text(manifest_data)

    return sdir


def save_snapshot_incremental(
    service: str,
    profile: str,
    resources: dict[str, list[dict[str, Any]]],
    *,
    connector_name: str = "",
    redacted: bool = True,
) -> Path:
    sdir = snapshot_dir(service, profile)
    manifest_path = sdir / "manifest.json"

    if not manifest_path.exists():
        return save_snapshot(
            service, profile, resources,
            connector_name=connector_name, redacted=redacted,
        )

    existing_manifest = SnapshotManifest.from_dict(json.loads(manifest_path.read_text()))
    merged: dict[str, list[dict[str, Any]]] = {}

    for rtype in set(list(existing_manifest.resource_counts.keys()) + list(resources.keys())):
        rtype_path = sdir / f"{rtype}.json"
        existing_items: list[dict[str, Any]] = []
        if rtype_path.exists():
            existing_items = json.loads(rtype_path.read_text())

        new_items = resources.get(rtype, [])
        existing_ids: set[str] = set()
        for item in existing_items:
            item_id = str(item.get("id", ""))
            if item_id:
                existing_ids.add(item_id)

        for item in new_items:
            item_id = str(item.get("id", ""))
            if item_id and item_id in existing_ids:
                continue
            existing_items.append(item)
            if item_id:
                existing_ids.add(item_id)

        merged[rtype] = existing_items

    return save_snapshot(
        service, profile, merged,
        connector_name=connector_name, redacted=redacted,
    )


def load_snapshot(service: str, profile: str) -> tuple[SnapshotManifest, dict[str, dict[str, Any]]]:
    sdir = snapshot_dir(service, profile)
    manifest_path = sdir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Snapshot '{profile}' not found for service '{service}'. "
            f"Expected at: {sdir}"
        )

    manifest = SnapshotManifest.from_dict(json.loads(manifest_path.read_text()))

    baseline: dict[str, dict[str, Any]] = {}
    for rtype in manifest.resource_counts:
        rtype_path = sdir / f"{rtype}.json"
        if rtype_path.exists():
            items = json.loads(rtype_path.read_text())
            keyed: dict[str, Any] = {}
            for i, item in enumerate(items):
                rid = str(item.get("id", i))
                keyed[rid] = item
            baseline[rtype] = keyed

    return manifest, baseline


def list_snapshots(service: str | None = None) -> list[dict[str, Any]]:
    base = default_snapshots_dir()
    if not base.exists():
        return []

    results: list[dict[str, Any]] = []
    service_dirs = [base / service] if service else [d for d in base.iterdir() if d.is_dir()]

    for svc_dir in service_dirs:
        if not svc_dir.is_dir():
            continue
        for profile_dir in svc_dir.iterdir():
            if not profile_dir.is_dir():
                continue
            manifest_path = profile_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    m = SnapshotManifest.from_dict(json.loads(manifest_path.read_text()))
                    results.append(m.to_dict())
                except Exception:
                    pass

    return results


def delete_snapshot(service: str, profile: str) -> bool:
    import shutil
    sdir = snapshot_dir(service, profile)
    if sdir.exists():
        shutil.rmtree(sdir)
        return True
    return False
