"""
Linear GraphQL API Fake - DoubleAgent Service

A high-fidelity fake of the Linear GraphQL API for AI agent testing.
Built with FastAPI for async support.

Linear API Notes:
- All API calls are POST to /graphql
- Request body: {"query": "...", "variables": {...}}
- Response: {"data": {...}} or {"errors": [...]}
- Authentication via Bearer token in Authorization header
"""

import asyncio
import os
import time
import uuid as _uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Header, Query
from graphql import FieldNode, OperationDefinitionNode, parse as gql_parse
from pydantic import BaseModel


# =============================================================================
# State
# =============================================================================

DEFAULT_TEAM_ID = "team-00000001"
DEFAULT_USER_ID = "user-00000001"

DEFAULT_WORKFLOW_STATES = {
    "state-todo": {
        "id": "state-todo",
        "name": "Todo",
        "type": "unstarted",
        "color": "#e2e2e2",
    },
    "state-inprogress": {
        "id": "state-inprogress",
        "name": "In Progress",
        "type": "started",
        "color": "#f2c94c",
    },
    "state-done": {
        "id": "state-done",
        "name": "Done",
        "type": "completed",
        "color": "#5e6ad2",
    },
    "state-canceled": {
        "id": "state-canceled",
        "name": "Canceled",
        "type": "cancelled",
        "color": "#95a2b3",
    },
}

DEFAULT_TEAM = {
    "id": DEFAULT_TEAM_ID,
    "name": "DoubleAgent",
    "key": "DA",
    "description": "Default team",
}

DEFAULT_USER = {
    "id": DEFAULT_USER_ID,
    "name": "DoubleAgent User",
    "displayName": "DoubleAgent",
    "email": "doubleagent@example.com",
    "active": True,
}

state: dict[str, Any] = {
    "teams": {DEFAULT_TEAM_ID: DEFAULT_TEAM},
    "users": {DEFAULT_USER_ID: DEFAULT_USER},
    "issues": {},
    "projects": {},
    "webhooks": [],
    "event_log": [],
}

counters: dict[str, int] = {
    "issue_number": 0,
    "project_number": 0,
}


def new_id() -> str:
    return str(_uuid.uuid4())


def new_issue_id() -> str:
    counters["issue_number"] += 1
    return f"issue-{counters['issue_number']:08d}"


def new_project_id() -> str:
    counters["project_number"] += 1
    return f"project-{counters['project_number']:08d}"


def reset_state() -> None:
    global state, counters
    state = {
        "teams": {DEFAULT_TEAM_ID: DEFAULT_TEAM},
        "users": {DEFAULT_USER_ID: DEFAULT_USER},
        "issues": {},
        "projects": {},
        "webhooks": [],
        "event_log": [],
    }
    counters = {
        "issue_number": 0,
        "project_number": 0,
    }


def now() -> str:
    return "2024-01-01T00:00:00.000Z"


# =============================================================================
# Pydantic Models
# =============================================================================

class GraphQLRequest(BaseModel):
    query: str
    variables: Optional[dict[str, Any]] = None
    operationName: Optional[str] = None


class SeedData(BaseModel):
    teams: list[dict[str, Any]] = []
    users: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    webhooks: list[dict[str, Any]] = []


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Linear GraphQL API Fake",
    description="DoubleAgent fake of the Linear GraphQL API",
    version="1.0.0",
    lifespan=lifespan,
)


