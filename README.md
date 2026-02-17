<p align="center">
  <img src="public/assets/doubleagent_logo.png" alt="doubleagent Logo" width="400">
</p>

# doubleagent

**Test against real APIs without the real APIs.**

High-fidelity fakes of third-party services for AI agent development. Run dozens of agents in parallel, iterate fast, and never worry about rate limits, state cleanup, or API costs.

## Why?

AI agents iterate fast. Real APIs can't keep up:

- **Rate limits.** An agent debugging a task might hit the same endpoint 50 times in an hour. GitHub gives you 5,000 requests/hour. Run 10 agents? You're done in minutes.
- **State collisions.** Parallel agents create repos, post messages, fire webhooks  -  all stomping on each other's state with no isolation.
- **No reset.** Every run leaves garbage behind. You can't un-send a Slack message or un-create a GitHub repo without cleanup scripts.
- **Cost.** Stripe, Twilio, Okta  -  every API call costs money. Multiply by dozens of agents and hundreds of iterations.
- **Slow feedback.** Real calls take 200-500ms. Agents need millisecond responses to iterate quickly.

DoubleAgent gives you **fakes that behave like the real thing**  -  isolated per agent, instantly resettable, unlimited requests.

## Quick Start

```bash
# Install
curl -sSL https://raw.githubusercontent.com/islo-labs/doubleagent/main/install.sh | bash

# Start a service
doubleagent start github

# Your code hits localhost instead of the real API
# Official SDKs just work
```

## Usage


### CLI

```bash
doubleagent start github              # Start on default port
doubleagent start github --port 9000  # Custom port
doubleagent start github slack        # Multiple services

doubleagent status                    # Show running services
doubleagent stop                      # Stop all
doubleagent reset github              # Clear state
doubleagent seed github ./data.yaml   # Load fixtures
```

When a service starts, the CLI prints the environment variable to use:

```bash
$ doubleagent start github
✓ github running on http://localhost:8080 (PID: 12345)
  Export: DOUBLEAGENT_GITHUB_URL=http://localhost:8080
```

### Using with Official SDKs

Point the official SDK at the fake service URL:

```python
import os
from github import Github

# Use the env var set by doubleagent start
client = Github(
    base_url=os.environ["DOUBLEAGENT_GITHUB_URL"],
    login_or_token="fake-token"
)

repo = client.get_user().create_repo("test-repo")
issue = repo.create_issue(title="Test issue")
```

## Project Configuration

Define which services your project needs in a `doubleagent.yaml` file at the root of your repository:

```yaml
services:
  - github
  - slack
```

When this file exists, you can install all services at once:

```bash
# Reads doubleagent.yaml and installs all listed services
doubleagent add
```

Without the file, you specify services explicitly:

```bash
doubleagent add github slack
```

The CLI finds `doubleagent.yaml` (or `doubleagent.yml`) by searching from the current directory upward, so it works from any subdirectory in your project.

### Example: full project setup

```yaml
# doubleagent.yaml
services:
  - github
  - slack
  - stripe
```

```bash
# One command to install everything
doubleagent add

# Start the services you need
doubleagent start github slack
```

## Fakes, Not Mocks

**Mocks** return hard-coded responses. Call `create_customer()` and get `{"id": "cus_123"}` every time.

**Fakes** implement real behavior. Create a customer, it gets stored. Retrieve it later, it's there. Delete it, it's gone.

- **Contract-tested** — Every fake passes tests against the real API
- **Official SDK compatible** — Use PyGithub, stripe-python, etc. directly  
- **Built by agents, for agents** — Designed for AI agent workflows

## Available Services

| Service | Status | Official SDK |
|---------|--------|--------------|
| GitHub | ✅ Available | PyGithub, octokit |
| Slack | ✅ Available | slack_sdk |
| Descope | ✅ Available | descope |
| Jira | 🚧 Coming soon | atlassian-python-api |
| Okta | 🚧 Coming soon | okta |
| Auth0 | ✅ Available | auth0-python |
| Stripe | ✅ Available | stripe |

## Contributing

1. Create `services/<name>/`
2. Implement the fake with `/_doubleagent/health`, `reset`, and `seed` endpoints
3. Write contract tests with the official SDK
4. Validate against the real API

See [docs/contributing.md](docs/contributing.md) for details.

### Required Service Interface

Every service must implement these endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/_doubleagent/health` | GET | Health check |
| `/_doubleagent/reset` | POST | Clear all state |
| `/_doubleagent/seed` | POST | Seed state from JSON |
| `/_doubleagent/events` | GET | Event log for debugging (optional) |

### Webhook Support

Services that support webhooks will automatically dispatch events when state changes. Register webhooks via the service API or seed them with test data. See [docs/webhooks.md](docs/webhooks.md) for details.

## License

MIT
