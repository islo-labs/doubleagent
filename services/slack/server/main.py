"""
Slack Web API Fake - DoubleAgent Service

A high-fidelity fake of the Slack Web API for AI agent testing.
Built with FastAPI for async support.

Slack API Notes:
- Most endpoints use POST with form data or JSON body
- Responses always include "ok": true/false
- Errors include "error" field with error code
"""

import os
import asyncio
from contextlib import asynccontextmanager
from typing import Any, Optional
import time

import httpx
from fastapi import FastAPI, HTTPException, Form, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# =============================================================================
# State
# =============================================================================

state: dict[str, Any] = {
    "users": {},
    "channels": {},
    "messages": {},  # channel_id -> [message]
    "webhooks": [],  # Event subscriptions
    "event_log": [],  # Dispatched events for debugging
}

counters: dict[str, int] = {
    "user_id": 0,
    "channel_id": 0,
    "message_ts": 1700000000,  # Slack uses Unix timestamp as message ID
}

DEFAULT_USER = {
    "id": "U00000001",
    "team_id": "T00000001",
    "name": "doubleagent",
    "real_name": "DoubleAgent Bot",
    "is_bot": False,
}

DEFAULT_BOT = {
    "id": "B00000001",
    "name": "doubleagent-bot",
    "app_id": "A00000001",
}


def next_id(key: str) -> str:
    counters[key] += 1
    if key == "user_id":
        return f"U{counters[key]:08d}"
    elif key == "channel_id":
        return f"C{counters[key]:08d}"
    elif key == "message_ts":
        return f"{counters[key]}.000000"
    return str(counters[key])


def reset_state() -> None:
    global state, counters
    state = {
        "users": {},
        "channels": {},
        "messages": {},
        "webhooks": [],
        "event_log": [],
    }
    counters = {
        "user_id": 0,
        "channel_id": 0,
        "message_ts": 1700000000,
    }


# =============================================================================
# Pydantic Models
# =============================================================================

class SeedData(BaseModel):
    users: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    webhooks: list[dict[str, Any]] = []


class SlackResponse(BaseModel):
    ok: bool
    error: Optional[str] = None


# Chat endpoint models (JSON body)
class PostMessageRequest(BaseModel):
    channel: str
    text: Optional[str] = None
    blocks: Optional[list[dict]] = None
    thread_ts: Optional[str] = None


class UpdateMessageRequest(BaseModel):
    channel: str
    ts: str
    text: Optional[str] = None


class DeleteMessageRequest(BaseModel):
    channel: str
    ts: str


class AddReactionRequest(BaseModel):
    channel: str
    timestamp: str
    name: str


class ConversationHistoryRequest(BaseModel):
    channel: str
    cursor: Optional[str] = None
    limit: int = 100


# =============================================================================
# App Setup
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Slack Web API Fake",
    description="DoubleAgent fake of the Slack Web API",
    version="1.0.0",
    lifespan=lifespan,
)


def slack_error(error_code: str) -> JSONResponse:
    """Return Slack-style error response."""
    return JSONResponse({"ok": False, "error": error_code})


