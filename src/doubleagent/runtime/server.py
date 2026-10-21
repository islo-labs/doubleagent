"""Private router-to-runtime managed-request channel."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .core import Runtime
from .protocol import PROTOCOL_VERSION, read_frame, request_from_wire, response_to_wire, write_frame


class RuntimeServer:
    def __init__(self, runtime: Runtime, path: Path) -> None:
        self.runtime = runtime
        self.path = path
        self.server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if self.path.exists():
            raise FileExistsError(self.path)
        self.server = await asyncio.start_unix_server(self._handle, path=str(self.path))
        self.path.chmod(0o600)

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.path.unlink(missing_ok=True)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            message = await read_frame(reader)
            if message.get("version") != PROTOCOL_VERSION:
                answer = {"version": PROTOCOL_VERSION, "kind": "error", "error": "version_mismatch"}
            elif message.get("kind") == "health":
                answer = {
                    "version": PROTOCOL_VERSION,
                    "kind": "health",
                    "health": self.runtime.health(),
                }
            elif message.get("kind") == "managed_request":
                request = request_from_wire(message["request"])
                source_request_id = message["request_id"]
                if not isinstance(source_request_id, str) or not source_request_id:
                    raise ValueError("invalid request ID")
                response = await self.runtime.dispatch(request, source_request_id=source_request_id)
                answer = {
                    "version": PROTOCOL_VERSION,
                    "kind": "raw_response",
                    "request_id": message["request_id"],
                    "response": response_to_wire(response),
                }
            else:
                answer = {"version": PROTOCOL_VERSION, "kind": "error", "error": "unknown_kind"}
            await write_frame(writer, answer)
        except (ValueError, KeyError, TypeError, asyncio.IncompleteReadError):
            await write_frame(
                writer, {"version": PROTOCOL_VERSION, "kind": "error", "error": "invalid_request"}
            )
        finally:
            writer.close()
            await writer.wait_closed()
