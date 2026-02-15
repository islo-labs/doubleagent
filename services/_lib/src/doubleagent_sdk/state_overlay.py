"""Copy-on-write state overlay for DoubleAgent fakes.

Provides a two-layer state model:
  - **baseline**: immutable snapshot data loaded on start (or empty)
  - **overlay**: mutable layer that captures all writes

Reads fall through overlay → baseline.  Deletes record a tombstone so
baseline values are hidden without mutation.  ``reset()`` clears overlay +
tombstones, returning to the snapshot baseline.
"""

from __future__ import annotations

import copy
from typing import Any, Callable


class StateOverlay:
    """Copy-on-write state: reads fall through to baseline, writes go to overlay."""

    def __init__(self, baseline: dict[str, dict[str, Any]] | None = None) -> None:
        # baseline: resource_type -> resource_id -> obj
        self._baseline: dict[str, dict[str, Any]] = baseline or {}
        # overlay: resource_type -> resource_id -> obj  (mutable writes)
        self._overlay: dict[str, dict[str, Any]] = {}
        # tombstones: set of "resource_type:resource_id" for deleted keys
        self._tombstones: set[str] = set()
        # counters: resource_type -> next id (auto-increment)
        self._counters: dict[str, int] = {}

    # ------------------------------------------------------------------
    # ID generation
    # ------------------------------------------------------------------

    def next_id(self, resource_type: str) -> int:
        """Return the next auto-increment id for *resource_type*.

        Initialised to max(existing ids) + 1 on first call so snapshot
        baseline ids are never reused.
        """
        if resource_type not in self._counters:
            max_id = 0
            for store in (self._baseline, self._overlay):
                for rid in store.get(resource_type, {}):
                    try:
                        max_id = max(max_id, int(rid))
                    except (ValueError, TypeError):
                        pass
            self._counters[resource_type] = max_id
        self._counters[resource_type] += 1
        return self._counters[resource_type]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def get(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
        """Return a resource by type + id, or ``None`` if missing/deleted.

        Returns a **deep copy** of baseline objects so callers can mutate
        without corrupting the immutable baseline layer.
        """
        key = f"{resource_type}:{resource_id}"
        if key in self._tombstones:
            return None
        obj = self._overlay.get(resource_type, {}).get(resource_id)
        if obj is not None:
            return obj
        baseline_obj = self._baseline.get(resource_type, {}).get(resource_id)
        if baseline_obj is not None:
            return copy.deepcopy(baseline_obj)
        return None

    def put(self, resource_type: str, resource_id: str, obj: dict[str, Any]) -> None:
        """Create or update a resource in the overlay."""
        self._overlay.setdefault(resource_type, {})[resource_id] = obj
        self._tombstones.discard(f"{resource_type}:{resource_id}")

    def delete(self, resource_type: str, resource_id: str) -> bool:
        """Mark a resource as deleted.  Returns ``True`` if it existed."""
        key = f"{resource_type}:{resource_id}"
        existed = self.get(resource_type, resource_id) is not None
        self._overlay.get(resource_type, {}).pop(resource_id, None)
        self._tombstones.add(key)
        return existed

    def list_all(
        self,
        resource_type: str,
        filter_fn: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Return all live resources of *resource_type*, optionally filtered.

        Baseline items are deep-copied to protect the immutable layer.
        """
        # Deep-copy baseline, then overlay (overlay wins on key collision)
        merged: dict[str, Any] = {
            k: copy.deepcopy(v)
            for k, v in self._baseline.get(resource_type, {}).items()
        }
        merged.update(self._overlay.get(resource_type, {}))
        items = [
            v
            for k, v in merged.items()
            if f"{resource_type}:{k}" not in self._tombstones
        ]
        if filter_fn:
            items = [i for i in items if filter_fn(i)]
        return items

    def count(self, resource_type: str) -> int:
        """Return the count of live resources of *resource_type*."""
        return len(self.list_all(resource_type))

    # ------------------------------------------------------------------
    # Reset semantics
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset to snapshot baseline — clears overlay and tombstones."""
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def reset_hard(self) -> None:
        """Reset to empty — clears baseline, overlay, and tombstones."""
        self._baseline.clear()
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    # ------------------------------------------------------------------
    # Bootstrap / seed
    # ------------------------------------------------------------------

    def load_baseline(self, data: dict[str, dict[str, Any]]) -> None:
        """Replace baseline with *data* and clear overlay.

        Called by ``/_doubleagent/bootstrap`` after snapshot load.
        """
        self._baseline = data
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def seed(self, data: dict[str, dict[str, Any]]) -> dict[str, int]:
        """Merge *data* into overlay (baseline preserved beneath).

        Returns a dict of resource_type → count seeded.
        """
        counts: dict[str, int] = {}
        for rtype, resources in data.items():
            for rid, obj in resources.items():
                self.put(rtype, rid, obj)
            counts[rtype] = len(resources)
        return counts

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def resource_types(self) -> set[str]:
        """Return the set of known resource types across baseline + overlay."""
        return set(self._baseline.keys()) | set(self._overlay.keys())

    def stats(self) -> dict[str, Any]:
        """Return diagnostic stats about the state layers."""
        return {
            "baseline_types": {k: len(v) for k, v in self._baseline.items()},
            "overlay_types": {k: len(v) for k, v in self._overlay.items()},
            "tombstone_count": len(self._tombstones),
            "has_baseline": bool(self._baseline),
        }

    def snapshot_profile(self) -> dict[str, dict[str, Any]]:
        """Return a deep copy of the baseline (for inspection)."""
        return copy.deepcopy(self._baseline)
