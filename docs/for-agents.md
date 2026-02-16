# DoubleAgent: Guide for AI Agents

This guide helps AI coding agents contribute new services to DoubleAgent.

## Overview

DoubleAgent provides fake SaaS APIs for testing. Your task is to implement
a fake that matches the real API closely enough that official SDKs work.

## Toolchain Management

DoubleAgent uses [mise](https://mise.jdx.dev) for toolchain management. Each service has a `.mise.toml` file declaring required tools (Python, uv, Node, etc.).

**The CLI automatically handles this** - when you run `doubleagent start` or `doubleagent contract`, it detects `.mise.toml` and wraps commands with `mise exec --`.

If mise is not installed, you'll see:
```
mise not found. This service requires mise for toolchain management.

Install mise:
curl https://mise.run | sh
```

## Adding a New Service

> **Reference Implementation:** See `services/github/` for a complete working example.

### 1. Gather Information

Before implementing, collect:

- **API documentation** - Official docs, OpenAPI spec if available
- **Official SDK** - The Python/JS SDK people use with this API
- **Core endpoints** - Focus on endpoints AI agents commonly use

### 2. Create Directory Structure

```
services/{service-name}/
├── .mise.toml          # Toolchain requirements (python, uv, node, etc.)
├── service.yaml        # Service definition
├── server/
│   ├── main.py         # HTTP server (FastAPI) with inlined state management
│   └── pyproject.toml
├── contracts/
│   ├── conftest.py     # pytest fixtures with official SDK
│   ├── test_*.py       # Contract tests
│   └── pyproject.toml
└── fixtures/
    └── startup.yaml    # Default seed data
```

**.mise.toml** declares toolchain requirements:

```toml
[tools]
python = "3.11"
```

### 3. Implement Server with Inlined State Management

Each service inlines three state management classes directly at the top of `main.py`. **Do not import from a shared library.** Copy these classes from an existing service like `services/github/server/main.py`:

1. **`StateOverlay`** — Copy-on-write state with baseline/overlay/tombstones
2. **`NamespaceRouter`** — Per-namespace StateOverlay instances
3. **`WebhookSimulator`** — Webhook delivery with retry, HMAC, audit log

Also include the constants:
```python
NAMESPACE_HEADER = "X-DoubleAgent-Namespace"
DEFAULT_NAMESPACE = "default"
```

After the inlined classes, implement your service endpoints:

```python
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse

# --- Inlined SDK classes go here (copy from services/github/server/main.py) ---
# class StateOverlay: ...
# class NamespaceRouter: ...
# class WebhookSimulator: ...

# State
router = NamespaceRouter()
webhook_sim = WebhookSimulator(max_retries=3, retry_delays=[0.5, 2.0, 10.0])

def get_namespace(request: Request) -> str:
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)

def get_state(request: Request) -> StateOverlay:
    return router.get_state(get_namespace(request))

app = FastAPI()

# REQUIRED: /_doubleagent control plane endpoints
@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}

@app.post("/_doubleagent/reset")
async def reset(request: Request, hard: bool = Query(default=False)):
    ns = get_namespace(request)
    router.reset_namespace(ns, hard=hard)
    webhook_sim.clear()
    return {"status": "ok", "reset_mode": "hard" if hard else "baseline", "namespace": ns}

@app.post("/_doubleagent/seed")
async def seed(request: Request, data: SeedData):
    state = get_state(request)
    # ... seed logic ...
    return {"status": "ok", "seeded": counts}

@app.post("/_doubleagent/bootstrap")
async def bootstrap(data: BootstrapData):
    # Load immutable baseline
    router.load_baseline(baseline_dict)
    return {"status": "ok", "loaded": counts}

@app.get("/_doubleagent/info")
async def info(request: Request):
    state = get_state(request)
    return {"name": "service-name", "version": "1.0", "state": state.stats()}

@app.get("/_doubleagent/webhooks")
async def list_webhook_deliveries(request: Request):
    ns = get_namespace(request)
    return webhook_sim.get_deliveries(namespace=ns)

@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    return router.list_namespaces()

# API endpoints — implement based on API docs
# All endpoints use get_state(request) to access namespace-isolated state

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
```

**services/{service_name}/server/pyproject.toml:**
```toml
[project]
name = "{service_name}-fake"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
]
```

### 4. Implement API Endpoints

Match the real API's:
- URL paths
- HTTP methods
- Request/response formats
- Error responses
- Status codes

All endpoints access state via `get_state(request)` which automatically handles namespace isolation.

### 5. Write Contract Tests

Contract tests MUST use the official SDK. If the official SDK can parse responses
without errors, the fake is compatible.

```python
# Good - uses official SDK
from github import Github  # Official PyGithub

def test_create_issue(github_client):
    issue = github_client.create_issue(...)

# Bad - uses custom client
def test_create_issue():
    response = requests.post("/issues", ...)  # Don't do this
```

Include tests for:
- Basic CRUD operations
- Namespace isolation (two namespaces, verify mutations don't leak)
- Snapshot semantics (bootstrap, reset, hard reset)

### 6. Create Fixtures

**services/{service_name}/fixtures/startup.yaml:**
```yaml
# Tier 2 fixture: "startup" — a small dataset for quick testing
users:
  - name: alice
    email: alice@example.com
  - name: bob
    email: bob@example.com
```

### 7. Validate

Run contract tests against the fake:

```bash
doubleagent contract {service-name}
```

## State Management Pattern

All services use the same `get_state(request)` pattern:

```python
@app.get("/api/v2/items")
async def list_items(request: Request):
    state = get_state(request)  # Namespace-aware
    return state.list_all("items")

@app.post("/api/v2/items")
async def create_item(request: Request, body: CreateItemRequest):
    state = get_state(request)
    item_id = str(state.next_id("items"))
    item = {"id": item_id, "name": body.name}
    state.put("items", item_id, item)
    return item

@app.delete("/api/v2/items/{item_id}")
async def delete_item(request: Request, item_id: str):
    state = get_state(request)
    state.delete("items", item_id)
    return Response(status_code=204)
```

## Tips for Good Fakes

### Error Responses

Match the real API's error format:

```python
# GitHub-style errors
raise HTTPException(status_code=404, detail={"message": "Not Found"})

# Auth0-style errors
return JSONResponse(status_code=404,
    content={"statusCode": 404, "error": "Not Found", "message": "..."})

# Slack-style errors
return {"ok": False, "error": "channel_not_found"}
```

### Pagination

If the real API paginates, implement it:

```python
@app.get("/items")
async def list_items(request: Request, page: int = Query(1), per_page: int = Query(30)):
    state = get_state(request)
    items = state.list_all("items")
    start = (page - 1) * per_page
    return items[start : start + per_page]
```

### Webhooks

Dispatch events through the WebhookSimulator:

```python
async def _dispatch_event(request: Request, event_type: str, payload: dict):
    state = get_state(request)
    ns = get_namespace(request)
    for wh in state.list_all("webhooks"):
        if not wh.get("active", True):
            continue
        await webhook_sim.deliver(
            target_url=wh["url"],
            event_type=event_type,
            payload=payload,
            namespace=ns,
        )
```

## Checklist

Before submitting:

- [ ] `.mise.toml` declares `python = "3.11"`
- [ ] State management classes inlined at top of `main.py` (copied from existing service)
- [ ] All `/_doubleagent/*` control plane endpoints implemented
- [ ] `get_state(request)` used for all state access (namespace-aware)
- [ ] Contract tests use official SDK
- [ ] Namespace isolation tests included
- [ ] Snapshot/COW tests included (bootstrap, reset, hard reset)
- [ ] `fixtures/startup.yaml` with sample data
- [ ] `service.yaml` is complete with brief and supported_flows
- [ ] Error responses match real API format
- [ ] `pyproject.toml` does NOT list `doubleagent-sdk` as a dependency
