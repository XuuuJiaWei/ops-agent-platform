"""Unified FastAPI backend exposing all ops_pilot protocol surfaces."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from ops_pilot.a2a.agent_card import build_agent_card
from ops_pilot.a2a.executor import create_executor
from ops_pilot.a2a.task_store import create_task_store
from ops_pilot.agent.extensions import RuntimeExtensionFactory
from ops_pilot.agent.manager import AgentRuntimeManager
from ops_pilot.agent.runtime import build_agent_runtime
from ops_pilot.agui.resilient import create_resilient_agui_agent
from ops_pilot.agui.runtime import create_copilotkit_runtime_extension
from ops_pilot.api.errors import register_exception_handlers
from ops_pilot.config.settings import Settings, get_settings
from ops_pilot.health.app import router as health_router
from ops_pilot.spaces import SpacesRuntimeExtension, create_spaces_runtime_extension
from ops_pilot.spaces.api import create_spaces_router
from ops_pilot.spaces.resolver import CardResolver

logger = logging.getLogger("uvicorn.error")


def create_backend_app(
    settings: Settings | None = None,
    runtime: Any | None = None,
    runtime_extensions: tuple[RuntimeExtensionFactory, ...] = (
        create_spaces_runtime_extension,
        create_copilotkit_runtime_extension,
    ),
) -> FastAPI:
    """Create the standard backend with AG-UI, A2A, and health routes."""

    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from copilotkit import LangGraphAGUIAgent
    from copilotkit.langgraph import copilotkit_customize_config

    resolved_settings = settings or get_settings()
    runtime_manager = AgentRuntimeManager(
        settings=resolved_settings,
        runtime=runtime,
        extensions=runtime_extensions if runtime is None else (),
    )

    def _mount_protocol_routes(app: FastAPI, task_store: Any) -> None:
        agui_config = copilotkit_customize_config(
            emit_tool_calls=True,
            emit_messages=True,
        )
        agui_config.update(
            runtime_manager.current.runnable_config(
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
                run_controller=runtime_manager.runtime_proxy(),
            ),
            path=resolved_settings.chat_base_path.rstrip("/") or "/",
        )

        agent_card = build_agent_card(resolved_settings)
        request_handler = DefaultRequestHandler(
            agent_executor=create_executor(runtime_manager.runtime_proxy(), resolved_settings),
            task_store=task_store,
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

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        task_store_closer = None
        try:
            if runtime is None:
                runtime_manager.attach_runtime(
                    await build_agent_runtime(resolved_settings, extensions=runtime_extensions)
                )
            mcp_status = runtime_manager.current.mcp.status
            server_summary = ", ".join(
                f"{server.name}={'ok' if server.ok else 'failed'}({server.tool_count})" for server in mcp_status.servers
            )
            logger.info("MCP runtime ready: %s; %d tools", server_summary or "no servers", mcp_status.tool_count)
            if not getattr(app.state, "protocol_routes_mounted", False):
                task_store, task_store_closer = await create_task_store(resolved_settings)
                app.state.a2a_task_store_closer = task_store_closer
                _mount_protocol_routes(app, task_store)
                app.state.protocol_routes_mounted = True
            if resolved_settings.spaces_resolver_enabled and not getattr(app.state, "resolver_task", None):
                rt = runtime_manager.current
                resolver = CardResolver(
                    repository=rt.extension(SpacesRuntimeExtension).repository,
                    tools_by_name={tool.name: tool for tool in rt.mcp.tools},
                    hitl_tools=frozenset(rt.mcp.hitl_tools),
                    poll_interval_s=resolved_settings.spaces_resolver_poll_seconds,
                )
                app.state.resolver_task = asyncio.create_task(resolver.run_forever())
                logger.info("Card resolver started (poll=%ss)", resolved_settings.spaces_resolver_poll_seconds)
            yield
        finally:
            resolver_task = getattr(app.state, "resolver_task", None)
            if resolver_task is not None:
                resolver_task.cancel()
                try:
                    await resolver_task
                except asyncio.CancelledError:
                    pass
                app.state.resolver_task = None
            # Read owners from state at shutdown so test-swapped fakes are honored.
            store_closer = getattr(app.state, "a2a_task_store_closer", None)
            if store_closer is not None:
                await store_closer()
            runtime_owner = getattr(app.state, "agent_runtime_manager", None)
            runtime_shutdown = getattr(runtime_owner, "shutdown", None)
            if runtime_shutdown is not None:
                await runtime_shutdown()

    app = FastAPI(title="ops_pilot Backend", version="0.1.0", lifespan=_lifespan)
    register_exception_handlers(app)
    app.state.agent_runtime_manager = runtime_manager
    app.include_router(health_router)
    app.include_router(
        create_spaces_router(lambda: runtime_manager.current.extension(SpacesRuntimeExtension).repository)
    )

    @app.get("/status")
    async def runtime_status() -> dict[str, Any]:
        return runtime_manager.status().as_dict()

    return app
