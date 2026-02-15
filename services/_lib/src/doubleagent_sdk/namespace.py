"""Per-agent namespace isolation.

All namespaces share the same immutable snapshot baseline but get
independent mutable overlays.  The namespace is communicated via
the ``X-DoubleAgent-Namespace`` HTTP header (default: ``"default"``).
"""

from __future__ import annotations

import copy
from typing import Any

from doubleagent_sdk.state_overlay import StateOverlay

NAMESPACE_HEADER = "X-DoubleAgent-Namespace"
DEFAULT_NAMESPACE = "default"


class NamespaceRouter:
    """Manages isolated :class:`StateOverlay` instances keyed by namespace."""

    def __init__(self, baseline: dict[str, dict[str, Any]] | None = None) -> None:
        self._baseline: dict[str, dict[str, Any]] = baseline or {}
        self._namespaces: dict[str, StateOverlay] = {}

    def get_state(self, namespace: str | None = None) -> StateOverlay:
        """Return (or lazily create) the :class:`StateOverlay` for *namespace*."""
        ns = namespace or DEFAULT_NAMESPACE
        if ns not in self._namespaces:
            # Each namespace gets its own overlay but shares the baseline
            # We use the same baseline dict (read-only) for memory efficiency
            self._namespaces[ns] = StateOverlay(baseline=self._baseline)
        return self._namespaces[ns]

    def load_baseline(self, data: dict[str, dict[str, Any]]) -> None:
        """Replace the shared baseline and reset all namespace overlays."""
        self._baseline = data
        for overlay in self._namespaces.values():
            overlay.load_baseline(data)

    def reset_namespace(self, namespace: str | None = None, *, hard: bool = False) -> None:
        """Reset a single namespace overlay (or hard-reset to empty)."""
        ns = namespace or DEFAULT_NAMESPACE
        if ns in self._namespaces:
            if hard:
                self._namespaces[ns].reset_hard()
            else:
                self._namespaces[ns].reset()

    def reset_all(self, *, hard: bool = False) -> None:
        """Reset every namespace."""
        for ns in list(self._namespaces):
            self.reset_namespace(ns, hard=hard)

    def list_namespaces(self) -> list[dict[str, Any]]:
        """Return metadata about active namespaces."""
        result = []
        for ns, overlay in self._namespaces.items():
            stats = overlay.stats()
            result.append({"namespace": ns, **stats})
        return result

    def delete_namespace(self, namespace: str) -> bool:
        """Remove a namespace entirely.  Returns True if it existed."""
        return self._namespaces.pop(namespace, None) is not None
