"""PyAirbyte backend for snapshot pulls."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "PyAirbyte is not installed. Install it with:\n"
    "  uv pip install 'airbyte>=0.19.0'"
)


def _import_airbyte():
    try:
        import airbyte as ab
    except ImportError as exc:
        raise RuntimeError(_INSTALL_HINT) from exc
    return ab


def image_to_connector_name(image: str) -> str:
    # airbyte/source-jira:latest -> source-jira
    name = image.split("/")[-1]
    name = name.split(":")[0]
    return name


class PyAirbyteBackend:
    def __init__(self, connector_name: str, config: dict[str, Any]) -> None:
        self.connector_name = connector_name
        self.config = config
        self._source = None

    def _source_handle(self):
        if self._source is None:
            ab = _import_airbyte()
            self._source = ab.get_source(
                self.connector_name,
                config=self.config,
                install_if_missing=True,
            )
        return self._source

    def discover_streams(self) -> list[str]:
        source = self._source_handle()
        return list(source.get_available_streams())

    def pull_stream(
        self,
        stream: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        source = self._source_handle()
        source.select_streams([stream])
        records: list[dict[str, Any]] = []
        for record in source.get_records(stream, limit=limit):
            plain = dict(record)
            plain = {
                key: value
                for key, value in plain.items()
                if not key.startswith("_ab_") and not key.startswith("ab_")
            }
            records.append(plain)
        logger.info("  pulled %s: %d", stream, len(records))
        return records

    def pull_streams(
        self,
        streams: list[str],
        per_stream_limits: dict[str, int] | None = None,
        global_limit: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        limits = per_stream_limits or {}
        result: dict[str, list[dict[str, Any]]] = {}
        for stream in streams:
            limit = limits.get(stream, global_limit)
            try:
                result[stream] = self.pull_stream(stream, limit=limit)
            except Exception as exc:  # noqa: BLE001
                logger.warning("stream pull failed for %s: %s", stream, exc)
        return result

