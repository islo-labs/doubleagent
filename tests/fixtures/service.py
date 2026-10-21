"""Deterministic test-only provider service."""

from doubleagent.sdk import Operation, OperationKind, ProviderRequest, ProviderResponse


class RecordingService:
    def classify(self, request: ProviderRequest) -> Operation:
        match request.path:
            case "/read":
                return Operation(name="read", kind=OperationKind.READ)
            case "/write":
                return Operation(name="write", kind=OperationKind.VIRTUAL_WRITE)
            case "/bad-write":
                return Operation(name="write", kind=OperationKind.VIRTUAL_WRITE)
            case "/undeclared":
                return Operation(name="not_in_manifest", kind=OperationKind.READ)
            case _:
                return Operation(name="unknown", kind=OperationKind.UNSUPPORTED)

    async def handle(self, operation, request, service_context):
        if operation.name == "read":
            task = service_context.task.task_payload["prompt"].encode()
            upstream = await service_context.upstream.request(request)
            return ProviderResponse(
                status=upstream.status,
                headers=request.headers,
                body=task + b"\x00" + upstream.body,
            )
        if request.path == "/bad-write":
            await service_context.upstream.request(request)
        await service_context.overlay.put("last_write", request.body)
        return ProviderResponse(status=201, body=request.body)
