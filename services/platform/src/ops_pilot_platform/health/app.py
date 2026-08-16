"""Lightweight health routes for local protocol servers."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.runtime.spec import RuntimeSpec

from ops_pilot_platform.api.errors import register_exception_handlers
from ops_pilot_platform.health.status import build_runtime_status, health_snapshot


def create_health_router(spec: RuntimeSpec) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, object]:
        return health_snapshot(spec)

    return router


def create_health_app(spec: RuntimeSpec, runtime: AgentRuntime | None = None) -> FastAPI:
    app = FastAPI(title="ops_pilot Health", version="0.1.0")
    register_exception_handlers(app)
    app.include_router(create_health_router(spec))

    if runtime is not None:

        @app.get("/status")
        async def status() -> dict[str, object]:
            return build_runtime_status(runtime)

    return app


__all__ = ["build_runtime_status", "create_health_app", "create_health_router", "health_snapshot"]
