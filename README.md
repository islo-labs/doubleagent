# DoubleAgent

**Fake services. Real agents.**

Open-source, high-fidelity fakes of popular third-party services (GitHub, Jira, Okta, etc.) that let unattended AI coding agents run at scale without touching real APIs.

## Quick Start

```bash
# Install
curl -sSL https://doubleagent.dev/install.sh | sh

# Start services
doubleagent start github jira

# Your agents can now use:
# - GitHub API at http://localhost:8080
# - Jira API at http://localhost:8081
```

## Why DoubleAgent?

AI coding agents are going from supervised tools to unattended workers running at scale. At that scale, real services don't work:

- You can't create a thousand test accounts
- Nobody will let you hammer their API at that volume
- You can't reset state between runs
- Every API call costs money

DoubleAgent provides **high-fidelity fakes** — not mocks or stubs — that behave like real services.

## Features

- **Fakes, not mocks** — Real API behavior, not hard-coded responses
- **Contract-tested** — Every fake passes tests against the real API
- **Official SDK compatible** — Use PyGithub, slack_sdk, etc. directly
- **Built by agents, for agents** — Designed for AI agent workflows

## Usage

### CLI

```bash
# Start services
doubleagent start github              # Start GitHub fake on default port
doubleagent start github --port 9000  # Custom port
doubleagent start github jira slack   # Multiple services

# Manage services
doubleagent status                    # Show running services
doubleagent stop github               # Stop a service
doubleagent stop                      # Stop all services

# State management
doubleagent reset github              # Clear GitHub state
doubleagent seed github ./data.yaml   # Seed with test data

# Contract testing
doubleagent contract github --target fake   # Test fake
doubleagent contract github --target real   # Test real API
doubleagent contract github --target both   # Validate fidelity
```

### Python SDK

```python
from doubleagent import DoubleAgent

# Start services programmatically
async with DoubleAgent() as da:
    github = await da.start("github")
    
    # Use official PyGithub SDK!
    from github import Github
    client = Github(base_url=github.url, login_or_token="fake-token")
    
    repo = client.get_user().create_repo("test-repo")
    issue = repo.create_issue(title="Test issue")
    
    # Reset between tests
    await github.reset()
```

### pytest Integration

```python
import pytest
from doubleagent.pytest import github_service

@pytest.fixture
def github():
    with github_service() as gh:
        yield gh

def test_create_issue(github):
    from github import Github
    client = Github(base_url=github.url, login_or_token="fake")
    # ... test code using official SDK
```

## Available Services

| Service | Status | Official SDK |
|---------|--------|--------------|
| GitHub | ✅ Available | PyGithub, octokit |
| Jira | 🚧 Coming soon | atlassian-python-api |
| Slack | 🚧 Coming soon | slack_sdk |
| Okta | 🚧 Coming soon | okta |
| Auth0 | 🚧 Coming soon | auth0-python |

## Contributing

DoubleAgent is designed to be contributed to by both humans and AI agents.

### Adding a New Service

1. Create service directory: `services/<name>/`
2. Implement HTTP server with required `/_doubleagent` endpoints
3. Write contract tests using official SDK
4. Validate against real API

See [docs/contributing.md](docs/contributing.md) for details.

### Required Service Interface

Every service must implement these endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/_doubleagent/health` | GET | Health check |
| `/_doubleagent/reset` | POST | Clear all state |
| `/_doubleagent/seed` | POST | Seed state from JSON |

## License

MIT
