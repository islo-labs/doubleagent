"""Versioned local JSON framing; bodies are base64 to preserve arbitrary bytes."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
from typing import Any

from doubleagent.sdk.models import ProviderRequest, ProviderResponse

PROTOCOL_VERSION = 1
MAX_FRAME = 10 * 1024 * 1024


def request_to_wire(request: ProviderRequest) -> dict[str, Any]:
    return {
        "method": request.method,
        "scheme": request.scheme,
        "host": request.host,
        "path": request.path,
        "raw_target": request.raw_target,
        "query": request.query,
        "headers": request.headers,
        "body_b64": base64.b64encode(request.body).decode("ascii"),
    }


def request_from_wire(data: dict[str, Any]) -> ProviderRequest:
    return ProviderRequest(
        method=data["method"],
        scheme=data["scheme"],
        host=data["host"],
        path=data["path"],
        raw_target=data["raw_target"],
        query=data.get("query", []),
        headers=data.get("headers", []),
        body=base64.b64decode(data["body_b64"], validate=True),
    )


def response_to_wire(response: ProviderResponse) -> dict[str, Any]:
    return {
        "status": response.status,
        "headers": response.headers,
        "body_b64": base64.b64encode(response.body).decode("ascii"),
    }


def response_from_wire(data: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        status=data["status"],
        headers=data.get("headers", []),
        body=base64.b64decode(data["body_b64"], validate=True),
    )


def modified_read_to_wire(
    request_id: str, source_request_id: str, request: ProviderRequest
) -> dict[str, Any]:
    """Describe a read for the separate router gateway-forward channel."""
    if not request_id or not source_request_id:
        raise ValueError("request IDs are required")
    return {
        "version": PROTOCOL_VERSION,
        "kind": "modified_read",
        "request_id": request_id,
        "source_request_id": source_request_id,
        "request": request_to_wire(request),
    }


async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    size = struct.unpack(">I", await reader.readexactly(4))[0]
    if size > MAX_FRAME:
        raise ValueError("local protocol frame too large")
    message = json.loads(await reader.readexactly(size))
    if not isinstance(message, dict):
        raise ValueError("local protocol frame must be an object")
    return message


async def write_frame(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode()
    if len(payload) > MAX_FRAME:
        raise ValueError("local protocol frame too large")
    writer.write(struct.pack(">I", len(payload)) + payload)
    await writer.drain()
