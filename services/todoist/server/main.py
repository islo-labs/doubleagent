"""
Todoist API Fake - DoubleAgent Service

A high-fidelity fake of the Todoist REST API v1 for AI agent testing.
Built with FastAPI. Supports tasks, projects, sections, labels, comments,
quick-add NLP parsing, filter queries, idempotency, and webhooks.
"""

import os
import re
import uuid
import hmac
import json
import hashlib
import base64
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse

# =============================================================================
# State
# =============================================================================

state: dict[str, Any] = {}
counters: dict[str, int] = {}
idempotency_cache: dict[str, tuple[int, Any]] = {}

DEFAULT_NOW = "2024-01-01T00:00:00Z"

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _init_state() -> None:
    global state, counters, idempotency_cache
    state = {
        "tasks": {},
        "projects": {},
        "sections": {},
        "labels": {},
        "shared_labels": {},
        "comments": {},
        "webhooks": [],
        "webhook_deliveries": [],
    }
    counters = {
        "task": 0,
        "project": 0,
        "section": 0,
        "label": 0,
        "shared_label": 0,
        "comment": 0,
        "webhook": 0,
    }
    idempotency_cache = {}


_init_state()


def next_id(prefix: str) -> str:
    counters[prefix] += 1
    return f"{prefix}-{counters[prefix]}"


def now_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# =============================================================================
# Date / Due Parsing Helpers
# =============================================================================

def _next_weekday(weekday: int) -> date:
    """Return the date of the next occurrence of `weekday` (0=Mon..6=Sun)."""
    today = date.today()
    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def _parse_time(s: str) -> tuple[int, int]:
    """Parse '3pm', '2:30pm', '14:30' into (hour, minute)."""
    s = s.strip().lower()
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", s)
    if not m:
        return (12, 0)
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    return (hour, minute)


def build_due(
    due_string: str | None = None,
    due_date: str | None = None,
    due_datetime: str | None = None,
    due_lang: str = "en",
) -> dict | None:
    """Build a due dict from add_task/update_task parameters."""
    if due_string is not None:
        if due_string.lower() in ("no date", "no due date", ""):
            return None
        return _parse_due_string(due_string, due_lang)
    if due_datetime is not None:
        # "2026-03-15T14:30:00" or "2026-03-15T14:30:00Z"
        dt_str = due_datetime.replace("Z", "")
        return {
            "date": dt_str,
            "string": due_datetime,
            "lang": due_lang,
            "is_recurring": False,
            "timezone": None,
        }
    if due_date is not None:
        # "2026-03-15"
        return {
            "date": due_date,
            "string": due_date,
            "lang": due_lang,
            "is_recurring": False,
            "timezone": None,
        }
    return None


def _parse_due_string(s: str, lang: str = "en") -> dict:
    """Parse a natural-language due string into a due dict."""
    lower = s.lower().strip()
    is_recurring = False
    due_date_str: str | None = None

    # "every <day>"
    m = re.match(r"every\s+(\w+)", lower)
    if m:
        day_name = m.group(1)
        is_recurring = True
        if day_name in WEEKDAYS:
            d = _next_weekday(WEEKDAYS[day_name])
            due_date_str = d.isoformat()

    # "next <day>"
    if due_date_str is None:
        m = re.match(r"next\s+(\w+)", lower)
        if m:
            day_name = m.group(1)
            if day_name in WEEKDAYS:
                d = _next_weekday(WEEKDAYS[day_name])
                due_date_str = d.isoformat()

    # "tomorrow at <time>"
    if due_date_str is None:
        m = re.match(r"tomorrow\s+at\s+([\d:]+\s*(?:am|pm)?)", lower)
        if m:
            h, mi = _parse_time(m.group(1))
            d = date.today() + timedelta(days=1)
            dt = datetime(d.year, d.month, d.day, h, mi)
            due_date_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

    # "today at <time>"
    if due_date_str is None:
        m = re.match(r"today\s+at\s+([\d:]+\s*(?:am|pm)?)", lower)
        if m:
            h, mi = _parse_time(m.group(1))
            d = date.today()
            dt = datetime(d.year, d.month, d.day, h, mi)
            due_date_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

    # "tomorrow"
    if due_date_str is None and lower == "tomorrow":
        d = date.today() + timedelta(days=1)
        due_date_str = d.isoformat()

    # "today"
    if due_date_str is None and lower == "today":
        due_date_str = date.today().isoformat()

    # Fallback: try ISO date
    if due_date_str is None:
        try:
            date.fromisoformat(lower)
            due_date_str = lower
        except ValueError:
            # Unknown string, store it but set date to today
            due_date_str = date.today().isoformat()

    return {
        "date": due_date_str,
        "string": s,
        "lang": lang,
        "is_recurring": is_recurring,
        "timezone": None,
    }


