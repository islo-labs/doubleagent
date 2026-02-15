"""Integration tests for PyAirbyteBackend using source-faker.

These tests require the ``airbyte`` package to be installed.
They are automatically skipped if the package is not available.
"""

import pytest

try:
    import airbyte  # noqa: F401
    HAS_AIRBYTE = True
except ImportError:
    HAS_AIRBYTE = False

from doubleagent_sdk.pyairbyte_backend import image_to_connector_name


# =============================================================================
# Unit tests (always run)
# =============================================================================


def test_image_to_connector_name():
    assert image_to_connector_name("airbyte/source-jira:latest") == "source-jira"
    assert image_to_connector_name("airbyte/source-github:0.5.0") == "source-github"
    assert image_to_connector_name("source-faker") == "source-faker"
    assert image_to_connector_name("airbyte/source-salesforce:latest") == "source-salesforce"


# =============================================================================
# Integration tests (require airbyte package)
# =============================================================================


@pytest.mark.skipif(not HAS_AIRBYTE, reason="airbyte package not installed")
class TestPyAirbyteBackend:
    def test_discover_streams(self):
        """source-faker should discover known streams."""
        from doubleagent_sdk.pyairbyte_backend import PyAirbyteBackend

        backend = PyAirbyteBackend("source-faker", config={"count": 10})
        streams = backend.discover_streams()
        assert isinstance(streams, list)
        assert len(streams) > 0
        assert "users" in streams

    def test_pull_with_limit(self):
        """Pull 5 records from source-faker users stream."""
        from doubleagent_sdk.pyairbyte_backend import PyAirbyteBackend

        backend = PyAirbyteBackend("source-faker", config={"count": 100})
        records = backend.pull_stream("users", limit=5)
        assert len(records) == 5
        assert isinstance(records[0], dict)
        # Verify Airbyte metadata columns are stripped
        for key in records[0]:
            assert not key.startswith("_ab_")
            assert not key.startswith("ab_")

    def test_pull_streams(self):
        """Pull multiple streams with per-stream limits."""
        from doubleagent_sdk.pyairbyte_backend import PyAirbyteBackend

        backend = PyAirbyteBackend("source-faker", config={"count": 100})
        result = backend.pull_streams(
            ["users", "products"],
            per_stream_limits={"users": 3, "products": 2},
        )
        assert "users" in result
        assert "products" in result
        assert len(result["users"]) == 3
        assert len(result["products"]) == 2
