"""
GitHub API Fake — DoubleAgent Service

A high-fidelity fake of the GitHub REST API for AI agent testing.
Copy-on-write state, per-agent namespace isolation, and webhook
delivery with retry + HMAC.
"""

import asyncio
import copy
import hashlib
import hmac
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request, Query
from pydantic import BaseModel


# =============================================================================
# Inline SDK: StateOverlay (copy-on-write state)
# =============================================================================

NAMESPACE_HEADER = "X-DoubleAgent-Namespace"
DEFAULT_NAMESPACE = "default"


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
# Inline SDK: NamespaceRouter (per-agent isolation)
# =============================================================================

class NamespaceRouter:
    """Manages isolated StateOverlay instances keyed by namespace."""

    def __init__(self) -> None:
        self._baseline: dict[str, dict[str, Any]] = {}
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

    def reset_all(self, *, hard: bool = False) -> None:
        for ns in list(self._namespaces):
            self.reset_namespace(ns, hard=hard)

    def list_namespaces(self) -> list[dict[str, Any]]:
        result = []
        for ns, overlay in self._namespaces.items():
            stats = overlay.stats()
            result.append({"namespace": ns, **stats})
        return result

    def delete_namespace(self, namespace: str) -> bool:
        return self._namespaces.pop(namespace, None) is not None


# =============================================================================
# Inline SDK: WebhookSimulator (delivery with retry + HMAC)
# =============================================================================

@dataclass
class WebhookDelivery:
    id: str
    event_type: str
    payload: dict[str, Any]
    target_url: str
    namespace: str
    status: str = "pending"
    attempts: int = 0
    last_attempt_at: float | None = None
    response_code: int | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "event_type": self.event_type,
            "target_url": self.target_url, "namespace": self.namespace,
            "status": self.status, "attempts": self.attempts,
            "last_attempt_at": self.last_attempt_at,
            "response_code": self.response_code, "error": self.error,
            "created_at": self.created_at,
        }


