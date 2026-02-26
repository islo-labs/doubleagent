"""
Contract tests for PostHog event capture.

Uses the official posthog Python SDK to verify the fake works correctly.
"""

import httpx
import os
from posthog import Posthog

SERVICE_URL = os.environ["DOUBLEAGENT_POSTHOG_URL"]


def _get_events(**params) -> list[dict]:
    """Helper to query captured events from the fake."""
    resp = httpx.get(f"{SERVICE_URL}/_doubleagent/events", params=params)
    return resp.json()["events"]


def _get_persons() -> dict:
    """Helper to query person profiles from the fake."""
    resp = httpx.get(f"{SERVICE_URL}/_doubleagent/persons")
    return resp.json()["persons"]


def _get_groups() -> dict:
    """Helper to query group profiles from the fake."""
    resp = httpx.get(f"{SERVICE_URL}/_doubleagent/groups")
    return resp.json()["groups"]


def test_basic_capture(posthog_client: Posthog):
    """Test basic event capture."""
    posthog_client.capture("page_view", distinct_id="user-1")

    events = _get_events(event="page_view")
    assert len(events) == 1
    assert events[0]["distinct_id"] == "user-1"
    assert events[0]["event"] == "page_view"


def test_capture_with_properties(posthog_client: Posthog):
    """Test event capture with custom properties."""
    posthog_client.capture(
        "button_click",
        distinct_id="user-1",
        properties={"button_id": "signup", "page": "/home"},
    )

    events = _get_events(event="button_click")
    assert len(events) == 1
    assert events[0]["properties"]["button_id"] == "signup"
    assert events[0]["properties"]["page"] == "/home"


def test_capture_with_group_context(posthog_client: Posthog):
    """Test event capture with group context (matches islo usage)."""
    posthog_client.capture(
        "feature_used",
        distinct_id="user-1",
        groups={"tenant": "tenant-123"},
    )

    events = _get_events(event="feature_used")
    assert len(events) == 1
    assert events[0]["properties"]["$groups"]["tenant"] == "tenant-123"


def test_capture_with_set(posthog_client: Posthog):
    """Test that $set in capture updates person profile."""
    posthog_client.capture(
        "login",
        distinct_id="user-1",
        properties={"$set": {"email": "user@example.com", "name": "Test User"}},
    )

    persons = _get_persons()
    assert "user-1" in persons
    assert persons["user-1"]["properties"]["email"] == "user@example.com"
    assert persons["user-1"]["properties"]["name"] == "Test User"


def test_set_creates_person_profile(posthog_client: Posthog):
    """Test that set() creates/updates a person profile."""
    posthog_client.set(
        distinct_id="user-2",
        properties={"email": "user2@example.com", "plan": "pro"},
    )

    events = _get_events(event="$set")
    assert len(events) == 1
    assert events[0]["distinct_id"] == "user-2"

    persons = _get_persons()
    assert "user-2" in persons
    assert persons["user-2"]["properties"]["email"] == "user2@example.com"
    assert persons["user-2"]["properties"]["plan"] == "pro"


def test_set_once(posthog_client: Posthog):
    """Test that set_once() only sets properties not already present."""
    posthog_client.set(
        distinct_id="user-3",
        properties={"email": "user3@example.com", "signup_date": "2024-01-01"},
    )
    posthog_client.set_once(
        distinct_id="user-3",
        properties={"email": "should_not_overwrite@example.com", "first_seen": "2024-01-01"},
    )

    persons = _get_persons()
    assert persons["user-3"]["properties"]["email"] == "user3@example.com"  # Not overwritten
    assert persons["user-3"]["properties"]["first_seen"] == "2024-01-01"  # Set


def test_group_identify(posthog_client: Posthog):
    """Test group_identify() creates a group profile."""
    posthog_client.group_identify(
        group_type="tenant",
        group_key="tenant-456",
        properties={"name": "Acme Corp", "plan": "enterprise"},
    )

    events = _get_events(event="$groupidentify")
    assert len(events) == 1

    groups = _get_groups()
    assert "tenant:tenant-456" in groups
    assert groups["tenant:tenant-456"]["properties"]["name"] == "Acme Corp"
    assert groups["tenant:tenant-456"]["properties"]["plan"] == "enterprise"


def test_multiple_events(posthog_client: Posthog):
    """Test capturing multiple events in sequence."""
    posthog_client.capture("event_a", distinct_id="user-1")
    posthog_client.capture("event_b", distinct_id="user-1")
    posthog_client.capture("event_a", distinct_id="user-2")

    all_events = _get_events()
    assert len(all_events) == 3

    user1_events = _get_events(distinct_id="user-1")
    assert len(user1_events) == 2

    event_a = _get_events(event="event_a")
    assert len(event_a) == 2


def test_filter_events_by_name_and_distinct_id(posthog_client: Posthog):
    """Test filtering events by both event name and distinct_id."""
    posthog_client.capture("page_view", distinct_id="user-1")
    posthog_client.capture("page_view", distinct_id="user-2")
    posthog_client.capture("button_click", distinct_id="user-1")

    events = _get_events(event="page_view", distinct_id="user-1")
    assert len(events) == 1
    assert events[0]["distinct_id"] == "user-1"
    assert events[0]["event"] == "page_view"
