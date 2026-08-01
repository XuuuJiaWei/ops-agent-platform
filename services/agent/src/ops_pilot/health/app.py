"""Lightweight health routes for local protocol servers."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.config.settings import get_settings
from ops_pilot.health.status import build_runtime_status, health_snapshot

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    return health_snapshot(get_settings())


def create_health_app(runtime: AgentRuntime | None = None) -> FastAPI:
    app = FastAPI(title="ops_pilot Health", version="0.1.0")
    app.include_router(router)

    if runtime is not None:

        @app.get("/status")
        async def status() -> dict[str, object]:
            return build_runtime_status(runtime)

    return app


__all__ = ["build_runtime_status", "create_health_app", "health_snapshot", "router"]
