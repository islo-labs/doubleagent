"""Trusted health and capability ASGI surface."""

from fastapi import FastAPI

from .core import Runtime


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict:
        return runtime.health()

    return app
