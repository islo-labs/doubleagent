"""Deterministic local upstream for service import contract tests.

Usage: from tests.import_stub import ImportStub; with ImportStub() as upstream: ...
No external service or credentials are needed.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse
import json

DATA = {
    "users": [
        {"id": "U-old", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "U-start", "created_at": "2026-09-15T12:00:00Z"},
        {"id": "U-end", "created_at": "2026-10-15T12:00:00Z"},
    ],
    "channels": [
        {"id": "C1", "created_at": "2026-09-15T12:00:00Z", "owner": "U-old"},
        {"id": "C2", "created_at": "2026-10-01T00:00:00Z", "owner": "U-start"},
        {"id": "C-end", "created_at": "2026-10-15T12:00:00Z", "owner": "U-start"},
    ],
    "messages": [
        {"id": "M-start", "created_at": "2026-09-15T12:00:00Z", "channel": "C1", "user": "U-start"},
        {"id": "M-inside", "created_at": "2026-10-01T00:00:00Z", "channel": "C1", "user": "U-old"},
        {"id": "M-end", "created_at": "2026-10-15T12:00:00Z", "channel": "C1", "user": "U-start"},
    ],
}


class ImportStub:
    """Context manager with a two-item page size and injectable failures."""

    def __init__(self, mode="ok", token="test-source-token"):
        self.mode = mode
        self.token = token
        self.requests = []

    def __enter__(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                resource = parsed.path.strip("/")
                query = parse_qs(parsed.query)
                page = int(query.get("page", ["1"])[0])
                stub.requests.append((resource, page, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != f"Bearer {stub.token}":
                    return self.reply(401, {"error": "unauthorized"})
                if resource not in DATA or page < 1:
                    return self.reply(404, {"error": "not_found"})
                if page > 1 and stub.mode == "rate_limit":
                    return self.reply(429, {"error": "rate_limited"})
                if page > 1 and stub.mode == "fail":
                    return self.reply(500, {"error": "upstream_failure"})
                records = DATA[resource]
                if stub.mode == "missing_parent" and resource == "users":
                    records = [item for item in records if item["id"] != "U-old"]
                offset = (page - 1) * 2
                result = records[offset:offset + 2]
                next_page = page + 1 if offset + 2 < len(records) else None
                self.reply(200, {"items": result, "next_page": next_page})

            def reply(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
