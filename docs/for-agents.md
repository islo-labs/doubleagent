# DoubleAgent: Guide for AI Agents

This guide helps AI coding agents contribute new services to DoubleAgent.

## Overview

DoubleAgent provides fake SaaS APIs for testing. Your task is to implement
a fake that matches the real API closely enough that official SDKs work.

## Adding a New Service

### 1. Gather Information

Before implementing, collect:

- **API documentation** - Official docs, OpenAPI spec if available
- **Official SDK** - The Python/JS SDK people use with this API
- **Core endpoints** - Focus on endpoints AI agents commonly use

### 2. Create Directory Structure

```
services/{service-name}/
├── service.yaml        # Service definition
├── server/
│   ├── main.py         # HTTP server (Flask recommended)
│   └── requirements.txt
├── contracts/
│   ├── conftest.py     # pytest fixtures with official SDK
│   ├── test_*.py       # Contract tests
│   └── requirements.txt
└── fixtures/
    └── sample.yaml     # Example seed data
```

### 3. Implement Required Endpoints

Every service MUST implement these `/_doubleagent` endpoints:

```python
@app.route("/_doubleagent/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})

@app.route("/_doubleagent/reset", methods=["POST"])
def reset():
    # Clear all in-memory state
    global state
    state = initial_state()
    return jsonify({"status": "ok"})

@app.route("/_doubleagent/seed", methods=["POST"])
def seed():
    data = request.json
    # Populate state from data
    return jsonify({"status": "ok", "seeded": counts})
```

### 4. Implement API Endpoints

Match the real API's:
- URL paths
- HTTP methods
- Request/response formats
- Error responses
- Status codes

### 5. Write Contract Tests

Contract tests MUST use the official SDK:

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

Run contract tests against both targets:

```bash
# Against your fake
DOUBLEAGENT_TARGET=fake pytest

# Against real API (needs credentials)
DOUBLEAGENT_TARGET=real pytest
```

Both MUST pass.

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
# GitHub-style errors
return jsonify({"message": "Not Found"}), 404

# Jira-style errors
return jsonify({"errorMessages": ["Issue not found"]}), 404
```

### Pagination

If the real API paginates, implement it:

```python
@app.route("/items")
def list_items():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 30))
    
    items = list(state["items"].values())
    start = (page - 1) * per_page
    end = start + per_page
    
    return jsonify(items[start:end])
```

### Webhooks

If the real API has webhooks:

```python
import threading
import requests

def dispatch_webhook(resource_key, event_type, payload):
    for hook in webhooks.get(resource_key, []):
        threading.Thread(
            target=requests.post,
            args=(hook["url"],),
            kwargs={"json": payload},
            daemon=True
        ).start()
```

## Common Patterns

### GitHub-style API

```python
# Nested resources: /repos/{owner}/{repo}/issues
@app.route("/repos/<owner>/<repo>/issues", methods=["POST"])
def create_issue(owner, repo):
    repo_key = f"{owner}/{repo}"
    ...
```

### Jira-style API

```python
# Query parameters: /search?jql=project=TEST
@app.route("/search")
def search():
    jql = request.args.get("jql", "")
    ...
```

### Auth endpoints

```python
# OAuth-style: /oauth/token
@app.route("/oauth/token", methods=["POST"])
def get_token():
    return jsonify({
        "access_token": "fake-token",
        "token_type": "Bearer",
        "expires_in": 3600,
    })
```

## Checklist

Before submitting:

- [ ] `/_doubleagent/health` returns `{"status": "healthy"}`
- [ ] `/_doubleagent/reset` clears all state
- [ ] `/_doubleagent/seed` can populate state
- [ ] Contract tests use official SDK
- [ ] Tests pass against fake (`--target fake`)
- [ ] Tests pass against real API (`--target real`)
- [ ] service.yaml is complete
- [ ] Error responses match real API format
