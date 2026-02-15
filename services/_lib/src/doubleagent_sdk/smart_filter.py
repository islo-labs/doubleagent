"""Smart filtering for DoubleAgent snapshot seeding.

Implements relational following and per-stream sampling on raw records
already pulled from an Airbyte source.  This module is a pure
data-transformation layer — it never calls any external API.

Example seeding config in service.yaml::

    seeding:
      default_limit: 50
      seed_streams:
        - stream: projects
          limit: 3
          follow:
            - child_stream: issues
              foreign_key: project_id
              limit_per_parent: 10
        - stream: issues
          follow:
            - child_stream: comments
              foreign_key: issue_id
              limit_per_parent: 5
        - stream: users
          limit: 20
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Config dataclasses
# =============================================================================


@dataclass
class FollowRule:
    """Declares a parent-to-child relationship between streams."""

    child_stream: str
    foreign_key: str  # field on child records that references parent
    parent_key: str = "id"  # field on parent records (default: "id")
    limit_per_parent: int | None = None  # max children per parent

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FollowRule":
        return cls(
            child_stream=data["child_stream"],
            foreign_key=data["foreign_key"],
            parent_key=data.get("parent_key", "id"),
            limit_per_parent=data.get("limit_per_parent"),
        )


@dataclass
class SeedStreamConfig:
    """Configuration for pulling a single stream during smart seeding."""

    stream: str
    limit: int | None = None
    follow: list[FollowRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeedStreamConfig":
        follow = [FollowRule.from_dict(f) for f in data.get("follow", [])]
        return cls(
            stream=data["stream"],
            limit=data.get("limit"),
            follow=follow,
        )


@dataclass
class SeedingConfig:
    """Top-level seeding configuration, parsed from service.yaml."""

    seed_streams: list[SeedStreamConfig] = field(default_factory=list)
    default_limit: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeedingConfig":
        seed_streams = [
            SeedStreamConfig.from_dict(s) for s in data.get("seed_streams", [])
        ]
        return cls(
            seed_streams=seed_streams,
            default_limit=data.get("default_limit"),
        )

    def all_stream_names(self) -> set[str]:
        """Return all stream names referenced in the config (roots + children)."""
        names: set[str] = set()
        for sc in self.seed_streams:
            names.add(sc.stream)
            for rule in sc.follow:
                names.add(rule.child_stream)
        return names


# =============================================================================
# Relational filter
# =============================================================================


def apply_relational_filter(
    all_records: dict[str, list[dict[str, Any]]],
    config: SeedingConfig,
) -> dict[str, list[dict[str, Any]]]:
    """Apply relational following and per-stream limits.

    Algorithm (breadth-first):
    1. For each seed_stream, take up to ``limit`` records (the "roots").
    2. For each follow rule: collect parent keys, filter child stream,
       cap by ``limit_per_parent``.
    3. Child streams can have their own follow rules (looked up from
       seed_streams by name).
    4. Streams not reachable from seed_streams are excluded.
    5. Records reachable via multiple paths are deduplicated by ``id``.
    """
    # Index seed_stream configs by stream name for follow-rule lookup
    stream_configs: dict[str, SeedStreamConfig] = {
        sc.stream: sc for sc in config.seed_streams
    }

    # Output: stream_name -> {id -> record} (deduplication by id)
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    # Track which streams need processing: (stream_name, parent_keys_or_None)
    # parent_keys=None means this is a root stream (apply its own limit)
    queue: list[tuple[str, set[Any] | None, FollowRule | None]] = []

    # Determine which streams are reached via follow rules (not roots)
    child_streams: set[str] = set()
    for sc in config.seed_streams:
        for rule in sc.follow:
            child_streams.add(rule.child_stream)

    # Enqueue root streams: those with an explicit limit, or those
    # not reachable as children of any follow rule.  Streams that
    # appear in seed_streams ONLY to define their own follow rules
    # (no limit, reachable via follow) are skipped here — they'll
    # be processed when reached via the follow queue.
    for sc in config.seed_streams:
        if sc.stream not in all_records:
            continue
        is_child = sc.stream in child_streams
        if sc.limit is not None or not is_child:
            queue.append((sc.stream, None, None))

    visited_edges: set[tuple[str, str]] = set()  # prevent infinite loops

    while queue:
        stream_name, parent_keys, follow_rule = queue.pop(0)
        raw = all_records.get(stream_name, [])

        if parent_keys is not None and follow_rule is not None:
            # This stream was reached via a follow rule — filter by FK
            filtered = _filter_by_foreign_key(
                raw,
                follow_rule.foreign_key,
                parent_keys,
                follow_rule.limit_per_parent,
            )
        else:
            # Root stream — apply its own limit
            sc = stream_configs.get(stream_name)
            limit = (sc.limit if sc and sc.limit is not None else config.default_limit)
            filtered = raw[:limit] if limit is not None else list(raw)

        # Add to output (deduplicate by id)
        for record in filtered:
            rid = str(record.get("id", id(record)))
            output[stream_name][rid] = record

        # Process follow rules for this stream
        sc = stream_configs.get(stream_name)
        if sc:
            for rule in sc.follow:
                edge = (stream_name, rule.child_stream)
                if edge in visited_edges:
                    continue
                visited_edges.add(edge)

                # Collect parent keys from the filtered records
                pkeys = _collect_keys(filtered, rule.parent_key)
                if pkeys and rule.child_stream in all_records:
                    queue.append((rule.child_stream, pkeys, rule))

    # Convert output from {stream: {id: record}} to {stream: [records]}
    return {
        stream: list(records.values())
        for stream, records in output.items()
        if records  # skip empty streams
    }


def _collect_keys(
    records: list[dict[str, Any]],
    key_field: str,
) -> set[Any]:
    """Extract the set of values for a given field from records."""
    keys: set[Any] = set()
    for record in records:
        val = record.get(key_field)
        if val is not None:
            keys.add(str(val))  # normalize to string for consistent matching
    return keys


def _filter_by_foreign_key(
    records: list[dict[str, Any]],
    foreign_key: str,
    allowed_values: set[Any],
    limit_per_parent: int | None = None,
) -> list[dict[str, Any]]:
    """Keep only records whose foreign_key value is in allowed_values.

    If ``limit_per_parent`` is set, cap the number of records per
    unique foreign key value.
    """
    if limit_per_parent is None:
        return [
            r for r in records
            if str(r.get(foreign_key, "")) in allowed_values
        ]

    # Group by FK value, cap each group
    counts: dict[str, int] = defaultdict(int)
    result: list[dict[str, Any]] = []
    for r in records:
        fk_val = str(r.get(foreign_key, ""))
        if fk_val in allowed_values:
            if counts[fk_val] < limit_per_parent:
                result.append(r)
                counts[fk_val] += 1
    return result
