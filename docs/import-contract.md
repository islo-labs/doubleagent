# Live import protocol and contract

A service opts in with `import.supported: true` and a nonempty `import.resources` list in its `service.yaml`. Existing services are fixture-only (`supported: false`). The CLI reads the running service's metadata before reading the source token and sends `POST /_doubleagent/import` to that service. It never calls a vendor API.

```http
POST /_doubleagent/import
Authorization: Bearer <source token>
Content-Type: application/json

{"start_at":"2026-07-17T12:00:00Z","end_at":"2026-10-15T12:00:00Z"}
```

Both timestamps are normalized UTC RFC3339 values. The window is half-open: `start_at <= timestamp < end_at`. A successful response is HTTP 2xx with:

```json
{
  "start_at": "2026-07-17T12:00:00Z",
  "end_at": "2026-10-15T12:00:00Z",
  "imported": {"users": 2, "channels": 1, "messages": 10},
  "warnings": []
}
```

`imported` contains nonnegative counts by resource, including zero where useful. `warnings` is an array of human-readable strings; it must not contain tokens or other secrets. The service should use a non-2xx status for invalid credentials, rate limits, invalid windows, and upstream failures. Error bodies must not include the token. The CLI intentionally does not show error bodies.

## Atomic state and reset

The service owns upstream pagination, resource mapping, permission handling, and relationship closure. Build a complete candidate state away from the active state. Read every required page; fetch parent resources needed by selected children, even if those parents fall outside the date window; validate all references and required fields. Only then swap the candidate into active state and save a deep copy as the process-local reset baseline. Do not store the source token in either state. A failed import leaves both active state and reset baseline untouched. `POST /_doubleagent/reset` restores the latest successful import baseline; if none exists, it restores the service's normal clean initial state. A later successful import replaces the earlier baseline.

## Deterministic contract cases

Run these cases against a local upstream stub with fixed data and an import-capable service. The fixture should expose two pages per resource, records exactly at both boundaries, a child whose parent is older than `start_at`, and a failure switch on page two. The stub must record requested pages and authorization headers. No real vendor credentials are used in CI.

1. Import with a valid token: all pages are requested once, records at `start_at` are included, records at `end_at` are excluded, and `imported` counts match the resulting fake API data.
2. Include the older parent needed by a selected child, or return a non-2xx response before changing state if the parent cannot be fetched. Every imported relationship must resolve.
3. With a wrong token, return an authorization error. Existing fake data and the reset baseline remain unchanged.
4. With a stub 429 on a later page, return a non-2xx response and preserve active state and baseline. Test a retry if the service implements one; any final failure still rolls back.
5. With a stub 500 or malformed later page, return a non-2xx response and preserve active state and baseline.
6. After a successful import, mutate fake data and call reset. The imported world returns exactly. Start a fresh process and reset; the normal clean world returns.
7. Assert the token appears only in upstream authorization headers, never in import request JSON, fake API responses, logs, persisted state, warnings, or errors.

`tests/import_stub.py` provides a fixed paginated upstream for these cases. Set its `mode` to `rate_limit`, `fail`, or `missing_parent` to exercise failure paths. A service's contract tests should start it locally, point its vendor client at the stub, and assert its own fake API behavior. The stub's simple URLs are illustrative; each importer can adapt the same data and failure cases to its vendor's wire format.
