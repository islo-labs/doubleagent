import os
import pytest
import requests
from todoist_api_python.api import TodoistAPI


def get_fake_url() -> str:
    """Get the fake service URL from environment variable"""
    # Try both formats (with dot and with underscore)
    url = os.environ.get("DOUBLEAGENT_TODOIST_COM_URL") or os.environ.get("DOUBLEAGENT_TODOIST.COM_URL")
    if not url:
        raise ValueError(
            "DOUBLEAGENT_TODOIST_COM_URL environment variable is required"
        )
    return url.rstrip("/")


@pytest.fixture(scope="session")
def fake_url() -> str:
    """Provide the fake service URL"""
    return get_fake_url()


@pytest.fixture
def reset_state(fake_url: str):
    """Reset the fake service state before each test"""
    response = requests.post(f"{fake_url}/_doubleagent/reset")
    response.raise_for_status()
    assert response.json() == {"status": "ok"}


@pytest.fixture
def todoist_client(fake_url: str, reset_state, monkeypatch) -> TodoistAPI:
    """
    Provide a configured Todoist SDK client pointing at the fake service.
    The reset_state fixture ensures state is cleared before each test.
    """
    # Monkey-patch the API_URL in the endpoints module to point to our fake
    import todoist_api_python._core.endpoints as endpoints

    monkeypatch.setattr(endpoints, "API_URL", fake_url + "/api/v1")

    # Create the client with fake token (the fake ignores it)
    client = TodoistAPI("fake-token")

    return client
