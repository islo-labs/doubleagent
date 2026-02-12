# DoubleAgent

**Fake services. Real agents.**

You're running AI coding agents at scale — hundreds of them creating PRs, filing
issues, calling APIs concurrently. You can't point them at real GitHub, real Jira,
or real Okta because:

- You can't create a thousand test accounts
- Nobody will let you hammer their API at that volume
- You can't reset state between runs
- Every API call costs money

DoubleAgent gives you **high-fidelity, in-memory fakes** of popular services that
your agents can hit instead. One config file, one command, and your agents have a
full simulated world to run wild in.

## What you get

| Service | Port | API coverage |
|---------|------|--------------|
| **GitHub** | configurable | Repos, Issues, Pull Requests |
| **Jira** | configurable | Projects, Issues, Search |
| More coming | | Okta, Slack, ... |

Every fake:

- **Behaves like the real thing.** Create a repo, open an issue against it, list
  issues back — the state is consistent. Not hard-coded stubs that break the
  moment your agent does something unexpected.
- **Resets in one call.** `POST /_/reset` wipes all state so each agent run
  starts clean.
- **Runs in-memory.** No database, no Docker dependencies. Starts in milliseconds.

## Quick start

**Prerequisites:** Go 1.23+

**1. Clone and build**

```bash
git clone https://github.com/islo-labs/double-agent.git
cd double-agent
go build -o double ./cmd/double
```

**2. Configure your services** in `double.hcl`:

```hcl
service "github" "primary" {
  port = 8081
  env = {
    DEFAULT_ORG = "acme"
  }
}

service "jira" "main" {
  port = 9090
  env = {
    PROJECT_KEY = "AGENT"
  }
}
```

**3. Run**

```bash
./double run
```

```
2026/02/12 10:00:00 DoubleAgent starting with 2 service(s)
2026/02/12 10:00:00 starting github/primary (v1) on :8081
2026/02/12 10:00:00 starting jira/main (v1) on :9090
```

**4. Point your agents at it**

```bash
# Create a repo
curl -X POST localhost:8081/repos \
  -d '{"owner":"acme","name":"my-app","private":false}'

# Open an issue
curl -X POST localhost:8081/repos/acme/my-app/issues \
  -d '{"title":"Fix login bug","body":"Login fails on retry"}'

# List issues
curl localhost:8081/repos/acme/my-app/issues

# Reset everything
curl -X POST localhost:8081/_/reset
```

## Available APIs

### GitHub (built-in)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/repos` | Create repository |
| `GET` | `/repos/{owner}/{repo}` | Get repository |
| `POST` | `/repos/{owner}/{repo}/issues` | Create issue |
| `GET` | `/repos/{owner}/{repo}/issues` | List issues |
| `POST` | `/repos/{owner}/{repo}/pulls` | Create pull request |
| `GET` | `/repos/{owner}/{repo}/pulls/{number}` | Get pull request |

**Config:** `DEFAULT_ORG` — default owner for new repos.

### Jira (built-in)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/rest/api/2/project` | Create project |
| `GET` | `/rest/api/2/project` | List projects |
| `GET` | `/rest/api/2/project/{key}` | Get project |
| `POST` | `/rest/api/2/issue` | Create issue |
| `GET` | `/rest/api/2/issue/{key}` | Get issue |
| `GET` | `/rest/api/2/search` | Search issues |

**Config:** `PROJECT_KEY` — default project key (auto-created on startup).

### Reset (all services)

Every service exposes `POST /_/reset` to wipe all in-memory state.

## External plugins (stdio)

Plugins don't have to be compiled into the binary. Any executable that speaks the
DoubleAgent JSON-line protocol over stdin/stdout can be used as a plugin.

### Using an external plugin

Add a `command` field to your service block:

```hcl
service "todo" "main" {
  port    = 8083
  command = ["go", "run", "./plugins/todo"]
  env     = {}
}
```

The engine spawns the command as a subprocess and proxies HTTP requests to it
over stdio.

### Writing an external plugin

An external plugin is any executable that reads JSON requests from stdin and
writes JSON responses to stdout, one per line.

**With the Go SDK** (easiest path — implement `sdk.Plugin` and call `sdk.Serve`):

```go
package main

import "github.com/islo-labs/double-agent/pkg/sdk"

type MyPlugin struct { /* ... */ }

func (p *MyPlugin) Info() sdk.PluginInfo {
    return sdk.PluginInfo{Name: "my-service", Version: "v1"}
}
func (p *MyPlugin) Configure(env map[string]string) error { return nil }
func (p *MyPlugin) ServeHTTP(w http.ResponseWriter, r *http.Request) { /* ... */ }
func (p *MyPlugin) Reset() error { return nil }

func main() {
    sdk.Serve(&MyPlugin{})
}
```

**In any language** — just speak the protocol:

```
→ stdin:  {"id":1,"method":"info"}
← stdout: {"id":1,"result":{"name":"my-service","version":"v1"}}

→ stdin:  {"id":2,"method":"configure","params":{"env":{"KEY":"val"}}}
← stdout: {"id":2,"result":{}}

→ stdin:  {"id":3,"method":"http","params":{"method":"GET","path":"/items","headers":{},"body":""}}
← stdout: {"id":3,"result":{"status":200,"headers":{"Content-Type":"application/json"},"body":"[]"}}

→ stdin:  {"id":4,"method":"reset"}
← stdout: {"id":4,"result":{}}
```

See `plugins/todo/` for a complete working example.

## Configuration reference

```hcl
service "<type>" "<name>" {
  port    = 8081                              # required — HTTP port
  version = "v1"                              # optional — API version
  command = ["path/to/plugin"]                # optional — external plugin command
  env = {                                     # optional — key-value config
    KEY = "value"
  }
}
```

You can run multiple instances of the same service type with different names
and ports:

```hcl
service "github" "production" {
  port = 8081
  env  = { DEFAULT_ORG = "acme" }
}

service "github" "staging" {
  port = 8082
  env  = { DEFAULT_ORG = "acme-staging" }
}
```

## Project structure

```
cmd/double/          CLI entrypoint
pkg/sdk/             Plugin interface + stdio protocol
internal/
  config/            HCL config parsing
  engine/            Plugin lifecycle (start, proxy, shutdown)
  builtin/           Built-in plugin registry
plugins/
  github/            GitHub fake (built-in)
  jira/              Jira fake (built-in)
  todo/              Todo fake (external stdio plugin example)
```

## License

Apache 2.0