# =============================================================================
# Quick Add NLP Parser
# =============================================================================

def parse_quick_add(text: str) -> dict:
    """Parse quick-add text into task fields."""
    content = text
    priority = 1
    project_id = None
    labels: list[str] = []
    due: dict | None = None

    # Extract priority (p1-p4, case-insensitive) — inverted mapping
    m = re.search(r"\bp([1-4])\b", content, re.IGNORECASE)
    if m:
        p_level = int(m.group(1))
        priority = 5 - p_level  # p1→4, p2→3, p3→2, p4→1
        content = content[: m.start()] + content[m.end() :]

    # Extract #ProjectName — only strip if project exists (matches real API)
    m = re.search(r"#(\S+)", content)
    if m:
        project_name = m.group(1)
        # Look up project
        for p in state["projects"].values():
            if p["name"] == project_name:
                project_id = p["id"]
                break
        if project_id is not None:
            # Only strip the #tag when the project was found
            content = content[: m.start()] + content[m.end() :]

    # Extract due date patterns from remaining content
    # Order: most specific first
    # "tomorrow at TIME" / "today at TIME"
    m = re.search(r"\b(tomorrow\s+at\s+[\d:]+\s*(?:am|pm)?)\b", content, re.IGNORECASE)
    if m:
        due = _parse_due_string(m.group(1))
        content = content[: m.start()] + content[m.end() :]
    else:
        m = re.search(r"\b(today\s+at\s+[\d:]+\s*(?:am|pm)?)\b", content, re.IGNORECASE)
        if m:
            due = _parse_due_string(m.group(1))
            content = content[: m.start()] + content[m.end() :]

    # "every <day>"
    if due is None:
        m = re.search(r"\b(every\s+\w+)\b", content, re.IGNORECASE)
        if m:
            due = _parse_due_string(m.group(1))
            content = content[: m.start()] + content[m.end() :]

    # "next <day>"
    if due is None:
        m = re.search(r"\b(next\s+\w+)\b", content, re.IGNORECASE)
        if m:
            due = _parse_due_string(m.group(1))
            content = content[: m.start()] + content[m.end() :]

    # "tomorrow" / "today"
    if due is None:
        m = re.search(r"\b(tomorrow)\b", content, re.IGNORECASE)
        if m:
            due = _parse_due_string("tomorrow")
            content = content[: m.start()] + content[m.end() :]
        else:
            m = re.search(r"\b(today)\b", content, re.IGNORECASE)
            if m:
                due = _parse_due_string("today")
                content = content[: m.start()] + content[m.end() :]

    # Clean up content
    content = re.sub(r"\s+", " ", content).strip()

    result: dict[str, Any] = {
        "content": content,
        "priority": priority,
        "labels": labels,
        "due": due,
    }
    if project_id:
        result["project_id"] = project_id
    return result


# =============================================================================
# Filter Query Parser
# =============================================================================

def _evaluate_filter(query: str, tasks: list[dict]) -> list[dict]:
    """Evaluate a Todoist filter query against a list of active tasks.

    Supports: pN, @label, @label*, #Project, today, tomorrow, overdue,
    N days, -N days, and AND (&) / OR (|) operators.
    Priority mapping: p1(filter)→priority 4(API), p4→priority 1.
    """
    # Split by | (OR) first, then by & (AND)
    or_clauses = [c.strip() for c in query.split("|")]
    result_ids: set[str] = set()

    for or_clause in or_clauses:
        and_parts = [p.strip() for p in or_clause.split("&")]
        # Start with all tasks, intersect with each AND condition
        matching = set(t["id"] for t in tasks)
        for part in and_parts:
            part = part.strip()
            condition_ids = _evaluate_single_condition(part, tasks)
            matching &= condition_ids
        result_ids |= matching

    return [t for t in tasks if t["id"] in result_ids]


