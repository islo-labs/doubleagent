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
│   ├── main.py         # HTTP server (FastAPI recommended)
│   └── pyproject.toml
├── contracts/
│   ├── conftest.py     # pytest fixtures with official SDK
│   ├── test_*.py       # Contract tests
│   └── pyproject.toml
└── fixtures/
    └── sample.yaml     # Example seed data
```

**.mise.toml** declares toolchain requirements:

```toml
[tools]
python = "3.11"
uv = "latest"
```

### 3. Implement Required Endpoints

Every service MUST implement these `/_doubleagent` endpoints:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}

@app.post("/_doubleagent/reset")
async def reset():
    # Clear all in-memory state
    global state
    state = initial_state()
    return {"status": "ok"}

@app.post("/_doubleagent/seed")
async def seed(data: dict):
    # Populate state from data
    return {"status": "ok", "seeded": counts}
```

### 4. Implement API Endpoints

Match the real API's:
- URL paths
- HTTP methods
- Request/response formats
- Error responses
- Status codes

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

### 6. Validate

Run contract tests against the fake:

```bash
cd services/{service-name}/contracts
uv run pytest -v
```

## Tips for Good Fakes

### State Management

```python
# Use simple in-memory dicts
state = {
    "users": {},
    "items": {},
}

# Auto-increment IDs
counters = {"user_id": 0, "item_id": 0}

def next_id(key):
    counters[key] += 1
    return counters[key]
```

### Error Responses

Match the real API's error format:

```python
from fastapi import HTTPException

# GitHub-style errors
raise HTTPException(status_code=404, detail={"message": "Not Found"})

# Jira-style errors
raise HTTPException(status_code=404, detail={"errorMessages": ["Issue not found"]})
```

### Pagination

If the real API paginates, implement it:

```python
from fastapi import Query

@app.get("/items")
async def list_items(page: int = Query(1), per_page: int = Query(30)):
    items = list(state["items"].values())
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end]
```

### Webhooks

If the real API has webhooks:

```python
import asyncio
import httpx

async def dispatch_webhook(resource_key, event_type, payload):
    for hook in webhooks.get(resource_key, []):
        asyncio.create_task(
            _send_webhook(hook["url"], event_type, payload)
        )

async def _send_webhook(url, event_type, payload):
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload, headers={"X-Event-Type": event_type})
```

## Common Patterns

### GitHub-style API

```python
# Nested resources: /repos/{owner}/{repo}/issues
@app.post("/repos/{owner}/{repo}/issues")
async def create_issue(owner: str, repo: str, issue: IssueCreate):
    repo_key = f"{owner}/{repo}"
    ...
```

### Jira-style API

```python
# Query parameters: /search?jql=project=TEST
@app.get("/search")
async def search(jql: str = ""):
    ...
```

### Auth endpoints

```python
# OAuth-style: /oauth/token
@app.post("/oauth/token")
async def get_token():
    return {
        "access_token": "fake-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
```

## Checklist

Before submitting:

- [ ] `.mise.toml` declares toolchain requirements
- [ ] `/_doubleagent/health` returns `{"status": "healthy"}`
- [ ] `/_doubleagent/reset` clears all state
- [ ] `/_doubleagent/seed` can populate state
- [ ] Contract tests use official SDK
- [ ] Tests pass against fake
- [ ] service.yaml is complete
- [ ] Error responses match real API format
