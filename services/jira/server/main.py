"""
Jira Cloud API Fake — DoubleAgent Service

Read-only snapshot server for Jira data pulled via Airbyte connector.
Serves snapshot data as a REST API with COW state, namespace isolation,
and standard DoubleAgent control-plane endpoints.

Endpoints:
    GET  /resources                     → list available resource types
    GET  /resources/{type}              → list resources (with filtering)
    GET  /resources/{type}/{id}         → get single resource by ID
    /_doubleagent/*                     → control plane (health, reset, seed, bootstrap, etc.)
"""

import copy
import os
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Query, Request

# =============================================================================
# Namespace constants
# =============================================================================

NAMESPACE_HEADER = "X-DoubleAgent-Namespace"
DEFAULT_NAMESPACE = "default"


# =============================================================================
# Copy-on-write state overlay
# =============================================================================

class StateOverlay:
    """Copy-on-write state: reads fall through to baseline, writes go to overlay."""

    def __init__(self, baseline: dict[str, dict[str, Any]] | None = None) -> None:
        self._baseline: dict[str, dict[str, Any]] = baseline or {}
        self._overlay: dict[str, dict[str, Any]] = {}
        self._tombstones: set[str] = set()
        self._counters: dict[str, int] = {}

    def next_id(self, resource_type: str) -> int:
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

    def get(self, resource_type: str, resource_id: str) -> dict[str, Any] | None:
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
        self._overlay.setdefault(resource_type, {})[resource_id] = obj
        self._tombstones.discard(f"{resource_type}:{resource_id}")

    def delete(self, resource_type: str, resource_id: str) -> bool:
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
        return len(self.list_all(resource_type))

    def reset(self) -> None:
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def reset_hard(self) -> None:
        self._baseline.clear()
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def load_baseline(self, data: dict[str, dict[str, Any]]) -> None:
        self._baseline = data
        self._overlay.clear()
        self._tombstones.clear()
        self._counters.clear()

    def seed(self, data: dict[str, dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rtype, resources in data.items():
            for rid, obj in resources.items():
                self.put(rtype, rid, obj)
            counts[rtype] = len(resources)
        return counts

    def resource_types(self) -> set[str]:
        return set(self._baseline.keys()) | set(self._overlay.keys())

    def stats(self) -> dict[str, Any]:
        return {
            "baseline_types": {k: len(v) for k, v in self._baseline.items()},
            "overlay_types": {k: len(v) for k, v in self._overlay.items()},
            "tombstone_count": len(self._tombstones),
            "has_baseline": bool(self._baseline),
        }


# =============================================================================
# Namespace router
# =============================================================================

class NamespaceRouter:
    """Manages isolated StateOverlay instances keyed by namespace."""

    def __init__(self, baseline: dict[str, dict[str, Any]] | None = None) -> None:
        self._baseline: dict[str, dict[str, Any]] = baseline or {}
        self._namespaces: dict[str, StateOverlay] = {}

    def get_state(self, namespace: str | None = None) -> StateOverlay:
        ns = namespace or DEFAULT_NAMESPACE
        if ns not in self._namespaces:
            self._namespaces[ns] = StateOverlay(baseline=self._baseline)
        return self._namespaces[ns]

    def load_baseline(self, data: dict[str, dict[str, Any]]) -> None:
        self._baseline = data
        for overlay in self._namespaces.values():
            overlay.load_baseline(data)

    def reset_namespace(self, namespace: str | None = None, *, hard: bool = False) -> None:
        ns = namespace or DEFAULT_NAMESPACE
        if ns in self._namespaces:
            if hard:
                self._namespaces[ns].reset_hard()
            else:
                self._namespaces[ns].reset()

    def list_namespaces(self) -> list[dict[str, Any]]:
        result = []
        for ns, overlay in self._namespaces.items():
            stats = overlay.stats()
            result.append({"namespace": ns, **stats})
        return result


# =============================================================================
# State / helpers
# =============================================================================

router = NamespaceRouter()


def get_namespace(request: Request) -> str:
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)


def get_state(request: Request) -> StateOverlay:
    return router.get_state(get_namespace(request))


# =============================================================================
# App
# =============================================================================

app = FastAPI(
    title="Jira API Fake",
    description="DoubleAgent fake of the Jira Cloud REST API (read-only snapshot server)",
    version="0.1.0",
)


# =============================================================================
# /_doubleagent control plane
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset(request: Request, hard: bool = Query(default=False)):
    ns = get_namespace(request)
    router.reset_namespace(ns, hard=hard)
    mode = "hard (empty)" if hard else "baseline"
    return {"status": "ok", "reset_mode": mode, "namespace": ns}


@app.post("/_doubleagent/seed")
async def seed(request: Request):
    state = get_state(request)
    ns = get_namespace(request)
    body = await request.json()
    counts = state.seed(body)
    return {"status": "ok", "seeded": counts, "namespace": ns}


@app.post("/_doubleagent/bootstrap")
async def bootstrap(request: Request):
    body = await request.json()
    baseline: dict[str, dict[str, Any]] = {}
    for rtype, resources in body.items():
        if isinstance(resources, dict):
            baseline[rtype] = resources
    router.load_baseline(baseline)
    counts = {k: len(v) for k, v in baseline.items()}
    return {"status": "ok", "loaded": counts}


@app.get("/_doubleagent/info")
async def info(request: Request):
    state = get_state(request)
    return {
        "name": "jira",
        "version": "0.1",
        "namespace": get_namespace(request),
        "state": state.stats(),
    }


@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    return router.list_namespaces()


# =============================================================================
# Resource explorer endpoints (read-only)
# =============================================================================

@app.get("/resources")
async def list_resource_types(request: Request):
    """List all available resource types and their counts."""
    state = get_state(request)
    types = state.resource_types()
    result = {}
    for rtype in sorted(types):
        result[rtype] = state.count(rtype)
    return {"resource_types": result, "total_types": len(result)}


@app.get("/resources/{resource_type}")
async def list_resources(
    request: Request,
    resource_type: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None, description="Filter: field=value"),
):
    """List resources of a given type with optional filtering."""
    state = get_state(request)

    filter_fn = None
    if q:
        parts = q.split("=", 1)
        if len(parts) == 2:
            field, value = parts
            filter_fn = lambda r, f=field, v=value: str(r.get(f, "")) == v

    items = state.list_all(resource_type, filter_fn)
    total = len(items)
    items = items[offset : offset + limit]
    return {
        "resource_type": resource_type,
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }


@app.get("/resources/{resource_type}/{resource_id}")
async def get_resource(request: Request, resource_type: str, resource_id: str):
    """Get a single resource by type and ID."""
    state = get_state(request)
    obj = state.get(resource_type, resource_id)
    if obj is None:
        raise HTTPException(status_code=404, detail={
            "error": "not_found",
            "resource_type": resource_type,
            "resource_id": resource_id,
        })
    return obj


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8090))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
