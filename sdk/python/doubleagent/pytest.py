"""
pytest fixtures for DoubleAgent services.

Usage:
    from doubleagent.pytest import github_service
    
    @pytest.fixture
    def github():
        with github_service() as gh:
            yield gh
    
    def test_something(github):
        from github import Github
        client = Github(base_url=github.url, login_or_token="fake")
        # ... test code ...
"""

import asyncio
from contextlib import contextmanager
from typing import Generator, Optional

from .client import DoubleAgent, Service


@contextmanager
def github_service(port: Optional[int] = None) -> Generator[Service, None, None]:
    """Fixture for GitHub service."""
    with service("github", port=port) as svc:
        yield svc


@contextmanager
def jira_service(port: Optional[int] = None) -> Generator[Service, None, None]:
    """Fixture for Jira service."""
    with service("jira", port=port) as svc:
        yield svc


@contextmanager
def slack_service(port: Optional[int] = None) -> Generator[Service, None, None]:
    """Fixture for Slack service."""
    with service("slack", port=port) as svc:
        yield svc


@contextmanager
def service(name: str, port: Optional[int] = None) -> Generator[Service, None, None]:
    """
    Generic fixture for any DoubleAgent service.
    
    Usage:
        @pytest.fixture
        def my_service():
            with service("my-service") as svc:
                yield svc
    """
    da = DoubleAgent()
    
    # Start service synchronously
    loop = asyncio.new_event_loop()
    try:
        svc = loop.run_until_complete(da.start(name, port=port))
        yield svc
    finally:
        da.stop_all()
        loop.close()
