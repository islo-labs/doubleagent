"""Tests for the Airbyte Protocol adapter.

These tests verify JSONL parsing, stream grouping, catalog handling,
config generation, and the adapter's SnapshotConnector interface —
all without requiring Docker or a real Airbyte connector.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock

from doubleagent_sdk.airbyte_adapter import (
    AirbyteAdapter,
    AirbyteCatalog,
    AirbyteConnectorConfig,
    AirbyteMessage,
    AirbyteStream,
    _set_nested,
    build_configured_catalog,
    extract_catalog,
    extract_state,
    group_records_by_stream,
    parse_airbyte_output,
)


# =============================================================================
# AirbyteMessage parsing
# =============================================================================

class TestAirbyteMessageParsing:
    def test_parse_record_message(self):
        line = json.dumps({
            "type": "RECORD",
            "record": {
                "stream": "users",
                "data": {"id": 1, "name": "Alice"},
                "emitted_at": 1700000000000,
            },
        })
        msg = AirbyteMessage.from_line(line)
        assert msg is not None
        assert msg.type == "RECORD"
        assert msg.record["stream"] == "users"
        assert msg.record["data"]["name"] == "Alice"

    def test_parse_state_message(self):
        line = json.dumps({
            "type": "STATE",
            "state": {"data": {"cursor": "2024-01-01"}},
        })
        msg = AirbyteMessage.from_line(line)
        assert msg is not None
        assert msg.type == "STATE"
        assert msg.state["data"]["cursor"] == "2024-01-01"

    def test_parse_log_message(self):
        line = json.dumps({
            "type": "LOG",
            "log": {"level": "INFO", "message": "Starting sync"},
        })
        msg = AirbyteMessage.from_line(line)
        assert msg is not None
        assert msg.type == "LOG"
        assert msg.log["level"] == "INFO"

    def test_parse_catalog_message(self):
        line = json.dumps({
            "type": "CATALOG",
            "catalog": {
                "streams": [
                    {
                        "stream": {
                            "name": "repos",
                            "json_schema": {"properties": {"id": {"type": "integer"}}},
                            "supported_sync_modes": ["full_refresh", "incremental"],
                        },
                        "sync_mode": "full_refresh",
                        "destination_sync_mode": "overwrite",
                    }
                ],
            },
        })
        msg = AirbyteMessage.from_line(line)
        assert msg.type == "CATALOG"
        assert len(msg.catalog["streams"]) == 1

    def test_parse_connection_status(self):
        line = json.dumps({
            "type": "CONNECTION_STATUS",
            "connectionStatus": {"status": "SUCCEEDED"},
        })
        msg = AirbyteMessage.from_line(line)
        assert msg.type == "CONNECTION_STATUS"
        assert msg.connectionStatus["status"] == "SUCCEEDED"

    def test_parse_empty_line_returns_none(self):
        assert AirbyteMessage.from_line("") is None
        assert AirbyteMessage.from_line("   ") is None

    def test_parse_non_json_returns_none(self):
        assert AirbyteMessage.from_line("not json at all") is None
        assert AirbyteMessage.from_line("INFO: starting up...") is None

    def test_parse_json_without_type_returns_none(self):
        assert AirbyteMessage.from_line('{"data": 42}') is None


# =============================================================================
# JSONL output parsing (multi-line)
# =============================================================================

class TestParseAirbyteOutput:
    def test_parse_mixed_output(self):
        lines = [
            json.dumps({"type": "LOG", "log": {"level": "INFO", "message": "start"}}),
            json.dumps({"type": "RECORD", "record": {"stream": "users", "data": {"id": 1}}}),
            "some random log line from the connector",
            json.dumps({"type": "RECORD", "record": {"stream": "users", "data": {"id": 2}}}),
            json.dumps({"type": "RECORD", "record": {"stream": "repos", "data": {"id": 10}}}),
            json.dumps({"type": "STATE", "state": {"data": {"cursor": "abc"}}}),
        ]
        stdout = "\n".join(lines)
        messages = parse_airbyte_output(stdout)
        assert len(messages) == 5  # 1 LOG + 2 user RECORDS + 1 repo RECORD + 1 STATE

    def test_parse_empty_output(self):
        assert parse_airbyte_output("") == []

    def test_parse_only_junk(self):
        assert parse_airbyte_output("foo\nbar\nbaz") == []


# =============================================================================
# Group records by stream
# =============================================================================

class TestGroupRecordsByStream:
    def test_basic_grouping(self):
        messages = [
            AirbyteMessage(type="RECORD", record={"stream": "users", "data": {"id": 1}}),
            AirbyteMessage(type="RECORD", record={"stream": "repos", "data": {"id": 10}}),
            AirbyteMessage(type="RECORD", record={"stream": "users", "data": {"id": 2}}),
            AirbyteMessage(type="LOG", log={"level": "INFO", "message": "done"}),
        ]
        resources = group_records_by_stream(messages)
        assert len(resources["users"]) == 2
        assert len(resources["repos"]) == 1
        assert "LOG" not in resources

    def test_stream_mapping(self):
        messages = [
            AirbyteMessage(type="RECORD", record={"stream": "repositories", "data": {"id": 1}}),
            AirbyteMessage(type="RECORD", record={"stream": "pull_requests", "data": {"id": 2}}),
        ]
        resources = group_records_by_stream(
            messages,
            stream_mapping={"repositories": "repos", "pull_requests": "pulls"},
        )
        assert "repos" in resources
        assert "pulls" in resources
        assert "repositories" not in resources

    def test_no_records(self):
        messages = [
            AirbyteMessage(type="LOG", log={"level": "INFO", "message": "nothing"}),
        ]
        assert group_records_by_stream(messages) == {}


# =============================================================================
# Catalog extraction
# =============================================================================

class TestCatalogExtraction:
    def test_extract_catalog(self):
        messages = [
            AirbyteMessage(type="LOG", log={"level": "INFO", "message": "x"}),
            AirbyteMessage(type="CATALOG", catalog={
                "streams": [
                    {"stream": {"name": "users", "json_schema": {}, "supported_sync_modes": ["full_refresh"]}},
                    {"stream": {"name": "repos", "json_schema": {}, "supported_sync_modes": ["full_refresh", "incremental"]}},
                ],
            }),
        ]
        catalog = extract_catalog(messages)
        assert catalog is not None
        assert len(catalog.streams) == 2
        assert catalog.stream_names() == ["users", "repos"]
        assert catalog.get_stream("repos") is not None
        assert catalog.get_stream("nonexistent") is None

    def test_no_catalog(self):
        messages = [AirbyteMessage(type="LOG", log={"level": "INFO", "message": "x"})]
        assert extract_catalog(messages) is None


class TestStateExtraction:
    def test_extract_last_state(self):
        messages = [
            AirbyteMessage(type="STATE", state={"data": {"cursor": "a"}}),
            AirbyteMessage(type="RECORD", record={"stream": "x", "data": {}}),
            AirbyteMessage(type="STATE", state={"data": {"cursor": "b"}}),
        ]
        state = extract_state(messages)
        assert state["data"]["cursor"] == "b"  # last state wins

    def test_no_state(self):
        messages = [AirbyteMessage(type="RECORD", record={"stream": "x", "data": {}})]
        assert extract_state(messages) is None


# =============================================================================
# AirbyteConnectorConfig
# =============================================================================

class TestAirbyteConnectorConfig:
    def test_from_dict(self):
        data = {
            "image": "airbyte/source-github:latest",
            "streams": ["repositories", "issues"],
            "config_env": {"GITHUB_TOKEN": "credentials.personal_access_token"},
            "stream_mapping": {"repositories": "repos"},
        }
        config = AirbyteConnectorConfig.from_dict(data)
        assert config.image == "airbyte/source-github:latest"
        assert config.streams == ["repositories", "issues"]
        assert config.config_env == {"GITHUB_TOKEN": "credentials.personal_access_token"}
        assert config.stream_mapping == {"repositories": "repos"}

    def test_build_connector_config_from_env(self):
        config = AirbyteConnectorConfig(
            image="test",
            config_env={
                "GITHUB_TOKEN": "credentials.personal_access_token",
                "GITHUB_REPOS": "repositories",
            },
        )
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_xxx", "GITHUB_REPOS": "myorg/myrepo"}):
            result = config.build_connector_config()
        assert result == {
            "credentials": {"personal_access_token": "ghp_xxx"},
            "repositories": "myorg/myrepo",
        }

    def test_build_connector_config_missing_env(self):
        config = AirbyteConnectorConfig(
            image="test",
            config_env={"MISSING_VAR": "some.path"},
        )
        with patch.dict(os.environ, {}, clear=True):
            result = config.build_connector_config()
        assert result == {}  # missing vars are skipped

    def test_map_stream_name(self):
        config = AirbyteConnectorConfig(
            image="test",
            stream_mapping={"repositories": "repos"},
        )
        assert config.map_stream_name("repositories") == "repos"
        assert config.map_stream_name("issues") == "issues"  # unmapped = pass-through


class TestSetNested:
    def test_single_level(self):
        d: dict = {}
        _set_nested(d, "key", "value")
        assert d == {"key": "value"}

    def test_multi_level(self):
        d: dict = {}
        _set_nested(d, "a.b.c", 42)
        assert d == {"a": {"b": {"c": 42}}}

    def test_merge_into_existing(self):
        d = {"a": {"existing": 1}}
        _set_nested(d, "a.new_key", 2)
        assert d == {"a": {"existing": 1, "new_key": 2}}


# =============================================================================
# Configured catalog building
# =============================================================================

class TestBuildConfiguredCatalog:
    def test_full_catalog(self):
        catalog = AirbyteCatalog(streams=[
            AirbyteStream(name="users", supported_sync_modes=["full_refresh"]),
            AirbyteStream(name="repos", supported_sync_modes=["full_refresh", "incremental"]),
        ])
        result = build_configured_catalog(catalog)
        assert len(result["streams"]) == 2

    def test_selected_streams(self):
        catalog = AirbyteCatalog(streams=[
            AirbyteStream(name="users"),
            AirbyteStream(name="repos"),
            AirbyteStream(name="issues"),
        ])
        result = build_configured_catalog(catalog, selected_streams=["repos", "issues"])
        names = [s["stream"]["name"] for s in result["streams"]]
        assert names == ["repos", "issues"]

    def test_empty_selection(self):
        catalog = AirbyteCatalog(streams=[AirbyteStream(name="users")])
        result = build_configured_catalog(catalog, selected_streams=["nonexistent"])
        assert len(result["streams"]) == 0


# =============================================================================
# AirbyteCatalog
# =============================================================================

class TestAirbyteCatalog:
    def test_from_dict_nested_stream(self):
        """Airbyte catalogs nest stream data inside a 'stream' key."""
        data = {
            "streams": [
                {
                    "stream": {
                        "name": "users",
                        "json_schema": {"properties": {"id": {"type": "integer"}}},
                        "supported_sync_modes": ["full_refresh"],
                    },
                    "sync_mode": "full_refresh",
                    "destination_sync_mode": "overwrite",
                },
            ],
        }
        catalog = AirbyteCatalog.from_dict(data)
        assert len(catalog.streams) == 1
        assert catalog.streams[0].name == "users"

    def test_from_dict_flat_stream(self):
        """Some catalogs may have flat stream dicts."""
        data = {
            "streams": [
                {"name": "repos", "json_schema": {}, "supported_sync_modes": ["full_refresh"]},
            ],
        }
        catalog = AirbyteCatalog.from_dict(data)
        assert catalog.streams[0].name == "repos"


# =============================================================================
# AirbyteAdapter (SnapshotConnector interface) — unit tests without Docker
# =============================================================================

class TestAirbyteAdapterInterface:
    def test_name(self):
        config = AirbyteConnectorConfig(image="airbyte/source-github:latest")
        adapter = AirbyteAdapter(config)
        assert adapter.name() == "airbyte:airbyte/source-github:latest"

    def test_required_credential_fields(self):
        config = AirbyteConnectorConfig(
            image="test",
            config_env={"GITHUB_TOKEN": "creds.token", "ORG": "organization"},
        )
        adapter = AirbyteAdapter(config)
        assert set(adapter.required_credential_fields()) == {"GITHUB_TOKEN", "ORG"}

    def test_list_schemas_with_cached_catalog(self):
        config = AirbyteConnectorConfig(
            image="test",
            streams=["users"],
            stream_mapping={"users": "people"},
        )
        adapter = AirbyteAdapter(config)
        # Inject a catalog to avoid Docker call
        adapter._catalog = AirbyteCatalog(streams=[
            AirbyteStream(
                name="users",
                json_schema={"properties": {"id": {}, "name": {}, "email": {}}},
                supported_sync_modes=["full_refresh", "incremental"],
            ),
            AirbyteStream(
                name="repos",
                json_schema={},
                supported_sync_modes=["full_refresh"],
            ),
        ])
        schemas = adapter.list_schemas()
        # Should only include "users" (filtered by config.streams),
        # mapped to "people"
        assert len(schemas) == 1
        assert schemas[0].name == "people"
        assert schemas[0].supports_incremental is True
        assert "id" in schemas[0].fields

    def test_state_management(self):
        config = AirbyteConnectorConfig(image="test")
        adapter = AirbyteAdapter(config)
        assert adapter.get_state() is None

        adapter.load_state({"cursor": "2024-01-01"})
        assert adapter.get_state() == {"cursor": "2024-01-01"}


# =============================================================================
# Integration-style test: simulate full JSONL → snapshot pipeline
# =============================================================================

class TestEndToEndPipeline:
    """Simulates what happens when an Airbyte connector emits records."""

    def test_full_pipeline(self):
        """Parse JSONL → group → map streams → verify structure."""
        # Simulate connector output
        lines = [
            json.dumps({"type": "LOG", "log": {"level": "INFO", "message": "Syncing..."}}),
            json.dumps({"type": "RECORD", "record": {"stream": "repositories", "data": {"id": 1, "name": "myrepo", "full_name": "org/myrepo"}, "emitted_at": 1700000000}}),
            json.dumps({"type": "RECORD", "record": {"stream": "repositories", "data": {"id": 2, "name": "other", "full_name": "org/other"}, "emitted_at": 1700000001}}),
            json.dumps({"type": "RECORD", "record": {"stream": "issues", "data": {"id": 100, "title": "Bug", "state": "open"}, "emitted_at": 1700000002}}),
            json.dumps({"type": "STATE", "state": {"data": {"repositories": {"cursor": "2024-01-01"}}}}),
            json.dumps({"type": "LOG", "log": {"level": "INFO", "message": "Done"}}),
        ]
        stdout = "\n".join(lines)

        # Parse
        messages = parse_airbyte_output(stdout)
        assert len(messages) == 6

        # Group with stream mapping
        resources = group_records_by_stream(
            messages,
            stream_mapping={"repositories": "repos"},
        )
        assert "repos" in resources
        assert "issues" in resources
        assert len(resources["repos"]) == 2
        assert len(resources["issues"]) == 1

        # Extract state
        state = extract_state(messages)
        assert state is not None
        assert state["data"]["repositories"]["cursor"] == "2024-01-01"

        # Verify data integrity
        assert resources["repos"][0]["name"] == "myrepo"
        assert resources["issues"][0]["title"] == "Bug"
