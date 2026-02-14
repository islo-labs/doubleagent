# Add a New Service to DoubleAgent

You are tasked with adding a new fake service to DoubleAgent. Follow these steps:

## Context

DoubleAgent provides fake SaaS APIs for AI agent testing. Services are:
- Standalone HTTP servers (any language, FastAPI/Express recommended)
- Contract-tested using official SDKs
- Designed to be drop-in replacements for real APIs

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

**services/{service_name}/service.yaml:**
```yaml
name: {service_name}
version: "1.0"
description: {description}
docs: {api_docs_url}

server:
  command: ["uv", "run", "python", "main.py"]
  # Port is managed by the CLI via --port flag or DOUBLEAGENT_PORT env var
  # Default: 8080, multiple services use sequential ports (8080, 8081, ...)

contracts:
  # Command to run contract tests (language-agnostic)
  command: ["uv", "run", "pytest", "-v", "--tb=short"]
  # For TypeScript: ["npm", "test"]
  # For Go: ["go", "test", "./..."]

env:
  # The CLI sets PORT and DOUBLEAGENT_{SERVICE}_URL automatically
  {SERVICE}_TOKEN: "doubleagent-fake-token"
```

### Step 3: Implement Server

**services/{service_name}/server/main.py:**

```python
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

# State
state = {...}
counters = {...}

# REQUIRED: /_doubleagent endpoints
@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}

@app.post("/_doubleagent/reset")
async def reset():
    # Reset all state
    return {"status": "ok"}

@app.post("/_doubleagent/seed")
async def seed(data: dict):
    # Seed from data
    return {"status": "ok", "seeded": {}}

# API endpoints
# ... implement based on API docs ...

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

**services/{service_name}/server/pyproject.toml:**
```toml
[project]
name = "{service_name}-fake"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
]
```

### Step 4: Write Contract Tests

Contract tests use the official SDK to verify the fake works correctly.
If the official SDK can parse responses without errors, the fake is compatible.

The CLI starts the service automatically before running tests, setting `DOUBLEAGENT_{SERVICE}_URL` as an environment variable.

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
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield
```

**services/{service_name}/contracts/test_{resource}.py:**
```python
class Test{Resource}:
    def test_create(self, client):
        # Use official SDK to test
        result = client.create_{resource}(...)
        assert result.id is not None
```

**services/{service_name}/contracts/pyproject.toml:**
```toml
[project]
name = "{service_name}-contracts"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "{official_sdk_package}",
    "pytest>=8.0.0",
    "httpx>=0.27.0",
]
```

### Step 5: Test

```bash
# Install dependencies
cd services/{service_name}/server && uv sync
cd services/{service_name}/contracts && uv sync

# Run contract tests (CLI starts/stops the service automatically)
doubleagent contract {service_name}
```

## Requirements

- All `/_doubleagent/*` endpoints must be implemented
- Contract tests must use the official SDK
- Tests must pass with official SDK
- Error responses should match the real API format
