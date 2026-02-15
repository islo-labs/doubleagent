import os
import hmac
import hashlib
import json
import copy
from flask import Flask, jsonify, request
from typing import Dict, List, Any, Optional

app = Flask(__name__)

# In-memory state
state: Dict[str, Any] = {}

def initialize_state():
    """Initialize or reset all state"""
    global state
    state = {
        "projects": {},
        "tasks": {},
        "sections": {},
        "comments": {},
        "labels": {},
        "shared_labels": {},
        "project_counter": 1,
        "task_counter": 1,
        "section_counter": 1,
        "comment_counter": 1,
        "label_counter": 1,
        "webhooks": {},
        "webhook_counter": 1,
        "webhook_deliveries": [],
        "request_ids": {},
    }

# Initialize state on startup
initialize_state()

# Control plane endpoints

@app.route("/_doubleagent/health", methods=["GET"])
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy"})

@app.route("/_doubleagent/reset", methods=["POST"])
def reset():
    """Reset all state"""
    initialize_state()
    return jsonify({"status": "ok"})

@app.route("/_doubleagent/seed", methods=["POST"])
def seed():
    """Seed state from JSON body"""
    global state
    seed_data = request.get_json()

    if seed_data:
        # Merge seed data into state
        for key, value in seed_data.items():
            if key in state:
                if isinstance(state[key], dict) and isinstance(value, dict):
                    state[key].update(value)
                else:
                    state[key] = value

    return jsonify({"status": "ok", "seeded": seed_data})

# Todoist REST API v2 endpoints

# Helper functions

def check_request_idempotency():
    """
    Check X-Request-Id header for idempotency on POST requests.
    If the request ID has been seen before, return the cached response.
    Returns None if this is a new request or not applicable.
    """
    # Only apply to POST requests (create/update operations)
    if request.method != "POST":
        return None

    # Get X-Request-Id header
    request_id = request.headers.get("X-Request-Id")
    if not request_id:
        return None

    # Check if we've seen this request ID before
    if request_id in state["request_ids"]:
        cached_response = state["request_ids"][request_id]
        # Return the cached response
        return jsonify(cached_response["body"]), cached_response["status_code"]

    return None

def cache_request_response(response_data, status_code=200):
    """
    Cache the response for the current request's X-Request-Id.
    Only caches for POST requests with X-Request-Id header.
    """
    # Only cache for POST requests
    if request.method != "POST":
        return

    # Get X-Request-Id header
    request_id = request.headers.get("X-Request-Id")
    if not request_id:
        return

    # Cache the response
    state["request_ids"][request_id] = {
        "body": response_data,
        "status_code": status_code,
    }

def get_base_url():
    """Get the base URL from the request"""
    return request.url_root.rstrip("/")

