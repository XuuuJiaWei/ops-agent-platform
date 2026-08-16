"""Runtime status composition."""

from __future__ import annotations

from typing import Any

from ops_pilot.agent.runtime import AgentRuntime
from ops_pilot.observability.langfuse import describe_tracing
from ops_pilot.runtime.spec import RuntimeSpec


def build_runtime_status(runtime: AgentRuntime) -> dict[str, Any]:
    return {
        "ok": True,
        "environment": runtime.spec.observability.environment,
        "assistant_id": runtime.spec.assistant_id,
        "model": {
            "provider": runtime.spec.model.provider,
            "name": runtime.spec.model.name,
        },
        "mcp": runtime.mcp.status.as_dict(),
        "skills": list(runtime.skills),
        "sandbox": _runtime_sandbox_status(runtime),
        "logging": _logging_status(runtime.spec),
        "tracing": runtime.tracing.as_dict(),
        "tools": [getattr(tool, "name", repr(tool)) for tool in runtime.tools],
    }


def health_snapshot(spec: RuntimeSpec) -> dict[str, Any]:
    tracing = describe_tracing(spec.observability)
    return {
        "status": "ok",
        "environment": spec.observability.environment,
        "assistant_id": spec.assistant_id,
        "model": spec.model.name,
        "sandbox": _spec_sandbox_status(spec),
        "logging": _logging_status(spec),
        "tracing": tracing.as_dict(),
    }


def _runtime_sandbox_status(runtime: AgentRuntime) -> dict[str, Any]:
    sandbox = getattr(runtime, "sandbox", None)
    if sandbox is None:
        return _spec_sandbox_status(runtime.spec)
    return sandbox.as_dict()


def _logging_status(runtime: RuntimeSpec) -> dict[str, Any]:
    agent_logging = runtime.observability.logging
    return {
        "enabled": agent_logging.enabled,
        "level": agent_logging.level,
        "payloads": agent_logging.payloads,
        "max_preview_chars": agent_logging.max_preview_chars,
    }


def _spec_sandbox_status(runtime: RuntimeSpec) -> dict[str, Any]:
    return {
        "enabled": runtime.sandbox.enabled,
        "mode": "opensandbox" if runtime.sandbox.enabled else "state",
        "domain": runtime.sandbox.domain,
        "protocol": runtime.sandbox.protocol,
        "image": runtime.sandbox.image,
        "use_server_proxy": runtime.sandbox.use_server_proxy,
        "api_key_configured": bool(runtime.sandbox.api_key),
        "allocation_scope": runtime.sandbox.scope,
        "workspace_path": runtime.sandbox.workspace_path,
        "max_active": runtime.sandbox.max_active,
    }
