"""
Todoist API Fake - DoubleAgent Service

A high-fidelity fake of the Todoist API v1 for AI agent testing.
Built with FastAPI. The real API base is https://api.todoist.com/api/v1.

The SDK (todoist-api-python v3.x) sends requests to /api/v1/* paths,
so all resource endpoints will be mounted under /api/v1/.
"""

import os
import string
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel


# =============================================================================
# Helpers
# =============================================================================

def _now() -> str:
    """Return current UTC time in RFC3339 with microsecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _generate_id() -> str:
    """Generate a 16-character alphanumeric ID similar to Todoist's format."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=16))


def _next_label_id() -> str:
    """Generate a numeric label ID."""
    counters["label_id"] += 1
    return str(counters["label_id"])


def _next_order() -> int:
    """Generate next order value."""
    counters["order"] += 1
    return counters["order"]


# =============================================================================
# State
# =============================================================================

DEFAULT_USER_ID = "57605981"
INBOX_PROJECT_ID = _generate_id()


def _make_inbox_project() -> dict[str, Any]:
    """Create the default Inbox project."""
    now = _now()
    return {
        "id": INBOX_PROJECT_ID,
        "can_assign_tasks": False,
        "child_order": 0,
        "color": "grey",
        "creator_uid": DEFAULT_USER_ID,
        "created_at": now,
        "is_archived": False,
        "is_deleted": False,
        "is_favorite": False,
        "is_frozen": False,
        "name": "Inbox",
        "updated_at": now,
        "view_style": "list",
        "default_order": 0,
        "description": "",
        "public_access": False,
        "public_key": "",
        "access": {"visibility": "restricted", "configuration": {}},
        "role": "CREATOR",
        "parent_id": None,
        "inbox_project": True,
        "is_collapsed": False,
        "is_shared": False,
    }


def _initial_state() -> dict[str, dict]:
    """Return a fresh initial state with default Inbox project."""
    return {
        "tasks": {},
        "projects": {INBOX_PROJECT_ID: _make_inbox_project()},
        "sections": {},
        "comments": {},
        "labels": {},
    }


state: dict[str, dict] = _initial_state()

counters: dict[str, int] = {
    "label_id": 1000000000,
    "order": 0,
}


def reset_state() -> None:
    """Reset all state to initial defaults."""
    global state
    state = _initial_state()
    counters["label_id"] = 1000000000
    counters["order"] = 0


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="Todoist API Fake",
    description="DoubleAgent fake of the Todoist API v1",
    version="1.0.0",
    lifespan=lifespan,
)


# =============================================================================
# /_doubleagent control-plane endpoints
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    """Reset all state to initial defaults."""
    reset_state()
    return {"status": "ok"}


class SeedData(BaseModel):
    tasks: Optional[list[dict[str, Any]]] = None
    projects: Optional[list[dict[str, Any]]] = None
    sections: Optional[list[dict[str, Any]]] = None
    comments: Optional[list[dict[str, Any]]] = None
    labels: Optional[list[dict[str, Any]]] = None


@app.post("/_doubleagent/seed")
async def seed(data: SeedData):
    """Seed state from JSON payload."""
    seeded: dict[str, int] = {}

    if data.projects:
        for project in data.projects:
            pid = project.get("id", _generate_id())
            project["id"] = pid
            state["projects"][pid] = project
        seeded["projects"] = len(data.projects)

    if data.sections:
        for section in data.sections:
            sid = section.get("id", _generate_id())
            section["id"] = sid
            state["sections"][sid] = section
        seeded["sections"] = len(data.sections)

    if data.tasks:
        for task in data.tasks:
            tid = task.get("id", _generate_id())
            task["id"] = tid
            state["tasks"][tid] = task
        seeded["tasks"] = len(data.tasks)

    if data.comments:
        for comment in data.comments:
            cid = comment.get("id", _generate_id())
            comment["id"] = cid
            state["comments"][cid] = comment
        seeded["comments"] = len(data.comments)

    if data.labels:
        for label in data.labels:
            lid = label.get("id", _next_label_id())
            label["id"] = lid
            state["labels"][lid] = label
        seeded["labels"] = len(data.labels)

    return {"status": "ok", "seeded": seeded}


