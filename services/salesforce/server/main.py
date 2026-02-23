"""
Salesforce CRM API Fake — DoubleAgent Service

Read-only snapshot server for Salesforce data pulled via Airbyte connector.
Serves snapshot data as a REST API with standard DoubleAgent control-plane endpoints.

Endpoints:
    GET  /resources                     -> list available resource types
    GET  /resources/{type}              -> list resources (with filtering)
    GET  /resources/{type}/{id}         -> get single resource by ID
    /_doubleagent/*                     -> control plane (health, reset, seed)
"""

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request


# =============================================================================
# State
# =============================================================================

state: dict[str, dict[str, Any]] = {}


# =============================================================================
# App
# =============================================================================

app = FastAPI(
    title="Salesforce API Fake",
    description="DoubleAgent fake of the Salesforce CRM REST API (read-only snapshot server)",
    version="0.1.0",
)


# =============================================================================
# /_doubleagent control plane
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    global state
    state = {}
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(request: Request):
    body = await request.json()
    counts: dict[str, int] = {}
    for rtype, resources in body.items():
        if isinstance(resources, dict):
            state.setdefault(rtype, {}).update(resources)
            counts[rtype] = len(resources)
    return {"status": "ok", "seeded": counts}


# =============================================================================
# Resource explorer endpoints (read-only)
# =============================================================================

@app.get("/resources")
async def list_resource_types():
    """List all available resource types and their counts."""
    result = {rtype: len(items) for rtype, items in sorted(state.items())}
    return {"resource_types": result, "total_types": len(result)}


@app.get("/resources/{resource_type}")
async def list_resources(
    resource_type: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    q: Optional[str] = Query(default=None, description="Filter: field=value"),
):
    """List resources of a given type with optional filtering."""
    items = list(state.get(resource_type, {}).values())

    if q:
        parts = q.split("=", 1)
        if len(parts) == 2:
            field, value = parts
            items = [r for r in items if str(r.get(field, "")) == value]

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
async def get_resource(resource_type: str, resource_id: str):
    """Get a single resource by type and ID."""
    collection = state.get(resource_type, {})
    obj = collection.get(resource_id)
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
    port = int(os.environ.get("PORT", 8091))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
