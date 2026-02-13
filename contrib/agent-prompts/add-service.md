# Agent Prompt: Add a New Service to DoubleAgent

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
  port: 8080

contracts:
  sdk:
    package: {official_sdk_package}
  real_api:
    base_url: {real_api_url}
    auth:
      type: bearer
      env_var: {AUTH_ENV_VAR}

env:
  {SERVICE}_API_URL: "http://localhost:${port}"
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

**services/{service_name}/contracts/conftest.py:**
```python
import pytest
from {official_sdk} import Client
from doubleagent_contracts import Target

@pytest.fixture
def target(doubleagent_service) -> Target:
    return Target.from_env(
        service_name="{service_name}",
        fake_url=doubleagent_service.url,
        real_url="{real_api_url}",
        auth_env_var="{AUTH_ENV_VAR}",
    )

@pytest.fixture
def client(target: Target) -> Client:
    return Client(base_url=target.base_url, token=target.auth_token)
```

**services/{service_name}/contracts/test_{resource}.py:**
```python
from doubleagent_contracts import contract_test

@contract_test
class Test{Resource}:
    def test_create(self, client, target):
        # Use official SDK to test
        result = client.create_{resource}(...)
        assert result.id is not None
```

### Step 5: Test

```bash
# Install dependencies
cd services/{service_name}/server
uv sync

# Test against fake
cd services/{service_name}/contracts
DOUBLEAGENT_TARGET=fake pytest -v

# Test against real (requires API credentials)
{AUTH_ENV_VAR}=your-token DOUBLEAGENT_TARGET=real pytest -v
```

## Requirements

- All `/_doubleagent/*` endpoints must be implemented
- Contract tests must use the official SDK
- Tests must pass against both fake and real API
- Error responses should match the real API format