def gql_error(message: str, code: str = "BAD_REQUEST") -> dict:
    """Return a GraphQL-style error response."""
    return {"errors": [{"message": message, "extensions": {"code": code}}]}


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

    if data.teams:
        for t in data.teams:
            team_id = t.get("id") or new_id()
            state["teams"][team_id] = {
                "id": team_id,
                "name": t["name"],
                "key": t.get("key", t["name"][:3].upper()),
                "description": t.get("description", ""),
            }
        seeded["teams"] = len(data.teams)

    if data.users:
        for u in data.users:
            user_id = u.get("id") or new_id()
            state["users"][user_id] = {
                "id": user_id,
                "name": u["name"],
                "displayName": u.get("displayName", u["name"]),
                "email": u.get("email", ""),
                "active": u.get("active", True),
            }
        seeded["users"] = len(data.users)

    if data.issues:
        for i in data.issues:
            issue_id = i.get("id") or new_issue_id()
            team_id = i.get("teamId", DEFAULT_TEAM_ID)
            state_id = i.get("stateId", "state-todo")
            assignee_id = i.get("assigneeId")
            state["issues"][issue_id] = {
                "id": issue_id,
                "title": i["title"],
                "description": i.get("description", ""),
                "priority": i.get("priority", 0),
                "state": DEFAULT_WORKFLOW_STATES.get(
                    state_id, DEFAULT_WORKFLOW_STATES["state-todo"]
                ),
                "team": state["teams"].get(team_id, DEFAULT_TEAM),
                "assignee": state["users"].get(assignee_id) if assignee_id else None,
                "createdAt": i.get("createdAt", now()),
                "updatedAt": i.get("updatedAt", now()),
            }
        seeded["issues"] = len(data.issues)

    if data.projects:
        for p in data.projects:
            project_id = p.get("id") or new_project_id()
            state["projects"][project_id] = {
                "id": project_id,
                "name": p["name"],
                "description": p.get("description", ""),
                "state": p.get("state", "planned"),
                "createdAt": p.get("createdAt", now()),
                "updatedAt": p.get("updatedAt", now()),
            }
        seeded["projects"] = len(data.projects)

    if data.webhooks:
        for w in data.webhooks:
            state["webhooks"].append({
                "url": w["url"],
                "events": w.get("events", ["*"]),
                "active": w.get("active", True),
            })
        seeded["webhooks"] = len(data.webhooks)

    return {"status": "ok", "seeded": seeded}


@app.get("/_doubleagent/info")
async def info():
    """Service info - OPTIONAL."""
    return {
        "name": "linear",
        "version": "1.0",
        "endpoints": {
            "teams": len(state["teams"]),
            "users": len(state["users"]),
            "issues": len(state["issues"]),
            "projects": len(state["projects"]),
        },
    }


@app.get("/_doubleagent/events")
async def get_events(limit: int = Query(default=50, le=500)):
    """
    Get event dispatch log for debugging.

    Returns a list of all webhook dispatch attempts with their status.
    Useful for verifying webhooks were sent and diagnosing delivery issues.
    """
    events = state["event_log"][-limit:]
    return {
        "total": len(state["event_log"]),
        "returned": len(events),
        "events": events,
    }


@app.delete("/_doubleagent/events")
async def clear_events():
    """Clear the event log."""
    state["event_log"] = []
    return {"status": "ok"}


# =============================================================================
# GraphQL Endpoint
# =============================================================================

def get_root_fields(query: str) -> list[str]:
    """Parse a GraphQL query and return the root field names."""
    try:
        doc = gql_parse(query)
        fields = []
        for defn in doc.definitions:
            if isinstance(defn, OperationDefinitionNode):
                for sel in defn.selection_set.selections:
                    if isinstance(sel, FieldNode):
                        fields.append(sel.name.value)
        return fields
    except Exception:
        return []


@app.post("/graphql")
async def graphql_endpoint(
    request: GraphQLRequest,
    authorization: Optional[str] = Header(None),
):
    """Main Linear GraphQL endpoint."""
    if not authorization or not authorization.startswith("Bearer "):
        return gql_error("Unauthorized", "UNAUTHORIZED")

    root_fields = get_root_fields(request.query)
    if not root_fields:
        return gql_error("Failed to parse query", "BAD_REQUEST")

    variables = request.variables or {}
    data: dict[str, Any] = {}

    for field in root_fields:
        result = await handle_field(field, variables)
        if "errors" in result:
            return result
        data.update(result.get("data", {}))

    return {"data": data}