# =============================================================================
# Error helpers
# =============================================================================

def _error_response(
    http_code: int,
    error: str,
    error_tag: str,
    error_code: int,
    **extra_fields,
) -> JSONResponse:
    """Return a Todoist-style error response (NOT wrapped by FastAPI)."""
    error_extra: dict[str, Any] = {
        "event_id": _generate_id(),
        "retry_after": 2,
    }
    error_extra.update(extra_fields)
    return JSONResponse(
        status_code=http_code,
        content={
            "error": error,
            "error_code": error_code,
            "error_extra": error_extra,
            "error_tag": error_tag,
            "http_code": http_code,
        },
    )


def _not_found(resource: str) -> JSONResponse:
    return _error_response(404, f"{resource} not found", "NOT_FOUND", 478)


def _invalid_argument(argument: str, expected: str = "minlen", threshold: int = 1) -> JSONResponse:
    return _error_response(
        400,
        "Invalid argument value",
        "INVALID_ARGUMENT_VALUE",
        20,
        argument=argument,
        expected=expected,
        threshold=threshold,
    )


def _argument_missing(argument: str) -> JSONResponse:
    return _error_response(
        400,
        "Required argument is missing",
        "ARGUMENT_MISSING",
        19,
        argument=argument,
    )


# =============================================================================
# Task helpers
# =============================================================================

