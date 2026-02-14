"""
Contract tests for Slack channels (conversations) API.

Uses the official slack_sdk WebClient to verify the fake works correctly.
"""

import uuid
from slack_sdk import WebClient


def test_create_channel(slack_client: WebClient):
    """Test creating a public channel."""
    channel_name = f"test-channel-{uuid.uuid4().hex[:8]}"
    
    response = slack_client.conversations_create(name=channel_name)
    
    assert response["ok"] is True
    assert response["channel"]["name"] == channel_name
    assert response["channel"]["is_private"] is False


def test_create_private_channel(slack_client: WebClient):
    """Test creating a private channel."""
    channel_name = f"test-private-{uuid.uuid4().hex[:8]}"
    
    response = slack_client.conversations_create(name=channel_name, is_private=True)
    
    assert response["ok"] is True
    assert response["channel"]["name"] == channel_name
    assert response["channel"]["is_private"] is True


def test_list_channels(slack_client: WebClient):
    """Test listing channels."""
    # Create a channel first
    channel_name = f"test-list-{uuid.uuid4().hex[:8]}"
    slack_client.conversations_create(name=channel_name)
    
    # List channels
    response = slack_client.conversations_list()
    
    assert response["ok"] is True
    assert "channels" in response


def test_get_channel_info(slack_client: WebClient):
    """Test getting channel info."""
    # Create a channel first
    channel_name = f"test-info-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Get channel info
    response = slack_client.conversations_info(channel=channel_id)
    
    assert response["ok"] is True
    assert response["channel"]["id"] == channel_id
    assert response["channel"]["name"] == channel_name


def test_archive_channel(slack_client: WebClient):
    """Test archiving a channel."""
    # Create a channel first
    channel_name = f"test-archive-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Archive channel
    response = slack_client.conversations_archive(channel=channel_id)
    
    assert response["ok"] is True
    
    # Verify archived
    info_response = slack_client.conversations_info(channel=channel_id)
    assert info_response["channel"]["is_archived"] is True


def test_set_channel_topic(slack_client: WebClient):
    """Test setting channel topic."""
    # Create a channel first
    channel_name = f"test-topic-{uuid.uuid4().hex[:8]}"
    create_response = slack_client.conversations_create(name=channel_name)
    channel_id = create_response["channel"]["id"]
    
    # Set topic
    topic_text = "This is a test topic"
    response = slack_client.conversations_setTopic(channel=channel_id, topic=topic_text)
    
    assert response["ok"] is True
    
    # Verify topic
    info_response = slack_client.conversations_info(channel=channel_id)
    assert info_response["channel"]["topic"]["value"] == topic_text