async def handle_field(field: str, variables: dict) -> dict:
    """Dispatch a GraphQL root field to the appropriate handler."""
    handlers: dict[str, Any] = {
        # Queries
        "viewer": handle_viewer,
        "teams": handle_teams,
        "team": handle_team,
        "issues": handle_issues,
        "issue": handle_issue,
        "projects": handle_projects,
        "project": handle_project,
        # Mutations
        "issueCreate": handle_issue_create,
        "issueUpdate": handle_issue_update,
        "issueDelete": handle_issue_delete,
        "projectCreate": handle_project_create,
        "projectUpdate": handle_project_update,
    }

    handler = handlers.get(field)
    if not handler:
        return gql_error(f"Unknown field: {field}", "BAD_REQUEST")

    return await handler(variables)


# =============================================================================
# Query Handlers
# =============================================================================

async def handle_viewer(variables: dict) -> dict:
    return {"data": {"viewer": DEFAULT_USER}}


async def handle_teams(variables: dict) -> dict:
    teams = list(state["teams"].values())
    return {"data": {"teams": {"nodes": teams}}}


async def handle_team(variables: dict) -> dict:
    team_id = variables.get("id")
    if team_id not in state["teams"]:
        return gql_error(f"Team not found: {team_id}", "NOT_FOUND")
    return {"data": {"team": state["teams"][team_id]}}


async def handle_issues(variables: dict) -> dict:
    filter_input = variables.get("filter", {})
    first = variables.get("first", 50)

    issues = list(state["issues"].values())

    if filter_input:
        team_id_eq = (
            filter_input.get("team", {}).get("id", {}).get("eq")
        )
        if team_id_eq:
            issues = [i for i in issues if i.get("team", {}).get("id") == team_id_eq]

        state_name_eq = (
            filter_input.get("state", {}).get("name", {}).get("eq")
        )
        if state_name_eq:
            issues = [
                i for i in issues if i.get("state", {}).get("name") == state_name_eq
            ]

        priority_eq = filter_input.get("priority", {}).get("eq")
        if priority_eq is not None:
            issues = [i for i in issues if i.get("priority") == priority_eq]

    issues = issues[:first]
    return {"data": {"issues": {"nodes": issues}}}


async def handle_issue(variables: dict) -> dict:
    issue_id = variables.get("id")
    if issue_id not in state["issues"]:
        return gql_error(f"Issue not found: {issue_id}", "NOT_FOUND")
    return {"data": {"issue": state["issues"][issue_id]}}


async def handle_projects(variables: dict) -> dict:
    first = variables.get("first", 50)
    projects = list(state["projects"].values())[:first]
    return {"data": {"projects": {"nodes": projects}}}


async def handle_project(variables: dict) -> dict:
    project_id = variables.get("id")
    if project_id not in state["projects"]:
        return gql_error(f"Project not found: {project_id}", "NOT_FOUND")
    return {"data": {"project": state["projects"][project_id]}}


# =============================================================================
# Mutation Handlers
# =============================================================================

async def handle_issue_create(variables: dict) -> dict:
    input_data = variables.get("input", {})

    if not input_data.get("title"):
        return gql_error("title is required", "BAD_USER_INPUT")

    issue_id = new_issue_id()
    team_id = input_data.get("teamId", DEFAULT_TEAM_ID)
    state_id = input_data.get("stateId", "state-todo")
    assignee_id = input_data.get("assigneeId")

    issue = {
        "id": issue_id,
        "title": input_data["title"],
        "description": input_data.get("description", ""),
        "priority": input_data.get("priority", 0),
        "state": DEFAULT_WORKFLOW_STATES.get(
            state_id, DEFAULT_WORKFLOW_STATES["state-todo"]
        ),
        "team": state["teams"].get(team_id, DEFAULT_TEAM),
        "assignee": state["users"].get(assignee_id) if assignee_id else None,
        "createdAt": now(),
        "updatedAt": now(),
    }
    state["issues"][issue_id] = issue

    await dispatch_event("Issue", "create", {"issue": issue})

    return {"data": {"issueCreate": {"success": True, "issue": issue}}}