def get_auth_token(authorization: Optional[str]) -> Optional[str]:
    """Extract token from Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


# =============================================================================
# /_doubleagent endpoints (REQUIRED)
# =============================================================================

@app.get("/_doubleagent/health")
async def health():
    """Health check - REQUIRED."""
    return {"status": "healthy"}


@app.post("/_doubleagent/reset")
async def reset():
    """Reset all state - REQUIRED."""
    reset_state()
    return {"status": "ok"}


@app.post("/_doubleagent/seed")
async def seed(data: SeedData):
    """Seed state from JSON - REQUIRED."""
    seeded: dict[str, int] = {}
    
    if data.users:
        for u in data.users:
            user_id = u.get("id") or next_id("user_id")
            state["users"][user_id] = {
                "id": user_id,
                "team_id": u.get("team_id", "T00000001"),
                "name": u.get("name", f"user{user_id}"),
                "real_name": u.get("real_name", ""),
                "is_bot": u.get("is_bot", False),
                "is_admin": u.get("is_admin", False),
            }
        seeded["users"] = len(data.users)
    
    if data.channels:
        for c in data.channels:
            channel_id = c.get("id") or next_id("channel_id")
            state["channels"][channel_id] = {
                "id": channel_id,
                "name": c.get("name", f"channel-{channel_id}"),
                "is_channel": True,
                "is_private": c.get("is_private", False),
                "is_archived": c.get("is_archived", False),
                "created": int(time.time()),
                "creator": c.get("creator", DEFAULT_USER["id"]),
                "topic": {"value": c.get("topic", ""), "creator": "", "last_set": 0},
                "purpose": {"value": c.get("purpose", ""), "creator": "", "last_set": 0},
                "num_members": c.get("num_members", 1),
            }
            state["messages"][channel_id] = []
        seeded["channels"] = len(data.channels)
    
    if data.messages:
        for m in data.messages:
            channel_id = m.get("channel")
            if channel_id:
                ts = next_id("message_ts")
                msg = {
                    "type": "message",
                    "ts": ts,
                    "user": m.get("user", DEFAULT_USER["id"]),
                    "text": m.get("text", ""),
                    "channel": channel_id,
                }
                if channel_id not in state["messages"]:
                    state["messages"][channel_id] = []
                state["messages"][channel_id].append(msg)
        seeded["messages"] = len(data.messages)
    
    if data.webhooks:
        for w in data.webhooks:
            webhook = {
                "url": w["url"],
                "events": w.get("events", ["*"]),
                "active": w.get("active", True),
            }
            state["webhooks"].append(webhook)
        seeded["webhooks"] = len(data.webhooks)
    
    return {"status": "ok", "seeded": seeded}


@app.get("/_doubleagent/info")
async def info():
    """Service info - OPTIONAL."""
    return {
        "name": "slack",
        "version": "1.0",
        "endpoints": {
            "users": len(state["users"]),
            "channels": len(state["channels"]),
            "messages": sum(len(msgs) for msgs in state["messages"].values()),
        }
    }


@app.get("/_doubleagent/events")
async def get_events(limit: int = Query(default=50, le=500)):
    """
    Get event dispatch log for debugging.
    
    Returns a list of all event dispatch attempts with their status.
    Useful for verifying webhooks were sent and diagnosing delivery issues.
    """
    events = state["event_log"][-limit:]
    return {
        "total": len(state["event_log"]),
        "returned": len(events),
        "events": events,
    }


@app.delete("/_doubleagent/events")
async def clear_events():
    """Clear the event log."""
    state["event_log"] = []
    return {"status": "ok"}


# =============================================================================
# Auth endpoints
# =============================================================================

@app.post("/auth.test")
async def auth_test(authorization: Optional[str] = Header(None)):
    """Test authentication."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    return {
        "ok": True,
        "url": "https://doubleagent.slack.com/",
        "team": "DoubleAgent",
        "user": DEFAULT_USER["name"],
        "team_id": "T00000001",
        "user_id": DEFAULT_USER["id"],
        "bot_id": DEFAULT_BOT["id"],
    }


# =============================================================================
# User endpoints
# =============================================================================

@app.post("/users.list")
async def users_list(
    authorization: Optional[str] = Header(None),
    cursor: Optional[str] = Form(None),
    limit: int = Form(100),
):
    """List users in workspace."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    users = list(state["users"].values())
    if not users:
        users = [DEFAULT_USER]
    
    return {
        "ok": True,
        "members": users,
        "response_metadata": {"next_cursor": ""},
    }


@app.post("/users.info")
async def users_info(
    authorization: Optional[str] = Header(None),
    user: str = Form(...),
):
    """Get user info."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if user in state["users"]:
        return {"ok": True, "user": state["users"][user]}
    
    if user == DEFAULT_USER["id"]:
        return {"ok": True, "user": DEFAULT_USER}
    
    return slack_error("user_not_found")


