# Contributing to DoubleAgent

DoubleAgent is designed to be contributed to by both humans and AI agents.

## Adding a New Service

### Step 1: Create Service Directory

```bash
# Scaffold from template
doubleagent new my-service --template python-fastapi

# Or manually create structure:
mkdir -p services/my-service/{server,contracts,fixtures}
```

### Step 2: Implement the Service

Services are standalone HTTP servers. Use any language/framework you prefer.

**Required endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/_doubleagent/health` | GET | Health check - return `{"status": "healthy"}` |
| `/_doubleagent/reset` | POST | Clear all state |
| `/_doubleagent/seed` | POST | Seed state from JSON body |

**Example (Python/FastAPI):**

```python
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

@app.get("/_doubleagent/health")
async def health():
    return {"status": "healthy"}

@app.post("/_doubleagent/reset")
async def reset():
    # Clear your state here
    return {"status": "ok"}

@app.post("/_doubleagent/seed")
async def seed(data: dict):
    # Seed your state here
    return {"status": "ok", "seeded": {...}}

# Add your API endpoints...

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

### Step 3: Create service.yaml

```yaml
name: my-service
version: "1.0"
description: Description of what this service fakes
docs: https://api.example.com/docs

server:
  command: ["uv", "run", "python", "main.py"]
  port: 8080

contracts:
  sdk:
    package: official-sdk-package
  real_api:
    base_url: https://api.example.com
    auth:
      type: bearer
      env_var: API_TOKEN

env:
  API_URL: "http://localhost:${port}"
  API_TOKEN: "doubleagent-fake-token"
```

### Step 4: Write Contract Tests

Contract tests use the **official SDK** to verify the fake matches the real API.

```python
# services/my-service/contracts/conftest.py
import pytest
from official_sdk import Client
from doubleagent_contracts import Target

@pytest.fixture
def client(target: Target) -> Client:
    return Client(base_url=target.base_url, token=target.auth_token)

# services/my-service/contracts/test_items.py
from doubleagent_contracts import contract_test

@contract_test
class TestItems:
    def test_create_item(self, client, target):
        item = client.create_item(name="test")
        assert item.name == "test"
```

### Step 5: Validate

```bash
# Test against fake
doubleagent contract my-service --target fake

# Test against real API (requires API token)
doubleagent contract my-service --target real

# Both must pass!
doubleagent contract my-service --target both
```

## Code Quality

- Follow the existing code style
- Add tests for new functionality
- Update documentation as needed
- Keep dependencies minimal

## Pull Request Process

1. Fork the repository
2. Create a feature branch
3. Implement your changes
4. Ensure all tests pass
5. Submit a pull request

## Service Quality Standards

Good DoubleAgent services:

1. **High fidelity** - Match real API behavior, not just structure
2. **Contract tested** - Tests pass against both real and fake
3. **Official SDK compatible** - Works with the vendor's SDK
4. **Well documented** - Clear service.yaml and README
5. **Webhook support** - If the real API has webhooks, implement them

## Questions?

Open an issue or discussion on GitHub.
