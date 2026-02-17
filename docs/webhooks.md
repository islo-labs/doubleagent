# Testing Webhooks with DoubleAgent

DoubleAgent fakes dispatch webhooks just like the real services. When you create a PR, post a message, or perform other actions, the fake will automatically send webhook events to registered endpoints.

## Quick Start

### 1. Start your services

```bash
doubleagent start github slack
```

### 2. Register a webhook

Before creating resources, register a webhook pointing to your application:

```python
import httpx

GITHUB_URL = "http://localhost:8080"  # GitHub fake
MY_APP_URL = "http://localhost:3000"  # Your webhook handler

# Register webhook for PR events
httpx.post(f"{GITHUB_URL}/repos/acme/webapp/hooks", json={
    "config": {"url": f"{MY_APP_URL}/webhooks/github"},
    "events": ["pull_request", "issues"],
})
```

Or seed webhooks during setup:

```python
httpx.post(f"{GITHUB_URL}/_doubleagent/seed", json={
    "repos": [{"owner": "acme", "name": "webapp"}],
    "webhooks": [{
        "owner": "acme",
        "repo": "webapp",
        "url": f"{MY_APP_URL}/webhooks/github",
        "events": ["pull_request"],
    }],
})
```

### 3. Trigger events

Now when you create resources, webhooks fire automatically:

```python
# This triggers a webhook to your app
httpx.post(f"{GITHUB_URL}/repos/acme/webapp/pulls", json={
    "title": "Add feature",
    "head": "feature-branch",
    "base": "main",
})
```

### 4. Debug with the event log

Check `/_doubleagent/events` to see what webhooks were dispatched:

```python
resp = httpx.get(f"{GITHUB_URL}/_doubleagent/events")
events = resp.json()["events"]

for event in events:
    print(f"{event['event_type']}: {event['status']} -> {event['url']}")
    if event.get("error"):
        print(f"  Error: {event['error']}")
```

Example output:
```
pull_request: delivered -> http://localhost:3000/webhooks/github
pull_request: connection_failed -> http://localhost:9999/dead-endpoint
  Error: Connection failed: [Errno 111] Connection refused
```

## Event Log API

### GET `/_doubleagent/events?limit=50`

Returns recent webhook dispatch attempts:

```json
{
  "total": 42,
  "returned": 42,
  "events": [
    {
      "timestamp": 1700000000.123,
      "repo": "acme/webapp",
      "hook_id": 1,
      "event_type": "pull_request",
      "url": "http://localhost:3000/webhooks/github",
      "status": "delivered",
      "response_code": 200,
      "error": null
    }
  ]
}
```

Status values:
- `delivered` — Webhook sent successfully
- `timeout` — Request timed out (5s default)
- `connection_failed` — Could not connect to URL
- `error` — Other error (see `error` field)

### DELETE `/_doubleagent/events`

Clear the event log.

## Seeding Webhooks

Both GitHub and Slack fakes support seeding webhooks:

### GitHub

```json
{
  "repos": [{"owner": "acme", "name": "webapp"}],
  "webhooks": [{
    "owner": "acme",
    "repo": "webapp", 
    "url": "http://localhost:3000/webhooks/github",
    "events": ["pull_request", "issues", "push"]
  }]
}
```

### Slack

```json
{
  "channels": [{"id": "C001", "name": "general"}],
  "webhooks": [{
    "url": "http://localhost:3000/webhooks/slack",
    "events": ["message", "channel_created"]
  }]
}
```

## Full Example

Here's a complete test that:
1. Seeds a repo with a webhook
2. Creates a PR (triggers webhook)
3. Verifies the webhook was delivered

```python
import httpx
import subprocess
import time

# Start your app and the fake
# ...

GITHUB_URL = "http://localhost:8080"
APP_URL = "http://localhost:3000"

# Seed repo + webhook in one call
httpx.post(f"{GITHUB_URL}/_doubleagent/seed", json={
    "repos": [{"owner": "acme", "name": "webapp"}],
    "webhooks": [{
        "owner": "acme",
        "repo": "webapp",
        "url": f"{APP_URL}/webhooks/github",
        "events": ["pull_request"],
    }],
})

# Create PR — webhook fires automatically
httpx.post(f"{GITHUB_URL}/repos/acme/webapp/pulls", json={
    "title": "Add authentication",
    "head": "feature/auth",
    "base": "main",
})

# Give webhook time to deliver
time.sleep(0.2)

# Check the event log
resp = httpx.get(f"{GITHUB_URL}/_doubleagent/events")
events = resp.json()["events"]

assert len(events) == 1
assert events[0]["status"] == "delivered"
assert events[0]["event_type"] == "pull_request"
print("✓ Webhook delivered successfully!")
```

## Tips

- **Register webhooks before creating resources** — Events dispatched before webhook registration are not retroactively sent.

- **Use the event log for debugging** — If your app isn't receiving webhooks, check `/_doubleagent/events` to see if they're being dispatched and what errors occurred.

- **Seed webhooks for cleaner tests** — Instead of calling the hooks API, seed webhooks with your test data for a single-request setup.

- **Events are best-effort** — Like real webhooks, delivery failures don't cause API errors. Check the event log to verify delivery.
