"""Smart relational filtering for pulled records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FollowRule:
    child_stream: str
    foreign_key: str
    parent_key: str = "id"
    limit_per_parent: int | None = None

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
    stream: str
    limit: int | None = None
    follow: list[FollowRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeedStreamConfig":
        return cls(
            stream=data["stream"],
            limit=data.get("limit"),
            follow=[FollowRule.from_dict(f) for f in data.get("follow", [])],
        )


@dataclass
class SeedingConfig:
    seed_streams: list[SeedStreamConfig] = field(default_factory=list)
    default_limit: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SeedingConfig":
        return cls(
            seed_streams=[
                SeedStreamConfig.from_dict(s) for s in data.get("seed_streams", [])
            ],
            default_limit=data.get("default_limit"),
        )

    def all_stream_names(self) -> set[str]:
        names: set[str] = set()
        for stream_cfg in self.seed_streams:
            names.add(stream_cfg.stream)
            for rule in stream_cfg.follow:
                names.add(rule.child_stream)
        return names


def _collect_keys(records: list[dict[str, Any]], key: str) -> set[str]:
    result: set[str] = set()
    for row in records:
        value = row.get(key)
        if value is not None:
            result.add(str(value))
    return result


def _filter_children(
    records: list[dict[str, Any]],
    foreign_key: str,
    allowed_parent_ids: set[str],
    limit_per_parent: int | None,
) -> list[dict[str, Any]]:
    if limit_per_parent is None:
        return [
            row for row in records if str(row.get(foreign_key, "")) in allowed_parent_ids
        ]

    per_parent_count: dict[str, int] = defaultdict(int)
    result: list[dict[str, Any]] = []
    for row in records:
        parent_id = str(row.get(foreign_key, ""))
        if parent_id not in allowed_parent_ids:
            continue
        if per_parent_count[parent_id] >= limit_per_parent:
            continue
        per_parent_count[parent_id] += 1
        result.append(row)
    return result


def apply_relational_filter(
    resources: dict[str, list[dict[str, Any]]],
    config: SeedingConfig,
) -> dict[str, list[dict[str, Any]]]:
    stream_cfg = {s.stream: s for s in config.seed_streams}
    output: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    queue: list[tuple[str, set[str] | None, FollowRule | None]] = []
    visited_edges: set[tuple[str, str]] = set()

    for root in config.seed_streams:
        queue.append((root.stream, None, None))

    while queue:
        stream_name, parent_ids, follow_rule = queue.pop(0)
        rows = resources.get(stream_name, [])

        if parent_ids is not None and follow_rule is not None:
            selected = _filter_children(
                rows,
                follow_rule.foreign_key,
                parent_ids,
                follow_rule.limit_per_parent,
            )
        else:
            limit = stream_cfg.get(stream_name, SeedStreamConfig(stream=stream_name)).limit
            if limit is None:
                limit = config.default_limit
            selected = rows[:limit] if limit is not None else list(rows)

        for row in selected:
            record_id = str(row.get("id", id(row)))
            output[stream_name][record_id] = row

        cfg = stream_cfg.get(stream_name)
        if not cfg:
            continue

        for rule in cfg.follow:
            edge = (stream_name, rule.child_stream)
            if edge in visited_edges:
                continue
            visited_edges.add(edge)

            child_rows = resources.get(rule.child_stream, [])
            if not child_rows:
                continue

            ids = _collect_keys(selected, rule.parent_key)
            if ids:
                queue.append((rule.child_stream, ids, rule))

    return {
        stream: list(id_map.values()) for stream, id_map in output.items() if id_map
    }

