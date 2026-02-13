"""
GitHub API Fake - DoubleAgent Service

A high-fidelity fake of the GitHub REST API for AI agent testing.
"""

import os
import threading
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# =============================================================================
# State
# =============================================================================

state = {
    "users": {},
    "repos": {},
    "issues": {},
    "pulls": {},
    "webhooks": {},  # repo_key -> [webhook]
}

counters = {
    "repo_id": 0,
    "issue_id": 0,
    "pull_id": 0,
    "webhook_id": 0,
}

DEFAULT_USER = {
    "login": "doubleagent",
    "id": 1,
    "type": "User",
    "site_admin": False,
}


def next_id(key):
    counters[key] += 1
    return counters[key]


def reset_state():
    global state, counters
    state = {
        "users": {},
        "repos": {},
        "issues": {},
        "pulls": {},
        "webhooks": {},
    }
    counters = {
        "repo_id": 0,
        "issue_id": 0,
        "pull_id": 0,
        "webhook_id": 0,
    }


# =============================================================================
# /_doubleagent endpoints (REQUIRED)
# =============================================================================

@app.route("/_doubleagent/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


@app.route("/_doubleagent/reset", methods=["POST"])
def reset():
    reset_state()
    return jsonify({"status": "ok"})


@app.route("/_doubleagent/seed", methods=["POST"])
def seed():
    data = request.json or {}
    seeded = {}
    
    if "repos" in data:
        for r in data["repos"]:
            key = f"{r['owner']}/{r['name']}"
            repo_id = next_id("repo_id")
            state["repos"][key] = {
                "id": repo_id,
                "name": r["name"],
                "full_name": key,
                "owner": {"login": r["owner"], "id": 1, "type": "User"},
                "private": r.get("private", False),
                "description": r.get("description", ""),
                "default_branch": r.get("default_branch", "main"),
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        seeded["repos"] = len(data["repos"])
    
    if "issues" in data:
        for i in data["issues"]:
            issue_id = next_id("issue_id")
            repo_key = i.get("repo", "doubleagent/test")
            state["issues"][issue_id] = {
                "id": issue_id,
                "number": issue_id,
                "title": i["title"],
                "body": i.get("body", ""),
                "state": i.get("state", "open"),
                "repo_key": repo_key,
                "user": DEFAULT_USER,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
        seeded["issues"] = len(data["issues"])
    
    return jsonify({"status": "ok", "seeded": seeded})


@app.route("/_doubleagent/info", methods=["GET"])
def info():
    return jsonify({
        "name": "github",
        "version": "1.0",
        "endpoints": {
            "repos": len(state["repos"]),
            "issues": len(state["issues"]),
            "pulls": len(state["pulls"]),
        }
    })


# =============================================================================
# User endpoints
# =============================================================================

@app.route("/user", methods=["GET"])
def get_authenticated_user():
    """Get the authenticated user."""
    return jsonify(DEFAULT_USER)


@app.route("/users/<login>", methods=["GET"])
def get_user(login):
    """Get a user by login."""
    if login in state["users"]:
        return jsonify(state["users"][login])
    return jsonify({
        "login": login,
        "id": hash(login) % 1000000,
        "type": "User",
        "site_admin": False,
    })


# =============================================================================
# Repository endpoints
# =============================================================================

@app.route("/user/repos", methods=["GET", "POST"])
def user_repos():
    """List or create repos for authenticated user."""
    if request.method == "GET":
        repos = [r for r in state["repos"].values() 
                 if r["owner"]["login"] == DEFAULT_USER["login"]]
        return jsonify(repos)
    
    # POST - create repo
    data = request.json
    repo_id = next_id("repo_id")
    name = data["name"]
    key = f"{DEFAULT_USER['login']}/{name}"
    
    repo = {
        "id": repo_id,
        "name": name,
        "full_name": key,
        "owner": DEFAULT_USER,
        "private": data.get("private", False),
        "description": data.get("description", ""),
        "default_branch": "main",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "html_url": f"https://github.com/{key}",
        "clone_url": f"https://github.com/{key}.git",
    }
    state["repos"][key] = repo
    
    return jsonify(repo), 201


@app.route("/repos/<owner>/<repo>", methods=["GET", "PATCH", "DELETE"])
def repo_detail(owner, repo):
    """Get, update, or delete a repository."""
    key = f"{owner}/{repo}"
    
    if request.method == "GET":
        if key not in state["repos"]:
            return jsonify({"message": "Not Found"}), 404
        return jsonify(state["repos"][key])
    
    if request.method == "PATCH":
        if key not in state["repos"]:
            return jsonify({"message": "Not Found"}), 404
        data = request.json
        repo_obj = state["repos"][key]
        if "description" in data:
            repo_obj["description"] = data["description"]
        if "private" in data:
            repo_obj["private"] = data["private"]
        if "default_branch" in data:
            repo_obj["default_branch"] = data["default_branch"]
        return jsonify(repo_obj)
    
    if request.method == "DELETE":
        if key in state["repos"]:
            del state["repos"][key]
        return "", 204


# =============================================================================
# Issue endpoints
# =============================================================================

@app.route("/repos/<owner>/<repo>/issues", methods=["GET", "POST"])
def repo_issues(owner, repo):
    """List or create issues."""
    key = f"{owner}/{repo}"
    
    if request.method == "GET":
        filter_state = request.args.get("state", "open")
        issues = [i for i in state["issues"].values() 
                  if i["repo_key"] == key and 
                  (filter_state == "all" or i["state"] == filter_state)]
        return jsonify(issues)
    
    # POST - create issue
    if key not in state["repos"]:
        return jsonify({"message": "Not Found"}), 404
    
    data = request.json
    issue_id = next_id("issue_id")
    
    # Count existing issues for this repo to get number
    repo_issues = [i for i in state["issues"].values() if i["repo_key"] == key]
    number = len(repo_issues) + 1
    
    issue = {
        "id": issue_id,
        "number": number,
        "title": data["title"],
        "body": data.get("body", ""),
        "state": "open",
        "repo_key": key,
        "user": DEFAULT_USER,
        "labels": data.get("labels", []),
        "assignees": data.get("assignees", []),
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "html_url": f"https://github.com/{key}/issues/{number}",
    }
    state["issues"][issue_id] = issue
    
    # Dispatch webhooks
    dispatch_webhook(owner, repo, "issues", {
        "action": "opened",
        "issue": issue,
        "repository": state["repos"].get(key, {}),
    })
    
    return jsonify(issue), 201


@app.route("/repos/<owner>/<repo>/issues/<int:issue_number>", methods=["GET", "PATCH"])
def issue_detail(owner, repo, issue_number):
    """Get or update an issue."""
    key = f"{owner}/{repo}"
    
    # Find issue by number
    issue = None
    for i in state["issues"].values():
        if i["repo_key"] == key and i["number"] == issue_number:
            issue = i
            break
    
    if not issue:
        return jsonify({"message": "Not Found"}), 404
    
    if request.method == "GET":
        return jsonify(issue)
    
    # PATCH - update issue
    data = request.json
    old_state = issue["state"]
    
    if "title" in data:
        issue["title"] = data["title"]
    if "body" in data:
        issue["body"] = data["body"]
    if "state" in data:
        issue["state"] = data["state"]
    if "labels" in data:
        issue["labels"] = data["labels"]
    if "assignees" in data:
        issue["assignees"] = data["assignees"]
    
    # Dispatch webhook if state changed
    if data.get("state") and data["state"] != old_state:
        dispatch_webhook(owner, repo, "issues", {
            "action": "closed" if data["state"] == "closed" else "reopened",
            "issue": issue,
            "repository": state["repos"].get(key, {}),
        })
    
    return jsonify(issue)


# =============================================================================
# Pull Request endpoints
# =============================================================================

@app.route("/repos/<owner>/<repo>/pulls", methods=["GET", "POST"])
def repo_pulls(owner, repo):
    """List or create pull requests."""
    key = f"{owner}/{repo}"
    
    if request.method == "GET":
        filter_state = request.args.get("state", "open")
        pulls = [p for p in state["pulls"].values() 
                 if p["repo_key"] == key and 
                 (filter_state == "all" or p["state"] == filter_state)]
        return jsonify(pulls)
    
    # POST - create PR
    if key not in state["repos"]:
        return jsonify({"message": "Not Found"}), 404
    
    data = request.json
    pull_id = next_id("pull_id")
    
    # Count existing PRs for number
    repo_pulls = [p for p in state["pulls"].values() if p["repo_key"] == key]
    number = len(repo_pulls) + 1
    
    pull = {
        "id": pull_id,
        "number": number,
        "title": data["title"],
        "body": data.get("body", ""),
        "state": "open",
        "head": {"ref": data["head"], "sha": "abc123"},
        "base": {"ref": data["base"], "sha": "def456"},
        "repo_key": key,
        "user": DEFAULT_USER,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "merged": False,
        "mergeable": True,
        "html_url": f"https://github.com/{key}/pull/{number}",
    }
    state["pulls"][pull_id] = pull
    
    # Dispatch webhook
    dispatch_webhook(owner, repo, "pull_request", {
        "action": "opened",
        "pull_request": pull,
        "repository": state["repos"].get(key, {}),
    })
    
    return jsonify(pull), 201


@app.route("/repos/<owner>/<repo>/pulls/<int:pull_number>", methods=["GET", "PATCH"])
def pull_detail(owner, repo, pull_number):
    """Get or update a pull request."""
    key = f"{owner}/{repo}"
    
    pull = None
    for p in state["pulls"].values():
        if p["repo_key"] == key and p["number"] == pull_number:
            pull = p
            break
    
    if not pull:
        return jsonify({"message": "Not Found"}), 404
    
    if request.method == "GET":
        return jsonify(pull)
    
    # PATCH - update PR
    data = request.json
    if "title" in data:
        pull["title"] = data["title"]
    if "body" in data:
        pull["body"] = data["body"]
    if "state" in data:
        pull["state"] = data["state"]
    
    return jsonify(pull)


# =============================================================================
# Webhook endpoints
# =============================================================================

@app.route("/repos/<owner>/<repo>/hooks", methods=["GET", "POST"])
def repo_hooks(owner, repo):
    """List or create webhooks."""
    key = f"{owner}/{repo}"
    
    if request.method == "GET":
        hooks = state["webhooks"].get(key, [])
        return jsonify(hooks)
    
    # POST - create webhook
    data = request.json
    webhook_id = next_id("webhook_id")
    
    hook = {
        "id": webhook_id,
        "url": data["config"]["url"],
        "events": data.get("events", ["*"]),
        "active": True,
        "config": data["config"],
    }
    
    if key not in state["webhooks"]:
        state["webhooks"][key] = []
    state["webhooks"][key].append(hook)
    
    return jsonify(hook), 201


@app.route("/repos/<owner>/<repo>/hooks/<int:hook_id>", methods=["GET", "DELETE"])
def hook_detail(owner, repo, hook_id):
    """Get or delete a webhook."""
    key = f"{owner}/{repo}"
    hooks = state["webhooks"].get(key, [])
    
    hook = next((h for h in hooks if h["id"] == hook_id), None)
    if not hook:
        return jsonify({"message": "Not Found"}), 404
    
    if request.method == "GET":
        return jsonify(hook)
    
    # DELETE
    state["webhooks"][key] = [h for h in hooks if h["id"] != hook_id]
    return "", 204


def dispatch_webhook(owner, repo, event_type, payload):
    """Dispatch webhooks asynchronously."""
    key = f"{owner}/{repo}"
    hooks = state["webhooks"].get(key, [])
    
    for hook in hooks:
        if not hook["active"]:
            continue
        if event_type not in hook["events"] and "*" not in hook["events"]:
            continue
        
        # Fire in background thread
        threading.Thread(
            target=_send_webhook,
            args=(hook["url"], event_type, payload)
        ).start()


def _send_webhook(url, event_type, payload):
    """Send webhook (runs in background thread)."""
    try:
        requests.post(
            url,
            json=payload,
            headers={
                "X-GitHub-Event": event_type,
                "Content-Type": "application/json",
            },
            timeout=5
        )
    except Exception:
        pass  # Webhook delivery is best-effort


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
