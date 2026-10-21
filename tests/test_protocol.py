import asyncio
import struct
from contextlib import suppress
from pathlib import Path

import pytest

from doubleagent.runtime import RuntimeServer
from doubleagent.runtime.protocol import (
    MAX_FRAME,
    PROTOCOL_VERSION,
    modified_read_to_wire,
    read_frame,
    request_from_wire,
    request_to_wire,
    response_from_wire,
    response_to_wire,
    write_frame,
)
from doubleagent.sdk import ProviderRequest, ProviderResponse

from .test_runtime import make_runtime


def test_raw_codec_preserves_duplicates_and_binary_bodies():
    request = ProviderRequest(
        method="PATCH",
        host="alpha.example",
        path="/a%2Fb",
        query=(("a", "1"), ("a", "2")),
        headers=(("Set-Cookie", "a"), ("Set-Cookie", "b")),
        body=b"\x00\xff",
    )
    response = ProviderResponse(status=418, headers=request.headers, body=request.body)
    assert request_from_wire(request_to_wire(request)) == request
    assert response_from_wire(response_to_wire(response)) == response
    modified = modified_read_to_wire("upstream-1", "agent-1", request)
    assert modified["kind"] == "modified_read"
    assert request_from_wire(modified["request"]) == request


def test_request_preserves_scheme_and_exact_target():
    request = ProviderRequest(
        method="GET",
        scheme="http",
        host="alpha.example:8080",
        path="/a%2Fb",
        raw_target="/a%2Fb?space=a+b&space=a%20b&flag&flag=&x=%2f",
        query=(("space", "a b"), ("space", "a b"), ("flag", ""), ("flag", ""), ("x", "/")),
    )
    assert request_from_wire(request_to_wire(request)) == request
    assert request_to_wire(request)["raw_target"] == request.raw_target
    assert request_to_wire(request)["scheme"] == "http"


@pytest.mark.asyncio
async def test_json_array_frame_gets_invalid_request(tmp_path):
    runtime, _ = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(server.path))
        writer.write(struct.pack(">I", 2) + b"[]")
        await writer.drain()
        assert (await read_frame(reader))["error"] == "invalid_request"
        writer.close()
        await writer.wait_closed()
    finally:
        await server.close()


def test_transport_frame_ceiling_is_ten_mib():
    assert MAX_FRAME == 10 * 1024 * 1024


@pytest.mark.asyncio
async def test_runtime_socket_and_version_negotiation(tmp_path):
    runtime, _ = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    try:
        reader, writer = await asyncio.open_unix_connection(str(server.path))
        await write_frame(writer, {"version": 99, "kind": "health"})
        assert (await read_frame(reader))["error"] == "version_mismatch"
        writer.close()
        await writer.wait_closed()
        reader, writer = await asyncio.open_unix_connection(str(server.path))
        await write_frame(writer, {"version": PROTOCOL_VERSION, "kind": "health"})
        assert (await read_frame(reader))["health"]["status"] == "ready"
        writer.close()
        await writer.wait_closed()
    finally:
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["alpha.example", "ALPHA.example", "alpha.example:443"])
async def test_rust_router_python_runtime_round_trip(tmp_path, authority):
    binary = Path(__file__).parents[1] / "target/debug/doubleagent-router"
    if not binary.exists():
        pytest.skip("build router binary before integration test")
    runtime, recorder = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    router_socket = tmp_path / "router.sock"
    process = await asyncio.create_subprocess_exec(
        str(binary), str(router_socket), str(server.path), "alpha.example,beta.example"
    )
    try:
        for _ in range(100):
            if router_socket.exists() or process.returncode is not None:
                break
            await asyncio.sleep(0.01)
        assert router_socket.exists()
        reader, writer = await asyncio.open_unix_connection(str(router_socket))
        request = ProviderRequest(
            method="POST",
            scheme="http",
            host=authority,
            path="/read",
            raw_target="/read?a=1&a=2&flag&flag=&space=a+b&space=a%20b",
            query=(
                ("a", "1"),
                ("a", "2"),
                ("flag", ""),
                ("flag", ""),
                ("space", "a b"),
                ("space", "a b"),
            ),
            headers=(("X-A", "first"), ("X-A", "second")),
            body=b"\x00\xff",
        )
        await write_frame(
            writer,
            {
                "version": PROTOCOL_VERSION,
                "kind": "managed_request",
                "request_id": "request-1",
                "request": request_to_wire(request),
            },
        )
        result = await read_frame(reader)
        assert result["kind"] == "raw_response"
        assert result["request_id"] == "request-1"
        assert response_from_wire(result["response"]).body == b"hello\x00\x00\xff"
        assert recorder.requests == [request]
        assert recorder.source_ids == ["request-1"]
        writer.close()
        await writer.wait_closed()
    finally:
        process.terminate()
        await process.wait()
        await server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hosts",
    ["alpha.example", "alpha.example,beta.example,extra.example", "alpha.example,wrong.example"],
)
async def test_router_rejects_mismatched_managed_host_table(tmp_path, hosts):
    binary = Path(__file__).parents[1] / "target/debug/doubleagent-router"
    if not binary.exists():
        pytest.skip("build router binary before integration test")
    runtime, _ = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    router_socket = tmp_path / "router.sock"
    process = await asyncio.create_subprocess_exec(
        str(binary), str(router_socket), str(server.path), hosts
    )
    try:
        assert await asyncio.wait_for(process.wait(), timeout=2) != 0
        assert not router_socket.exists()
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
        await server.close()