def create_project_response(project_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a project response with default fields"""
    response = {
        "id": str(project_data["id"]),
        "name": project_data["name"],
        "description": project_data.get("description", ""),
        "color": project_data.get("color", "charcoal"),
        "order": project_data.get("order", 0),
        "is_collapsed": project_data.get("is_collapsed", False),
        "is_shared": project_data.get("is_shared", False),
        "is_favorite": project_data.get("is_favorite", False),
        "is_archived": project_data.get("is_archived", False),
        "can_assign_tasks": project_data.get("can_assign_tasks", True),
        "view_style": project_data.get("view_style", "list"),
        "created_at": project_data.get("created_at", "2026-02-15T00:00:00Z"),
        "updated_at": project_data.get("updated_at", "2026-02-15T00:00:00Z"),
    }

    # Optional fields - only include if explicitly set
    if "parent_id" in project_data and project_data["parent_id"]:
        response["parent_id"] = project_data["parent_id"]
    if "is_inbox_project" in project_data and project_data["is_inbox_project"] is not None:
        response["is_inbox_project"] = project_data["is_inbox_project"]
    if "workspace_id" in project_data and project_data["workspace_id"]:
        response["workspace_id"] = project_data["workspace_id"]
    if "folder_id" in project_data and project_data["folder_id"]:
        response["folder_id"] = project_data["folder_id"]

    return response

def create_task_response(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a task response with default fields"""
    base_url = get_base_url()

    response = {
        "id": str(task_data["id"]),
        "content": task_data["content"],
        "description": task_data.get("description", ""),
        "project_id": task_data["project_id"],
        "section_id": task_data.get("section_id"),
        "parent_id": task_data.get("parent_id"),
        "labels": task_data.get("labels", []),
        "priority": task_data.get("priority", 1),
        "order": task_data.get("order", 0),
        "is_collapsed": task_data.get("is_collapsed", False),
        "assignee_id": task_data.get("assignee_id"),
        "assigner_id": task_data.get("assigner_id"),
        "created_at": task_data.get("created_at", "2026-02-15T00:00:00Z"),
        "updated_at": task_data.get("updated_at", "2026-02-15T00:00:00Z"),
        "creator_id": task_data.get("creator_id", "1"),
        "completed_at": task_data.get("completed_at"),
        "url": f"{base_url}/app/task/{task_data['id']}",
        "due": task_data.get("due"),
        "duration": task_data.get("duration"),
        "deadline": task_data.get("deadline"),
    }

    return response

# Project endpoints

@app.route("/api/v1/projects", methods=["GET"])
def get_projects():
    """Get all projects"""
    projects = [
        create_project_response(p)
        for p in state["projects"].values()
        if not p.get("is_archived", False)
    ]
    # Return in paginated format with cursor
    # For simplicity, return all projects in one page with no next cursor
    return jsonify({"results": projects})

@app.route("/api/v1/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    """Get a specific project"""
    if project_id not in state["projects"]:
        return jsonify({"error": "Project not found"}), 404

    project = state["projects"][project_id]
    return jsonify(create_project_response(project))

@app.route("/api/v1/projects", methods=["POST"])
def create_project():
    """Create a new project"""
    # Check for idempotent request
    idempotent_response = check_request_idempotency()
    if idempotent_response is not None:
        return idempotent_response

    data = request.get_json()

    if not data or "name" not in data:
        return jsonify({"error": "Name is required"}), 400

    project_id = str(state["project_counter"])
    state["project_counter"] += 1

    project = {
        "id": project_id,
        "name": data["name"],
        "description": data.get("description", ""),
        "color": data.get("color", "charcoal"),
        "parent_id": data.get("parent_id"),
        "order": data.get("order", 0),
        "is_collapsed": data.get("is_collapsed", False),
        "is_shared": data.get("is_shared", False),
        "is_favorite": data.get("is_favorite", False),
        "is_archived": False,
        "can_assign_tasks": data.get("can_assign_tasks", True),
        "view_style": data.get("view_style", "list"),
        "created_at": "2026-02-15T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
        "is_inbox_project": data.get("is_inbox_project"),
        "workspace_id": data.get("workspace_id"),
        "folder_id": data.get("folder_id"),
        "collaborators": [],
    }

    state["projects"][project_id] = project

    # Trigger webhook for project:added event
    trigger_webhook("project:added", project)

    response_data = create_project_response(project)
    cache_request_response(response_data, 200)
    return jsonify(response_data)

@app.route("/api/v1/projects/<project_id>", methods=["POST"])
def update_project(project_id):
    """Update an existing project"""
    # Check for idempotent request
    idempotent_response = check_request_idempotency()
    if idempotent_response is not None:
        return idempotent_response

    if project_id not in state["projects"]:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json()
    project = state["projects"][project_id]

    # Update allowed fields
    if "name" in data:
        project["name"] = data["name"]
    if "description" in data:
        project["description"] = data["description"]
    if "color" in data:
        project["color"] = data["color"]
    if "is_favorite" in data:
        project["is_favorite"] = data["is_favorite"]
    if "view_style" in data:
        project["view_style"] = data["view_style"]

    # Update timestamp
    project["updated_at"] = "2026-02-15T00:00:00Z"

    response_data = create_project_response(project)
    cache_request_response(response_data, 200)
    return jsonify(response_data)

@app.route("/api/v1/projects/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    """Delete a project"""
    if project_id not in state["projects"]:
        return jsonify({"error": "Project not found"}), 404

    del state["projects"][project_id]

    # Also delete associated tasks and sections
    state["tasks"] = {
        tid: task for tid, task in state["tasks"].items()
        if task.get("project_id") != project_id
    }
    state["sections"] = {
        sid: section for sid, section in state["sections"].items()
        if section.get("project_id") != project_id
    }

    return "", 204

@app.route("/api/v1/projects/<project_id>/archive", methods=["POST"])
def archive_project(project_id):
    """Archive a project"""
    if project_id not in state["projects"]:
        return jsonify({"error": "Project not found"}), 404

    state["projects"][project_id]["is_archived"] = True
    return jsonify(create_project_response(state["projects"][project_id]))

@app.route("/api/v1/projects/<project_id>/unarchive", methods=["POST"])
def unarchive_project(project_id):
    """Unarchive a project"""
    if project_id not in state["projects"]:
        return jsonify({"error": "Project not found"}), 404

    state["projects"][project_id]["is_archived"] = False
    return jsonify(create_project_response(state["projects"][project_id]))

@app.route("/api/v1/projects/<project_id>/collaborators", methods=["GET"])
def get_project_collaborators(project_id):
    """Get collaborators for a shared project"""
    if project_id not in state["projects"]:
        return jsonify({"error": "Project not found"}), 404

    project = state["projects"][project_id]
    collaborators = project.get("collaborators", [])

    # Return in paginated format with cursor
    return jsonify({"results": collaborators})

# Task endpoints

def parse_filter_query(query: str, task: Dict[str, Any]) -> bool:
    """
    Parse and evaluate Todoist filter query syntax.
    Supports labels (@label), priorities (p1-p4), due dates (today, tomorrow, overdue),
    projects (#project), and AND (&) / OR (|) operators.
    """
    if not query:
        return True

    # Handle OR operator (|) - split and evaluate each part
    if "|" in query:
        parts = [p.strip() for p in query.split("|")]
        return any(parse_filter_query(part, task) for part in parts)

    # Handle AND operator (&) - split and evaluate all parts
    if "&" in query:
        parts = [p.strip() for p in query.split("&")]
        return all(parse_filter_query(part, task) for part in parts)

    # Remove parentheses if present
    query = query.strip("()")

    # Priority filter (p1, p2, p3, p4)
    if query.lower() in ["p1", "p2", "p3", "p4"]:
        priority_value = int(query[1])
        return task.get("priority") == priority_value

    # Label filter (@label)
    if query.startswith("@"):
        label_name = query[1:]
        # Support wildcard matching (@label*)
        if label_name.endswith("*"):
            label_prefix = label_name[:-1]
            return any(label.startswith(label_prefix) for label in task.get("labels", []))
        return label_name in task.get("labels", [])

    # Project filter (#project)
    if query.startswith("#"):
        project_name = query[1:]
        # Look up project by name
        project_id = task.get("project_id")
        if project_id and project_id in state["projects"]:
            return state["projects"][project_id]["name"] == project_name
        return False

    # Due date filters
    from datetime import datetime, timedelta
    task_due = task.get("due")

    if query.lower() == "today":
        if not task_due or not task_due.get("date"):
            return False
        due_date_str = str(task_due["date"])
        # Parse date (could be date or datetime)
        if "T" in due_date_str or " " in due_date_str:
            # Datetime format
            try:
                due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
            except:
                return False
        else:
            # Date format
            try:
                due_date = datetime.strptime(due_date_str.split()[0] if " " in due_date_str else due_date_str, "%Y-%m-%d").date()
            except:
                return False
        today = datetime.now().date()
        return due_date == today

    if query.lower() == "tomorrow":
        if not task_due or not task_due.get("date"):
            return False
        due_date_str = str(task_due["date"])
        try:
            if "T" in due_date_str or " " in due_date_str:
                due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
            else:
                due_date = datetime.strptime(due_date_str.split()[0] if " " in due_date_str else due_date_str, "%Y-%m-%d").date()
        except:
            return False
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        return due_date == tomorrow

    if query.lower() == "overdue":
        if not task_due or not task_due.get("date"):
            return False
        due_date_str = str(task_due["date"])
        try:
            if "T" in due_date_str or " " in due_date_str:
                due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
            else:
                due_date = datetime.strptime(due_date_str.split()[0] if " " in due_date_str else due_date_str, "%Y-%m-%d").date()
        except:
            return False
        today = datetime.now().date()
        return due_date < today

    # Date range filters like "7 days", "next 7 days"
    if "days" in query.lower() or "day" in query.lower():
        if not task_due or not task_due.get("date"):
            return False

        # Parse number of days
        parts = query.lower().replace("next", "").replace("day", "").replace("days", "").strip().split()
        if parts and parts[0].lstrip("-").isdigit():
            num_days = int(parts[0])
            due_date_str = str(task_due["date"])
            try:
                if "T" in due_date_str or " " in due_date_str:
                    due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00")).date()
                else:
                    due_date = datetime.strptime(due_date_str.split()[0] if " " in due_date_str else due_date_str, "%Y-%m-%d").date()
            except:
                return False

            today = datetime.now().date()
            if num_days > 0:
                # Future dates (e.g., "7 days", "next 7 days")
                end_date = today + timedelta(days=num_days)
                return today <= due_date <= end_date
            else:
                # Past dates (e.g., "-3 days")
                start_date = today + timedelta(days=num_days)
                return start_date <= due_date <= today

    # No match - return False
    return False

@app.route("/api/v1/tasks", methods=["GET"])
def get_tasks():
    """Get all active (non-completed) tasks with optional filters"""
    # Get filter parameters
    project_id = request.args.get("project_id")
    section_id = request.args.get("section_id")
    parent_id = request.args.get("parent_id")
    label = request.args.get("label")
    ids = request.args.get("ids")  # Comma-separated task IDs
    filter_query = request.args.get("filter")  # Complex filter query (e.g., "p1 & @work", "today | overdue")

    # Filter tasks
    tasks = []
    for task in state["tasks"].values():
        # Skip completed tasks
        if task.get("completed_at"):
            continue

        # Apply simple filters (these have precedence if filter is not provided)
        if not filter_query:
            if project_id and task.get("project_id") != project_id:
                continue
            if section_id and task.get("section_id") != section_id:
                continue
            if parent_id and task.get("parent_id") != parent_id:
                continue
            if label and label not in task.get("labels", []):
                continue
            if ids:
                id_list = [id.strip() for id in ids.split(",")]
                if task["id"] not in id_list:
                    continue
        else:
            # Apply complex filter query (filter takes precedence over other params)
            if not parse_filter_query(filter_query, task):
                continue

        tasks.append(create_task_response(task))

    # Return in paginated format
    return jsonify({"results": tasks})

@app.route("/api/v1/tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    """Get a specific task by ID"""
    if task_id not in state["tasks"]:
        return jsonify({"error": "Task not found"}), 404

    task = state["tasks"][task_id]
    # Return completed tasks too (unlike get_tasks)
    return jsonify(create_task_response(task))

@app.route("/api/v1/tasks", methods=["POST"])
def create_task():
    """Create a new task"""
    # Check for idempotent request
    idempotent_response = check_request_idempotency()
    if idempotent_response is not None:
        return idempotent_response

    data = request.get_json()

    if not data or "content" not in data:
        return jsonify({"error": "Content is required"}), 400

    task_id = str(state["task_counter"])
    state["task_counter"] += 1

    # Build due object from due_string, due_date, or due_datetime
    due = None
    if "due_string" in data or "due_date" in data or "due_datetime" in data:
        due = {}
        # Both date and string fields are required by the SDK
        if "due_date" in data:
            due["date"] = data["due_date"]
            # Create string representation
            if "due_string" not in data:
                due["string"] = str(data["due_date"])
        elif "due_datetime" in data:
            due["date"] = data["due_datetime"]  # Store in date field
            # Create string representation
            if "due_string" not in data:
                due["string"] = str(data["due_datetime"])
        else:
            # For due_string, provide a dummy date (real API parses it)
            due["date"] = "2026-02-16"

        if "due_string" in data:
            due["string"] = data["due_string"]
        # Add optional fields
        due["timezone"] = data.get("due_timezone")
        due["is_recurring"] = data.get("is_recurring", False)

    # Build duration object
    duration = None
    if "duration" in data and "duration_unit" in data:
        duration = {
            "amount": data["duration"],
            "unit": data["duration_unit"],
        }

    task = {
        "id": task_id,
        "content": data["content"],
        "description": data.get("description", ""),
        "project_id": data.get("project_id", "inbox"),
        "section_id": data.get("section_id"),
        "parent_id": data.get("parent_id"),
        "order": data.get("order", 0),
        "labels": data.get("labels", []),
        "priority": data.get("priority", 1),
        "due": due,
        "duration": duration,
        "assignee_id": data.get("assignee_id"),
        "assigner_id": data.get("assigner_id"),
        "is_collapsed": False,
        "created_at": "2026-02-15T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
        "creator_id": "1",
        "completed_at": None,
    }

    state["tasks"][task_id] = task

    # Trigger webhook for item:added event
    trigger_webhook("item:added", task)

    response_data = create_task_response(task)
    cache_request_response(response_data, 200)
    return jsonify(response_data)

@app.route("/api/v1/tasks/<task_id>", methods=["POST"])
def update_task(task_id):
    """Update an existing task"""
    # Check for idempotent request
    idempotent_response = check_request_idempotency()
    if idempotent_response is not None:
        return idempotent_response

    if task_id not in state["tasks"]:
        return jsonify({"error": "Task not found"}), 404

    data = request.get_json()
    task = state["tasks"][task_id]

    # Update allowed fields
    if "content" in data:
        task["content"] = data["content"]
    if "description" in data:
        task["description"] = data["description"]
    if "labels" in data:
        task["labels"] = data["labels"]
    if "priority" in data:
        task["priority"] = data["priority"]

    # Update due date
    if "due_string" in data or "due_date" in data or "due_datetime" in data:
        # Handle special "no date" string to remove due date
        if data.get("due_string") == "no date":
            task["due"] = None
        else:
            due = task.get("due", {}) or {}
            # Both date and string fields are required by the SDK
            if "due_date" in data:
                due["date"] = data["due_date"]
                if "string" not in due:
                    due["string"] = str(data["due_date"])
            elif "due_datetime" in data:
                due["date"] = data["due_datetime"]
                if "string" not in due:
                    due["string"] = str(data["due_datetime"])
            elif "due_string" in data and "date" not in due:
                # For due_string, provide a dummy date if not already set
                due["date"] = "2026-02-16"

            if "due_string" in data:
                due["string"] = data["due_string"]
            if "due_timezone" in data:
                due["timezone"] = data["due_timezone"]
            if "is_recurring" in data:
                due["is_recurring"] = data["is_recurring"]
            task["due"] = due

    # Update duration
    if "duration" in data or "duration_unit" in data:
        if data.get("duration") is None:
            task["duration"] = None
        elif "duration" in data and "duration_unit" in data:
            task["duration"] = {
                "amount": data["duration"],
                "unit": data["duration_unit"],
            }

    # Update assignee
    if "assignee_id" in data:
        task["assignee_id"] = data["assignee_id"]

    # Update collapsed state
    if "collapsed" in data:
        task["is_collapsed"] = data["collapsed"]

    # Update timestamp
    task["updated_at"] = "2026-02-15T00:00:00Z"

    # Trigger webhook for item:updated event
    trigger_webhook("item:updated", task)

    response_data = create_task_response(task)
    cache_request_response(response_data, 200)
    return jsonify(response_data)

@app.route("/api/v1/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    """Delete a task permanently"""
    if task_id not in state["tasks"]:
        return jsonify({"error": "Task not found"}), 404

    task = state["tasks"][task_id]

    # Trigger webhook for item:deleted event before deletion
    trigger_webhook("item:deleted", task)

    del state["tasks"][task_id]
    return "", 204

@app.route("/api/v1/tasks/<task_id>/close", methods=["POST"])
def complete_task(task_id):
    """Mark a task as completed (close it)"""
    if task_id not in state["tasks"]:
        return jsonify({"error": "Task not found"}), 404

    task = state["tasks"][task_id]
    task["completed_at"] = "2026-02-15T00:00:00Z"
    task["updated_at"] = "2026-02-15T00:00:00Z"

    return "", 204

@app.route("/api/v1/tasks/<task_id>/reopen", methods=["POST"])
def uncomplete_task(task_id):
    """Reopen a completed task"""
    if task_id not in state["tasks"]:
        return jsonify({"error": "Task not found"}), 404

    task = state["tasks"][task_id]
    task["completed_at"] = None
    task["updated_at"] = "2026-02-15T00:00:00Z"

    return "", 204

@app.route("/api/v1/tasks/filter", methods=["GET"])
def filter_tasks():
    """Filter tasks using Todoist's filter query language"""
    query = request.args.get("query")

    # Filter tasks
    tasks = []
    for task in state["tasks"].values():
        # Skip completed tasks
        if task.get("completed_at"):
            continue

        # Apply query filter using the same parser as get_tasks
        if query and not parse_filter_query(query, task):
            continue

        tasks.append(create_task_response(task))

    # Return in paginated format
    return jsonify({"results": tasks})

# Section endpoints

def create_section_response(section_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a section response with default fields"""
    return {
        "id": str(section_data["id"]),
        "name": section_data["name"],
        "project_id": section_data["project_id"],
        "order": section_data.get("order", 0),
        "collapsed": section_data.get("is_collapsed", False),
    }

@app.route("/api/v1/sections", methods=["GET"])
def get_sections():
    """Get all sections, optionally filtered by project"""
    project_id = request.args.get("project_id")

    sections = []
    for section in state["sections"].values():
        # Apply project_id filter if provided
        if project_id and section.get("project_id") != project_id:
            continue
        sections.append(create_section_response(section))

    # Return in paginated format with cursor (simplified - all in one page)
    return jsonify({"results": sections})

@app.route("/api/v1/sections/<section_id>", methods=["GET"])
def get_section(section_id):
    """Get a specific section by ID"""
    if section_id not in state["sections"]:
        return jsonify({"message": "Section not found"}), 404

    section = state["sections"][section_id]
    return jsonify(create_section_response(section))

@app.route("/api/v1/sections", methods=["POST"])
def create_section():
    """Create a new section"""
    data = request.get_json()

    if not data or "name" not in data:
        return jsonify({"message": "Name is required"}), 400

    if "project_id" not in data:
        return jsonify({"message": "Project ID is required"}), 400

    section_id = str(state["section_counter"])
    state["section_counter"] += 1

    section = {
        "id": section_id,
        "name": data["name"],
        "project_id": data["project_id"],
        "order": data.get("order", 0),
        "is_collapsed": False,
    }

    state["sections"][section_id] = section
    return jsonify(create_section_response(section))

@app.route("/api/v1/sections/<section_id>", methods=["POST"])
def update_section(section_id):
    """Update an existing section"""
    if section_id not in state["sections"]:
        return jsonify({"message": "Section not found"}), 404

    data = request.get_json()

    if not data or "name" not in data:
        return jsonify({"message": "Name is required"}), 400

    section = state["sections"][section_id]
    section["name"] = data["name"]

    return jsonify(create_section_response(section))

@app.route("/api/v1/sections/<section_id>", methods=["DELETE"])
def delete_section(section_id):
    """Delete a section and its tasks"""
    if section_id not in state["sections"]:
        return jsonify({"message": "Section not found"}), 404

    # Delete the section
    del state["sections"][section_id]

    # Also delete tasks in this section
    state["tasks"] = {
        tid: task for tid, task in state["tasks"].items()
        if task.get("section_id") != section_id
    }

    return "", 204

# Comment endpoints

def create_comment_response(comment_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a comment response with default fields"""
    response = {
        "id": str(comment_data["id"]),
        "content": comment_data["content"],
        "posted_at": comment_data.get("posted_at", "2026-02-15T00:00:00Z"),
        "posted_uid": comment_data.get("posted_uid", "1"),
    }

    # Include task_id or project_id (only one will be set)
    if comment_data.get("task_id"):
        response["task_id"] = comment_data["task_id"]
        response["project_id"] = None
    else:
        response["project_id"] = comment_data.get("project_id")
        response["task_id"] = None

    # Include attachment if present
    if comment_data.get("attachment"):
        response["attachment"] = comment_data["attachment"]
    else:
        response["attachment"] = None

    return response

@app.route("/api/v1/comments", methods=["GET"])
def get_comments():
    """Get all comments for a task or project"""
    task_id = request.args.get("task_id")
    project_id = request.args.get("project_id")

    # One of task_id or project_id is required
    if not task_id and not project_id:
        return jsonify({"error": "Either task_id or project_id is required"}), 400

    # Filter comments
    comments = []
    for comment in state["comments"].values():
        if task_id and comment.get("task_id") == task_id:
            comments.append(create_comment_response(comment))
        elif project_id and comment.get("project_id") == project_id:
            comments.append(create_comment_response(comment))

    # Return in paginated format (simplified - all in one page)
    return jsonify({"results": comments})

@app.route("/api/v1/comments/<comment_id>", methods=["GET"])
def get_comment(comment_id):
    """Get a specific comment by ID"""
    if comment_id not in state["comments"]:
        return jsonify({"error": "Comment not found"}), 404

    comment = state["comments"][comment_id]
    return jsonify(create_comment_response(comment))

@app.route("/api/v1/comments", methods=["POST"])
def create_comment():
    """Create a new comment"""
    data = request.get_json()

    if not data or "content" not in data:
        return jsonify({"error": "Content is required"}), 400

    # One of task_id or project_id is required
    task_id = data.get("task_id")
    project_id = data.get("project_id")

    if not task_id and not project_id:
        return jsonify({"error": "Either task_id or project_id is required"}), 400

    comment_id = str(state["comment_counter"])
    state["comment_counter"] += 1

    comment = {
        "id": comment_id,
        "content": data["content"],
        "posted_at": "2026-02-15T00:00:00Z",
        "posted_uid": "1",
    }

    # Set task_id or project_id (only one)
    if task_id:
        comment["task_id"] = task_id
    else:
        comment["project_id"] = project_id

    # Add attachment if provided
    if "attachment" in data:
        attachment = data["attachment"]
        comment["attachment"] = {
            "resource_type": attachment.get("resource_type"),
            "file_url": attachment.get("file_url"),
            "file_type": attachment.get("file_type"),
            "file_name": attachment.get("file_name"),
        }

    state["comments"][comment_id] = comment
    return jsonify(create_comment_response(comment))

@app.route("/api/v1/comments/<comment_id>", methods=["POST"])
def update_comment(comment_id):
    """Update an existing comment"""
    if comment_id not in state["comments"]:
        return jsonify({"error": "Comment not found"}), 404

    data = request.get_json()

    if not data or "content" not in data:
        return jsonify({"error": "Content is required"}), 400

    comment = state["comments"][comment_id]
    comment["content"] = data["content"]

    return jsonify(create_comment_response(comment))

@app.route("/api/v1/comments/<comment_id>", methods=["DELETE"])
def delete_comment(comment_id):
    """Delete a comment"""
    if comment_id not in state["comments"]:
        return jsonify({"error": "Comment not found"}), 404

    del state["comments"][comment_id]
    return "", 204

# Label endpoints

def create_label_response(label_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a label response with default fields"""
    return {
        "id": str(label_data["id"]),
        "name": label_data["name"],
        "color": label_data.get("color", "charcoal"),
        "order": label_data.get("order", 0),
        "is_favorite": label_data.get("is_favorite", False),
    }

@app.route("/api/v1/labels", methods=["GET"])
def get_labels():
    """Get all personal labels"""
    labels = [
        create_label_response(label)
        for label in state["labels"].values()
    ]
    # Return in paginated format with results key
    return jsonify({"results": labels})

@app.route("/api/v1/labels/<label_id>", methods=["GET"])
def get_label(label_id):
    """Get a specific personal label"""
    if label_id not in state["labels"]:
        return jsonify({"error": "Label not found"}), 404

    label = state["labels"][label_id]
    return jsonify(create_label_response(label))

@app.route("/api/v1/labels", methods=["POST"])
def create_label():
    """Create a new personal label"""
    data = request.get_json()

    if not data or "name" not in data:
        return jsonify({"error": "Name is required"}), 400

    label_id = str(state["label_counter"])
    state["label_counter"] += 1

    # Map item_order to order field
    order = data.get("order", 0)
    if "item_order" in data:
        order = data["item_order"]

    label = {
        "id": label_id,
        "name": data["name"],
        "color": data.get("color", "charcoal"),
        "order": order,
        "is_favorite": data.get("is_favorite", False),
    }

    state["labels"][label_id] = label
    return jsonify(create_label_response(label))

@app.route("/api/v1/labels/<label_id>", methods=["POST"])
def update_label(label_id):
    """Update an existing personal label"""
    if label_id not in state["labels"]:
        return jsonify({"error": "Label not found"}), 404

    data = request.get_json()
    label = state["labels"][label_id]

    # Update allowed fields
    if "name" in data:
        label["name"] = data["name"]
    if "color" in data:
        label["color"] = data["color"]
    if "order" in data:
        label["order"] = data["order"]
    # Map item_order to order field
    if "item_order" in data:
        label["order"] = data["item_order"]
    if "is_favorite" in data:
        label["is_favorite"] = data["is_favorite"]

    return jsonify(create_label_response(label))

@app.route("/api/v1/labels/<label_id>", methods=["DELETE"])
def delete_label(label_id):
    """Delete a personal label"""
    if label_id not in state["labels"]:
        return jsonify({"error": "Label not found"}), 404

    del state["labels"][label_id]
    return "", 204

@app.route("/api/v1/labels/search", methods=["GET"])
def search_labels():
    """Search personal labels by name"""
    query = request.args.get("query", "")

    if not query:
        return jsonify({"error": "Query parameter is required"}), 400

    # Filter labels by name containing query (case-insensitive)
    matching_labels = [
        create_label_response(label)
        for label in state["labels"].values()
        if query.lower() in label["name"].lower()
    ]

    # Return in paginated format with results key
    return jsonify({"results": matching_labels})

# Shared label endpoints

@app.route("/api/v1/labels/shared", methods=["GET"])
def get_shared_labels():
    """Get all shared labels"""
    labels = [
        create_label_response(label)
        for label in state["shared_labels"].values()
    ]
    # Return in paginated format with results key
    return jsonify({"results": labels})

@app.route("/api/v1/labels/shared/rename", methods=["POST"])
def rename_shared_label():
    """Rename a shared label"""
    # The SDK sends query parameters, not JSON body
    old_name = request.args.get("name")
    new_name = request.args.get("new_name")

    # Also check JSON body as fallback
    if not old_name or not new_name:
        data = request.get_json()
        if data:
            old_name = data.get("name", old_name)
            new_name = data.get("new_name", new_name)

    if not old_name or not new_name:
        return jsonify({"error": "Both name and new_name are required"}), 400

    # Find the shared label by name
    label_to_rename = None
    for label in state["shared_labels"].values():
        if label["name"] == old_name:
            label_to_rename = label
            break

    if not label_to_rename:
        return jsonify({"error": "Shared label not found"}), 404

    # Update the name
    label_to_rename["name"] = new_name

    return jsonify(create_label_response(label_to_rename))

@app.route("/api/v1/labels/shared/remove", methods=["POST"])
def remove_shared_label():
    """Remove a shared label"""
    data = request.get_json()

    if not data or "name" not in data:
        return jsonify({"error": "Name is required"}), 400

    label_name = data["name"]

    # Find and remove the shared label by name
    label_id_to_remove = None
    for label_id, label in state["shared_labels"].items():
        if label["name"] == label_name:
            label_id_to_remove = label_id
            break

    if not label_id_to_remove:
        return jsonify({"error": "Shared label not found"}), 404

    del state["shared_labels"][label_id_to_remove]
    return jsonify(True)

# Webhook endpoints (Sync API v9)

def compute_hmac_signature(payload: str, client_secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload"""
    import base64
    signature = hmac.new(
        client_secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')

def trigger_webhook(event_name: str, event_data: Dict[str, Any], user_id: str = "1"):
    """Trigger webhook delivery for registered webhooks"""
    for webhook_id, webhook in state["webhooks"].items():
        # Check if this webhook is subscribed to this event
        if event_name not in webhook.get("events", []):
            continue

        # Deep copy event_data to prevent mutations from affecting stored deliveries
        event_data_copy = copy.deepcopy(event_data)

        # Build webhook payload matching Todoist format
        payload = {
            "event_name": event_name,
            "user_id": int(user_id),
            "initiator": {
                "id": int(user_id),
                "email": "user@example.com",
                "full_name": "Test User",
                "is_premium": True,
                "image_id": None,
            },
            "event_data": event_data_copy,
            "version": "9",
        }

        # Compute HMAC signature with consistent key ordering
        # Use sort_keys=True to ensure consistent JSON serialization
        payload_json = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        signature = compute_hmac_signature(payload_json, webhook.get("client_secret", ""))

        # Store delivery record (in a real implementation, would POST to webhook URL)
        delivery = {
            "id": str(len(state["webhook_deliveries"]) + 1),
            "webhook_id": webhook_id,
            "event_name": event_name,
            "payload": payload,
            "payload_json": payload_json,  # Store serialized JSON for signature verification
            "signature": signature,
            "url": webhook["url"],
            "delivered_at": "2026-02-15T00:00:00Z",
        }
        state["webhook_deliveries"].append(delivery)

@app.route("/sync/v9/webhooks", methods=["POST"])
def register_webhook():
    """Register a new webhook"""
    data = request.get_json()

    # Validate required fields
    if not data:
        return jsonify({"error": "Request body is required"}), 400

    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    url = data.get("url")
    events = data.get("events", [])

    if not client_id:
        return jsonify({"error": "client_id is required"}), 400
    if not client_secret:
        return jsonify({"error": "client_secret is required"}), 400
    if not url:
        return jsonify({"error": "url is required"}), 400
    if not events or not isinstance(events, list):
        return jsonify({"error": "events array is required"}), 400

    # Create webhook
    webhook_id = str(state["webhook_counter"])
    state["webhook_counter"] += 1

    webhook = {
        "id": webhook_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "url": url,
        "events": events,
        "created_at": "2026-02-15T00:00:00Z",
    }

    state["webhooks"][webhook_id] = webhook

    # Return webhook info (without exposing client_secret in response)
    return jsonify({
        "id": webhook_id,
        "url": url,
        "events": events,
        "user_id": "1",
    })

@app.route("/sync/v9/webhooks", methods=["GET"])
def list_webhooks():
    """List all registered webhooks"""
    webhooks = []
    for webhook in state["webhooks"].values():
        webhooks.append({
            "id": webhook["id"],
            "url": webhook["url"],
            "events": webhook["events"],
            "user_id": "1",
        })
    return jsonify(webhooks)

@app.route("/sync/v9/webhooks/<webhook_id>", methods=["DELETE"])
def delete_webhook(webhook_id):
    """Delete a webhook"""
    if webhook_id not in state["webhooks"]:
        return jsonify({"error": "Webhook not found"}), 404

    del state["webhooks"][webhook_id]
    return "", 204

@app.route("/_doubleagent/webhook_deliveries", methods=["GET"])
def get_webhook_deliveries():
    """Get webhook delivery history (testing helper endpoint)"""
    return jsonify({"deliveries": state["webhook_deliveries"]})

@app.route("/_doubleagent/request_ids", methods=["GET"])
def get_request_ids():
    """Get request ID cache (testing helper endpoint)"""
    return jsonify({"request_ids": state["request_ids"]})

# Quick Add endpoint (Sync API v9)

def parse_quick_add_text(text: str) -> Dict[str, Any]:
    """
    Parse Todoist quick add notation from text.

    Supports:
    - #project - Project assignment
    - @label - Label assignment (multiple labels supported)
    - +assignee - Assignee (ignored in fake)
    - p1/p2/p3/p4 - Priority levels
    - Natural language dates (stored as-is in due_string)

    Returns dict with content, project_name, labels, priority, due_string
    """
    import re

    result = {
        "content": text,
        "project_name": None,
        "labels": [],
        "priority": 1,
        "due_string": None,
        "assignee": None,
    }

    # Extract project (#project_name)
    project_match = re.search(r'#([^\s#@+]+)', text)
    if project_match:
        result["project_name"] = project_match.group(1)
        text = text.replace(project_match.group(0), "").strip()

    # Extract labels (@label_name)
    label_matches = re.findall(r'@([^\s#@+]+)', text)
    if label_matches:
        result["labels"] = label_matches
        for match in label_matches:
            text = text.replace(f"@{match}", "").strip()

    # Extract assignee (+assignee_name) - just remove it, we don't use it in fake
    assignee_match = re.search(r'\+([^\s#@+]+)', text)
    if assignee_match:
        result["assignee"] = assignee_match.group(1)
        text = text.replace(assignee_match.group(0), "").strip()

    # Extract priority (p1, p2, p3, p4) - case insensitive
    priority_match = re.search(r'\bp([1-4])\b', text, re.IGNORECASE)
    if priority_match:
        result["priority"] = int(priority_match.group(1))
        text = text.replace(priority_match.group(0), "").strip()

    # Extract natural language due dates (common patterns)
    # These patterns should come at the end or be recognizable
    # Order matters - more specific patterns first
    due_date_patterns = [
        # Patterns with time components (must come first)
        r'\b(today|tomorrow|yesterday)\s+at\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b',
        # Recurring patterns
        r'\bevery\s+\w+\b',  # every Monday, every day, etc.
        # Next/this patterns
        r'\b(next|this)\s+\w+\b',  # next Monday, this Friday
        # Simple day keywords (must come after compound patterns)
        r'\b(today|tomorrow|yesterday)\b',
        # Named dates with numbers
        r'\b\w+\s+\d{1,2}(st|nd|rd|th)?\b',  # March 15th, Feb 3
        # Relative dates
        r'\bin\s+\d+\s+(day|days|week|weeks|month|months)\b',
        # Numeric dates
        r'\b\d{1,2}/\d{1,2}(/\d{2,4})?\b',  # 3/15 or 3/15/2026
        r'\b\d{4}-\d{2}-\d{2}\b',  # 2026-03-15
    ]

    for pattern in due_date_patterns:
        due_match = re.search(pattern, text, re.IGNORECASE)
        if due_match:
            result["due_string"] = due_match.group(0)
            text = text.replace(due_match.group(0), "").strip()
            break

    # Clean up content - remove extra spaces
    result["content"] = re.sub(r'\s+', ' ', text).strip()

    return result

@app.route("/api/v1/tasks/quick", methods=["POST"])
def quick_add_task_rest_api():
    """
    Quick Add endpoint (REST API v2) - parse natural language task entry.

    Accepts a 'text' parameter with Todoist quick add notation:
    - #project for project assignment
    - @label for labels
    - +assignee for assignment (ignored)
    - p1-p4 for priority
    - Natural language dates (tomorrow, every Monday, etc.)

    Optional parameters:
    - note: Add a note/description to the task
    - reminder: Reminder string (not implemented in fake)
    - auto_reminder: Auto reminder flag (not implemented in fake)
    - meta: Return extra metadata (not implemented in fake)
    """
    data = request.get_json() or {}
    text = data.get("text")
    note = data.get("note")

    if not text:
        return jsonify({"error": "text parameter is required"}), 400

    # Parse the quick add text
    parsed = parse_quick_add_text(text)

    # Look up project by name if specified
    project_id = None
    if parsed["project_name"]:
        for pid, proj in state["projects"].items():
            if proj["name"] == parsed["project_name"]:
                project_id = pid
                break

    # Create the task using the same logic as create_task endpoint
    task_id = str(state["task_counter"])
    state["task_counter"] += 1

    # Build due object if due_string was parsed
    due = None
    if parsed["due_string"]:
        due = {
            "date": "2026-02-16",  # Dummy date, real API would parse this
            "string": parsed["due_string"],
            "timezone": None,
            "is_recurring": "every" in parsed["due_string"].lower(),
        }

    task = {
        "id": task_id,
        "content": parsed["content"],
        "description": note or "",
        "project_id": project_id or "inbox",
        "section_id": None,
        "parent_id": None,
        "order": 0,
        "labels": parsed["labels"],
        "priority": parsed["priority"],
        "due": due,
        "duration": None,
        "assignee_id": None,
        "assigner_id": None,
        "is_collapsed": False,
        "created_at": "2026-02-15T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
        "creator_id": "1",
        "completed_at": None,
    }

    state["tasks"][task_id] = task

    # Trigger webhook for item:added event
    trigger_webhook("item:added", task)

    # Return in REST API format (standard task response)
    return jsonify(create_task_response(task))


@app.route("/sync/v9/quick/add", methods=["POST"])
def quick_add_task():
    """
    Quick Add endpoint - parse natural language task entry.

    Accepts a 'text' parameter with Todoist quick add notation:
    - #project for project assignment
    - @label for labels
    - +assignee for assignment (ignored)
    - p1-p4 for priority
    - Natural language dates (tomorrow, every Monday, etc.)

    Optional parameters:
    - note: Add a note/description to the task
    - reminder: Reminder string (not implemented in fake)
    - auto_reminder: Auto reminder flag (not implemented in fake)
    - meta: Return extra metadata (not implemented in fake)
    """
    # Get form data (sent as application/x-www-form-urlencoded) or JSON
    if request.content_type and 'application/json' in request.content_type:
        data = request.get_json() or {}
        text = data.get("text")
        note = data.get("note")
    else:
        text = request.form.get("text")
        note = request.form.get("note")

    if not text:
        return jsonify({"error": "text parameter is required"}), 400

    # Parse the quick add text
    parsed = parse_quick_add_text(text)

    # Look up project by name if specified
    project_id = None
    if parsed["project_name"]:
        for pid, proj in state["projects"].items():
            if proj["name"] == parsed["project_name"]:
                project_id = pid
                break

    # Create the task using the same logic as create_task endpoint
    task_id = str(state["task_counter"])
    state["task_counter"] += 1

    # Build due object if due_string was parsed
    due = None
    if parsed["due_string"]:
        due = {
            "date": "2026-02-16",  # Dummy date, real API would parse this
            "string": parsed["due_string"],
            "timezone": None,
            "is_recurring": "every" in parsed["due_string"].lower(),
        }

    task = {
        "id": task_id,
        "content": parsed["content"],
        "description": note or "",
        "project_id": project_id or "inbox",
        "section_id": None,
        "parent_id": None,
        "order": 0,
        "labels": parsed["labels"],
        "priority": parsed["priority"],
        "due": due,
        "duration": None,
        "assignee_id": None,
        "assigner_id": None,
        "is_collapsed": False,
        "created_at": "2026-02-15T00:00:00Z",
        "updated_at": "2026-02-15T00:00:00Z",
        "creator_id": "1",
        "completed_at": None,
        # Additional fields for Sync API response format
        "added_by_uid": "2671355",
        "assigned_by_uid": "2671355",
        "sync_id": None,
        "added_at": "2026-02-15T00:00:00Z",
        "is_deleted": False,
        "user_id": "2671355",
        "deadline": None,
        "responsible_uid": "2671355",
        "collapsed": False,
        "checked": False,
        "child_order": 0,
    }

    state["tasks"][task_id] = task

    # Trigger webhook for item:added event
    trigger_webhook("item:added", task)

    # Return in Sync API format (slightly different from REST API)
    response = {
        "id": task_id,
        "content": task["content"],
        "description": task["description"],
        "project_id": task["project_id"],
        "section_id": task["section_id"],
        "parent_id": task["parent_id"],
        "order": task["order"],
        "labels": task["labels"],
        "priority": task["priority"],
        "due": task["due"],
        "duration": task["duration"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
        "is_deleted": False,
        "user_id": "2671355",
        "added_by_uid": "2671355",
        "assigned_by_uid": "2671355",
        "responsible_uid": "2671355",
        "sync_id": None,
        "added_at": task["added_at"],
        "deadline": None,
        "collapsed": False,
        "checked": False,
        "child_order": 0,
    }

    return jsonify(response)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
