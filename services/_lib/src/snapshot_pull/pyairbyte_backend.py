"""PyAirbyte backend for DoubleAgent snapshot pulling.

Uses the ``airbyte`` (PyAirbyte) package to pull data from Airbyte source
connectors as pip-installed Python packages — no Docker required.

The ``airbyte`` package is an optional dependency.  If not installed,
this module raises a clear error with install instructions.

Usage::

    backend = PyAirbyteBackend("source-jira", config={"api_token": "..."})
    streams = backend.discover_streams()
    records = backend.pull_streams(["projects", "issues"], per_stream_limits={"projects": 3})
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_INSTALL_MSG = (
    "PyAirbyte is not installed. Install it with:\n"
    "  uv pip install 'airbyte>=0.19.0'\n"
    "Or set DOUBLEAGENT_SNAPSHOTS_DIR and populate snapshots manually."
)


def _get_airbyte():  # noqa: ANN202
    """Lazy-import the airbyte package."""
    try:
        import airbyte as ab
        return ab
    except ImportError:
        raise ImportError(_INSTALL_MSG) from None


def image_to_connector_name(image: str) -> str:
    """Convert Docker image name to PyAirbyte connector name.

    ``'airbyte/source-jira:latest'`` → ``'source-jira'``
    ``'airbyte/source-github:0.5.0'`` → ``'source-github'``
    ``'source-faker'`` → ``'source-faker'``
    """
    name = image.split("/")[-1]
    name = name.split(":")[0]
    return name


class PyAirbyteBackend:
    """Wraps PyAirbyte's ``ab.get_source()`` + ``get_records()`` API.

    Parameters
    ----------
    connector_name:
        Airbyte connector name, e.g. ``"source-jira"``.
    config:
        Connector config dict (built from config_env mappings + env vars).
    """

    def __init__(self, connector_name: str, config: dict[str, Any]) -> None:
        self._connector_name = connector_name
        self._config = config
        self._source = None

    def _get_source(self):  # noqa: ANN202
        if self._source is not None:
            return self._source

        ab = _get_airbyte()
        logger.info("Initializing PyAirbyte source: %s", self._connector_name)
        self._source = ab.get_source(
            self._connector_name,
            config=self._config,
            install_if_missing=True,
        )
        return self._source

    def discover_streams(self) -> list[str]:
        source = self._get_source()
        streams = source.get_available_streams()
        logger.info("Discovered %d streams: %s", len(streams), ", ".join(streams[:10]))
        return list(streams)

    def pull_stream(
        self,
        stream: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        source = self._get_source()
        source.select_streams([stream])

        logger.info("  Pulling %s (limit=%s)...", stream, limit or "all")

        records = []
        for record in source.get_records(stream, limit=limit):
            plain = {
                k: v for k, v in dict(record).items()
                if not k.startswith("_ab_") and not k.startswith("ab_")
            }
            records.append(plain)

        logger.info("  %s: %d records", stream, len(records))
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
            except Exception as exc:
                logger.warning("Failed to pull stream '%s': %s", stream, exc)

        return result
