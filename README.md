# DoubleAgent

DoubleAgent is a provider virtualization foundation for historical agent evaluations. An evaluation runs in a dedicated trusted Sandbox B with a Python service runtime and a small Rust router. Services classify provider requests, read registered task input, and render provider responses. The router and runtime communicate through a versioned private protocol.

This is experimental Service SDK `v0`. It intentionally has no compatibility with the earlier fake service CLI, seed/reset model, or checkpoint/capture interfaces.

## Layout

- `src/doubleagent/sdk/`: provider neutral request, response, operation, context, and capability contracts.
- `src/doubleagent/runtime/`: explicit service loading, bound task context, dispatch, and local server.
- `crates/router/`: versioned private framing and a local managed request forwarding process.
- `tests/fixtures/`: deterministic test-only services and manifests.

## Local checks

```sh
uv sync --extra dev
cargo build -p doubleagent-router
uv run pytest
uv run ruff check .
uv run pre-commit run --all-files
cargo fmt --all -- --check
cargo clippy -p doubleagent-router --all-targets -- -D warnings
cargo test -p doubleagent-router
```

## Trusted runtime launch

The control plane prepares one trusted JSON configuration per evaluation containing `evaluation_id`, `task_id`, `cutoff_at`, `bundle_version`, `registered_task`, and an array of absolute `service_manifests` paths. The task contains `task_id`, raw `task_payload`, raw `registration_payload`, and `source_links`. The runtime verifies the task binding and freezes nested task data before loading services. This launch format is a local bootstrap contract; the hosted task client and durable task API belong to ISL-1743.

```sh
uv run doubleagent-runtime \
  --config /private/evaluation.json \
  --runtime-socket /private/runtime.sock \
  --health-socket /private/health.sock
```

The `GET /health` ASGI route and both Unix sockets are trusted control surfaces. Sandbox A must have no access to them. The runtime process uses a restrictive umask for its sockets. The Rust router skeleton accepts a private local ingress socket, the runtime socket, and a comma separated host table:

```sh
cargo run -p doubleagent-router -- /private/router.sock /private/runtime.sock alpha.example
```

The router checks runtime protocol compatibility and health before binding its ingress socket. The complete transparent Sandbox A egress and Islo gateway adapter are owned by ISL-1755. The launcher currently supplies the validated host table; manifest to router table provisioning belongs to that integration.

See [Service SDK](docs/service-sdk.md) and [Local protocol](docs/local-protocol.md).
