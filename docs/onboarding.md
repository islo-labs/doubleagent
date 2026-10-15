# Starting with DoubleAgent

Install the CLI and start the fake service you need. Use a local fixture to create a repeatable world:

```bash
doubleagent start slack
doubleagent seed slack ./fixture.yaml
doubleagent reset slack
```

Fixture seeding works for every service with a seed endpoint. Live import is available only when a service advertises `import.supported: true` and implements the [import protocol](import-contract.md). The bundled services currently advertise `false`.

For an import-capable service, put the vendor token in an environment variable and pass its **name** to the CLI:

```bash
export SOURCE_TOKEN='your-vendor-token'
doubleagent seed my-service --api-key-env SOURCE_TOKEN
# Or choose an explicit half-open window:
doubleagent seed my-service --api-key-env SOURCE_TOKEN \
  --end-at 2026-10-15T12:00:00Z --days-back 30
```

The default window ends at current UTC time and starts 90 days earlier. Keep tokens out of command arguments, fixture files, commits, and logs. After a successful import, `doubleagent reset my-service` restores that imported world for this process. A newly started service without an import uses its normal clean reset.

Service contributors can use the deterministic local stub in `tests/import_stub.py` and the [contract cases](import-contract.md) to test an importer without real vendor credentials.
