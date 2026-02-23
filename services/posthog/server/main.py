"""
PostHog Analytics API Fake - DoubleAgent Service

A fake of the PostHog API for AI agent testing.
Built with FastAPI.

PostHog API Notes:
- Auth is via `api_key` in the JSON body, not headers
- Events flow through a single `/batch/` endpoint
- Feature flags are evaluated via `/flags/?v=2`
- The SDK does NOT parse the `/batch/` response body (only checks HTTP 200)
"""

import os
import time
import json
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# =============================================================================
# State
# =============================================================================

state: dict[str, Any] = {
    "events": [],           # All captured events (append-only)
    "persons": {},          # distinct_id -> {distinct_id, properties}
    "groups": {},           # "type:key" -> {type, key, properties}
    "feature_flags": {},    # flag_key -> {key, enabled, variant, payload, filters, ...}
}


def reset_state() -> None:
    global state
    state = {
        "events": [],
        "persons": {},
        "groups": {},
        "feature_flags": {},
    }


# =============================================================================
# Pydantic Models
# =============================================================================

class SeedData(BaseModel):
    feature_flags: list[dict[str, Any]] = []
    persons: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="PostHog Analytics API Fake",
    description="DoubleAgent fake of the PostHog Analytics API",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# /_doubleagent endpoints (REQUIRED)
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    """Health check - REQUIRED."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    """Reset all state - REQUIRED."""
    reset_state()
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(data: SeedData):
    """Seed state from JSON - REQUIRED."""
    seeded: dict[str, int] = {}

    if data.feature_flags:
        for f in data.feature_flags:
            key = f["key"]
            state["feature_flags"][key] = {
                "key": key,
                "enabled": f.get("enabled", True),
                "variant": f.get("variant"),
                "payload": f.get("payload"),
                "filters": f.get("filters", {}),
            }
        seeded["feature_flags"] = len(data.feature_flags)

    if data.persons:
        for p in data.persons:
            distinct_id = p["distinct_id"]
            state["persons"][distinct_id] = {
                "distinct_id": distinct_id,
                "properties": p.get("properties", {}),
            }
        seeded["persons"] = len(data.persons)

    if data.groups:
        for g in data.groups:
            group_key = f"{g['type']}:{g['key']}"
            state["groups"][group_key] = {
                "type": g["type"],
                "key": g["key"],
                "properties": g.get("properties", {}),
            }
        seeded["groups"] = len(data.groups)

    if data.events:
        for e in data.events:
            state["events"].append(e)
        seeded["events"] = len(data.events)

    return {"status": "ok", "seeded": seeded}


@app.get("/_doubleagent/events")
async def get_events(
    event: Optional[str] = Query(None),
    distinct_id: Optional[str] = Query(None),
    limit: int = Query(default=100, le=1000),
):
    """Query captured events, optionally filtered by event name or distinct_id."""
    events = state["events"]

    if event:
        events = [e for e in events if e.get("event") == event]
    if distinct_id:
        events = [e for e in events if e.get("distinct_id") == distinct_id]

    events = events[-limit:]

    return {
        "total": len(state["events"]),
        "returned": len(events),
        "events": events,
    }


@app.get("/_doubleagent/persons")
async def get_persons():
    """Get all person profiles."""
    return {"persons": state["persons"]}


@app.get("/_doubleagent/groups")
async def get_groups():
    """Get all group profiles."""
    return {"groups": state["groups"]}


# =============================================================================
# PostHog API: /batch/ - Event Ingestion
# =============================================================================

@app.post("/batch/")
@app.post("/batch")
async def batch(request: Request):
    """
    Batch event ingestion endpoint.

    The PostHog SDK sends all events here: capture(), set(), set_once(),
    group_identify(), alias(). Auth is via api_key in the JSON body.

    The SDK does NOT parse the response body — it only checks for HTTP 200.
    """
    body = await request.json()
    batch_events = body.get("batch", [])

    for event_msg in batch_events:
        event_name = event_msg.get("event", "")
        distinct_id = event_msg.get("distinct_id", "")
        properties = event_msg.get("properties", {})

        # Store the event
        stored_event = {
            "event": event_name,
            "distinct_id": distinct_id,
            "properties": properties,
            "timestamp": event_msg.get("timestamp", ""),
        }
        state["events"].append(stored_event)

        # Process side effects based on event type
        if event_name == "$set":
            _process_set(distinct_id, event_msg.get("$set", {}))

        elif event_name == "$set_once":
            _process_set_once(distinct_id, event_msg.get("$set_once", {}))

        elif event_name == "$groupidentify":
            _process_group_identify(properties)

        else:
            # Regular capture events may also carry $set/$set_once in properties
            if "$set" in properties:
                _process_set(distinct_id, properties["$set"])
            if "$set_once" in properties:
                _process_set_once(distinct_id, properties["$set_once"])

    return JSONResponse(content={"status": 1}, status_code=200)


def _process_set(distinct_id: str, set_props: dict) -> None:
    """Apply $set properties to a person profile (overwrites existing)."""
    if not distinct_id or not set_props:
        return
    if distinct_id not in state["persons"]:
        state["persons"][distinct_id] = {
            "distinct_id": distinct_id,
            "properties": {},
        }
    state["persons"][distinct_id]["properties"].update(set_props)


def _process_set_once(distinct_id: str, set_once_props: dict) -> None:
    """Apply $set_once properties to a person profile (only sets if not already present)."""
    if not distinct_id or not set_once_props:
        return
    if distinct_id not in state["persons"]:
        state["persons"][distinct_id] = {
            "distinct_id": distinct_id,
            "properties": {},
        }
    for k, v in set_once_props.items():
        if k not in state["persons"][distinct_id]["properties"]:
            state["persons"][distinct_id]["properties"][k] = v


def _process_group_identify(properties: dict) -> None:
    """Process a $groupidentify event to create/update a group profile."""
    group_type = properties.get("$group_type", "")
    group_key = properties.get("$group_key", "")
    group_set = properties.get("$group_set", {})

    if not group_type or not group_key:
        return

    storage_key = f"{group_type}:{group_key}"
    if storage_key not in state["groups"]:
        state["groups"][storage_key] = {
            "type": group_type,
            "key": group_key,
            "properties": {},
        }
    state["groups"][storage_key]["properties"].update(group_set)


# =============================================================================
# PostHog API: /flags/?v=2 - Feature Flag Evaluation (v2 format)
# =============================================================================

@app.post("/flags/")
@app.post("/flags")
async def flags(request: Request):
    """
    Feature flag evaluation endpoint (v2 format).

    Called by feature_enabled(), get_feature_flag(), get_all_flags(),
    and get_feature_flag_payload(). Returns per-flag objects with
    key, enabled, variant, reason, and metadata.
    """
    body = await request.json()
    flag_keys_to_evaluate = body.get("flag_keys_to_evaluate")

    flags_to_eval = state["feature_flags"]
    if flag_keys_to_evaluate:
        flags_to_eval = {
            k: v for k, v in flags_to_eval.items()
            if k in flag_keys_to_evaluate
        }

    flags_response = {}
    for key, flag_def in flags_to_eval.items():
        enabled = flag_def.get("enabled", False)
        variant = flag_def.get("variant")
        payload = flag_def.get("payload")

        flag_obj: dict[str, Any] = {
            "key": key,
            "enabled": enabled,
            "variant": variant if enabled else None,
            "reason": {
                "code": "matched_condition" if enabled else "no_matching_condition",
                "condition_index": 0 if enabled else None,
                "description": "Matched condition set 1" if enabled else "No matching condition",
            },
            "metadata": {
                "id": hash(key) % 10000,
                "version": 1,
            },
        }

        if payload is not None and enabled:
            flag_obj["metadata"]["payload"] = payload

        flags_response[key] = flag_obj

    return {
        "flags": flags_response,
        "requestId": f"fake-{int(time.time())}",
        "evaluatedAt": int(time.time()),
        "errorsWhileComputingFlags": False,
        "quotaLimited": [],
    }


# =============================================================================
# PostHog API: /decide/ - Legacy Feature Flag Evaluation
# =============================================================================

@app.post("/decide/")
@app.post("/decide")
async def decide(request: Request):
    """
    Legacy feature flag evaluation endpoint.

    Returns the older featureFlags/featureFlagPayloads format.
    The current SDK (v7+) uses /flags/?v=2 instead, but this
    endpoint is kept for compatibility.
    """
    feature_flags: dict[str, Any] = {}
    feature_flag_payloads: dict[str, str] = {}

    for key, flag_def in state["feature_flags"].items():
        enabled = flag_def.get("enabled", False)
        variant = flag_def.get("variant")
        payload = flag_def.get("payload")

        if enabled:
            feature_flags[key] = variant if variant else True
            if payload is not None:
                feature_flag_payloads[key] = payload
        else:
            feature_flags[key] = False

    return {
        "featureFlags": feature_flags,
        "featureFlagPayloads": feature_flag_payloads,
    }


# =============================================================================
# PostHog API: /api/feature_flag/local_evaluation/ - Flag Definitions
# =============================================================================

@app.get("/api/feature_flag/local_evaluation/")
@app.get("/api/feature_flag/local_evaluation")
async def local_evaluation(
    token: Optional[str] = Query(None),
    send_cohorts: Optional[str] = Query(None),
):
    """
    Feature flag definitions for local evaluation.

    Called by the SDK's load_feature_flags() when personal_api_key is set.
    Returns flag definitions with filters for client-side evaluation.
    """
    flags_list = []
    for i, (key, flag_def) in enumerate(state["feature_flags"].items()):
        enabled = flag_def.get("enabled", False)
        variant = flag_def.get("variant")
        payload = flag_def.get("payload")
        filters = flag_def.get("filters", {})

        # Build a minimal flag definition
        flag_definition: dict[str, Any] = {
            "id": i + 1,
            "name": key,
            "key": key,
            "active": enabled,
            "is_simple_flag": False,
            "ensure_experience_continuity": False,
            "filters": filters if filters else {
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100 if enabled else 0,
                    }
                ],
            },
        }

        # Add multivariate config if variant is specified
        if variant and "multivariate" not in flag_definition["filters"]:
            flag_definition["filters"]["multivariate"] = {
                "variants": [
                    {"key": variant, "rollout_percentage": 100},
                ]
            }

        # Add payloads if specified
        if payload is not None and "payloads" not in flag_definition["filters"]:
            lookup_key = variant if variant else "true"
            flag_definition["filters"]["payloads"] = {
                lookup_key: payload,
            }

        flags_list.append(flag_definition)

    return {
        "flags": flags_list,
        "group_type_mapping": {},
        "cohorts": {},
    }


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8084))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
