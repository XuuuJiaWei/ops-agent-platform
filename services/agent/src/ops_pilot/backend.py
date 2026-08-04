"""Unified FastAPI backend exposing all ops_pilot protocol surfaces."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from ops_pilot.a2a.agent_card import build_agent_card
from ops_pilot.a2a.executor import create_executor
from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.agent.manager import AgentRuntimeManager
from ops_pilot.agui.resilient import create_resilient_agui_agent
from ops_pilot.api.errors import register_exception_handlers
from ops_pilot.config.settings import Settings, get_settings
from ops_pilot.health.app import router as health_router
from ops_pilot.tunnel.app import router as tunnel_router
from ops_pilot.tunnel.local_bridge import LocalBridgeManager
from ops_pilot.tunnel.manager import manager as tunnel_manager


async def create_backend_app(
    settings: Settings | None = None,
    runtime: Any | None = None,
) -> FastAPI:
    """Create the standard backend with AG-UI, A2A, health, and tunnel routes."""

    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore as A2ATaskStore
    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from copilotkit import LangGraphAGUIAgent
    from copilotkit.langgraph import copilotkit_customize_config

    resolved_settings = settings or get_settings()
    resolved_runtime = runtime or await create_agent_runtime_async(resolved_settings)
    runtime_manager = AgentRuntimeManager(settings=resolved_settings, runtime=resolved_runtime)
    local_bridge_manager = LocalBridgeManager(tunnel_manager)

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        # Read the manager from state at shutdown so a test-swapped fake is honored.
        runtime_manager = getattr(app.state, "agent_runtime_manager", None)
        runtime_shutdown = getattr(runtime_manager, "shutdown", None)
        if runtime_shutdown is not None:
            await runtime_shutdown()
        manager = getattr(app.state, "local_bridge_manager", None)
        bridge_shutdown = getattr(manager, "shutdown", None)
        if bridge_shutdown is not None:
            await bridge_shutdown()

    app = FastAPI(title="ops_pilot Backend", version="0.1.0", lifespan=_lifespan)
    register_exception_handlers(app)
    app.state.agent_runtime_manager = runtime_manager
    app.state.local_bridge_manager = local_bridge_manager

    agui_config = copilotkit_customize_config(
        emit_tool_calls=True,
        emit_messages=True,
    )
    agui_config.update(
        resolved_runtime.runnable_config(
            protocol="copilotkit-agui",
            extra_metadata={"entrypoint": "backend"},
        )
    )
    add_langgraph_fastapi_endpoint(
        app=app,
        agent=create_resilient_agui_agent(
            LangGraphAGUIAgent,
            name=resolved_settings.assistant_id,
            description="ops_pilot DeepAgent exposed through AG-UI for CopilotKit.",
            graph=runtime_manager.graph_proxy(),
            config=agui_config,
        ),
        path=resolved_settings.chat_base_path.rstrip("/") or "/",
    )

    agent_card = build_agent_card(resolved_settings)
    request_handler = DefaultRequestHandler(
        agent_executor=create_executor(runtime_manager.runtime_proxy(), resolved_settings),
        task_store=A2ATaskStore(),
        agent_card=agent_card,
    )
    base_path = resolved_settings.a2a_base_path.rstrip("/") or "/a2a"
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
    app.include_router(health_router)
    app.include_router(tunnel_router)
    return app
