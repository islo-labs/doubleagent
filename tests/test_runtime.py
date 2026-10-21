import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from doubleagent.registry import ServiceRegistry
from doubleagent.runtime import Capabilities, Runtime, create_app
from doubleagent.runtime.core import BoundUpstream
from doubleagent.runtime.main import load_runtime
from doubleagent.sdk import EvaluationConfig, ProviderRequest, ProviderResponse, RegisteredTask

FIXTURES = Path(__file__).parent / "fixtures"


class RecordingCapabilities:
    def __init__(self):
        self.requests = []
        self.source_ids = []
        self.writes = []
        self.events = []

    async def request(self, request, *, source_request_id=None):
        self.requests.append(request)
        self.source_ids.append(source_request_id)
        return ProviderResponse(status=207, body=request.body)

    async def put(self, key, value):
        self.writes.append((key, value))

    def record(self, event, attributes):
        self.events.append((event, attributes))


def make_runtime(manifests=("alpha.yaml", "beta.yaml")):
    recorder = RecordingCapabilities()
    caps = Capabilities(*(recorder for _ in range(9)))
    task = RegisteredTask(
        task_id="task-1",
        task_payload={"prompt": "hello", "nested": {"links": ["one"]}},
        registration_payload={"source": "line-run"},
        source_links=("https://alpha.example/read",),
    )
    config = EvaluationConfig("evaluation-1", "task-1", datetime.now(UTC), "bundle-1")
    registry = ServiceRegistry([FIXTURES / name for name in manifests])
    return Runtime(config, task, registry, caps), recorder


@pytest.mark.asyncio
async def test_multiple_services_and_raw_request_handling():
    runtime, recorder = make_runtime()
    for host in ("alpha.example", "beta.example"):
        request = ProviderRequest(
            method="POST",
            host=host,
            path="/read",
            query=(("x", "1"), ("x", "2")),
            headers=(("X-Test", "one"), ("X-Test", "two")),
            body=b"\x00\xff",
        )
        response = await runtime.dispatch(request)
        assert response.status == 207
        assert response.headers == request.headers
        assert response.body == b"hello\x00\x00\xff"
    assert recorder.requests[0].query == (("x", "1"), ("x", "2"))
    assert len(recorder.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("authority", ["ALPHA.example", "alpha.example:443", "ALPHA.example:443"])
async def test_valid_authority_is_preserved_while_routing_to_declared_host(authority):
    runtime, recorder = make_runtime()
    request = ProviderRequest(method="GET", host=authority, path="/read", body=b"raw")
    response = await runtime.dispatch(request)
    assert response.status == 207
    assert recorder.requests == [request]
    assert recorder.requests[0].host == authority


@pytest.mark.asyncio
async def test_unknown_service_and_operation_fail_closed():
    runtime, recorder = make_runtime()
    assert (
        await runtime.dispatch(ProviderRequest(method="GET", host="other.example", path="/read"))
    ).status == 421
    assert (
        await runtime.dispatch(
            ProviderRequest(method="DELETE", host="alpha.example", path="/unknown")
        )
    ).status == 501
    assert (
        await runtime.dispatch(
            ProviderRequest(method="GET", host="alpha.example", path="/undeclared")
        )
    ).status == 501
    assert recorder.requests == []
    assert recorder.writes == []


@pytest.mark.asyncio
async def test_bound_capabilities_and_virtual_write():
    runtime, recorder = make_runtime()
    response = await runtime.dispatch(
        ProviderRequest(method="POST", host="alpha.example", path="/write", body=b"payload")
    )
    assert response.status == 201
    assert recorder.writes == [("last_write", b"payload")]
    assert recorder.requests == []
    bound = runtime._contexts["alpha"].upstream
    with pytest.raises(ValueError, match="outside bound"):
        await bound.request(ProviderRequest(method="GET", host="beta.example", path="/read"))
    blocked = await runtime.dispatch(
        ProviderRequest(method="POST", host="alpha.example", path="/bad-write")
    )
    assert blocked.status == 502
    assert recorder.requests == []


def test_task_binding_and_deep_immutability():
    runtime, _ = make_runtime()
    with pytest.raises(TypeError):
        runtime.task.task_payload["nested"]["links"] = ("changed",)
    with pytest.raises(AttributeError):
        runtime.task.task_payload["nested"]["links"].append("changed")
    with pytest.raises(ValueError, match="does not match"):
        Runtime(
            EvaluationConfig("other", "wrong", datetime.now(UTC), "bundle"),
            runtime.task,
            runtime.registry,
            Capabilities(*(RecordingCapabilities() for _ in range(9))),
        )


def test_registry_rejects_ambiguous_hosts_and_bad_versions(tmp_path):
    with pytest.raises(ValueError, match="duplicate service"):
        ServiceRegistry([FIXTURES / "alpha.yaml", FIXTURES / "alpha.yaml"])
    manifest = (FIXTURES / "alpha.yaml").read_text().replace("sdk_version: v0", "sdk_version: v1")
    path = tmp_path / "service.yaml"
    path.write_text(manifest)
    with pytest.raises(ValueError, match="unsupported SDK version"):
        ServiceRegistry([path])


def test_trusted_health_exposes_versions_and_services():
    runtime, _ = make_runtime()
    client = TestClient(create_app(runtime))
    health = client.get("/health").json()
    assert health["status"] == "ready"
    assert health["protocol_version"] == 1
    assert {item["name"] for item in health["services"]} == {"alpha", "beta"}


def test_trusted_launch_loads_registration_and_service_bundle(tmp_path):
    launch = {
        "evaluation_id": "evaluation-1",
        "task_id": "task-1",
        "cutoff_at": "2026-01-01T00:00:00+00:00",
        "bundle_version": "bundle-1",
        "registered_task": {
            "task_id": "task-1",
            "task_payload": {"prompt": "registered input"},
            "registration_payload": {"source": "line_run"},
            "source_links": ["https://alpha.example/read"],
        },
        "service_manifests": [
            str(FIXTURES.resolve() / "alpha.yaml"),
            str(FIXTURES.resolve() / "beta.yaml"),
        ],
    }
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps(launch))
    runtime = load_runtime(path)
    assert runtime.task.task_payload["prompt"] == "registered input"
    assert set(runtime.registry.hosts) == {"alpha.example", "beta.example"}
    launch["registered_task"]["task_id"] = "other-task"
    path.write_text(json.dumps(launch))
    with pytest.raises(ValueError, match="does not match"):
        load_runtime(path)


