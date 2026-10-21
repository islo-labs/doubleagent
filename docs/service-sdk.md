# Experimental Service SDK v0

Each enabled service has a `service.yaml` in the trusted deployment bundle:

```yaml
name: example
sdk_version: v0
recovery_policy_version: example-1
provider_hosts: [api.example.com]
routing_priority: 10
supported_operations: [get_item, create_item]
implementation: example.service:Service
```

The runtime rejects unknown SDK versions, duplicate service names, ambiguous hosts, and malformed entrypoints. The trusted deployment selects explicit manifest paths; agent requests never select a service implementation or task. Recovery policy versions are exposed in trusted health data for reproducibility.

`ProviderRequest` and `ProviderResponse` carry buffered raw body bytes and ordered, duplicate preserving query/header pairs. Requests also carry the original `scheme` and `raw_target`; services may use parsed pairs for logic but must use the raw target when exact gateway encoding matters. The service interface is:

```python
def classify(request: ProviderRequest) -> Operation: ...
async def handle(
    operation: Operation, request: ProviderRequest, service_context: ServiceContext
) -> ProviderResponse: ...
```

Operations have a service defined name and one of `READ`, `VIRTUAL_WRITE`, `SEARCH`, `AUTHENTICATION`, or `UNSUPPORTED`. Unknown operation names and `UNSUPPORTED` fail closed. Runtime errors return a managed failure; they never trigger real provider passthrough. For `VIRTUAL_WRITE`, the runtime supplies a denied upstream transport. Services must classify requests according to provider semantics: HTTP POST may be a read (for example, GraphQL) or a write.

`ServiceContext` has immutable evaluation identity/cutoff and deeply frozen registered task payload, registration payload, and source links. Its capability protocols are bound to the one evaluation. `UpstreamTransport` is additionally restricted to the service's declared hosts. For managed requests, the runtime binds the source request ID to a distinct upstream wrapper per dispatch and passes it as the `source_request_id` keyword argument to `request`; transports must preserve that ID when creating `modified_read` frames. The contracts are `TaskRegistrationClient`, `OverlayStore`, `IdentityRegistry`, `AuthorizationService`, `LazyReadCache`, `CursorStore`, `SearchStore`, `LogicalClock`, `Telemetry`, and `ServiceStateDefinition`. Typed service state implementations use a versioned schema and transaction bound repository in the shared evaluation database; the actual store is owned by ISL-1747.

The initial process entrypoint uses fail closed capability placeholders until the transport, state, and authorization implementations are supplied by their owning tickets. It reports `unhealthy` while those capabilities are absent, so the router cannot negotiate readiness. The trusted launch JSON is strictly validated for identifiers, task fields, timezone-aware cutoff, absolute manifest paths, and collection types. No phase one capture or checkpoint interface exists.

Provider filtering rules, overlay semantics, rendering, and search belong to services or their separate framework tickets; the core dispatch has no provider field or API knowledge.

## Upstream HTTP transports

Service implementations submit real provider reads through `context.upstream.request(request)`; the runtime binds the request to the service's declared hosts and, for managed requests, to the source router request ID. Both concrete transports return the SDK's raw `ProviderResponse` for provider errors such as 401, 403, 404, 429, and 5xx. They do not retry. Network and configuration failures raise `TransportError` with a stable `TransportErrorCode` (`invalid_target`, `credential_unavailable`, `connect_failure`, `timeout`, `response_too_large`, or `cancelled`). Cancellation raises `TransportCancelledError` (an `asyncio.CancelledError` subclass) so the caller can stop promptly while retaining a stable `cancelled` code.

`DirectTokenTransport` is for explicitly configured local/self-hosted credentials. Bind it to a provider key, account, and canonical allowed hosts with `TransportBinding`, and pass either `StaticCredentialProvider` or `EnvironmentCredentialProvider`. Credentials support `bearer`, `basic`, and `custom_header` strategies. The transport requires HTTPS unless `local_test=True`, disables redirects, drops agent credentials and internal/hop-by-hop headers, then injects the configured credential. It preserves duplicate safe headers and the exact raw request target/body. Close an owned client with `aclose()` when the evaluation ends.

`RouterBackedTransport` uses the separate private Unix socket for runtime-to-router gateway forwarding. It requires the per-dispatch `source_request_id`, sends a version 1 `modified_read` frame, and accepts only a matching `raw_response`. Python submits provider-facing fields only and cannot supply a protected gateway envelope. The Rust router owned by ISL-1755 must retain the original envelope by source ID, recombine it with these fields, and invoke the unchanged Islo gateway proxy contract. The socket must be available only inside trusted Sandbox B; Sandbox A must have no route or filesystem access to it. Until ISL-1755 supplies that forwarding server, hosted reads fail closed with `connect_failure`.

Both transports default to a 10-second connect timeout, 30-second total timeout, and 10 MiB response-body limit. The private protocol's 10 MiB *frame* limit can constrain a hosted response to less than 10 MiB after JSON/base64 encoding. A telemetry callback can record provider key, host, redacted path shape, method, status, duration, outcome, and request ID. No credential, query value, or body is recorded. `RecordingTransport` and `MockTransport` provide deterministic tests.
