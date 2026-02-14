# Contributing to DoubleAgent

DoubleAgent is designed to be contributed to by both humans and AI agents.

## Prerequisites

### Install mise (Toolchain Manager)

DoubleAgent uses [mise](https://mise.jdx.dev) for toolchain management. Each service declares its required tools in a `.mise.toml` file, and the CLI automatically uses mise when running commands.

```bash
# Install mise
curl https://mise.run | sh

# Add to your shell (bash/zsh)
echo 'eval "$(mise activate bash)"' >> ~/.bashrc
# or for zsh:
echo 'eval "$(mise activate zsh)"' >> ~/.zshrc
```

When you run `doubleagent start` or `doubleagent contract`, the CLI will automatically:
1. Detect if the service has a `.mise.toml` file
2. Wrap commands with `mise exec --` to ensure correct tool versions

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

### Step 3: Create service.yaml and .mise.toml

**service.yaml** - Service configuration:

```yaml
name: my-service
version: "1.0"
description: Description of what this service fakes
docs: https://api.example.com/docs

server:
  command: ["uv", "run", "python", "main.py"]
  port: 8080

contracts:
  command: ["uv", "run", "pytest", "-v", "--tb=short"]

env:
  API_URL: "http://localhost:${port}"
  API_TOKEN: "doubleagent-fake-token"
```

**.mise.toml** - Toolchain requirements (in service root):

```toml
[tools]
python = "3.11"
uv = "latest"
```

This ensures anyone running the service has the correct Python and uv versions.

### Step 4: Write Contract Tests

Contract tests use the **official SDK** to verify the fake works correctly.
If the official SDK can parse responses without errors, the fake is compatible.

The CLI starts the service automatically before running tests, setting `DOUBLEAGENT_{SERVICE}_URL` as an environment variable.

```python
# services/my-service/contracts/conftest.py
import os
import httpx
import pytest
from official_sdk import Client

SERVICE_URL = os.environ["DOUBLEAGENT_MY_SERVICE_URL"]

@pytest.fixture
def client() -> Client:
    return Client(base_url=SERVICE_URL, token="fake-token")

@pytest.fixture(autouse=True)
def reset_fake():
    httpx.post(f"{SERVICE_URL}/_doubleagent/reset")
    yield

# services/my-service/contracts/test_items.py
class TestItems:
    def test_create_item(self, client):
        item = client.create_item(name="test")
        assert item.name == "test"
```

### Step 5: Validate

```bash
# Run contract tests (CLI starts/stops the service automatically)
doubleagent contract my-service
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
2. **Contract tested** - Tests pass with official SDK
3. **Official SDK compatible** - Works with the vendor's SDK
4. **Well documented** - Clear service.yaml and README
5. **Webhook support** - If the real API has webhooks, implement them

## Questions?

Open an issue or discussion on GitHub.
