"""Generic snapshot explorer server for DoubleAgent.

Serves any Airbyte-pulled snapshot data as a read-only REST API.
Used by services that have an Airbyte connector but no custom fake
server (e.g., Jira, Salesforce).

Endpoints:
    GET  /resources                     → list available resource types
    GET  /resources/{type}              → list resources (with optional filtering)
    GET  /resources/{type}/{id}         → get single resource by ID

All standard /_doubleagent/* control-plane endpoints are supported:
    GET  /_doubleagent/health
    POST /_doubleagent/reset
    POST /_doubleagent/seed
    POST /_doubleagent/bootstrap
    GET  /_doubleagent/info
    GET  /_doubleagent/namespaces

Usage in service.yaml::

    server:
      command: ["uv", "run", "python", "-m", "doubleagent_sdk.generic_server"]
"""

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request

from doubleagent_sdk import NamespaceRouter, StateOverlay
from doubleagent_sdk.namespace import NAMESPACE_HEADER, DEFAULT_NAMESPACE


# =============================================================================
# Helpers
# =============================================================================

def get_namespace(request: Request) -> str:
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)


def get_state(request: Request) -> StateOverlay:
    return router.get_state(get_namespace(request))


# =============================================================================
# State
# =============================================================================

router = NamespaceRouter()


# =============================================================================
# App
# =============================================================================

app = FastAPI(
    title="DoubleAgent Snapshot Explorer",
    description="Generic read-only server for Airbyte-pulled snapshot data",
    version="1.0.0",
)


# =============================================================================
# /_doubleagent control-plane endpoints
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
    """Seed state from JSON.  Accepts any resource types."""
    state = get_state(request)
    ns = get_namespace(request)
    body = await request.json()
    counts = state.seed(body)
    return {"status": "ok", "seeded": counts, "namespace": ns}


@app.post("/_doubleagent/bootstrap")
async def bootstrap(request: Request):
    """Load snapshot baseline.  Called by CLI on start --snapshot."""
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
        "name": "snapshot-explorer",
        "version": "1.0",
        "type": "generic",
        "namespace": get_namespace(request),
        "state": state.stats(),
    }


@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    return router.list_namespaces()


# =============================================================================
# Resource explorer endpoints
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
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