def _make_task(
    content: str,
    project_id: str | None = None,
    section_id: str | None = None,
    parent_id: str | None = None,
    description: str = "",
    priority: int = 1,
    labels: list[str] | None = None,
    due: dict | None = None,
    duration: dict | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Create a new task dict with proper v1 fields."""
    now = _now()
    return {
        "user_id": DEFAULT_USER_ID,
        "id": task_id or _generate_id(),
        "project_id": project_id or INBOX_PROJECT_ID,
        "section_id": section_id,
        "parent_id": parent_id,
        "added_by_uid": DEFAULT_USER_ID,
        "assigned_by_uid": None,
        "responsible_uid": None,
        "labels": labels if labels is not None else [],
        "deadline": None,
        "duration": duration,
        "checked": False,
        "is_deleted": False,
        "added_at": now,
        "completed_at": None,
        "completed_by_uid": None,
        "updated_at": now,
        "due": due,
        "priority": priority,
        "child_order": _next_order(),
        "content": content,
        "description": description,
        "note_count": 0,
        "day_order": -1,
        "is_collapsed": False,
    }


def _build_due_from_date(due_date: str) -> dict[str, Any]:
    """Build a due object from a date string (YYYY-MM-DD)."""
    return {
        "date": due_date,
        "timezone": None,
        "string": due_date,
        "lang": "en",
        "is_recurring": False,
    }


def _build_due_from_string(due_string: str, due_lang: str = "en") -> dict[str, Any]:
    """Build a due object from a natural-language string."""
    from datetime import timedelta
    import re

    now = datetime.now(timezone.utc)
    is_recurring = _is_recurring_string(due_string)
    s = due_string.lower().strip()

    # Try to extract a time from the string (e.g. "at 9am", "at 10pm")
    time_match = re.search(r'at\s+(\d{1,2})(am|pm)', due_string, re.IGNORECASE)
    has_time = time_match is not None
    hour = 10  # default
    if time_match:
        h = int(time_match.group(1))
        ampm = time_match.group(2).lower()
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        hour = h

    # Determine the target date based on the natural language string
    if s == "today" or s.startswith("today"):
        target = now
    elif s == "tomorrow" or s.startswith("tomorrow"):
        target = now + timedelta(days=1)
    elif "next week" in s:
        target = now + timedelta(days=7)
    elif "next month" in s:
        target = now + timedelta(days=30)
    elif is_recurring:
        target = now + timedelta(days=1)
    else:
        target = now + timedelta(days=1)

    # If a time component was specified, use datetime format; otherwise date-only
    if has_time:
        due_date = target.strftime(f"%Y-%m-%dT{hour:02d}:00:00")
    else:
        due_date = target.strftime("%Y-%m-%d")

    return {
        "date": due_date,
        "timezone": None,
        "string": due_string,
        "lang": due_lang,
        "is_recurring": is_recurring,
    }


def _is_recurring_string(due_string: str) -> bool:
    """Check if a due string represents a recurring task."""
    s = due_string.lower().strip()
    return s.startswith("every ") or s.startswith("daily") or s.startswith("weekly") or s.startswith("monthly")


def _advance_recurring_due(due: dict[str, Any]) -> dict[str, Any]:
    """Advance a recurring due date to the next occurrence."""
    from datetime import timedelta
    import re

    date_str = due.get("date", "")
    due_string = due.get("string", "").lower()

    # Determine the interval from the recurring string
    days = 1  # default to daily
    if "week" in due_string:
        days = 7
    elif "month" in due_string:
        days = 30
    elif "year" in due_string:
        days = 365

    # Parse the date and advance
    if "T" in date_str:
        # datetime format: YYYY-MM-DDTHH:MM:SS
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
            dt = dt + timedelta(days=days)
            new_date = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            # Try with Z suffix
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            dt = dt + timedelta(days=days)
            new_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        # date-only: YYYY-MM-DD
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            dt = dt + timedelta(days=days)
            new_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            new_date = date_str

    return {
        **due,
        "date": new_date,
    }


# =============================================================================
# Project helpers
# =============================================================================

def _make_project(
    name: str,
    description: str = "",
    parent_id: str | None = None,
    color: str = "charcoal",
    is_favorite: bool = False,
    view_style: str = "list",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Create a new project dict with proper v1 fields."""
    now = _now()
    return {
        "id": project_id or _generate_id(),
        "can_assign_tasks": False,
        "child_order": _next_order(),
        "color": color,
        "creator_uid": DEFAULT_USER_ID,
        "created_at": now,
        "is_archived": False,
        "is_deleted": False,
        "is_favorite": is_favorite,
        "is_frozen": False,
        "name": name,
        "updated_at": now,
        "view_style": view_style,
        "default_order": 0,
        "description": description,
        "public_access": False,
        "public_key": "",
        "access": {"visibility": "restricted", "configuration": {}},
        "role": "CREATOR",
        "parent_id": parent_id,
        "inbox_project": False,
        "is_collapsed": False,
        "is_shared": False,
    }


# =============================================================================
# Section helpers
# =============================================================================

def _make_section(
    name: str,
    project_id: str,
    order: int | None = None,
    section_id: str | None = None,
) -> dict[str, Any]:
    """Create a new section dict with proper v1 fields."""
    now = _now()
    return {
        "id": section_id or _generate_id(),
        "user_id": DEFAULT_USER_ID,
        "project_id": project_id,
        "added_at": now,
        "updated_at": now,
        "archived_at": None,
        "name": name,
        "section_order": order if order is not None else _next_order(),
        "is_archived": False,
        "is_deleted": False,
        "is_collapsed": False,
    }


# =============================================================================
# Task Endpoints
# =============================================================================

@app.post("/api/v1/tasks")
async def create_task(request: Request):
    """Create a new task. Returns 200 with task object."""
    body = await request.json()

    content = body.get("content")
    if content is None:
        return _argument_missing("content")
    if not content or len(content) == 0:
        return _invalid_argument("content", "minlen", 1)

    # Build due object if provided
    due = None
    if body.get("due_string"):
        due_string_val = body["due_string"]
        if due_string_val.lower().strip() == "no date":
            due = None
        else:
            due = _build_due_from_string(
                due_string_val,
                body.get("due_lang", "en"),
            )
    elif body.get("due_date"):
        due = _build_due_from_date(body["due_date"])
    elif body.get("due_datetime"):
        due = {
            "date": body["due_datetime"],
            "timezone": None,
            "string": body["due_datetime"],
            "lang": body.get("due_lang", "en"),
            "is_recurring": False,
        }

    # Build duration object if provided
    duration = None
    if body.get("duration") is not None:
        duration = {
            "amount": body["duration"],
            "unit": body.get("duration_unit", "minute"),
        }

    # Resolve project_id: if parent_id is set but project_id is not,
    # inherit project_id from the parent task (real API behavior).
    project_id = body.get("project_id")
    parent_id = body.get("parent_id")
    if parent_id and not project_id:
        parent_task = state["tasks"].get(parent_id)
        if parent_task:
            project_id = parent_task.get("project_id")

    task = _make_task(
        content=content,
        project_id=project_id,
        section_id=body.get("section_id"),
        parent_id=parent_id,
        description=body.get("description", ""),
        priority=body.get("priority", 1),
        labels=body.get("labels"),
        due=due,
        duration=duration,
    )

    state["tasks"][task["id"]] = task
    return JSONResponse(content=task, status_code=200)


@app.get("/api/v1/tasks")
async def list_tasks(request: Request):
    """List active tasks with optional filtering. Returns paginated envelope."""
    project_id = request.query_params.get("project_id")
    section_id = request.query_params.get("section_id")
    parent_id = request.query_params.get("parent_id")
    label = request.query_params.get("label")
    ids_param = request.query_params.get("ids")

    # If filtering by IDs, parse the comma-separated list
    ids_filter: set[str] | None = None
    if ids_param:
        ids_filter = set(ids_param.split(","))

    results = []
    for task in state["tasks"].values():
        # Skip deleted tasks
        if task.get("is_deleted", False):
            continue
        # Skip completed tasks
        if task.get("checked", False):
            continue
        # Filter by IDs (if provided, only include tasks whose id is in the set)
        if ids_filter is not None:
            if task["id"] not in ids_filter:
                continue
        else:
            # Other filters only apply when not filtering by IDs
            # Filter by project_id
            if project_id and task.get("project_id") != project_id:
                continue
            # Filter by section_id
            if section_id and task.get("section_id") != section_id:
                continue
            # Filter by parent_id
            if parent_id and task.get("parent_id") != parent_id:
                continue
            # Filter by label
            if label and label not in (task.get("labels") or []):
                continue
        results.append(task)

    return JSONResponse(content={"results": results, "next_cursor": None}, status_code=200)


# --- Filter tasks endpoint (MUST be before /tasks/{task_id} to avoid route conflict) ---

def _is_due_today(task: dict[str, Any]) -> bool:
    """Check if a task is due today."""
    due = task.get("due")
    if not due:
        return False
    date_str = due.get("date", "")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # date_str can be "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS" or "YYYY-MM-DDTHH:MM:SSZ"
    return date_str.startswith(today_str)


def _parse_filter_query(query: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse a Todoist filter query and return matching tasks.

    Supports basic filter syntax:
    - 'today' — tasks due today
    - 'p1' — priority 4 (urgent), 'p2' → priority 3, 'p3' → priority 2, 'p4' → priority 1
    - '&' — AND combinator
    - '|' — OR combinator
    - '#ProjectName' — tasks in a project by name
    - '@label' — tasks with a label
    """
    query = query.strip()

    # Handle AND queries: "today & p1"
    if "&" in query:
        parts = [p.strip() for p in query.split("&")]
        result = list(tasks)
        for part in parts:
            result = _parse_filter_query(part, result)
        return result

    # Handle OR queries: "today | tomorrow"
    if "|" in query:
        parts = [p.strip() for p in query.split("|")]
        seen_ids: set[str] = set()
        result: list[dict[str, Any]] = []
        for part in parts:
            for t in _parse_filter_query(part, tasks):
                if t["id"] not in seen_ids:
                    seen_ids.add(t["id"])
                    result.append(t)
        return result

    q = query.lower().strip()

    # Priority filters: p1=priority 4, p2=priority 3, p3=priority 2, p4=priority 1
    priority_map = {"p1": 4, "p2": 3, "p3": 2, "p4": 1}
    if q in priority_map:
        target_priority = priority_map[q]
        return [t for t in tasks if t.get("priority") == target_priority]

    # 'today' filter
    if q == "today":
        return [t for t in tasks if _is_due_today(t)]

    # 'overdue' filter
    if q == "overdue":
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [t for t in tasks if t.get("due") and t["due"].get("date", "9999")[:10] < today_str]

    # 'no date' filter
    if q == "no date":
        return [t for t in tasks if not t.get("due")]

    # Label filter: @label_name
    if q.startswith("@"):
        label_name = query.strip()[1:]  # preserve original case
        return [t for t in tasks if label_name in (t.get("labels") or [])]

    # Project filter: #project_name
    if q.startswith("#"):
        project_name = query.strip()[1:]
        # Find project ID by name
        target_pid = None
        for p in state["projects"].values():
            if p.get("name") == project_name:
                target_pid = p["id"]
                break
        if target_pid is None:
            return []
        return [t for t in tasks if t.get("project_id") == target_pid]

    # Fallback: return all tasks (unknown filter)
    return list(tasks)


@app.get("/api/v1/tasks/filter")
async def filter_tasks(request: Request):
    """Filter tasks using Todoist filter query syntax. Returns paginated envelope."""
    query = request.query_params.get("query", "")

    # Start with all active, non-deleted tasks
    active_tasks = []
    for task in state["tasks"].values():
        if task.get("is_deleted", False):
            continue
        if task.get("checked", False):
            continue
        active_tasks.append(task)

    # Apply filter query
    results = _parse_filter_query(query, active_tasks)

    return JSONResponse(content={"results": results, "next_cursor": None}, status_code=200)


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a single task by ID."""
    task = state["tasks"].get(task_id)
    if task is None:
        return _not_found("Task")
    return JSONResponse(content=task, status_code=200)


@app.post("/api/v1/tasks/{task_id}")
async def update_task(task_id: str, request: Request):
    """Update a task. Returns 200 with updated task object."""
    task = state["tasks"].get(task_id)
    if task is None:
        return _not_found("Task")

    body = await request.json()

    # Update simple fields if provided
    for field in ("content", "description", "priority"):
        if field in body:
            task[field] = body[field]

    if "labels" in body:
        task["labels"] = body["labels"]

    # Handle due date updates
    if "due_string" in body:
        due_string_val = body["due_string"]
        if due_string_val.lower().strip() == "no date":
            task["due"] = None
        else:
            task["due"] = _build_due_from_string(
                due_string_val,
                body.get("due_lang", "en"),
            )
    elif "due_date" in body:
        task["due"] = _build_due_from_date(body["due_date"])
    elif "due_datetime" in body:
        task["due"] = {
            "date": body["due_datetime"],
            "timezone": None,
            "string": body["due_datetime"],
            "lang": body.get("due_lang", "en"),
            "is_recurring": False,
        }

    # Handle duration updates
    if "duration" in body:
        if body["duration"] is None:
            task["duration"] = None
        else:
            task["duration"] = {
                "amount": body["duration"],
                "unit": body.get("duration_unit", "minute"),
            }

    task["updated_at"] = _now()
    return JSONResponse(content=task, status_code=200)


@app.delete("/api/v1/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task. Returns 204 empty body."""
    task = state["tasks"].get(task_id)
    if task is None:
        return _not_found("Task")
    # Soft-delete: mark as deleted
    task["is_deleted"] = True
    task["updated_at"] = _now()
    # Cascade: soft-delete all subtasks
    for t in state["tasks"].values():
        if t.get("parent_id") == task_id:
            t["is_deleted"] = True
            t["updated_at"] = _now()
    return Response(status_code=204)


@app.post("/api/v1/tasks/{task_id}/close")
async def close_task(task_id: str):
    """Complete (close) a task. Returns 204 empty body.

    Non-recurring tasks: sets checked=True, completed_at=now.
    Recurring tasks: advances due.date to next occurrence, remains active.
    Cascades to subtasks: all subtasks are closed (checked=True).
    """
    task = state["tasks"].get(task_id)
    if task is None:
        return _not_found("Task")

    now = _now()

    # Check if this is a recurring task
    due = task.get("due")
    if due and due.get("is_recurring", False):
        # Recurring: advance due date, keep task active
        task["due"] = _advance_recurring_due(due)
        task["updated_at"] = now
        # Do NOT set checked or completed_at
    else:
        # Non-recurring: mark as completed
        task["checked"] = True
        task["completed_at"] = now
        task["completed_by_uid"] = DEFAULT_USER_ID
        task["updated_at"] = now

    # Cascade: close all subtasks (subtasks are always closed outright, not rescheduled)
    for t in state["tasks"].values():
        if t.get("parent_id") == task_id and not t.get("is_deleted", False):
            t["checked"] = True
            t["completed_at"] = now
            t["completed_by_uid"] = DEFAULT_USER_ID
            t["updated_at"] = now

    return Response(status_code=204)


@app.post("/api/v1/tasks/{task_id}/reopen")
async def reopen_task(task_id: str):
    """Reopen a completed task. Returns 204 empty body.

    Sets checked=False, completed_at=null, completed_by_uid=null.
    """
    task = state["tasks"].get(task_id)
    if task is None:
        return _not_found("Task")

    task["checked"] = False
    task["completed_at"] = None
    task["completed_by_uid"] = None
    task["updated_at"] = _now()

    return Response(status_code=204)


# =============================================================================
# Project Endpoints
# =============================================================================

@app.post("/api/v1/projects")
async def create_project(request: Request):
    """Create a new project. Returns 200 with project object."""
    body = await request.json()

    name = body.get("name")
    if name is None:
        return _argument_missing("name")
    if not name or len(name) == 0:
        return _invalid_argument("name", "minlen", 1)

    project = _make_project(
        name=name,
        description=body.get("description", ""),
        parent_id=body.get("parent_id"),
        color=body.get("color", "charcoal"),
        is_favorite=body.get("is_favorite", False),
        view_style=body.get("view_style", "list"),
    )

    state["projects"][project["id"]] = project
    return JSONResponse(content=project, status_code=200)


@app.get("/api/v1/projects")
async def list_projects(request: Request):
    """List all active projects. Returns paginated envelope."""
    results = []
    for project in state["projects"].values():
        if project.get("is_deleted", False):
            continue
        if project.get("is_archived", False):
            continue
        results.append(project)
    return JSONResponse(content={"results": results, "next_cursor": None}, status_code=200)


@app.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str):
    """Get a single project by ID."""
    project = state["projects"].get(project_id)
    if project is None:
        return _not_found("Project")
    # Projects are hard-deleted, so if is_deleted=True, return 404
    if project.get("is_deleted", False):
        return _not_found("Project")
    return JSONResponse(content=project, status_code=200)


@app.post("/api/v1/projects/{project_id}")
async def update_project(project_id: str, request: Request):
    """Update a project. Returns 200 with updated project object."""
    project = state["projects"].get(project_id)
    if project is None or project.get("is_deleted", False):
        return _not_found("Project")

    body = await request.json()
    for field in ("name", "description", "color", "is_favorite", "view_style"):
        if field in body:
            project[field] = body[field]

    project["updated_at"] = _now()
    return JSONResponse(content=project, status_code=200)


@app.delete("/api/v1/projects/{project_id}")
async def delete_project(project_id: str):
    """Delete a project. Returns 204 empty body. Hard-delete."""
    project = state["projects"].get(project_id)
    if project is None or project.get("is_deleted", False):
        return _not_found("Project")

    # Hard-delete the project (remove from state so GET returns 404)
    del state["projects"][project_id]

    # Cascade: hard-delete all tasks in this project (remove so GET returns 404)
    task_ids_to_remove = [
        tid for tid, task in state["tasks"].items()
        if task.get("project_id") == project_id
    ]
    for tid in task_ids_to_remove:
        del state["tasks"][tid]

    # Cascade: delete all sections in this project
    section_ids_to_remove = [
        sid for sid, section in state["sections"].items()
        if section.get("project_id") == project_id
    ]
    for sid in section_ids_to_remove:
        del state["sections"][sid]

    return Response(status_code=204)


@app.post("/api/v1/projects/{project_id}/archive")
async def archive_project(project_id: str):
    """Archive a project. Returns 200 with project object."""
    project = state["projects"].get(project_id)
    if project is None:
        return _not_found("Project")

    project["is_archived"] = True
    project["updated_at"] = _now()
    return JSONResponse(content=project, status_code=200)


@app.post("/api/v1/projects/{project_id}/unarchive")
async def unarchive_project(project_id: str):
    """Unarchive a project. Returns 200 with project object."""
    project = state["projects"].get(project_id)
    if project is None:
        return _not_found("Project")

    project["is_archived"] = False
    project["updated_at"] = _now()
    return JSONResponse(content=project, status_code=200)


# =============================================================================
# Section Endpoints
# =============================================================================

@app.post("/api/v1/sections")
async def create_section(request: Request):
    """Create a new section. Returns 200 with section object."""
    body = await request.json()

    name = body.get("name")
    if name is None:
        return _argument_missing("name")

    project_id = body.get("project_id")
    if project_id is None:
        return _argument_missing("project_id")

    section = _make_section(
        name=name,
        project_id=project_id,
        order=body.get("order"),
    )

    state["sections"][section["id"]] = section
    return JSONResponse(content=section, status_code=200)


@app.get("/api/v1/sections")
async def list_sections(request: Request):
    """List sections with optional project_id filter. Returns paginated envelope."""
    project_id = request.query_params.get("project_id")
    results = []
    for section in state["sections"].values():
        if section.get("is_deleted", False):
            continue
        if project_id and section.get("project_id") != project_id:
            continue
        results.append(section)
    return JSONResponse(content={"results": results, "next_cursor": None}, status_code=200)


@app.get("/api/v1/sections/{section_id}")
async def get_section(section_id: str):
    """Get a single section by ID."""
    section = state["sections"].get(section_id)
    if section is None:
        return _not_found("Section")
    return JSONResponse(content=section, status_code=200)


@app.post("/api/v1/sections/{section_id}")
async def update_section(section_id: str, request: Request):
    """Update a section. Returns 200 with updated section object."""
    section = state["sections"].get(section_id)
    if section is None or section.get("is_deleted", False):
        return _not_found("Section")

    body = await request.json()
    if "name" in body:
        section["name"] = body["name"]

    section["updated_at"] = _now()
    return JSONResponse(content=section, status_code=200)


@app.delete("/api/v1/sections/{section_id}")
async def delete_section(section_id: str):
    """Delete a section. Returns 204 empty body."""
    section = state["sections"].get(section_id)
    if section is None or section.get("is_deleted", False):
        return _not_found("Section")
    section["is_deleted"] = True
    section["updated_at"] = _now()
    return Response(status_code=204)


# =============================================================================
# Label helpers
# =============================================================================

def _make_label(
    name: str,
    color: str = "charcoal",
    order: int | None = None,
    is_favorite: bool = False,
    label_id: str | None = None,
) -> dict[str, Any]:
    """Create a new label dict with proper v1 fields."""
    return {
        "id": label_id or _next_label_id(),
        "name": name,
        "color": color,
        "order": order if order is not None else _next_order(),
        "is_favorite": is_favorite,
    }


# =============================================================================
# Label Endpoints
# =============================================================================

@app.post("/api/v1/labels")
async def create_label(request: Request):
    """Create a new label. Returns 200 with label object."""
    body = await request.json()

    name = body.get("name")
    if name is None:
        return _argument_missing("name")
    if not name or len(name) == 0:
        return _invalid_argument("name", "minlen", 1)

    # The SDK sends `item_order` but API returns `order`
    order = body.get("item_order", body.get("order"))

    label = _make_label(
        name=name,
        color=body.get("color", "charcoal"),
        order=order,
        is_favorite=body.get("is_favorite", False),
    )

    state["labels"][label["id"]] = label
    return JSONResponse(content=label, status_code=200)


@app.get("/api/v1/labels")
async def list_labels(request: Request):
    """List all labels. Returns paginated envelope.
    Soft-deleted labels are excluded from the list.
    """
    results = []
    for label in state["labels"].values():
        # Skip soft-deleted labels (they have _deleted flag)
        if label.get("_deleted", False):
            continue
        results.append(_label_response(label))
    return JSONResponse(content={"results": results, "next_cursor": None}, status_code=200)


@app.get("/api/v1/labels/{label_id}")
async def get_label(label_id: str):
    """Get a single label by ID.
    Soft-deleted labels still return 200 (they look identical to before deletion).
    """
    label = state["labels"].get(label_id)
    if label is None:
        return _not_found("Label")
    return JSONResponse(content=_label_response(label), status_code=200)


@app.post("/api/v1/labels/{label_id}")
async def update_label(label_id: str, request: Request):
    """Update a label. Returns 200 with updated label object."""
    label = state["labels"].get(label_id)
    if label is None:
        return _not_found("Label")

    body = await request.json()

    if "name" in body:
        label["name"] = body["name"]
    if "color" in body:
        label["color"] = body["color"]
    if "is_favorite" in body:
        label["is_favorite"] = body["is_favorite"]
    # The SDK sends `item_order` but we store as `order`
    if "item_order" in body:
        label["order"] = body["item_order"]
    elif "order" in body:
        label["order"] = body["order"]

    return JSONResponse(content=_label_response(label), status_code=200)


@app.delete("/api/v1/labels/{label_id}")
async def delete_label(label_id: str):
    """Delete a label. Returns 204 empty body.
    Labels are soft-deleted: GET still returns 200, but excluded from list.
    """
    label = state["labels"].get(label_id)
    if label is None:
        return _not_found("Label")
    # Soft-delete: mark with internal flag, keep in state
    label["_deleted"] = True
    return Response(status_code=204)


def _label_response(label: dict[str, Any]) -> dict[str, Any]:
    """Return a label dict suitable for API response (strip internal fields)."""
    return {k: v for k, v in label.items() if not k.startswith("_")}


# =============================================================================
# Comment helpers
# =============================================================================

def _make_comment(
    content: str,
    task_id: str | None = None,
    project_id: str | None = None,
    comment_id: str | None = None,
) -> dict[str, Any]:
    """Create a new comment dict with proper v1 fields.

    A comment has EITHER item_id (task comment) OR project_id (project comment),
    never both. The absent field is simply not present in the response.
    """
    now = _now()
    comment: dict[str, Any] = {
        "id": comment_id or _generate_id(),
        "posted_uid": DEFAULT_USER_ID,
        "content": content,
        "file_attachment": None,
        "uids_to_notify": None,
        "is_deleted": False,
        "posted_at": now,
        "reactions": None,
    }
    if task_id is not None:
        comment["item_id"] = task_id
    if project_id is not None:
        comment["project_id"] = project_id
    return comment


# =============================================================================
# Comment Endpoints
# =============================================================================

@app.post("/api/v1/comments")
async def create_comment(request: Request):
    """Create a new comment. Returns 200 with comment object."""
    body = await request.json()

    content = body.get("content")
    if content is None:
        return _argument_missing("content")
    if not content or len(content) == 0:
        return _invalid_argument("content", "minlen", 1)

    task_id = body.get("task_id")
    project_id = body.get("project_id")

    comment = _make_comment(
        content=content,
        task_id=task_id,
        project_id=project_id,
    )

    state["comments"][comment["id"]] = comment
    return JSONResponse(content=comment, status_code=200)


@app.get("/api/v1/comments")
async def list_comments(request: Request):
    """List comments for a task or project. Returns paginated envelope."""
    task_id = request.query_params.get("task_id")
    project_id = request.query_params.get("project_id")

    results = []
    for comment in state["comments"].values():
        # Skip soft-deleted comments
        if comment.get("is_deleted", False):
            continue
        # Filter by task_id
        if task_id and comment.get("item_id") != task_id:
            continue
        # Filter by project_id
        if project_id and comment.get("project_id") != project_id:
            continue
        results.append(comment)

    return JSONResponse(content={"results": results, "next_cursor": None}, status_code=200)


@app.get("/api/v1/comments/{comment_id}")
async def get_comment(comment_id: str):
    """Get a single comment by ID."""
    comment = state["comments"].get(comment_id)
    if comment is None:
        return _not_found("Comment")
    return JSONResponse(content=comment, status_code=200)


@app.post("/api/v1/comments/{comment_id}")
async def update_comment(comment_id: str, request: Request):
    """Update a comment. Returns 200 with updated comment object."""
    comment = state["comments"].get(comment_id)
    if comment is None or comment.get("is_deleted", False):
        return _not_found("Comment")

    body = await request.json()
    if "content" in body:
        comment["content"] = body["content"]

    return JSONResponse(content=comment, status_code=200)


@app.delete("/api/v1/comments/{comment_id}")
async def delete_comment(comment_id: str):
    """Delete a comment. Returns 204 empty body."""
    comment = state["comments"].get(comment_id)
    if comment is None:
        return _not_found("Comment")
    comment["is_deleted"] = True
    return Response(status_code=204)


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
