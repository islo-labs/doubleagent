"""Transport contract tests use in-memory HTTP and a private mock router socket."""

import asyncio
import base64
import struct

import httpx
import pytest

from doubleagent.runtime.protocol import MAX_FRAME, read_frame, response_to_wire, write_frame
from doubleagent.sdk import (
    Credential,
    DirectTokenTransport,
    EnvironmentCredentialProvider,
    ProviderRequest,
    ProviderResponse,
    RouterBackedTransport,
    StaticCredentialProvider,
    TransportBinding,
    TransportCancelledError,
    TransportError,
    TransportErrorCode,
)

BINDING = TransportBinding("github", "account-1", ("api.example.com",))
REQUEST = ProviderRequest(
    method="POST",
    host="API.EXAMPLE.COM",
    path="/v1/items",
    raw_target="/v1/items?x=a+b&x=a%20b&flag",
    query=(("x", "a b"), ("x", "a b"), ("flag", "")),
    headers=(
        ("X-Dupe", "a"),
        ("X-Dupe", "b"),
        ("Authorization", "agent-secret"),
        ("X-Islo-Authorization", "protected"),
        ("X-Original-Host", "wrong"),
        ("Connection", "X-Remove"),
        ("X-Remove", "remove"),
        ("Cookie", "secret"),
    ),
    body=b"\x00\xffraw",
)


@pytest.mark.parametrize(
    "strategy,expected",
    [
        ("bearer", "Bearer provider-secret"),
        ("basic", "Basic " + base64.b64encode(b"user:provider-secret").decode()),
        ("custom_header", "provider-secret"),
    ],
)
@pytest.mark.asyncio
async def test_direct_preserves_raw_request_and_injects_only_provider_credential(
    strategy, expected
):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            403, headers=[("X-Dupe", "one"), ("X-Dupe", "two")], stream=httpx.ByteStream(b"\xff")
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    credential = Credential(
        strategy,
        "provider-secret",
        username="user",
        header="X-Custom-Auth" if strategy == "custom_header" else "",
    )
    transport = DirectTokenTransport(BINDING, StaticCredentialProvider(credential), client=client)
    response = await transport.request(REQUEST)
    await client.aclose()
    assert response.status == 403 and response.body == b"\xff"
    assert [value for name, value in response.headers if name.lower() == "x-dupe"] == ["one", "two"]
    assert len(seen) == 1
    request = seen[0]
    assert request.url.raw_path == b"/v1/items?x=a+b&x=a%20b&flag"
    assert request.content == b"\x00\xffraw"
    assert request.headers.get_list("x-dupe") == ["a", "b"]
    assert (
        strategy == "custom_header"
        and request.headers["x-custom-auth"] == expected
        or strategy != "custom_header"
        and request.headers["authorization"] == expected
    )
    for forbidden in ("x-islo-authorization", "x-original-host", "x-remove", "cookie"):
        assert forbidden not in request.headers
    assert "agent-secret" not in repr(request.headers)


@pytest.mark.asyncio
async def test_direct_rejects_targets_redirects_and_large_responses():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = DirectTokenTransport(
        BINDING, StaticCredentialProvider(Credential("bearer", "secret")), client=client
    )
    for request in (
        REQUEST.model_copy(update={"host": "evil.example"}),
        REQUEST.model_copy(update={"scheme": "http"}),
    ):
        with pytest.raises(TransportError) as error:
            await transport.request(request)
        assert error.value.code == TransportErrorCode.INVALID_TARGET
    assert calls == 0
    with pytest.raises(TransportError) as error:
        await transport.request(REQUEST)
    assert error.value.code == TransportErrorCode.INVALID_TARGET and calls == 1
    await client.aclose()

    large_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, stream=httpx.ByteStream(b"12345"))
        )
    )
    limited = DirectTokenTransport(
        BINDING,
        StaticCredentialProvider(Credential("bearer", "secret")),
        client=large_client,
        response_limit=4,
    )
    with pytest.raises(TransportError) as error:
        await limited.request(REQUEST)
    assert error.value.code == TransportErrorCode.RESPONSE_TOO_LARGE
    await large_client.aclose()


