# DoubleAgent Architecture

## Overview

```
Rust CLI (crates/cli)          Python Services (services/*)
┌──────────────────┐           ┌──────────────────────────┐
│  doubleagent      │   HTTP    │  FastAPI servers          │
│  start/stop/reset │ ────────> │  per-service state        │
│  seed/contract    │           │  namespace isolation      │
│                   │           │  webhook simulation       │
└──────────────────┘           └──────────────────────────┘
```

The Rust CLI manages service lifecycle (start/stop/health-check) and sends HTTP commands to Python services. Each service is an independent FastAPI server with its own state.

## Copy-on-Write (CoW) State Model

Every service uses a two-layer state model:

```
┌─────────────────────────────┐
│  Overlay (mutable writes)   │  ← All API mutations go here
├─────────────────────────────┤
│  Tombstones                 │  ← Marks deleted baseline items
├─────────────────────────────┤
│  Baseline (immutable)       │  ← Snapshot data, read-only
└─────────────────────────────┘
```

- **Reads** fall through: overlay → baseline (skip tombstones)
- **Writes** always go to overlay
- **Deletes** add a tombstone (baseline item hidden, not mutated)
- **Reset** clears overlay + tombstones → back to snapshot
- **Hard reset** clears everything including baseline

This is implemented by the `StateOverlay` class, inlined at the top of each service's `main.py`.

## Namespace Isolation

The `X-DoubleAgent-Namespace` header routes requests to isolated state overlays. All namespaces share the same read-only baseline.

```
            ┌─ Namespace "agent-a" ─→ Overlay A
            │
Baseline ──┼─ Namespace "agent-b" ─→ Overlay B
            │
            └─ Namespace "default" ─→ Overlay Default
```

This allows multiple AI agents to share a single service instance without state collisions. Each agent sends its namespace header, gets its own mutable state, but can read from a shared baseline snapshot.

The `NamespaceRouter` class manages this, also inlined in each service.

## Webhook Simulation

The `WebhookSimulator` class provides:

- **Delivery with retry**: configurable max retries and exponential backoff delays
- **HMAC-SHA256 signatures**: `X-Hub-Signature-256` header for payload verification
- **Localhost-only allowlist**: prevents accidental delivery to external hosts
- **Audit log**: queryable via `/_doubleagent/webhooks` endpoint

## Service Structure

Each service follows this layout:

```
services/{name}/
├── .mise.toml          # Toolchain (python = "3.11")
├── service.yaml        # Service definition
├── server/
│   ├── main.py         # FastAPI server with inlined SDK classes
│   ├── pyproject.toml  # Dependencies (no shared SDK)
│   └── uv.lock
├── contracts/
│   ├── conftest.py     # Test fixtures
│   ├── test_*.py       # Contract tests using official SDK
│   ├── pyproject.toml
│   └── uv.lock
└── fixtures/
    └── startup.yaml    # Seed data for quick setup
```

### Inlined State Management

Each service inlines three classes at the top of `main.py` (no shared library dependency):

1. **`StateOverlay`** (~120 lines) — CoW state with baseline/overlay/tombstones
2. **`NamespaceRouter`** (~50 lines) — per-namespace StateOverlay management
3. **`WebhookSimulator`** (~120 lines) — webhook delivery with retry + HMAC

Copy these from any existing service (e.g., `services/github/server/main.py`).

## Control Plane Endpoints

Every service implements:

| Endpoint | Purpose |
|----------|---------|
| `GET /_doubleagent/health` | Returns `{"status": "healthy"}` |
| `POST /_doubleagent/reset` | Reset overlay (`?hard=true` also clears baseline) |
| `POST /_doubleagent/seed` | Merge fixture data into overlay |
| `POST /_doubleagent/bootstrap` | Load immutable baseline snapshot |
| `GET /_doubleagent/info` | Service metadata + state stats |
| `GET /_doubleagent/webhooks` | Query webhook delivery audit log |
| `GET /_doubleagent/namespaces` | List active namespaces with stats |

## CLI Architecture

The Rust CLI (`crates/cli` + `crates/core`) provides:

- **Process management**: start/stop/health-check services via `ProcessManager`
- **Service registry**: discover and install services via `ServiceRegistry`
- **Git operations**: fetch services from remote repo via `ServiceFetcher`
- **Toolchain management**: detect `.mise.toml` and wrap commands with `mise exec --`
- **Contract runner**: start service, run tests, report results

### Key Commands

| Command | Description |
|---------|-------------|
| `doubleagent start <service>` | Start a service (auto-installs if needed) |
| `doubleagent stop [service]` | Stop services |
| `doubleagent reset <service> [--hard]` | Reset state (soft or hard) |
| `doubleagent seed <service> --fixture <name>` | Seed from fixtures directory |
| `doubleagent seed <service> <file>` | Seed from explicit file |
| `doubleagent contract <service>` | Run contract tests |
| `doubleagent run -s <services> -- <cmd>` | Run command with services |

## Security

- **Localhost-only webhooks**: webhook targets must be localhost/private IPs
- **No real credentials**: all services accept any token for auth
- **Isolated state**: namespaces prevent cross-agent data leaks
- **No persistence**: all state is in-memory, lost on restart (by design)
