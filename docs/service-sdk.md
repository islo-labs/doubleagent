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
