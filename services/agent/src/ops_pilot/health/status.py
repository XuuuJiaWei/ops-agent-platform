"""Runtime status composition."""

from __future__ import annotations

from typing import Any

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.config import Settings
from ops_pilot.observability.langfuse import create_callback_handler


def build_runtime_status(runtime: AgentRuntime) -> dict[str, Any]:
    return {
        "ok": True,
        "environment": runtime.settings.app_env,
        "assistant_id": runtime.settings.assistant_id,
        "model": {
            "provider": "sap-ai-core",
            "name": runtime.settings.sap_model_name,
        },
        "protocols": {
            "chat_base_path": runtime.settings.chat_base_path,
            "a2a_base_path": runtime.settings.a2a_base_path,
            "a2a_task_store": runtime.settings.a2a_task_store,
        },
        "mcp": runtime.mcp.status.as_dict(),
        "skills": list(runtime.skills),
        "tracing": runtime.tracing.as_dict(),
        "tools": [getattr(tool, "name", repr(tool)) for tool in runtime.tools],
    }


def health_snapshot(settings: Settings) -> dict[str, Any]:
    tracing = create_callback_handler(settings)
    return {
        "status": "ok",
        "environment": settings.app_env,
        "assistant_id": settings.assistant_id,
        "model": settings.sap_model_name,
        "chat_base_path": settings.chat_base_path,
        "a2a_base_path": settings.a2a_base_path,
        "tracing": tracing.as_dict(),
    }

