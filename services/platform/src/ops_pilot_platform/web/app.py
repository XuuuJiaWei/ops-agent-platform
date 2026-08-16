"""Web protocol adapter over an explicitly composed agent runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from ops_pilot.agent.runtime import AgentRuntime, agent_runtime
from ops_pilot.runtime.spec import RuntimeSpec

from ops_pilot_platform.a2a.agent_card import build_agent_card
from ops_pilot_platform.a2a.executor import create_executor
from ops_pilot_platform.a2a.task_store import create_task_store
from ops_pilot_platform.agui.resilient import create_resilient_agui_agent
from ops_pilot_platform.api.errors import register_exception_handlers
from ops_pilot_platform.entrypoints.web import WebApplicationSpec
from ops_pilot_platform.health.app import create_health_router
from ops_pilot_platform.health.status import build_runtime_status
from ops_pilot_platform.web.spaces.api import create_spaces_router
from ops_pilot_platform.web.spaces.factory import create_space_repository
from ops_pilot_platform.web.spaces.repository import SpaceRepository
from ops_pilot_platform.web.spaces.resolver import CardResolver

logger = logging.getLogger("uvicorn.error")
RuntimeContextFactory = Callable[[RuntimeSpec], AbstractAsyncContextManager[AgentRuntime]]


def create_backend_app(
    application: WebApplicationSpec,
    *,
    runtime_context: RuntimeContextFactory = agent_runtime,
) -> FastAPI:
    """Expose exactly the protocol surfaces selected by the web application."""

    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from copilotkit import LangGraphAGUIAgent
    from copilotkit.langgraph import copilotkit_customize_config

    runtime: AgentRuntime | None = None
    spaces_repository: SpaceRepository | None = None

    def get_runtime() -> AgentRuntime:
        if runtime is None:
            raise RuntimeError("Agent runtime is not initialized yet.")
        return runtime

    def get_spaces_repository() -> SpaceRepository:
        if spaces_repository is None:
            raise RuntimeError("Spaces repository is not initialized yet.")
        return spaces_repository

    def mount_protocol_routes(app: FastAPI, active_runtime: AgentRuntime, task_store: Any | None) -> None:
        agui_config = copilotkit_customize_config(emit_tool_calls=True, emit_messages=True)
        agui_config.update(
            active_runtime.runnable_config(
                protocol="copilotkit-agui",
                extra_metadata={"entrypoint": application.runtime.entrypoint},
            )
        )
        add_langgraph_fastapi_endpoint(
            app=app,
            agent=create_resilient_agui_agent(
                LangGraphAGUIAgent,
                name=application.runtime.assistant_id,
                description="OpsPilot DeepAgent exposed through AG-UI for the web application.",
                graph=active_runtime.graph,
                config=agui_config,
                run_controller=active_runtime.run_controller,
            ),
            path=application.chat_base_path.rstrip("/") or "/",
        )

        if not application.enable_a2a or task_store is None:
            return
        agent_card = build_agent_card(
            assistant_id=application.runtime.assistant_id,
            host=application.host,
            port=application.port,
            a2a_base_path=application.a2a_base_path,
        )
        request_handler = DefaultRequestHandler(
            agent_executor=create_executor(active_runtime),
            task_store=task_store,
            agent_card=agent_card,
        )
        base_path = application.a2a_base_path.rstrip("/") or "/a2a"
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
    async def lifespan(app: FastAPI):
        nonlocal runtime, spaces_repository
        try:
            async with AsyncExitStack() as stack:
                active_runtime = await stack.enter_async_context(runtime_context(application.runtime))
                runtime = active_runtime
                if application.enable_spaces:
                    spaces_repository, spaces_closer = await create_space_repository(
                        application.runtime.persistence,
                        namespace=application.runtime.assistant_id,
                    )
                    if spaces_closer is not None:
                        stack.push_async_callback(spaces_closer)

                mcp_status = active_runtime.mcp.status
                server_summary = ", ".join(
                    f"{server.name}={'ok' if server.ok else 'failed'}({server.tool_count})"
                    for server in mcp_status.servers
                )
                logger.info("MCP runtime ready: %s; %d tools", server_summary or "no servers", mcp_status.tool_count)

                task_store = None
                if application.enable_a2a:
                    task_store, task_store_closer = await create_task_store(application.runtime.persistence)
                    if task_store_closer is not None:
                        stack.push_async_callback(task_store_closer)
                first_protocol_route = len(app.router.routes)
                stack.callback(_remove_routes, app, first_protocol_route)
                mount_protocol_routes(app, active_runtime, task_store)

                if application.enable_spaces:
                    resolver = CardResolver(
                        repository=get_spaces_repository(),
                        tools_by_name={tool.name: tool for tool in active_runtime.mcp.tools},
                        hitl_tools=frozenset(active_runtime.mcp.hitl_tools),
                        poll_interval_s=30,
                    )
                    resolver_task = asyncio.create_task(resolver.run_forever())
                    stack.push_async_callback(_cancel_task, resolver_task)
                yield
        finally:
            spaces_repository = None
            runtime = None

    app = FastAPI(title="ops_pilot Web Backend", version="0.1.0", lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(create_health_router(application.runtime))
    if application.enable_spaces:
        app.include_router(create_spaces_router(get_spaces_repository))

    @app.get("/status")
    async def runtime_status() -> dict[str, Any]:
        return build_runtime_status(get_runtime())

    return app


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _remove_routes(app: FastAPI, start: int) -> None:
    del app.router.routes[start:]
    app.openapi_schema = None
