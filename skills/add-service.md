# Add a New Service to DoubleAgent

You are tasked with adding a new fake service to DoubleAgent. Follow these steps:

## Context

DoubleAgent provides fake SaaS APIs for AI agent testing. Services are:
- Standalone FastAPI HTTP servers with inlined state management classes
- Contract-tested using official SDKs
- Designed to be drop-in replacements for real APIs
- Namespace-isolated with copy-on-write state

## Task: Add {SERVICE_NAME} Service

### Step 1: Research the API

1. Find official API documentation
2. Identify the official SDK (Python preferred for contracts)
3. List core endpoints that AI agents commonly use:
   - CRUD operations for main resources
   - Search/list endpoints
   - Any webhook capabilities

### Step 2: Create Service Structure

```bash
mkdir -p services/{service_name}/{server,contracts,fixtures}
```

Create these files:

**services/{service_name}/.mise.toml:**
```toml
[tools]
python = "3.11"
```

**services/{service_name}/service.yaml:**
```yaml
name: {service_name}
version: "1.0"
description: {description}
docs: {api_docs_url}

brief: |
  # A couple of paragraphs describing the real service and its main purpose.

supported_flows:
  - {flow-1}
  - {flow-2}

server:
  command: ["uv", "run", "python", "main.py"]

contracts:
  command: ["uv", "run", "pytest", "-v", "--tb=short"]

features:
  webhooks: true
```

### Step 3: Implement Server

**services/{service_name}/server/main.py:**

Start by copying the inlined state management classes from an existing service. Open `services/github/server/main.py` and copy everything from the top through the end of `WebhookSimulator`. This includes:

1. Constants: `NAMESPACE_HEADER`, `DEFAULT_NAMESPACE`
2. `StateOverlay` class (~120 lines)
3. `NamespaceRouter` class (~50 lines)
4. `WebhookDelivery` dataclass + `WebhookSimulator` class (~120 lines)

Then add your service-specific code:

```python
# --- After inlined SDK classes ---

from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse

# State
router = NamespaceRouter()
webhook_sim = WebhookSimulator(max_retries=3, retry_delays=[0.5, 2.0, 10.0])

def get_namespace(request: Request) -> str:
    return request.headers.get(NAMESPACE_HEADER, DEFAULT_NAMESPACE)

def get_state(request: Request) -> StateOverlay:
    return router.get_state(get_namespace(request))

app = FastAPI(title="{Service Name} API Fake", version="1.0.0")

# REQUIRED: All /_doubleagent control plane endpoints
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
    ns = get_namespace(request)
    seeded = {}
    # ... seed each resource type ...
    return {"status": "ok", "seeded": seeded, "namespace": ns}

@app.post("/_doubleagent/bootstrap")
async def bootstrap(data: BootstrapData):
    baseline = {}
    # ... build baseline dict from data ...
    router.load_baseline(baseline)
    counts = {k: len(v) for k, v in baseline.items()}
    return {"status": "ok", "loaded": counts}

@app.get("/_doubleagent/info")
async def info(request: Request):
    state = get_state(request)
    return {"name": "{service_name}", "version": "1.0",
            "namespace": get_namespace(request), "state": state.stats()}

@app.get("/_doubleagent/webhooks")
async def list_webhook_deliveries(request: Request, event_type: str = None, limit: int = 100):
    ns = get_namespace(request)
    return webhook_sim.get_deliveries(namespace=ns, event_type=event_type, limit=limit)

@app.get("/_doubleagent/namespaces")
async def list_namespaces():
    return router.list_namespaces()

# API endpoints — implement based on API docs
# All endpoints use get_state(request) for namespace-isolated state access

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

**Important:** Do NOT add `doubleagent-sdk` as a dependency. All state management classes are inlined.

### Step 4: Write Contract Tests

Contract tests use the official SDK to verify the fake works correctly.

**services/{service_name}/contracts/conftest.py:**
```python
import os
import httpx
import pytest
from {official_sdk} import Client

SERVICE_URL = os.environ["DOUBLEAGENT_{SERVICE_NAME}_URL"]

@pytest.fixture
def client() -> Client:
    return Client(base_url=SERVICE_URL, token="fake-token")

@pytest.fixture(autouse=True)
def reset_fake():
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset", params={"hard": "true"})
    yield
```

**services/{service_name}/contracts/test_{resource}.py:**
```python
class Test{Resource}CRUD:
    def test_create(self, client):
        result = client.create_{resource}(...)
        assert result.id is not None

    def test_list(self, client):
        # Create some items, then list
        ...

    def test_update(self, client):
        ...

    def test_delete(self, client):
        ...
```

**services/{service_name}/contracts/test_namespaces.py:**
```python
class TestNamespaceIsolation:
    def test_mutations_isolated(self, base_url):
        headers_a = {"X-DoubleAgent-Namespace": "ns-a", ...}
        headers_b = {"X-DoubleAgent-Namespace": "ns-b", ...}
        # Create in ns-a, verify not visible in ns-b
```

**services/{service_name}/contracts/test_snapshots.py:**
```python
class TestBootstrapAndCOW:
    def test_bootstrap_loads_baseline(self, client):
        # POST /_doubleagent/bootstrap with snapshot data
        # Verify data visible via SDK

    def test_reset_restores_baseline(self, client):
        # Bootstrap → mutate → reset → verify baseline restored

    def test_hard_reset_clears_everything(self, client):
        # Bootstrap → hard reset → verify everything gone
```

**services/{service_name}/contracts/pyproject.toml:**
```toml
[project]
name = "{service_name}-contracts"
version = "1.0.0"
requires-python = ">=3.11"
dependencies = [
    "{official_sdk_package}",
    "pytest>=8.0.0",
    "httpx>=0.27.0",
]
```

### Step 5: Create Fixtures

**services/{service_name}/fixtures/startup.yaml:**
```yaml
# Tier 2 fixture: "startup" — a small dataset for quick testing.
# Usage: doubleagent seed {service_name} --fixture startup
{resource_type}:
  - name: example-1
    ...
  - name: example-2
    ...
```

### Step 6: Generate Lock Files

```bash
cd services/{service_name}/server && uv lock
cd services/{service_name}/contracts && uv lock
```

### Step 7: Test

```bash
# Run contract tests (CLI starts/stops the service automatically)
doubleagent contract {service_name}
```

## Requirements

- All `/_doubleagent/*` control plane endpoints must be implemented
- State management classes inlined (not imported from shared library)
- Contract tests must use the official SDK
- Tests must include namespace isolation and snapshot/COW tests
- Error responses should match the real API format
- `pyproject.toml` must NOT depend on `doubleagent-sdk`
