"""A2A HTTP app factory using the official Python SDK route helpers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.config.settings import Settings, get_settings
from ops_pilot.health.app import router as health_router

from .agent_card import build_agent_card
from .executor import create_executor


async def create_a2a_app(settings: Settings | None = None, runtime: Any | None = None) -> FastAPI:
    """Create the local A2A protocol server for the shared DeepAgent."""

    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore as A2ATaskStore

    resolved_settings = settings or get_settings()
    resolved_runtime = runtime or await create_agent_runtime_async(resolved_settings)
    agent_card = build_agent_card(resolved_settings)
    request_handler = DefaultRequestHandler(
        agent_executor=create_executor(resolved_runtime, resolved_settings),
        task_store=A2ATaskStore(),
        agent_card=agent_card,
    )

    base_path = resolved_settings.a2a_base_path.rstrip("/") or "/a2a"
    app = FastAPI(title="ops_pilot A2A", version="0.1.0")
    app.include_router(health_router)
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            agent_card=agent_card,
            card_url=f"{base_path}/.well-known/agent-card.json",
        ),
        jsonrpc_routes=create_jsonrpc_routes(
            request_handler=request_handler,
            rpc_url=f"{base_path}/jsonrpc",
            enable_v0_3_compat=True,
        ),
    )
    return app


def create_app() -> FastAPI:
    import asyncio

    return asyncio.run(create_a2a_app())
