"""
Contract tests for Slack messages API.

Uses the official slack_sdk WebClient to verify the fake works correctly.
"""

import uuid
from slack_sdk import WebClient


def test_post_message(slack_client: WebClient):
    """Test posting a message to a channel."""
    # Create a channel first
    channel_name = f"test-msg-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Post message
    message_text = "Hello from DoubleAgent test!"
    response = slack_client.chat_postMessage(channel=channel_id, text=message_text)
    
    assert response["ok"] is True
    assert response["channel"] == channel_id
    assert "ts" in response
    assert response["message"]["text"] == message_text


def test_update_message(slack_client: WebClient):
    """Test updating a message."""
    # Create a channel first
    channel_name = f"test-update-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Post message
    post_response = slack_client.chat_postMessage(channel=channel_id, text="Original message")
    message_ts = post_response["ts"]
    
    # Update message
    new_text = "Updated message"
    response = slack_client.chat_update(channel=channel_id, ts=message_ts, text=new_text)
    
    assert response["ok"] is True
    assert response["ts"] == message_ts


def test_delete_message(slack_client: WebClient):
    """Test deleting a message."""
    # Create a channel first
    channel_name = f"test-delete-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Post message
    post_response = slack_client.chat_postMessage(channel=channel_id, text="Message to delete")
    message_ts = post_response["ts"]
    
    # Delete message
    response = slack_client.chat_delete(channel=channel_id, ts=message_ts)
    
    assert response["ok"] is True


def test_conversation_history(slack_client: WebClient):
    """Test getting conversation history."""
    # Create a channel first
    channel_name = f"test-history-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Post some messages
    slack_client.chat_postMessage(channel=channel_id, text="Message 1")
    slack_client.chat_postMessage(channel=channel_id, text="Message 2")
    slack_client.chat_postMessage(channel=channel_id, text="Message 3")
    
    # Get history
    response = slack_client.conversations_history(channel=channel_id)
    
    assert response["ok"] is True
    assert "messages" in response
    assert len(response["messages"]) >= 3


def test_add_reaction(slack_client: WebClient):
    """Test adding a reaction to a message."""
    # Create a channel first
    channel_name = f"test-react-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Post message
    post_response = slack_client.chat_postMessage(channel=channel_id, text="React to this!")
    message_ts = post_response["ts"]
    
    # Add reaction
    response = slack_client.reactions_add(channel=channel_id, timestamp=message_ts, name="thumbsup")
    
    assert response["ok"] is True
