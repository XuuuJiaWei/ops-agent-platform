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
            "provider": runtime.settings.model_provider,
            "name": runtime.settings.model_name,
        },
        "protocols": {
            "chat_base_path": runtime.settings.chat_base_path,
            "a2a_base_path": runtime.settings.a2a_base_path,
        },
        "mcp": runtime.mcp.status.as_dict(),
        "skills": list(runtime.skills),
        "sandbox": _runtime_sandbox_status(runtime),
        "tracing": runtime.tracing.as_dict(),
        "tools": [getattr(tool, "name", repr(tool)) for tool in runtime.tools],
    }


def health_snapshot(settings: Settings) -> dict[str, Any]:
    tracing = create_callback_handler(settings)
    return {
        "status": "ok",
        "environment": settings.app_env,
        "assistant_id": settings.assistant_id,
        "model": settings.model_name,
        "chat_base_path": settings.chat_base_path,
        "a2a_base_path": settings.a2a_base_path,
        "sandbox": _settings_sandbox_status(settings),
        "tracing": tracing.as_dict(),
    }


def _runtime_sandbox_status(runtime: AgentRuntime) -> dict[str, Any]:
    sandbox = getattr(runtime, "sandbox", None)
    if sandbox is None:
        return _settings_sandbox_status(runtime.settings)
    return sandbox.as_dict()


def _settings_sandbox_status(settings: Settings) -> dict[str, Any]:
    return {
        "enabled": settings.open_sandbox_enabled,
        "mode": "opensandbox" if settings.open_sandbox_enabled else "state",
        "domain": settings.open_sandbox_domain,
        "protocol": settings.open_sandbox_protocol,
        "image": settings.open_sandbox_image,
        "use_server_proxy": settings.open_sandbox_use_server_proxy,
        "api_key_configured": bool(settings.open_sandbox_api_key),
        "allocation_scope": settings.open_sandbox_scope,
        "workspace_path": settings.open_sandbox_workspace_path,
        "max_active": settings.open_sandbox_max_active,
    }