@pytest.mark.asyncio
async def test_direct_network_errors_are_stable_and_never_retry():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("secret URL and token", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events = []
    transport = DirectTokenTransport(
        BINDING,
        StaticCredentialProvider(Credential("bearer", "secret")),
        client=client,
        record=lambda name, attrs: events.append(attrs),
    )
    with pytest.raises(TransportError) as error:
        await transport.request(REQUEST, source_request_id="source-1")
    assert error.value.code == TransportErrorCode.CONNECT_FAILURE
    assert "secret" not in str(error.value) and calls == 1
    assert events[0]["request_id"] == "source-1"
    assert "secret" not in str(events) and "a+b" not in str(events)
    await client.aclose()


@pytest.mark.asyncio
async def test_environment_credential_missing_is_typed(monkeypatch):
    monkeypatch.delenv("DA_TEST_TOKEN", raising=False)
    transport = DirectTokenTransport(
        BINDING, EnvironmentCredentialProvider("bearer", "DA_TEST_TOKEN")
    )
    with pytest.raises(TransportError) as error:
        await transport.request(REQUEST)
    assert error.value.code == TransportErrorCode.CREDENTIAL_UNAVAILABLE
    await transport.aclose()


@pytest.mark.asyncio
async def test_router_channel_round_trip_preserves_request_and_source_binding(tmp_path):
    socket = tmp_path / "gateway-forward.sock"
    seen = []

    async def router(reader, writer):
        frame = await read_frame(reader)
        seen.append(frame)
        await write_frame(
            writer,
            {
                "version": 1,
                "kind": "raw_response",
                "request_id": frame["request_id"],
                "response": response_to_wire(
                    ProviderResponse(status=429, headers=(("Retry-After", "2"),), body=b"raw\x00")
                ),
            },
        )
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(router, path=str(socket))
    transport = RouterBackedTransport(BINDING, socket)
    try:
        responses = await asyncio.gather(
            *(transport.request(REQUEST, source_request_id=f"source-{i}") for i in range(12))
        )
    finally:
        server.close()
        await server.wait_closed()
    assert all(response.status == 429 and response.body == b"raw\x00" for response in responses)
    assert {frame["source_request_id"] for frame in seen} == {f"source-{i}" for i in range(12)}
    assert len({frame["request_id"] for frame in seen}) == 12
    for frame in seen:
        assert frame["kind"] == "modified_read"
        assert frame["request"]["raw_target"] == REQUEST.raw_target
        assert frame["request"]["body_b64"] == base64.b64encode(REQUEST.body).decode()
        assert frame["request"]["query"] == [["x", "a b"], ["x", "a b"], ["flag", ""]]
        assert [pair for pair in frame["request"]["headers"] if pair[0] == "X-Dupe"] == [
            ["X-Dupe", "a"],
            ["X-Dupe", "b"],
        ]
        assert not any(
            name.lower().startswith(("x-islo-", "x-original-"))
            for name, _ in frame["request"]["headers"]
        )
        assert "gateway_envelope" not in frame and "jwt" not in frame


@pytest.mark.asyncio
async def test_router_requires_source_and_maps_unavailable_channel(tmp_path):
    transport = RouterBackedTransport(BINDING, tmp_path / "absent.sock")
    with pytest.raises(TransportError) as error:
        await transport.request(REQUEST)
    assert error.value.code == TransportErrorCode.INVALID_TARGET
    with pytest.raises(TransportError) as error:
        await transport.request(REQUEST, source_request_id="source")
    assert error.value.code == TransportErrorCode.CONNECT_FAILURE


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
@pytest.mark.asyncio
async def test_provider_error_statuses_remain_raw(status):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, stream=httpx.ByteStream(b"provider error"))
        )
    )
    transport = DirectTokenTransport(
        BINDING, StaticCredentialProvider(Credential("bearer", "secret")), client=client
    )
    response = await transport.request(REQUEST)
    assert response.status == status and response.body == b"provider error"
    await client.aclose()


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_change_provider_result():
    def broken_record(_event, _attributes):
        raise RuntimeError("telemetry unavailable")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=httpx.ByteStream(b"ok")))
    )
    transport = DirectTokenTransport(
        BINDING,
        StaticCredentialProvider(Credential("bearer", "secret")),
        client=client,
        record=broken_record,
    )
    assert (await transport.request(REQUEST)).body == b"ok"
    await client.aclose()


@pytest.mark.asyncio
async def test_direct_cancellation_retains_asyncio_semantics():
    entered = asyncio.Event()

    async def handler(_request):
        entered.set()
        await asyncio.sleep(60)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = DirectTokenTransport(
        BINDING, StaticCredentialProvider(Credential("bearer", "secret")), client=client
    )
    task = asyncio.create_task(transport.request(REQUEST))
    await entered.wait()
    task.cancel()
    with pytest.raises(TransportCancelledError) as error:
        await task
    assert error.value.code == TransportErrorCode.CANCELLED
    await client.aclose()


@pytest.mark.asyncio
async def test_direct_rejects_undeclared_port_before_sending_credential():
    sent = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                sent.append(request) or httpx.Response(200, stream=httpx.ByteStream(b"ok"))
            )
        )
    )
    transport = DirectTokenTransport(
        BINDING, StaticCredentialProvider(Credential("bearer", "provider-secret")), client=client
    )
    with pytest.raises(TransportError) as error:
        await transport.request(REQUEST.model_copy(update={"host": "api.example.com:4443"}))
    assert error.value.code == TransportErrorCode.INVALID_TARGET
    assert sent == []
    await client.aclose()