def _evaluate_single_condition(cond: str, tasks: list[dict]) -> set[str]:
    """Evaluate a single filter condition and return matching task IDs."""
    cond = cond.strip()

    # Priority: p1-p4 (inverted mapping: p1 = highest = API priority 4)
    m = re.match(r"^p([1-4])$", cond, re.IGNORECASE)
    if m:
        p_level = int(m.group(1))
        api_priority = 5 - p_level
        return {t["id"] for t in tasks if t["priority"] == api_priority}

    # Label with wildcard: @label*
    m = re.match(r"^@(\S+)\*$", cond)
    if m:
        prefix = m.group(1)
        return {
            t["id"] for t in tasks
            if any(l.startswith(prefix) for l in (t.get("labels") or []))
        }

    # Label: @label
    m = re.match(r"^@(\S+)$", cond)
    if m:
        label = m.group(1)
        return {
            t["id"] for t in tasks
            if label in (t.get("labels") or [])
        }

    # Project: #ProjectName
    m = re.match(r"^#(\S+)$", cond)
    if m:
        project_name = m.group(1)
        # Find the project ID by name
        project_id = None
        for p in state["projects"].values():
            if p["name"] == project_name:
                project_id = p["id"]
                break
        if project_id is None:
            return set()
        return {t["id"] for t in tasks if t.get("project_id") == project_id}

    # Date conditions
    today = date.today()

    if cond.lower() == "today":
        return {
            t["id"] for t in tasks
            if t.get("due") and _due_date_obj(t["due"]) == today
        }

    if cond.lower() == "tomorrow":
        tomorrow = today + timedelta(days=1)
        return {
            t["id"] for t in tasks
            if t.get("due") and _due_date_obj(t["due"]) == tomorrow
        }

    if cond.lower() == "overdue":
        return {
            t["id"] for t in tasks
            if t.get("due") and _due_date_obj(t["due"]) is not None
            and _due_date_obj(t["due"]) < today
        }

    # "N days" — next N days (inclusive of today)
    m = re.match(r"^(\d+)\s+days?$", cond.lower())
    if m:
        n = int(m.group(1))
        end_date = today + timedelta(days=n)
        return {
            t["id"] for t in tasks
            if t.get("due") and _due_date_obj(t["due"]) is not None
            and today <= _due_date_obj(t["due"]) <= end_date
        }

    # "-N days" — past N days
    m = re.match(r"^-(\d+)\s+days?$", cond.lower())
    if m:
        n = int(m.group(1))
        start_date = today - timedelta(days=n)
        return {
            t["id"] for t in tasks
            if t.get("due") and _due_date_obj(t["due"]) is not None
            and start_date <= _due_date_obj(t["due"]) < today
        }

    # Fallback: no match
    return set()


def _due_date_obj(due: dict) -> date | None:
    """Extract a date object from a due dict."""
    d = due.get("date")
    if d is None:
        return None
    if isinstance(d, str):
        try:
            # Try datetime first (has 'T')
            if "T" in d:
                return datetime.fromisoformat(d.replace("Z", "")).date()
            return date.fromisoformat(d)
        except ValueError:
            return None
    return None


# =============================================================================
# Serialization Helpers
# =============================================================================

def _task_dict(task: dict) -> dict:
    """Return a task dict suitable for JSON response."""
    return {
        "id": task["id"],
        "content": task["content"],
        "description": task.get("description", ""),
        "project_id": task.get("project_id", "inbox"),
        "section_id": task.get("section_id"),
        "parent_id": task.get("parent_id"),
        "labels": task.get("labels") or [],
        "priority": task.get("priority", 1),
        "due": task.get("due"),
        "deadline": task.get("deadline"),
        "duration": task.get("duration"),
        "is_collapsed": False,
        "order": task.get("order", 1),
        "assignee_id": task.get("assignee_id"),
        "assigner_id": task.get("assigner_id"),
        "completed_at": task.get("completed_at"),
        "creator_id": "1",
        "created_at": task.get("created_at", now_str()),
        "updated_at": task.get("updated_at", now_str()),
    }


def _project_dict(project: dict) -> dict:
    return {
        "id": project["id"],
        "name": project["name"],
        "description": project.get("description", ""),
        "order": project.get("order", 1),
        "color": project.get("color", "charcoal"),
        "is_collapsed": project.get("is_collapsed", False),
        "is_shared": project.get("is_shared", False),
        "is_favorite": project.get("is_favorite", False),
        "is_archived": project.get("is_archived", False),
        "can_assign_tasks": project.get("can_assign_tasks", False),
        "view_style": project.get("view_style", "list"),
        "created_at": project.get("created_at", now_str()),
        "updated_at": project.get("updated_at", now_str()),
        "parent_id": project.get("parent_id"),
        "is_inbox_project": project.get("is_inbox_project", False),
        "workspace_id": project.get("workspace_id"),
        "folder_id": project.get("folder_id"),
    }


