"""
GitHub API Fake - DoubleAgent Service

A high-fidelity fake of the GitHub REST API for AI agent testing.
Built with FastAPI for async support and automatic OpenAPI generation.
"""

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# =============================================================================
# State
# =============================================================================

state: dict[str, dict] = {
    "users": {},
    "repos": {},
    "issues": {},
    "pulls": {},
    "webhooks": {},  # repo_key -> [webhook]
}

counters: dict[str, int] = {
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


def next_id(key: str) -> int:
    counters[key] += 1
    return counters[key]


def reset_state() -> None:
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
# Pydantic Models
# =============================================================================

class RepoCreate(BaseModel):
    name: str
    description: str = ""
    private: bool = False
    auto_init: bool = False


class RepoUpdate(BaseModel):
    description: Optional[str] = None
    private: Optional[bool] = None
    default_branch: Optional[str] = None


class IssueCreate(BaseModel):
    title: str
    body: str = ""
    labels: list[str] = []
    assignees: list[str] = []


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    state: Optional[str] = None
    labels: Optional[list[str]] = None
    assignees: Optional[list[str]] = None


class PullCreate(BaseModel):
    title: str
    body: str = ""
    head: str
    base: str


class PullUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    state: Optional[str] = None


class WebhookConfig(BaseModel):
    url: str
    content_type: str = "json"


class WebhookCreate(BaseModel):
    config: WebhookConfig
    events: list[str] = ["*"]


class SeedData(BaseModel):
    repos: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title="GitHub API Fake",
    description="DoubleAgent fake of the GitHub REST API",
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
    
    if data.repos:
        for r in data.repos:
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
        seeded["repos"] = len(data.repos)
    
    if data.issues:
        for i in data.issues:
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
        seeded["issues"] = len(data.issues)
    
    return {"status": "ok", "seeded": seeded}


@app.get("/_doubleagent/info")
async def info():
    """Service info - OPTIONAL."""
    return {
        "name": "github",
        "version": "1.0",
        "endpoints": {
            "repos": len(state["repos"]),
            "issues": len(state["issues"]),
            "pulls": len(state["pulls"]),
        }
    }


# =============================================================================
# User endpoints
# =============================================================================

@app.get("/user")
async def get_authenticated_user():
    """Get the authenticated user."""
    return DEFAULT_USER


@app.get("/users/{login}")
async def get_user(login: str):
    """Get a user by login."""
    if login in state["users"]:
        return state["users"][login]
    return {
        "login": login,
        "id": hash(login) % 1000000,
        "type": "User",
        "site_admin": False,
    }


# =============================================================================
# Repository endpoints
# =============================================================================

@app.get("/user/repos")
async def list_user_repos():
    """List repos for authenticated user."""
    repos = [r for r in state["repos"].values() 
             if r["owner"]["login"] == DEFAULT_USER["login"]]
    return repos


@app.post("/user/repos", status_code=201)
async def create_user_repo(repo: RepoCreate):
    """Create a repo for authenticated user."""
    repo_id = next_id("repo_id")
    key = f"{DEFAULT_USER['login']}/{repo.name}"
    
    repo_obj = {
        "id": repo_id,
        "name": repo.name,
        "full_name": key,
        "owner": DEFAULT_USER,
        "private": repo.private,
        "description": repo.description,
        "default_branch": "main",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "html_url": f"https://github.com/{key}",
        "clone_url": f"https://github.com/{key}.git",
    }
    state["repos"][key] = repo_obj
    
    return repo_obj


@app.get("/repos/{owner}/{repo}")
async def get_repo(owner: str, repo: str):
    """Get a repository."""
    key = f"{owner}/{repo}"
    if key not in state["repos"]:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    return state["repos"][key]


@app.patch("/repos/{owner}/{repo}")
async def update_repo(owner: str, repo: str, update: RepoUpdate):
    """Update a repository."""
    key = f"{owner}/{repo}"
    if key not in state["repos"]:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    
    repo_obj = state["repos"][key]
    if update.description is not None:
        repo_obj["description"] = update.description
    if update.private is not None:
        repo_obj["private"] = update.private
    if update.default_branch is not None:
        repo_obj["default_branch"] = update.default_branch
    
    return repo_obj


@app.delete("/repos/{owner}/{repo}", status_code=204)
async def delete_repo(owner: str, repo: str):
    """Delete a repository."""
    key = f"{owner}/{repo}"
    if key in state["repos"]:
        del state["repos"][key]
    return None


# =============================================================================
# Issue endpoints
# =============================================================================

@app.get("/repos/{owner}/{repo}/issues")
async def list_issues(owner: str, repo: str, state_filter: str = "open"):
    """List issues for a repository."""
    key = f"{owner}/{repo}"
    issues = [i for i in state["issues"].values() 
              if i["repo_key"] == key and 
              (state_filter == "all" or i["state"] == state_filter)]
    return issues


@app.post("/repos/{owner}/{repo}/issues", status_code=201)
async def create_issue(owner: str, repo: str, issue: IssueCreate):
    """Create an issue."""
    key = f"{owner}/{repo}"
    if key not in state["repos"]:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    
    issue_id = next_id("issue_id")
    
    # Count existing issues for this repo to get number
    repo_issues = [i for i in state["issues"].values() if i["repo_key"] == key]
    number = len(repo_issues) + 1
    
    issue_obj = {
        "id": issue_id,
        "number": number,
        "title": issue.title,
        "body": issue.body,
        "state": "open",
        "repo_key": key,
        "user": DEFAULT_USER,
        "labels": issue.labels,
        "assignees": issue.assignees,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "html_url": f"https://github.com/{key}/issues/{number}",
    }
    state["issues"][issue_id] = issue_obj
    
    # Dispatch webhooks
    await dispatch_webhook(owner, repo, "issues", {
        "action": "opened",
        "issue": issue_obj,
        "repository": state["repos"].get(key, {}),
    })
    
    return issue_obj


@app.get("/repos/{owner}/{repo}/issues/{issue_number}")
async def get_issue(owner: str, repo: str, issue_number: int):
    """Get an issue by number."""
    key = f"{owner}/{repo}"
    
    for i in state["issues"].values():
        if i["repo_key"] == key and i["number"] == issue_number:
            return i
    
    raise HTTPException(status_code=404, detail={"message": "Not Found"})


@app.patch("/repos/{owner}/{repo}/issues/{issue_number}")
async def update_issue(owner: str, repo: str, issue_number: int, update: IssueUpdate):
    """Update an issue."""
    key = f"{owner}/{repo}"
    
    issue = None
    for i in state["issues"].values():
        if i["repo_key"] == key and i["number"] == issue_number:
            issue = i
            break
    
    if not issue:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    
    old_state = issue["state"]
    
    if update.title is not None:
        issue["title"] = update.title
    if update.body is not None:
        issue["body"] = update.body
    if update.state is not None:
        issue["state"] = update.state
    if update.labels is not None:
        issue["labels"] = update.labels
    if update.assignees is not None:
        issue["assignees"] = update.assignees
    
    # Dispatch webhook if state changed
    if update.state and update.state != old_state:
        await dispatch_webhook(owner, repo, "issues", {
            "action": "closed" if update.state == "closed" else "reopened",
            "issue": issue,
            "repository": state["repos"].get(key, {}),
        })
    
    return issue


# =============================================================================
# Pull Request endpoints
# =============================================================================

@app.get("/repos/{owner}/{repo}/pulls")
async def list_pulls(owner: str, repo: str, state_filter: str = "open"):
    """List pull requests for a repository."""
    key = f"{owner}/{repo}"
    pulls = [p for p in state["pulls"].values() 
             if p["repo_key"] == key and 
             (state_filter == "all" or p["state"] == state_filter)]
    return pulls


@app.post("/repos/{owner}/{repo}/pulls", status_code=201)
async def create_pull(owner: str, repo: str, pull: PullCreate):
    """Create a pull request."""
    key = f"{owner}/{repo}"
    if key not in state["repos"]:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    
    pull_id = next_id("pull_id")
    
    # Count existing PRs for number
    repo_pulls = [p for p in state["pulls"].values() if p["repo_key"] == key]
    number = len(repo_pulls) + 1
    
    pull_obj = {
        "id": pull_id,
        "number": number,
        "title": pull.title,
        "body": pull.body,
        "state": "open",
        "head": {"ref": pull.head, "sha": "abc123"},
        "base": {"ref": pull.base, "sha": "def456"},
        "repo_key": key,
        "user": DEFAULT_USER,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "merged": False,
        "mergeable": True,
        "html_url": f"https://github.com/{key}/pull/{number}",
    }
    state["pulls"][pull_id] = pull_obj
    
    # Dispatch webhook
    await dispatch_webhook(owner, repo, "pull_request", {
        "action": "opened",
        "pull_request": pull_obj,
        "repository": state["repos"].get(key, {}),
    })
    
    return pull_obj


@app.get("/repos/{owner}/{repo}/pulls/{pull_number}")
async def get_pull(owner: str, repo: str, pull_number: int):
    """Get a pull request by number."""
    key = f"{owner}/{repo}"
    
    for p in state["pulls"].values():
        if p["repo_key"] == key and p["number"] == pull_number:
            return p
    
    raise HTTPException(status_code=404, detail={"message": "Not Found"})


@app.patch("/repos/{owner}/{repo}/pulls/{pull_number}")
async def update_pull(owner: str, repo: str, pull_number: int, update: PullUpdate):
    """Update a pull request."""
    key = f"{owner}/{repo}"
    
    pull = None
    for p in state["pulls"].values():
        if p["repo_key"] == key and p["number"] == pull_number:
            pull = p
            break
    
    if not pull:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    
    if update.title is not None:
        pull["title"] = update.title
    if update.body is not None:
        pull["body"] = update.body
    if update.state is not None:
        pull["state"] = update.state
    
    return pull


# =============================================================================
# Webhook endpoints
# =============================================================================

@app.get("/repos/{owner}/{repo}/hooks")
async def list_hooks(owner: str, repo: str):
    """List webhooks for a repository."""
    key = f"{owner}/{repo}"
    return state["webhooks"].get(key, [])


@app.post("/repos/{owner}/{repo}/hooks", status_code=201)
async def create_hook(owner: str, repo: str, webhook: WebhookCreate):
    """Create a webhook."""
    key = f"{owner}/{repo}"
    webhook_id = next_id("webhook_id")
    
    hook = {
        "id": webhook_id,
        "url": webhook.config.url,
        "events": webhook.events,
        "active": True,
        "config": webhook.config.model_dump(),
    }
    
    if key not in state["webhooks"]:
        state["webhooks"][key] = []
    state["webhooks"][key].append(hook)
    
    return hook


@app.get("/repos/{owner}/{repo}/hooks/{hook_id}")
async def get_hook(owner: str, repo: str, hook_id: int):
    """Get a webhook by ID."""
    key = f"{owner}/{repo}"
    hooks = state["webhooks"].get(key, [])
    
    for hook in hooks:
        if hook["id"] == hook_id:
            return hook
    
    raise HTTPException(status_code=404, detail={"message": "Not Found"})


@app.delete("/repos/{owner}/{repo}/hooks/{hook_id}", status_code=204)
async def delete_hook(owner: str, repo: str, hook_id: int):
    """Delete a webhook."""
    key = f"{owner}/{repo}"
    hooks = state["webhooks"].get(key, [])
    state["webhooks"][key] = [h for h in hooks if h["id"] != hook_id]
    return None


async def dispatch_webhook(owner: str, repo: str, event_type: str, payload: dict) -> None:
    """Dispatch webhooks asynchronously."""
    key = f"{owner}/{repo}"
    hooks = state["webhooks"].get(key, [])
    
    for hook in hooks:
        if not hook["active"]:
            continue
        if event_type not in hook["events"] and "*" not in hook["events"]:
            continue
        
        # Fire in background task
        asyncio.create_task(_send_webhook(hook["url"], event_type, payload))


async def _send_webhook(url: str, event_type: str, payload: dict) -> None:
    """Send webhook (runs as background task)."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                url,
                json=payload,
                headers={
                    "X-GitHub-Event": event_type,
                    "Content-Type": "application/json",
                },
                timeout=5.0,
            )
    except Exception:
        pass  # Webhook delivery is best-effort


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