@pytest.mark.asyncio
async def test_hosted_rejects_undeclared_port_before_using_channel(tmp_path):
    transport = RouterBackedTransport(BINDING, tmp_path / "absent.sock")
    with pytest.raises(TransportError) as error:
        await transport.request(
            REQUEST.model_copy(update={"host": "api.example.com:4443"}),
            source_request_id="source",
        )
    assert error.value.code == TransportErrorCode.INVALID_TARGET


@pytest.mark.asyncio
async def test_hosted_rejects_redirect_with_location(tmp_path):
    socket = tmp_path / "forward.sock"

    async def router(reader, writer):
        frame = await read_frame(reader)
        await write_frame(
            writer,
            {
                "version": 1,
                "kind": "raw_response",
                "request_id": frame["request_id"],
                "response": response_to_wire(
                    ProviderResponse(status=302, headers=(("Location", "https://other.example"),))
                ),
            },
        )
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(router, path=str(socket))
    try:
        with pytest.raises(TransportError) as error:
            await RouterBackedTransport(BINDING, socket).request(
                REQUEST, source_request_id="source"
            )
        assert error.value.code == TransportErrorCode.INVALID_TARGET
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_hosted_oversized_encoded_response_is_response_too_large(tmp_path):
    socket = tmp_path / "forward.sock"
    body_size = 12 * 1024 * 1024
    encoded_size = ((body_size + 2) // 3) * 4 + 128
    assert body_size < 13 * 1024 * 1024 and encoded_size > MAX_FRAME

    async def router(reader, writer):
        await read_frame(reader)
        writer.write(struct.pack(">I", encoded_size))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(router, path=str(socket))
    try:
        with pytest.raises(TransportError) as error:
            await RouterBackedTransport(BINDING, socket, response_limit=13 * 1024 * 1024).request(
                REQUEST, source_request_id="source"
            )
        assert error.value.code == TransportErrorCode.RESPONSE_TOO_LARGE
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_direct_allows_default_and_explicitly_bound_custom_port():
    seen = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                seen.append(request.url.port) or httpx.Response(200, stream=httpx.ByteStream(b"ok"))
            )
        )
    )
    credential = StaticCredentialProvider(Credential("bearer", "secret"))
    default_transport = DirectTokenTransport(BINDING, credential, client=client)
    custom_binding = TransportBinding("github", "account-1", ("api.example.com:4443",))
    custom_transport = DirectTokenTransport(custom_binding, credential, client=client)
    assert (
        await default_transport.request(REQUEST.model_copy(update={"host": "API.EXAMPLE.COM:443"}))
    ).status == 200
    assert (
        await custom_transport.request(REQUEST.model_copy(update={"host": "api.example.com:4443"}))
    ).status == 200
    with pytest.raises(TransportError) as error:
        await custom_transport.request(REQUEST)
    assert error.value.code == TransportErrorCode.INVALID_TARGET
    assert seen == [None, 4443]
    await client.aclose()


def test_hosted_default_body_limit_accounts_for_protocol_encoding(tmp_path):
    transport = RouterBackedTransport(BINDING, tmp_path / "forward.sock")
    assert transport.response_limit == 10 * 1024 * 1024
    assert len(base64.b64encode(b"x" * transport.response_limit)) < MAX_FRAME


@pytest.mark.parametrize(
    "body_size,should_succeed",
    [
        (10 * 1024 * 1024, True),
        (10 * 1024 * 1024 + 1, False),
    ],
)
@pytest.mark.asyncio
async def test_hosted_ten_mib_body_boundary_round_trip(tmp_path, body_size, should_succeed):
    socket = tmp_path / "forward.sock"
    body = b"x" * body_size

    async def router(reader, writer):
        frame = await read_frame(reader)
        try:
            await write_frame(
                writer,
                {
                    "version": 1,
                    "kind": "raw_response",
                    "request_id": frame["request_id"],
                    "response": response_to_wire(ProviderResponse(status=200, body=body)),
                },
            )
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(router, path=str(socket))
    try:
        transport = RouterBackedTransport(BINDING, socket)
        assert transport.response_limit == 10 * 1024 * 1024
        if should_succeed:
            response = await transport.request(REQUEST, source_request_id="source")
            assert response.status == 200 and response.body == body
        else:
            with pytest.raises(TransportError) as error:
                await transport.request(REQUEST, source_request_id="source")
            assert error.value.code == TransportErrorCode.RESPONSE_TOO_LARGE
    finally:
        server.close()
        await server.wait_closed()