def _section_dict(section: dict) -> dict:
    return {
        "id": section["id"],
        "name": section["name"],
        "project_id": section["project_id"],
        "is_collapsed": section.get("is_collapsed", False),
        "order": section.get("order", 1),
    }


def _comment_dict(comment: dict) -> dict:
    return {
        "id": comment["id"],
        "content": comment["content"],
        "poster_id": comment.get("poster_id", "1"),
        "posted_at": comment.get("posted_at", now_str()),
        "task_id": comment.get("task_id"),
        "project_id": comment.get("project_id"),
        "attachment": comment.get("attachment"),
    }


def _label_dict(label: dict) -> dict:
    return {
        "id": label["id"],
        "name": label["name"],
        "color": label.get("color", "charcoal"),
        "order": label.get("order", 0),
        "is_favorite": label.get("is_favorite", False),
    }


def _paginated(items: list) -> dict:
    return {"results": items, "next_cursor": None}


# =============================================================================
# Webhook Helpers
# =============================================================================

def _dispatch_webhooks(event_name: str, event_data: dict) -> None:
    """Record webhook deliveries for matching registered webhooks."""
    for wh in state["webhooks"]:
        if event_name not in wh["events"]:
            continue
        payload = {
            "event_name": event_name,
            "user_id": 1,
            "initiator": {
                "id": 1,
                "email": "user@example.com",
                "full_name": "Test User",
                "is_premium": False,
            },
            "event_data": event_data,
            "version": "9",
        }
        # Compute HMAC signature
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        sig = hmac.new(
            wh["client_secret"].encode("utf-8"),
            payload_json.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        sig_b64 = base64.b64encode(sig).decode("utf-8")

        state["webhook_deliveries"].append({
            "event_name": event_name,
            "payload": payload,
            "signature": sig_b64,
            "webhook_id": wh["id"],
        })


# =============================================================================
# App Setup
# =============================================================================

app = FastAPI(title="Todoist API Fake", version="1.0.0")


# =============================================================================
# Idempotency Middleware
# =============================================================================

@app.middleware("http")
async def idempotency_middleware(request: Request, call_next):
    if request.method == "POST":
        req_id = request.headers.get("x-request-id")
        if req_id and req_id in idempotency_cache:
            cached_status, cached_body = idempotency_cache[req_id]
            return JSONResponse(content=cached_body, status_code=cached_status)

    response = await call_next(request)

    # Cache POST responses when X-Request-Id is present
    if request.method == "POST":
        req_id = request.headers.get("x-request-id")
        if req_id and req_id not in idempotency_cache:
            # Read the response body for caching
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            try:
                body_json = json.loads(body)
                idempotency_cache[req_id] = (response.status_code, body_json)
            except (json.JSONDecodeError, ValueError):
                pass
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

    return response


# =============================================================================
# DoubleAgent Control Plane
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    _init_state()
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(request: Request):
    data = await request.json()
    seeded: dict[str, int] = {}

    for key, collection in data.items():
        if key == "shared_labels":
            for sl_id, sl_data in collection.items():
                state["shared_labels"][sl_id] = sl_data
            seeded["shared_labels"] = len(collection)
        elif key in state:
            if isinstance(collection, dict):
                for item_id, item_data in collection.items():
                    state[key][item_id] = item_data
                seeded[key] = len(collection)
            elif isinstance(collection, list):
                for item in collection:
                    item_id = item.get("id", next_id(key.rstrip("s")))
                    state[key][item_id] = item
                seeded[key] = len(collection)

    return {"status": "ok", "seeded": seeded}


@app.get("/_doubleagent/webhook_deliveries")
async def get_webhook_deliveries():
    return {"deliveries": state["webhook_deliveries"]}


@app.delete("/_doubleagent/webhook_deliveries")
async def clear_webhook_deliveries():
    state["webhook_deliveries"] = []
    return {"status": "ok"}


# =============================================================================
# Task Endpoints
# =============================================================================

@app.get("/api/v1/tasks/filter")
async def filter_tasks(query: str = Query("")):
    """Filter active tasks using Todoist filter query language."""
    active = [
        t for t in state["tasks"].values()
        if t.get("completed_at") is None and not t.get("_deleted")
    ]
    matched = _evaluate_filter(query, active)
    return _paginated([_task_dict(t) for t in matched])


@app.get("/api/v1/tasks")
async def list_tasks(
    project_id: str | None = Query(None),
    section_id: str | None = Query(None),
    label: str | None = Query(None),
    parent_id: str | None = Query(None),
):
    """List active tasks with optional filters."""
    active = [
        t for t in state["tasks"].values()
        if t.get("completed_at") is None and not t.get("_deleted")
    ]

    if project_id is not None:
        active = [t for t in active if t.get("project_id") == project_id]
    if section_id is not None:
        active = [t for t in active if t.get("section_id") == section_id]
    if label is not None:
        active = [t for t in active if label in (t.get("labels") or [])]
    if parent_id is not None:
        active = [t for t in active if t.get("parent_id") == parent_id]

    return _paginated([_task_dict(t) for t in active])


@app.post("/api/v1/tasks/quick")
async def quick_add_task(request: Request):
    """Quick add a task with natural language parsing."""
    body = await request.json()
    text = body.get("text", "")

    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    parsed = parse_quick_add(text)

    task_id = next_id("task")
    ts = now_str()
    task = {
        "id": task_id,
        "content": parsed["content"],
        "description": parsed.get("description", ""),
        "project_id": parsed.get("project_id", "inbox"),
        "section_id": None,
        "parent_id": None,
        "labels": parsed.get("labels", []),
        "priority": parsed.get("priority", 1),
        "due": parsed.get("due"),
        "deadline": None,
        "duration": None,
        "order": 1,
        "completed_at": None,
        "created_at": ts,
        "updated_at": ts,
    }
    state["tasks"][task_id] = task

    _dispatch_webhooks("item:added", _task_dict(task))
    return _task_dict(task)


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    task = state["tasks"].get(task_id)
    if task is None or task.get("_deleted"):
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(task)


@app.post("/api/v1/tasks/{task_id}/close")
async def close_task(task_id: str):
    task = state["tasks"].get(task_id)
    if task is None or task.get("_deleted"):
        raise HTTPException(status_code=404, detail="Task not found")

    # Check if recurring — reschedule instead of completing
    due = task.get("due")
    if due and due.get("is_recurring"):
        # Move due date forward by 7 days
        d = _due_date_obj(due)
        if d:
            new_d = d + timedelta(days=7)
            task["due"]["date"] = new_d.isoformat()
        task["updated_at"] = now_str()
    else:
        task["completed_at"] = now_str()
        task["updated_at"] = now_str()

    return Response(status_code=204)


@app.post("/api/v1/tasks/{task_id}/reopen")
async def reopen_task(task_id: str):
    task = state["tasks"].get(task_id)
    if task is None or task.get("_deleted"):
        raise HTTPException(status_code=404, detail="Task not found")
    task["completed_at"] = None
    task["updated_at"] = now_str()
    return Response(status_code=204)


@app.post("/api/v1/tasks/{task_id}/move")
async def move_task(task_id: str, request: Request):
    task = state["tasks"].get(task_id)
    if task is None or task.get("_deleted"):
        raise HTTPException(status_code=404, detail="Task not found")
    body = await request.json()
    if "project_id" in body:
        task["project_id"] = body["project_id"]
    if "section_id" in body:
        task["section_id"] = body["section_id"]
    if "parent_id" in body:
        task["parent_id"] = body["parent_id"]
    task["updated_at"] = now_str()
    return Response(status_code=204)


@app.post("/api/v1/tasks")
async def create_task(request: Request):
    body = await request.json()
    content = body.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")

    task_id = next_id("task")
    ts = now_str()

    # Build due
    due = build_due(
        due_string=body.get("due_string"),
        due_date=body.get("due_date"),
        due_datetime=body.get("due_datetime"),
        due_lang=body.get("due_lang", "en"),
    )

    # Build duration
    duration = None
    if body.get("duration") is not None:
        duration = {
            "amount": body["duration"],
            "unit": body.get("duration_unit", "minute"),
        }

    task = {
        "id": task_id,
        "content": content,
        "description": body.get("description", ""),
        "project_id": body.get("project_id", "inbox"),
        "section_id": body.get("section_id"),
        "parent_id": body.get("parent_id"),
        "labels": body.get("labels") or [],
        "priority": body.get("priority", 1),
        "due": due,
        "deadline": body.get("deadline"),
        "duration": duration,
        "order": body.get("order", 1),
        "assignee_id": body.get("assignee_id"),
        "completed_at": None,
        "created_at": ts,
        "updated_at": ts,
    }
    state["tasks"][task_id] = task

    _dispatch_webhooks("item:added", _task_dict(task))
    return _task_dict(task)


@app.post("/api/v1/tasks/{task_id}")
async def update_task(task_id: str, request: Request):
    task = state["tasks"].get(task_id)
    if task is None or task.get("_deleted"):
        raise HTTPException(status_code=404, detail="Task not found")

    body = await request.json()

    if "content" in body:
        task["content"] = body["content"]
    if "description" in body:
        task["description"] = body["description"]
    if "labels" in body:
        task["labels"] = body["labels"]
    if "priority" in body:
        task["priority"] = body["priority"]
    if "assignee_id" in body:
        task["assignee_id"] = body["assignee_id"]
    if "order" in body:
        task["order"] = body["order"]

    # Due date handling
    if "due_string" in body or "due_date" in body or "due_datetime" in body:
        task["due"] = build_due(
            due_string=body.get("due_string"),
            due_date=body.get("due_date"),
            due_datetime=body.get("due_datetime"),
            due_lang=body.get("due_lang", "en"),
        )

    # Duration
    if "duration" in body:
        if body["duration"] is None:
            task["duration"] = None
        else:
            task["duration"] = {
                "amount": body["duration"],
                "unit": body.get("duration_unit", "minute"),
            }

    task["updated_at"] = now_str()

    _dispatch_webhooks("item:updated", _task_dict(task))
    return _task_dict(task)


@app.delete("/api/v1/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    task = state["tasks"].get(task_id)
    if task is not None:
        task_data = _task_dict(task)
        task["_deleted"] = True
        _dispatch_webhooks("item:deleted", task_data)
    return Response(status_code=204)


# =============================================================================
# Project Endpoints
# =============================================================================

@app.get("/api/v1/projects")
async def list_projects():
    active = [
        p for p in state["projects"].values()
        if not p.get("is_archived") and not p.get("_deleted")
    ]
    return _paginated([_project_dict(p) for p in active])


@app.post("/api/v1/projects/{project_id}/archive")
async def archive_project(project_id: str):
    project = state["projects"].get(project_id)
    if project is None or project.get("_deleted"):
        raise HTTPException(status_code=404, detail="Project not found")
    project["is_archived"] = True
    project["updated_at"] = now_str()
    return _project_dict(project)


@app.post("/api/v1/projects/{project_id}/unarchive")
async def unarchive_project(project_id: str):
    project = state["projects"].get(project_id)
    if project is None or project.get("_deleted"):
        raise HTTPException(status_code=404, detail="Project not found")
    project["is_archived"] = False
    project["updated_at"] = now_str()
    return _project_dict(project)


@app.get("/api/v1/projects/{project_id}/collaborators")
async def get_collaborators(project_id: str):
    return _paginated([])


@app.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str):
    project = state["projects"].get(project_id)
    if project is None or project.get("_deleted"):
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_dict(project)


@app.post("/api/v1/projects")
async def create_project(request: Request):
    body = await request.json()
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    project_id = next_id("project")
    ts = now_str()

    project = {
        "id": project_id,
        "name": name,
        "description": body.get("description", ""),
        "order": body.get("order", 1),
        "color": body.get("color", "charcoal"),
        "is_collapsed": False,
        "is_shared": False,
        "is_favorite": body.get("is_favorite", False),
        "is_archived": False,
        "can_assign_tasks": False,
        "view_style": body.get("view_style", "list"),
        "parent_id": body.get("parent_id"),
        "is_inbox_project": False,
        "workspace_id": None,
        "folder_id": None,
        "created_at": ts,
        "updated_at": ts,
    }
    state["projects"][project_id] = project

    _dispatch_webhooks("project:added", _project_dict(project))
    return _project_dict(project)


@app.post("/api/v1/projects/{project_id}")
async def update_project(project_id: str, request: Request):
    project = state["projects"].get(project_id)
    if project is None or project.get("_deleted"):
        raise HTTPException(status_code=404, detail="Project not found")

    body = await request.json()
    for field in ("name", "description", "color", "is_favorite", "view_style", "order"):
        if field in body:
            project[field] = body[field]
    project["updated_at"] = now_str()
    return _project_dict(project)


@app.delete("/api/v1/projects/{project_id}", status_code=204)
async def delete_project(project_id: str):
    project = state["projects"].get(project_id)
    if project is not None:
        project["_deleted"] = True
        # Cascade: delete sections and tasks in this project
        for s in state["sections"].values():
            if s.get("project_id") == project_id:
                s["_deleted"] = True
                # Also delete tasks in this section
                for t in state["tasks"].values():
                    if t.get("section_id") == s["id"]:
                        t["_deleted"] = True
        for t in state["tasks"].values():
            if t.get("project_id") == project_id:
                t["_deleted"] = True
    return Response(status_code=204)


# =============================================================================
# Section Endpoints
# =============================================================================

@app.get("/api/v1/sections")
async def list_sections(project_id: str | None = Query(None)):
    sections = [
        s for s in state["sections"].values()
        if not s.get("_deleted")
    ]
    if project_id is not None:
        sections = [s for s in sections if s.get("project_id") == project_id]
    return _paginated([_section_dict(s) for s in sections])


@app.get("/api/v1/sections/{section_id}")
async def get_section(section_id: str):
    section = state["sections"].get(section_id)
    if section is None or section.get("_deleted"):
        raise HTTPException(status_code=404, detail="Section not found")
    return _section_dict(section)


@app.post("/api/v1/sections")
async def create_section(request: Request):
    body = await request.json()
    name = body.get("name")
    project_id = body.get("project_id")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    # Validate project_id exists (matches real API behavior)
    if project_id and project_id not in state["projects"]:
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid argument value", "error_code": 20},
        )

    section_id = next_id("section")
    section = {
        "id": section_id,
        "name": name,
        "project_id": project_id,
        "is_collapsed": False,
        "order": body.get("order", 1),
    }
    state["sections"][section_id] = section
    return _section_dict(section)