# =============================================================================
# Conversation/Channel endpoints
# =============================================================================

@app.post("/conversations.list")
async def conversations_list(
    authorization: Optional[str] = Header(None),
    types: str = Form("public_channel"),
    cursor: Optional[str] = Form(None),
    limit: int = Form(100),
):
    """List conversations/channels."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    channels = list(state["channels"].values())
    
    return {
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": ""},
    }


@app.post("/conversations.create")
async def conversations_create(
    authorization: Optional[str] = Header(None),
    name: str = Form(...),
    is_private: bool = Form(False),
):
    """Create a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    # Check for duplicate name
    for ch in state["channels"].values():
        if ch["name"] == name:
            return slack_error("name_taken")
    
    channel_id = next_id("channel_id")
    channel = {
        "id": channel_id,
        "name": name,
        "is_channel": not is_private,
        "is_private": is_private,
        "is_archived": False,
        "created": int(time.time()),
        "creator": DEFAULT_USER["id"],
        "topic": {"value": "", "creator": "", "last_set": 0},
        "purpose": {"value": "", "creator": "", "last_set": 0},
        "num_members": 1,
    }
    state["channels"][channel_id] = channel
    state["messages"][channel_id] = []
    
    # Dispatch event
    await dispatch_event("channel_created", {"channel": channel})
    
    return {"ok": True, "channel": channel}


@app.post("/conversations.info")
async def conversations_info(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
):
    """Get channel info."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    return {"ok": True, "channel": state["channels"][channel]}


@app.post("/conversations.archive")
async def conversations_archive(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
):
    """Archive a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    state["channels"][channel]["is_archived"] = True
    return {"ok": True}


@app.post("/conversations.unarchive")
async def conversations_unarchive(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
):
    """Unarchive a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    state["channels"][channel]["is_archived"] = False
    return {"ok": True}


@app.post("/conversations.setTopic")
async def conversations_set_topic(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    topic: str = Form(...),
):
    """Set channel topic."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    state["channels"][channel]["topic"] = {
        "value": topic,
        "creator": DEFAULT_USER["id"],
        "last_set": int(time.time()),
    }
    return {"ok": True, "topic": topic}


@app.post("/conversations.setPurpose")
async def conversations_set_purpose(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    purpose: str = Form(...),
):
    """Set channel purpose."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    state["channels"][channel]["purpose"] = {
        "value": purpose,
        "creator": DEFAULT_USER["id"],
        "last_set": int(time.time()),
    }
    return {"ok": True, "purpose": purpose}


async def _conversations_history_impl(
    authorization: Optional[str],
    channel: str,
    cursor: Optional[str],
    limit: int,
):
    """Implementation for conversation history (shared by GET and POST)."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    messages = state["messages"].get(channel, [])
    
    return {
        "ok": True,
        "messages": messages[-limit:],
        "has_more": len(messages) > limit,
        "response_metadata": {"next_cursor": ""},
    }


@app.get("/conversations.history")
async def conversations_history_get(
    authorization: Optional[str] = Header(None),
    channel: str = Query(...),
    cursor: Optional[str] = Query(None),
    limit: int = Query(100),
):
    """Get conversation history (GET method - per API docs)."""
    return await _conversations_history_impl(authorization, channel, cursor, limit)


@app.post("/conversations.history")
async def conversations_history_post(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    cursor: Optional[str] = Form(None),
    limit: int = Form(100),
):
    """Get conversation history (POST method - for SDK compatibility)."""
    return await _conversations_history_impl(authorization, channel, cursor, limit)


# =============================================================================
# Message endpoints
# =============================================================================

