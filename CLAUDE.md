# DoubleAgent

Stateful fakes of third-party SaaS APIs (GitHub, Slack, Auth0, Descope, Jira, Salesforce) for local AI agent development and testing.

## Architecture

```
Rust CLI (crates/cli)          Python Services (services/*)
┌──────────────────┐           ┌──────────────────────────┐
│  doubleagent      │   HTTP    │  FastAPI servers          │
│  start/stop/reset │ ────────> │  per-service state        │
│  seed/contract    │           │  namespace isolation      │
│                   │           │  webhook simulation       │
└──────────────────┘           └──────────────────────────┘
```

**State model**: Copy-on-Write (CoW) — shared read-only baseline (snapshot) + per-namespace mutable overlay + tombstones. Reset wipes overlay, not baseline.

**Namespace isolation**: `X-DoubleAgent-Namespace` header routes to isolated state. Multiple agents share baseline efficiently.

## Project Structure

```
crates/
  cli/src/          Rust CLI (clap). Entry: main.rs, commands in commands/
  core/src/         Rust core lib: config, service, process, git, mise
services/
  github/           GitHub fake (FastAPI) — server/, contracts/, fixtures/
  slack/            Slack fake (FastAPI) — same layout
  auth0/            Auth0 fake (FastAPI) — same layout
  descope/          Descope fake (FastAPI) — same layout
  jira/             Jira snapshot-only (Airbyte connector)
  salesforce/       Salesforce snapshot-only (Airbyte connector)
docs/               architecture.md, for-agents.md, contributing.md
skills/             AI agent prompts (add-service.md)
```

## Key Files

- `crates/cli/src/main.rs` — CLI entry point
- `crates/cli/src/commands/mod.rs` — Command definitions (clap enums)
- `crates/core/src/service.rs` — ServiceDefinition, ServiceRegistry
- `crates/core/src/process.rs` — ProcessManager (start/stop/health-check)
- `services/*/service.yaml` — Service definition (server command, contracts)
- `services/*/server/main.py` — FastAPI implementation with inlined state classes

## Service Pattern

Every fake service inlines three state management classes at the top of `main.py`:
1. **StateOverlay** — CoW state engine (baseline/overlay/tombstones)
2. **NamespaceRouter** — Per-agent isolation via X-DoubleAgent-Namespace header
3. **WebhookSimulator** — Delivery with retry, HMAC-SHA256, audit log

Copy these from any existing service (e.g., `services/github/server/main.py`). Do NOT import from a shared library.

Control plane endpoints: `/_doubleagent/{health,reset,seed,bootstrap,info,webhooks,namespaces}`
Data plane: real API endpoints matching the actual service's REST API.
State accessed via `get_state(request)` which reads `X-DoubleAgent-Namespace` header.

## Build & Test

```bash
# Rust
cargo build --release          # Build CLI binary
cargo test                     # Run Rust tests
cargo fmt --all -- --check     # Check formatting
cargo clippy --all-targets     # Lint

# Services (each service uses mise for toolchain)
doubleagent contract <service> # Run contract tests against a fake
doubleagent start <service>    # Start a service
doubleagent seed <service> --fixture startup  # Seed with fixture data
doubleagent reset <service> --hard            # Hard reset (clear everything)
```

## Conventions

- **Rust**: workspace with two crates (cli, core). Async with tokio. Clap for CLI.
- **Python services**: FastAPI + uvicorn. Python 3.11 via mise. Dependencies managed by uv.
- **Each service** has: `service.yaml`, `.mise.toml`, `server/`, `contracts/`, optionally `fixtures/`.
- **No shared SDK**: each service inlines state management classes directly in `main.py`.
- **Contract tests** use the real SDK (PyGithub, slack_sdk, etc.) to verify the fake behaves like the real service.

## Adding a New Service

Follow `skills/add-service.md` and `docs/for-agents.md`. The pattern:
1. Create `services/{name}/service.yaml`
2. Implement `server/main.py` — copy inlined classes from existing service, add API endpoints
3. Write contract tests in `contracts/` using the official SDK
4. Add `.mise.toml` for toolchain, `fixtures/startup.yaml` for seed data
5. Generate lock files with `uv lock`