_DEFAULT_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _is_target_allowed(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if hostname in allowed_hosts:
        return True
    try:
        addr = ip_address(hostname)
        return addr.is_loopback or addr.is_private
    except ValueError:
        return False


def _compute_signature(payload: dict[str, Any], secret: str | None) -> str | None:
    if not secret:
        return None
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class WebhookSimulator:
    def __init__(
        self,
        max_retries: int = 3,
        retry_delays: list[float] | None = None,
        allowed_hosts: set[str] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.max_retries = max_retries
        self.retry_delays = retry_delays or [1.0, 5.0, 30.0]
        self.allowed_hosts = allowed_hosts or _DEFAULT_ALLOWED_HOSTS
        self.timeout = timeout
        self._deliveries: list[WebhookDelivery] = []

    async def deliver(
        self, target_url: str, event_type: str, payload: dict[str, Any], *,
        secret: str | None = None, namespace: str = "default",
        extra_headers: dict[str, str] | None = None,
    ) -> WebhookDelivery:
        delivery = WebhookDelivery(
            id=uuid.uuid4().hex[:16], event_type=event_type,
            payload=payload, target_url=target_url, namespace=namespace,
        )
        self._deliveries.append(delivery)
        if not _is_target_allowed(target_url, self.allowed_hosts):
            delivery.status = "failed"
            delivery.error = f"target host not in allowlist: {urlparse(target_url).hostname}"
            return delivery
        asyncio.create_task(
            self._deliver_with_retry(delivery, secret=secret, extra_headers=extra_headers)
        )
        return delivery

    def get_deliveries(self, *, namespace: str | None = None,
                       event_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        results = self._deliveries
        if namespace:
            results = [d for d in results if d.namespace == namespace]
        if event_type:
            results = [d for d in results if d.event_type == event_type]
        return [d.to_dict() for d in reversed(results[-limit:])]

    def clear(self) -> None:
        self._deliveries.clear()

    async def _deliver_with_retry(self, delivery: WebhookDelivery, *,
                                  secret: str | None = None,
                                  extra_headers: dict[str, str] | None = None) -> None:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-DoubleAgent-Delivery": delivery.id,
            "X-DoubleAgent-Namespace": delivery.namespace,
        }
        sig = _compute_signature(delivery.payload, secret)
        if sig:
            headers["X-Hub-Signature-256"] = sig
        if extra_headers:
            headers.update(extra_headers)
        for attempt in range(self.max_retries):
            delivery.attempts = attempt + 1
            delivery.last_attempt_at = time.time()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(delivery.target_url, json=delivery.payload, headers=headers)
                delivery.response_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    delivery.status = "delivered"
                    return
            except Exception as exc:
                delivery.error = str(exc)
            if attempt < self.max_retries - 1:
                delay = self.retry_delays[attempt] if attempt < len(self.retry_delays) else self.retry_delays[-1]
                await asyncio.sleep(delay)
        delivery.status = "failed"


# =============================================================================
# Helpers
# =============================================================================

def get_base_url(request: Request) -> str:
    """Get base URL from request for API URLs."""
    return str(request.base_url).rstrip("/")


def get_namespace(request: Request) -> str:
    """Extract namespace from request header."""
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)


def get_state(request: Request) -> StateOverlay:
    """Get the state overlay for the current request's namespace."""
    return router.get_state(get_namespace(request))


# =============================================================================
# State (namespace-aware)
# =============================================================================

router = NamespaceRouter()
webhook_sim = WebhookSimulator(max_retries=3, retry_delays=[0.5, 2.0, 10.0])

DEFAULT_USER = {
    "login": "doubleagent",
    "id": 1,
    "type": "User",
    "site_admin": False,
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
    secret: Optional[str] = None


class WebhookCreate(BaseModel):
    config: WebhookConfig
    events: list[str] = ["*"]


class SeedData(BaseModel):
    repos: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []


class BootstrapData(BaseModel):
    """Data sent by CLI to load a snapshot baseline."""
    repos: dict[str, Any] = {}
    issues: dict[str, Any] = {}
    pulls: dict[str, Any] = {}
    users: dict[str, Any] = {}
    webhooks: dict[str, Any] = {}


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


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
    """Health check — REQUIRED."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset(request: Request, hard: bool = Query(default=False)):
    """Reset state — REQUIRED.

    Without ``?hard=true``, resets to snapshot baseline.
    With ``?hard=true``, resets to empty (ignores snapshot).
    """
    ns = get_namespace(request)
    router.reset_namespace(ns, hard=hard)
    webhook_sim.clear()
    mode = "hard (empty)" if hard else "baseline"
    return {"status": "ok", "reset_mode": mode, "namespace": ns}


@app.post("/_doubleagent/seed")
async def seed(request: Request, data: SeedData):
    """Seed state from JSON — REQUIRED.

    Merges into overlay; snapshot baseline is preserved beneath.
    """
    state = get_state(request)
    ns = get_namespace(request)
    seeded: dict[str, int] = {}

    if data.repos:
        for r in data.repos:
            key = f"{r['owner']}/{r['name']}"
            repo_id = state.next_id("repos")
            state.put("repos", key, {
                "id": repo_id,
                "name": r["name"],
                "full_name": key,
                "owner": {"login": r["owner"], "id": 1, "type": "User"},
                "private": r.get("private", False),
                "description": r.get("description", ""),
                "default_branch": r.get("default_branch", "main"),
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            })
        seeded["repos"] = len(data.repos)

    if data.issues:
        for i in data.issues:
            issue_id = state.next_id("issues")
            repo_key = i.get("repo", "doubleagent/test")
            state.put("issues", str(issue_id), {
                "id": issue_id,
                "number": issue_id,
                "title": i["title"],
                "body": i.get("body", ""),
                "state": i.get("state", "open"),
                "repo_key": repo_key,
                "user": DEFAULT_USER,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            })
        seeded["issues"] = len(data.issues)

    return {"status": "ok", "seeded": seeded, "namespace": ns}


@app.post("/_doubleagent/bootstrap")
async def bootstrap(data: BootstrapData):
    """Load snapshot baseline.  Called by CLI on ``start --snapshot``.

    Replaces the shared baseline for all namespaces.
    """
    baseline: dict[str, dict[str, Any]] = {}
    for rtype in ("repos", "issues", "pulls", "users", "webhooks"):
        d = getattr(data, rtype, {})
        if d:
            baseline[rtype] = d
    router.load_baseline(baseline)
    counts = {k: len(v) for k, v in baseline.items()}
    return {"status": "ok", "loaded": counts}


@app.get("/_doubleagent/info")
async def info(request: Request):
    """Service info — OPTIONAL."""
    state = get_state(request)
    return {
        "name": "github",
        "version": "1.0",
        "namespace": get_namespace(request),
        "state": state.stats(),
    }


@app.get("/_doubleagent/webhooks")
async def list_webhook_deliveries(
    request: Request,
    event_type: Optional[str] = None,
    limit: int = Query(default=100),
):
    """Query the webhook delivery log."""
    ns = get_namespace(request)
    return webhook_sim.get_deliveries(namespace=ns, event_type=event_type, limit=limit)


@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    """List active namespaces and their state sizes."""
    return router.list_namespaces()


# =============================================================================
# User endpoints
# =============================================================================

@app.get("/user")
async def get_authenticated_user():
    return DEFAULT_USER


@app.get("/users/{login}")
async def get_user(request: Request, login: str):
    state = get_state(request)
    user = state.get("users", login)
    if user:
        return user
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
async def list_user_repos(request: Request):
    state = get_state(request)
    base_url = get_base_url(request)
    repos = state.list_all("repos", lambda r: r.get("owner", {}).get("login") == DEFAULT_USER["login"])
    for r in repos:
        _enrich_repo_urls(r, base_url)
    return repos


@app.post("/user/repos", status_code=201)
async def create_user_repo(request: Request, repo: RepoCreate):
    state = get_state(request)
    repo_id = state.next_id("repos")
    key = f"{DEFAULT_USER['login']}/{repo.name}"
    base_url = get_base_url(request)

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
    _enrich_repo_urls(repo_obj, base_url)
    state.put("repos", key, repo_obj)
    return repo_obj


@app.get("/repos/{owner}/{repo}")
async def get_repo(request: Request, owner: str, repo: str):
    state = get_state(request)
    key = f"{owner}/{repo}"
    repo_obj = state.get("repos", key)
    if not repo_obj:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})
    _enrich_repo_urls(repo_obj, get_base_url(request))
    return repo_obj


@app.patch("/repos/{owner}/{repo}")
async def update_repo(request: Request, owner: str, repo: str, update: RepoUpdate):
    state = get_state(request)
    key = f"{owner}/{repo}"
    repo_obj = state.get("repos", key)
    if not repo_obj:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})

    if update.description is not None:
        repo_obj["description"] = update.description
    if update.private is not None:
        repo_obj["private"] = update.private
    if update.default_branch is not None:
        repo_obj["default_branch"] = update.default_branch

    _enrich_repo_urls(repo_obj, get_base_url(request))
    state.put("repos", key, repo_obj)
    return repo_obj


@app.delete("/repos/{owner}/{repo}", status_code=204)
async def delete_repo(request: Request, owner: str, repo: str):
    state = get_state(request)
    key = f"{owner}/{repo}"
    state.delete("repos", key)
    return None


def _enrich_repo_urls(repo_obj: dict, base_url: str) -> None:
    key = repo_obj.get("full_name", "")
    repo_obj["url"] = f"{base_url}/repos/{key}"
    repo_obj["issues_url"] = f"{base_url}/repos/{key}/issues{{/number}}"
    repo_obj["pulls_url"] = f"{base_url}/repos/{key}/pulls{{/number}}"


# =============================================================================
# Issue endpoints
# =============================================================================

@app.get("/repos/{owner}/{repo}/issues")
async def list_issues(
    request: Request,
    owner: str,
    repo: str,
    issue_state: str = Query(default="open", alias="state"),
):
    state = get_state(request)
    key = f"{owner}/{repo}"
    base_url = get_base_url(request)
    issues = state.list_all(
        "issues",
        lambda i: i.get("repo_key") == key and (issue_state == "all" or i.get("state") == issue_state),
    )
    for i in issues:
        _enrich_issue_urls(i, base_url, key)
    return issues


@app.post("/repos/{owner}/{repo}/issues", status_code=201)
async def create_issue(request: Request, owner: str, repo: str, issue: IssueCreate):
    state = get_state(request)
    key = f"{owner}/{repo}"
    if not state.get("repos", key):
        raise HTTPException(status_code=404, detail={"message": "Not Found"})

    issue_id = state.next_id("issues")

    # Count existing issues for this repo to get number
    repo_issues = state.list_all("issues", lambda i: i.get("repo_key") == key)
    number = len(repo_issues) + 1

    base_url = get_base_url(request)

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
    _enrich_issue_urls(issue_obj, base_url, key)
    state.put("issues", str(issue_id), issue_obj)

    # Dispatch webhooks
    await _dispatch_webhook(request, owner, repo, "issues", {
        "action": "opened",
        "issue": issue_obj,
        "repository": state.get("repos", key) or {},
    })

    return issue_obj


@app.get("/repos/{owner}/{repo}/issues/{issue_number}")
async def get_issue(request: Request, owner: str, repo: str, issue_number: int):
    state = get_state(request)
    key = f"{owner}/{repo}"
    base_url = get_base_url(request)

    for i in state.list_all("issues"):
        if i.get("repo_key") == key and i.get("number") == issue_number:
            _enrich_issue_urls(i, base_url, key)
            return i

    raise HTTPException(status_code=404, detail={"message": "Not Found"})


@app.patch("/repos/{owner}/{repo}/issues/{issue_number}")
async def update_issue(request: Request, owner: str, repo: str, issue_number: int, update: IssueUpdate):
    state = get_state(request)
    key = f"{owner}/{repo}"
    base_url = get_base_url(request)

    issue = None
    for i in state.list_all("issues"):
        if i.get("repo_key") == key and i.get("number") == issue_number:
            issue = i
            break

    if not issue:
        raise HTTPException(status_code=404, detail={"message": "Not Found"})

    old_state = issue.get("state")

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

    _enrich_issue_urls(issue, base_url, key)
    state.put("issues", str(issue["id"]), issue)

    if update.state and update.state != old_state:
        await _dispatch_webhook(request, owner, repo, "issues", {
            "action": "closed" if update.state == "closed" else "reopened",
            "issue": issue,
            "repository": state.get("repos", key) or {},
        })

    return issue


def _enrich_issue_urls(issue: dict, base_url: str, repo_key: str) -> None:
    issue["url"] = f"{base_url}/repos/{repo_key}/issues/{issue.get('number')}"
    issue["repository_url"] = f"{base_url}/repos/{repo_key}"


# =============================================================================
# Pull Request endpoints
# =============================================================================

@app.get("/repos/{owner}/{repo}/pulls")
async def list_pulls(request: Request, owner: str, repo: str, state_filter: str = "open"):
    state = get_state(request)
    key = f"{owner}/{repo}"
    pulls = state.list_all(
        "pulls",
        lambda p: p.get("repo_key") == key and (state_filter == "all" or p.get("state") == state_filter),
    )
    return pulls


@app.post("/repos/{owner}/{repo}/pulls", status_code=201)
async def create_pull(request: Request, owner: str, repo: str, pull: PullCreate):
    state = get_state(request)
    key = f"{owner}/{repo}"
    if not state.get("repos", key):
        raise HTTPException(status_code=404, detail={"message": "Not Found"})

    pull_id = state.next_id("pulls")

    repo_pulls = state.list_all("pulls", lambda p: p.get("repo_key") == key)
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
    state.put("pulls", str(pull_id), pull_obj)

    await _dispatch_webhook(request, owner, repo, "pull_request", {
        "action": "opened",
        "pull_request": pull_obj,
        "repository": state.get("repos", key) or {},
    })

    return pull_obj


@app.get("/repos/{owner}/{repo}/pulls/{pull_number}")
async def get_pull(request: Request, owner: str, repo: str, pull_number: int):
    state = get_state(request)
    key = f"{owner}/{repo}"

    for p in state.list_all("pulls"):
        if p.get("repo_key") == key and p.get("number") == pull_number:
            return p

    raise HTTPException(status_code=404, detail={"message": "Not Found"})


@app.patch("/repos/{owner}/{repo}/pulls/{pull_number}")
async def update_pull(request: Request, owner: str, repo: str, pull_number: int, update: PullUpdate):
    state = get_state(request)
    key = f"{owner}/{repo}"

    pull = None
    for p in state.list_all("pulls"):
        if p.get("repo_key") == key and p.get("number") == pull_number:
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

    state.put("pulls", str(pull["id"]), pull)
    return pull


# =============================================================================
# Webhook endpoints
# =============================================================================

@app.get("/repos/{owner}/{repo}/hooks")
async def list_hooks(request: Request, owner: str, repo: str):
    state = get_state(request)
    key = f"{owner}/{repo}"
    hooks = state.get("webhooks", key)
    return hooks or []


@app.post("/repos/{owner}/{repo}/hooks", status_code=201)
async def create_hook(request: Request, owner: str, repo: str, webhook: WebhookCreate):
    state = get_state(request)
    key = f"{owner}/{repo}"
    webhook_id = state.next_id("webhook_ids")

    hook = {
        "id": webhook_id,
        "url": webhook.config.url,
        "events": webhook.events,
        "active": True,
        "config": webhook.config.model_dump(),
    }

    # Store hooks as a list under the repo key
    existing = state.get("webhooks", key)
    hooks_list = existing if isinstance(existing, list) else []
    hooks_list.append(hook)
    state.put("webhooks", key, hooks_list)

    return hook


@app.get("/repos/{owner}/{repo}/hooks/{hook_id}")
async def get_hook(request: Request, owner: str, repo: str, hook_id: int):
    state = get_state(request)
    key = f"{owner}/{repo}"
    hooks = state.get("webhooks", key)
    if isinstance(hooks, list):
        for hook in hooks:
            if hook["id"] == hook_id:
                return hook

    raise HTTPException(status_code=404, detail={"message": "Not Found"})


@app.delete("/repos/{owner}/{repo}/hooks/{hook_id}", status_code=204)
async def delete_hook(request: Request, owner: str, repo: str, hook_id: int):
    state = get_state(request)
    key = f"{owner}/{repo}"
    hooks = state.get("webhooks", key)
    if isinstance(hooks, list):
        state.put("webhooks", key, [h for h in hooks if h["id"] != hook_id])
    return None


async def _dispatch_webhook(
    request: Request,
    owner: str,
    repo: str,
    event_type: str,
    payload: dict,
) -> None:
    """Dispatch webhooks via the WebhookSimulator."""
    state = get_state(request)
    ns = get_namespace(request)
    key = f"{owner}/{repo}"
    hooks = state.get("webhooks", key)

    if not isinstance(hooks, list):
        return

    for hook in hooks:
        if not hook.get("active"):
            continue
        if event_type not in hook.get("events", []) and "*" not in hook.get("events", []):
            continue

        secret = hook.get("config", {}).get("secret")
        await webhook_sim.deliver(
            target_url=hook["url"],
            event_type=event_type,
            payload=payload,
            secret=secret,
            namespace=ns,
            extra_headers={"X-GitHub-Event": event_type},
        )


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
