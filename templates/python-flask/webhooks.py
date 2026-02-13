"""
Webhook support for DoubleAgent services.

Optional helper for services that need webhook functionality.
"""

import threading
import requests
from typing import Any

# In-memory webhook storage
# Key: resource identifier (e.g., "org/repo")
# Value: list of webhook configs
webhooks: dict[str, list[dict]] = {}

_webhook_counter = 0


def register_webhook(resource_key: str, url: str, events: list[str]) -> dict:
    """
    Register a webhook for a resource.
    
    Args:
        resource_key: Identifier for the resource (e.g., "org/repo")
        url: URL to POST webhook events to
        events: List of event types to subscribe to (or ["*"] for all)
    
    Returns:
        Webhook configuration dict with id
    """
    global _webhook_counter
    _webhook_counter += 1
    
    hook = {
        "id": _webhook_counter,
        "url": url,
        "events": events,
        "active": True,
    }
    
    if resource_key not in webhooks:
        webhooks[resource_key] = []
    webhooks[resource_key].append(hook)
    
    return hook


def delete_webhook(resource_key: str, webhook_id: int) -> bool:
    """Delete a webhook by ID."""
    if resource_key not in webhooks:
        return False
    
    hooks = webhooks[resource_key]
    for i, hook in enumerate(hooks):
        if hook["id"] == webhook_id:
            del hooks[i]
            return True
    return False


def list_webhooks(resource_key: str) -> list[dict]:
    """List all webhooks for a resource."""
    return webhooks.get(resource_key, [])


def dispatch_webhook(resource_key: str, event_type: str, payload: dict[str, Any]) -> None:
    """
    Dispatch webhooks asynchronously.
    
    Fires matching webhooks in background threads (doesn't block).
    
    Args:
        resource_key: Identifier for the resource
        event_type: Type of event (e.g., "issues", "pull_request")
        payload: Event payload to send
    """
    hooks = webhooks.get(resource_key, [])
    
    for hook in hooks:
        if not hook["active"]:
            continue
        if event_type not in hook["events"] and "*" not in hook["events"]:
            continue
        
        # Fire in background thread
        threading.Thread(
            target=_send_webhook,
            args=(hook["url"], event_type, payload),
            daemon=True,
        ).start()


def _send_webhook(url: str, event_type: str, payload: dict) -> None:
    """Send webhook (runs in background thread)."""
    try:
        requests.post(
            url,
            json=payload,
            headers={
                "X-Event-Type": event_type,
                "Content-Type": "application/json",
            },
            timeout=5,
        )
    except Exception:
        # Webhook delivery is best-effort
        pass


def reset_webhooks() -> None:
    """Clear all registered webhooks. Call from /_doubleagent/reset."""
    global webhooks, _webhook_counter
    webhooks = {}
    _webhook_counter = 0