@app.post("/chat.postMessage")
async def chat_post_message(
    request: PostMessageRequest,
    authorization: Optional[str] = Header(None),
):
    """Post a message to a channel."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if request.channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    if not request.text and not request.blocks:
        return slack_error("no_text")
    
    ts = next_id("message_ts")
    message = {
        "type": "message",
        "ts": ts,
        "user": DEFAULT_USER["id"],
        "text": request.text or "",
        "channel": request.channel,
    }
    
    if request.thread_ts:
        message["thread_ts"] = request.thread_ts
    
    if request.blocks:
        message["blocks"] = request.blocks
    
    state["messages"][request.channel].append(message)
    
    # Dispatch event
    await dispatch_event("message", {
        "channel": request.channel,
        "user": DEFAULT_USER["id"],
        "text": request.text or "",
        "ts": ts,
    })
    
    return {
        "ok": True,
        "channel": request.channel,
        "ts": ts,
        "message": message,
    }


@app.post("/chat.update")
async def chat_update(
    request: UpdateMessageRequest,
    authorization: Optional[str] = Header(None),
):
    """Update a message."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if request.channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    messages = state["messages"].get(request.channel, [])
    for msg in messages:
        if msg["ts"] == request.ts:
            if request.text:
                msg["text"] = request.text
            msg["edited"] = {"user": DEFAULT_USER["id"], "ts": next_id("message_ts")}
            return {"ok": True, "channel": request.channel, "ts": request.ts, "text": request.text}
    
    return slack_error("message_not_found")


@app.post("/chat.delete")
async def chat_delete(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    ts: str = Form(...),
):
    """Delete a message."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    messages = state["messages"].get(channel, [])
    for i, msg in enumerate(messages):
        if msg["ts"] == ts:
            del messages[i]
            return {"ok": True, "channel": channel, "ts": ts}
    
    return slack_error("message_not_found")


@app.post("/reactions.add")
async def reactions_add(
    authorization: Optional[str] = Header(None),
    channel: str = Form(...),
    timestamp: str = Form(...),
    name: str = Form(...),
):
    """Add a reaction to a message."""
    token = get_auth_token(authorization)
    if not token:
        return slack_error("not_authed")
    
    if channel not in state["channels"]:
        return slack_error("channel_not_found")
    
    messages = state["messages"].get(channel, [])
    for msg in messages:
        if msg["ts"] == timestamp:
            if "reactions" not in msg:
                msg["reactions"] = []
            msg["reactions"].append({
                "name": name,
                "users": [DEFAULT_USER["id"]],
                "count": 1,
            })
            return {"ok": True}
    
    return slack_error("message_not_found")


# =============================================================================
# Events/Webhooks
# =============================================================================

async def dispatch_event(event_type: str, payload: dict) -> None:
    """Dispatch events to registered webhooks."""
    for i, webhook in enumerate(state["webhooks"]):
        if not webhook.get("active", True):
            continue
        
        event_data = {
            "type": event_type,
            "event": payload,
            "team_id": "T00000001",
            "event_time": int(time.time()),
        }
        
        asyncio.create_task(_send_event(webhook["url"], event_type, event_data, i))


async def _send_event(url: str, event_type: str, payload: dict, webhook_index: int) -> None:
    """Send event to webhook (runs as background task) and log the result."""
    event_record = {
        "timestamp": time.time(),
        "webhook_index": webhook_index,
        "event_type": event_type,
        "url": url,
        "status": "pending",
        "response_code": None,
        "error": None,
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5.0,
            )
            event_record["status"] = "delivered"
            event_record["response_code"] = resp.status_code
    except httpx.TimeoutException:
        event_record["status"] = "timeout"
        event_record["error"] = "Request timed out after 5s"
    except httpx.ConnectError as e:
        event_record["status"] = "connection_failed"
        event_record["error"] = f"Connection failed: {str(e)}"
    except Exception as e:
        event_record["status"] = "error"
        event_record["error"] = str(e)
    
    # Append to event log
    state["event_log"].append(event_record)
    
    # Keep log bounded (max 1000 events)
    if len(state["event_log"]) > 1000:
        state["event_log"] = state["event_log"][-1000:]


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8083))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
