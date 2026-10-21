# Private local protocol v1

Both peers use a length prefixed JSON object frame on private Unix sockets. The prefix is an unsigned 32 bit big endian byte count, limited to 10 MiB including JSON and base64 overhead. Every message has `version: 1` and `kind`. Binary bodies are standard base64 in `body_b64`. Query and header fields are ordered arrays of `[name, value]` pairs, preserving duplicates and their original casing. `method`, `scheme`, `host`, `path`, and `raw_target` are separate fields. `raw_target` retains the exact path and query encoding, including `+` versus `%20` and `flag` versus `flag=`; parsed `query` pairs remain available for services. Neither peer reconstructs the gateway target from parsed pairs.

The request `host` retains its original authority, including letter casing and an optional numeric port. Routing and service host binding use a lowercase DNS hostname key with the port removed; neither step rewrites the original authority. The router handles private ingress connections independently, bounds each ingress read to two seconds, and limits simultaneous connections to 128. Its aggregate ingress frame budget is 40 MiB; over-budget frames receive a fail-closed response, limiting concurrent JSON/base64 copies.

The router sends `{"version":1,"kind":"health"}` at startup. The runtime replies with `kind: "health"` and trusted capability data including `protocol_version`, SDK version, service hosts, and recovery policy versions. Readiness requires installed capabilities and exact equality between normalized runtime service hosts and the configured router host set. Any mismatch prevents the router from becoming ready.

Every later router health request probes the runtime with a two-second deadline. The router reports `unhealthy` when the runtime is unavailable or incompatible, so Sandbox B health gates Sandbox A egress throughout the evaluation rather than only at startup.

Router to runtime managed delivery:

```json
{"version":1,"kind":"managed_request","request_id":"opaque-id","request":{"method":"POST","scheme":"https","host":"api.example.com","path":"/v1/items","raw_target":"/v1/items?page=1&page=2","query":[["page","1"],["page","2"]],"headers":[["X-Test","a"],["X-Test","b"]],"body_b64":"AP8="}}
```

The runtime returns `{"version":1,"kind":"raw_response","request_id":"opaque-id","response":{"status":200,"headers":[],"body_b64":""}}`. Unknown managed hosts and operations return failure responses. Router failures return 502 and never fall back to the gateway.

The **separate** runtime to router gateway forwarding channel is reserved for a `modified_read` frame with `request_id`, `source_request_id`, and a `request` with the same raw shape. Its `raw_response` uses the same response shape. Managed dispatch binds the original `request_id` to a new immutable service context for each request; a transport receives it as `source_request_id` on `request(...)`. The router will combine the service modified provider request with the protected gateway envelope retained from `source_request_id`; Python must never receive or modify that envelope. ISL-1745 owns the transport implementation and ISL-1755 owns gateway forwarding. This skeleton does not open the forwarding channel, so a service requiring an upstream read fails closed until its bound transport is installed.

Malformed frames, including valid JSON values other than objects, return `kind: "error", error: "invalid_request"` from the runtime. Unsupported versions, unknown kinds, and lost peers are errors. The sockets and health surface must remain inaccessible from Sandbox A.

The Python `RouterBackedTransport` always opens a new connection to the runtime-to-router forwarding Unix socket for each real read. It submits only the provider-facing request and `source_request_id`; it strips agent credential, `X-Islo-*`, `X-Original-*`, host, and hop-by-hop headers first. The router must reject unknown/expired source IDs and never accept a gateway envelope from Python. A `raw_response` must echo the `request_id`; mismatches or malformed frames fail closed. The hosted transport defaults to a 7 MiB response-body limit to fit base64 within the existing 10 MiB frame ceiling; an oversized response frame maps to `response_too_large`. There are no automatic retries. The router forwarding server and protected-envelope recombination are owned by ISL-1755.