async def handle_issue_update(variables: dict) -> dict:
    issue_id = variables.get("id")
    input_data = variables.get("input", {})

    if issue_id not in state["issues"]:
        return gql_error(f"Issue not found: {issue_id}", "NOT_FOUND")

    issue = state["issues"][issue_id]

    if "title" in input_data:
        issue["title"] = input_data["title"]
    if "description" in input_data:
        issue["description"] = input_data["description"]
    if "priority" in input_data:
        issue["priority"] = input_data["priority"]
    if "stateId" in input_data:
        state_id = input_data["stateId"]
        issue["state"] = DEFAULT_WORKFLOW_STATES.get(state_id, issue["state"])
    if "assigneeId" in input_data:
        assignee_id = input_data["assigneeId"]
        issue["assignee"] = state["users"].get(assignee_id)

    issue["updatedAt"] = now()

    await dispatch_event("Issue", "update", {"issue": issue})

    return {"data": {"issueUpdate": {"success": True, "issue": issue}}}


async def handle_issue_delete(variables: dict) -> dict:
    issue_id = variables.get("id")

    if issue_id not in state["issues"]:
        return gql_error(f"Issue not found: {issue_id}", "NOT_FOUND")

    del state["issues"][issue_id]

    return {"data": {"issueDelete": {"success": True}}}


async def handle_project_create(variables: dict) -> dict:
    input_data = variables.get("input", {})

    if not input_data.get("name"):
        return gql_error("name is required", "BAD_USER_INPUT")

    project_id = new_project_id()

    project = {
        "id": project_id,
        "name": input_data["name"],
        "description": input_data.get("description", ""),
        "state": input_data.get("state", "planned"),
        "createdAt": now(),
        "updatedAt": now(),
    }
    state["projects"][project_id] = project

    await dispatch_event("Project", "create", {"project": project})

    return {"data": {"projectCreate": {"success": True, "project": project}}}


async def handle_project_update(variables: dict) -> dict:
    project_id = variables.get("id")
    input_data = variables.get("input", {})

    if project_id not in state["projects"]:
        return gql_error(f"Project not found: {project_id}", "NOT_FOUND")

    project = state["projects"][project_id]

    if "name" in input_data:
        project["name"] = input_data["name"]
    if "description" in input_data:
        project["description"] = input_data["description"]
    if "state" in input_data:
        project["state"] = input_data["state"]

    project["updatedAt"] = now()

    return {"data": {"projectUpdate": {"success": True, "project": project}}}


# =============================================================================
# Webhook / Event Dispatch
# =============================================================================

async def dispatch_event(resource_type: str, action: str, payload: dict) -> None:
    """Dispatch events to registered webhooks."""
    for i, webhook in enumerate(state["webhooks"]):
        if not webhook.get("active", True):
            continue

        event_data = {
            "type": resource_type,
            "action": action,
            "data": payload,
            "createdAt": now(),
        }

        asyncio.create_task(
            _send_event(webhook["url"], resource_type, action, event_data, i)
        )


async def _send_event(
    url: str, resource_type: str, action: str, payload: dict, webhook_index: int
) -> None:
    """Send event to webhook (runs as background task) and log the result."""
    event_record = {
        "timestamp": time.time(),
        "webhook_index": webhook_index,
        "resource_type": resource_type,
        "action": action,
        "url": url,
        "status": "pending",
        "response_code": None,
        "error": None,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5.0,
            )
            event_record["status"] = "delivered"
            event_record["response_code"] = resp.status_code
    except httpx.TimeoutException:
        event_record["status"] = "timeout"
        event_record["error"] = "Request timed out after 5s"
    except httpx.ConnectError as e:
        event_record["status"] = "connection_failed"
        event_record["error"] = f"Connection failed: {str(e)}"
    except Exception as e:
        event_record["status"] = "error"
        event_record["error"] = str(e)

    state["event_log"].append(event_record)

    # Keep log bounded (max 1000 events)
    if len(state["event_log"]) > 1000:
        state["event_log"] = state["event_log"][-1000:]


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8086))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
