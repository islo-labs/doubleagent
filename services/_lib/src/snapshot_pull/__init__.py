"""DoubleAgent snapshot pull tool.

Pulls data from Airbyte source connectors, applies smart relational
filtering, PII redaction, and saves as DoubleAgent snapshots.

Called by the Rust CLI: ``uv run python -m snapshot_pull ...``
"""