@app.post("/api/v1/sections/{section_id}")
async def update_section(section_id: str, request: Request):
    section = state["sections"].get(section_id)
    if section is None or section.get("_deleted"):
        raise HTTPException(status_code=404, detail="Section not found")

    body = await request.json()
    if "name" in body:
        section["name"] = body["name"]
    return _section_dict(section)


@app.delete("/api/v1/sections/{section_id}", status_code=204)
async def delete_section(section_id: str):
    section = state["sections"].get(section_id)
    if section is not None:
        section["_deleted"] = True
        # Cascade: delete tasks in this section
        for t in state["tasks"].values():
            if t.get("section_id") == section_id:
                t["_deleted"] = True
    return Response(status_code=204)


# =============================================================================
# Comment Endpoints
# =============================================================================

@app.get("/api/v1/comments")
async def list_comments(
    task_id: str | None = Query(None),
    project_id: str | None = Query(None),
):
    comments = [
        c for c in state["comments"].values()
        if not c.get("_deleted")
    ]
    if task_id is not None:
        comments = [c for c in comments if c.get("task_id") == task_id]
    if project_id is not None:
        comments = [c for c in comments if c.get("project_id") == project_id]
    return _paginated([_comment_dict(c) for c in comments])


@app.get("/api/v1/comments/{comment_id}")
async def get_comment(comment_id: str):
    comment = state["comments"].get(comment_id)
    if comment is None or comment.get("_deleted"):
        raise HTTPException(status_code=404, detail="Comment not found")
    return _comment_dict(comment)