@pytest.mark.asyncio
async def test_stalled_ingress_peer_does_not_block_router_health(tmp_path):
    binary = Path(__file__).parents[1] / "target/debug/doubleagent-router"
    if not binary.exists():
        pytest.skip("build router binary before integration test")
    runtime, _ = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    router_socket = tmp_path / "router.sock"
    process = await asyncio.create_subprocess_exec(
        str(binary), str(router_socket), str(server.path), "alpha.example,beta.example"
    )
    stalled = None
    healthy = None
    try:
        for _ in range(100):
            if router_socket.exists() or process.returncode is not None:
                break
            await asyncio.sleep(0.01)
        assert router_socket.exists()
        stalled_reader, stalled = await asyncio.open_unix_connection(str(router_socket))
        reader, healthy = await asyncio.open_unix_connection(str(router_socket))
        await write_frame(healthy, {"version": PROTOCOL_VERSION, "kind": "health"})
        response = await asyncio.wait_for(read_frame(reader), timeout=0.5)
        assert response["health"]["status"] == "ready"
        timeout_response = await asyncio.wait_for(read_frame(stalled_reader), timeout=3.0)
        assert timeout_response["response"]["status"] == 502
    finally:
        if healthy is not None:
            healthy.close()
            await healthy.wait_closed()
        if stalled is not None:
            stalled.close()
            await stalled.wait_closed()
        process.terminate()
        await process.wait()
        await server.close()


@pytest.mark.asyncio
async def test_slow_ingress_frame_has_total_deadline(tmp_path):
    binary = Path(__file__).parents[1] / "target/debug/doubleagent-router"
    if not binary.exists():
        pytest.skip("build router binary before integration test")
    runtime, _ = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    router_socket = tmp_path / "router.sock"
    process = await asyncio.create_subprocess_exec(
        str(binary), str(router_socket), str(server.path), "alpha.example,beta.example"
    )
    drip = None
    writer = None
    try:
        for _ in range(100):
            if router_socket.exists() or process.returncode is not None:
                break
            await asyncio.sleep(0.01)
        assert router_socket.exists()
        reader, writer = await asyncio.open_unix_connection(str(router_socket))
        writer.write(struct.pack(">I", 20))
        await writer.drain()

        async def send_slow_bytes():
            while True:
                writer.write(b"x")
                await writer.drain()
                await asyncio.sleep(0.25)

        drip = asyncio.create_task(send_slow_bytes())
        response = await asyncio.wait_for(read_frame(reader), timeout=3.0)
        assert response["response"]["status"] == 502
    finally:
        if drip is not None:
            drip.cancel()
            await asyncio.gather(drip, return_exceptions=True)
        if writer is not None:
            writer.close()
            with suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()
        process.terminate()
        await process.wait()
        await server.close()


@pytest.mark.asyncio
async def test_router_health_tracks_runtime_loss(tmp_path):
    binary = Path(__file__).parents[1] / "target/debug/doubleagent-router"
    if not binary.exists():
        pytest.skip("build router binary before integration test")
    runtime, _ = make_runtime()
    server = RuntimeServer(runtime, tmp_path / "runtime.sock")
    await server.start()
    router_socket = tmp_path / "router.sock"
    process = await asyncio.create_subprocess_exec(
        str(binary), str(router_socket), str(server.path), "alpha.example,beta.example"
    )

    async def health_status():
        reader, writer = await asyncio.open_unix_connection(str(router_socket))
        try:
            await write_frame(writer, {"version": PROTOCOL_VERSION, "kind": "health"})
            response = await asyncio.wait_for(read_frame(reader), timeout=3.0)
            return response["health"]["status"]
        finally:
            writer.close()
            await writer.wait_closed()

    try:
        for _ in range(100):
            if router_socket.exists() or process.returncode is not None:
                break
            await asyncio.sleep(0.01)
        assert router_socket.exists()
        assert await health_status() == "ready"
        await server.close()
        assert await health_status() == "unhealthy"
    finally:
        process.terminate()
        await process.wait()
        await server.close()