@pytest.mark.asyncio
async def test_source_id_is_bound_per_concurrent_request():
    class SourceRecorder(RecordingCapabilities):
        async def request(self, request, *, source_request_id=None):
            await asyncio.sleep(0)
            self.requests.append((request, source_request_id))
            return ProviderResponse(status=207, body=request.body)

    runtime, _ = make_runtime()
    source = SourceRecorder()
    runtime._contexts["alpha"] = replace(
        runtime._contexts["alpha"], upstream=BoundUpstream(source, ("alpha.example",))
    )
    requests = [
        ProviderRequest(method="GET", host="alpha.example", path="/read", body=str(i).encode())
        for i in range(2)
    ]
    await asyncio.gather(
        *(
            runtime.dispatch(request, source_request_id=f"source-{i}")
            for i, request in enumerate(requests)
        )
    )
    assert {(request.body, source_id) for request, source_id in source.requests} == {
        (b"0", "source-0"),
        (b"1", "source-1"),
    }


def test_unavailable_capabilities_do_not_report_ready(tmp_path):
    launch = {
        "evaluation_id": "e",
        "task_id": "t",
        "cutoff_at": "2026-01-01T00:00:00+00:00",
        "bundle_version": "v",
        "registered_task": {
            "task_id": "t",
            "task_payload": {},
            "registration_payload": {},
            "source_links": [],
        },
        "service_manifests": [str(FIXTURES.resolve() / "alpha.yaml")],
    }
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(launch))
    assert load_runtime(path).health()["status"] == "unhealthy"


def test_missing_required_capability_does_not_report_ready():
    runtime, recorder = make_runtime()
    caps = replace(Capabilities(*(recorder for _ in range(9))), authorization=None)
    assert (
        Runtime(runtime.config, runtime.task, runtime.registry, caps).health()["status"]
        == "unhealthy"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("evaluation_id", ""),
        ("task_id", 7),
        ("cutoff_at", "2026-01-01T00:00:00"),
        ("service_manifests", "tests/fixtures/alpha.yaml"),
        ("service_manifests", ["relative.yaml"]),
        ("source_links", "https://alpha.example"),
    ],
)
def test_trusted_launch_rejects_invalid_fields(tmp_path, field, value):
    launch = {
        "evaluation_id": "e",
        "task_id": "t",
        "cutoff_at": "2026-01-01T00:00:00+00:00",
        "bundle_version": "v",
        "registered_task": {
            "task_id": "t",
            "task_payload": {},
            "registration_payload": {},
            "source_links": [],
        },
        "service_manifests": [str(FIXTURES.resolve() / "alpha.yaml")],
    }
    (launch["registered_task"] if field == "source_links" else launch)[field] = value
    path = tmp_path / "launch.json"
    path.write_text(json.dumps(launch))
    with pytest.raises(ValueError):
        load_runtime(path)