@app.post("/api/v1/comments")
async def create_comment(request: Request):
    body = await request.json()
    content = body.get("content", "")
    task_id = body.get("task_id")
    project_id = body.get("project_id")

    comment_id = next_id("comment")
    ts = now_str()

    comment = {
        "id": comment_id,
        "content": content,
        "poster_id": "1",
        "posted_at": ts,
        "task_id": task_id,
        "project_id": project_id,
        "attachment": None,
    }
    state["comments"][comment_id] = comment
    return _comment_dict(comment)


@app.post("/api/v1/comments/{comment_id}")
async def update_comment(comment_id: str, request: Request):
    comment = state["comments"].get(comment_id)
    if comment is None or comment.get("_deleted"):
        raise HTTPException(status_code=404, detail="Comment not found")

    body = await request.json()
    if "content" in body:
        comment["content"] = body["content"]
    return _comment_dict(comment)


@app.delete("/api/v1/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: str):
    comment = state["comments"].get(comment_id)
    if comment is not None:
        comment["_deleted"] = True
    return Response(status_code=204)


# =============================================================================
# Label Endpoints (order matters: static paths before {label_id})
# =============================================================================

@app.get("/api/v1/labels/search")
async def search_labels(query: str = Query("")):
    labels = [
        l for l in state["labels"].values()
        if not l.get("_deleted") and query.lower() in l["name"].lower()
    ]
    return _paginated([_label_dict(l) for l in labels])


@app.get("/api/v1/labels/shared")
async def get_shared_labels():
    names = [
        sl["name"] for sl in state["shared_labels"].values()
        if not sl.get("_deleted")
    ]
    return _paginated(names)


@app.post("/api/v1/labels/shared/rename")
async def rename_shared_label(request: Request, name: str = Query("")):
    body = await request.json() if await request.body() else {}
    new_name = body.get("new_name", "")
    # SDK sends 'name' as query param and 'new_name' in body
    old_name = name
    for sl in state["shared_labels"].values():
        if sl["name"] == old_name and not sl.get("_deleted"):
            sl["name"] = new_name
            break
    return Response(status_code=204)


@app.post("/api/v1/labels/shared/remove")
async def remove_shared_label(request: Request):
    body = await request.json()
    name = body.get("name")
    for sl in state["shared_labels"].values():
        if sl["name"] == name:
            sl["_deleted"] = True
            break
    return Response(status_code=204)


@app.get("/api/v1/labels")
async def list_labels():
    labels = [
        l for l in state["labels"].values()
        if not l.get("_deleted")
    ]
    return _paginated([_label_dict(l) for l in labels])


@app.get("/api/v1/labels/{label_id}")
async def get_label(label_id: str):
    label = state["labels"].get(label_id)
    if label is None or label.get("_deleted"):
        raise HTTPException(status_code=404, detail="Label not found")
    return _label_dict(label)


@app.post("/api/v1/labels")
async def create_label(request: Request):
    body = await request.json()
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    label_id = next_id("label")
    label = {
        "id": label_id,
        "name": name,
        "color": body.get("color", "charcoal"),
        "order": body.get("item_order", body.get("order", 0)),
        "is_favorite": body.get("is_favorite", False),
    }
    state["labels"][label_id] = label
    return _label_dict(label)


@app.post("/api/v1/labels/{label_id}")
async def update_label(label_id: str, request: Request):
    label = state["labels"].get(label_id)
    if label is None or label.get("_deleted"):
        raise HTTPException(status_code=404, detail="Label not found")

    body = await request.json()
    for field in ("name", "color", "is_favorite"):
        if field in body:
            label[field] = body[field]
    if "item_order" in body:
        label["order"] = body["item_order"]
    if "order" in body:
        label["order"] = body["order"]
    return _label_dict(label)


@app.delete("/api/v1/labels/{label_id}", status_code=204)
async def delete_label(label_id: str):
    label = state["labels"].get(label_id)
    if label is not None:
        label["_deleted"] = True
    return Response(status_code=204)


# =============================================================================
# Webhook Endpoints (Sync API v9)
# =============================================================================

@app.post("/sync/v9/webhooks")
async def register_webhook(request: Request):
    body = await request.json()

    # Validate required fields
    for field in ("client_id", "client_secret", "url", "events"):
        if field not in body:
            return JSONResponse(
                status_code=400,
                content={"error": f"Missing required field: {field}"},
            )

    webhook_id = next_id("webhook")
    webhook = {
        "id": webhook_id,
        "client_id": body["client_id"],
        "client_secret": body["client_secret"],
        "url": body["url"],
        "events": body["events"],
        "user_id": "1",
    }
    state["webhooks"].append(webhook)
    return {
        "id": webhook_id,
        "url": body["url"],
        "events": body["events"],
        "user_id": "1",
    }


@app.get("/sync/v9/webhooks")
async def list_webhooks():
    return [
        {
            "id": wh["id"],
            "url": wh["url"],
            "events": wh["events"],
            "user_id": wh["user_id"],
        }
        for wh in state["webhooks"]
    ]


@app.delete("/sync/v9/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str):
    state["webhooks"] = [wh for wh in state["webhooks"] if wh["id"] != webhook_id]
    return Response(status_code=204)


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
