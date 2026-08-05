"""FastAPI app exposing the shared DeepAgent through AG-UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from ops_pilot.agent.factory import create_agent_runtime_async
from ops_pilot.agui.resilient import create_resilient_agui_agent
from ops_pilot.api.errors import register_exception_handlers
from ops_pilot.config.settings import Settings, get_settings
from ops_pilot.health.app import router as health_router
from ops_pilot.tunnel.app import router as tunnel_router


async def create_agui_app(settings: Settings | None = None, runtime: Any | None = None) -> FastAPI:
    """Create the local AG-UI server consumed by CopilotKit Runtime."""

    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from copilotkit import LangGraphAGUIAgent
    from copilotkit.langgraph import copilotkit_customize_config

    resolved_settings = settings or get_settings()
    resolved_runtime = runtime or await create_agent_runtime_async(resolved_settings)

    @asynccontextmanager
    async def _lifespan(_: FastAPI):
        yield
        aclose = getattr(resolved_runtime, "aclose", None)
        if aclose is not None:
            await aclose()
            return
        close = getattr(resolved_runtime, "close", None)
        if close is not None:
            close()

    app = FastAPI(title="ops_pilot AG-UI", version="0.1.0", lifespan=_lifespan)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(tunnel_router)

    agui_config = copilotkit_customize_config(
        emit_tool_calls=True,
        emit_messages=True,
    )
    agui_config.update(
        resolved_runtime.runnable_config(
            protocol="copilotkit-agui",
            extra_metadata={"entrypoint": "agui"},
        )
    )

    add_langgraph_fastapi_endpoint(
        app=app,
        agent=create_resilient_agui_agent(
            LangGraphAGUIAgent,
            name=resolved_settings.assistant_id,
            description="ops_pilot DeepAgent exposed through AG-UI for CopilotKit.",
            graph=resolved_runtime.graph,
            config=agui_config,
        ),
        path=resolved_settings.chat_base_path.rstrip("/") or "/",
    )
    return app
