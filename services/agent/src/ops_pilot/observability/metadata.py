"""Trace metadata builders shared by /chat and /a2a adapters."""

from __future__ import annotations

from typing import Any

from ops_pilot.config.settings import Settings


def build_trace_metadata(
    settings: Settings,
    *,
    protocol: str,
    thread_id: str | None = None,
    run_id: str | None = None,
    a2a_task_id: str | None = None,
    a2a_context_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session_id = thread_id or a2a_context_id
    metadata: dict[str, Any] = {
        "environment": settings.app_env,
        "assistant_id": settings.assistant_id,
        "protocol": protocol,
        "model_provider": settings.model_provider,
        "model_name": settings.model_name,
        "sap_model_name": settings.sap_model_name,
        "langfuse_trace_name": _trace_name(protocol),
        "langfuse_tags": _trace_tags(settings, protocol),
    }
    if session_id:
        metadata["langfuse_session_id"] = session_id[:200]
    if thread_id:
        metadata["thread_id"] = thread_id
    if run_id:
        metadata["run_id"] = run_id
    if a2a_task_id:
        metadata["a2a_task_id"] = a2a_task_id
    if a2a_context_id:
        metadata["a2a_context_id"] = a2a_context_id
    if extra:
        metadata.update(extra)
    user_id = metadata.get("user_id") or metadata.get("userId")
    if isinstance(user_id, str) and user_id.strip():
        metadata.setdefault("langfuse_user_id", user_id.strip())
    return metadata


def build_runnable_config(
    settings: Settings,
    *,
    callbacks: tuple[Any, ...] = (),
    protocol: str,
    recursion_limit: int | None = None,
    thread_id: str | None = None,
    run_id: str | None = None,
    a2a_task_id: str | None = None,
    a2a_context_id: str | None = None,
    configurable: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = build_trace_metadata(
        settings,
        protocol=protocol,
        thread_id=thread_id,
        run_id=run_id,
        a2a_task_id=a2a_task_id,
        a2a_context_id=a2a_context_id,
        extra=extra_metadata,
    )
    config: dict[str, Any] = {
        "metadata": metadata,
        "run_name": metadata["langfuse_trace_name"],
        "tags": metadata["langfuse_tags"],
    }
    if callbacks:
        config["callbacks"] = list(callbacks)
    if recursion_limit is not None:
        config["recursion_limit"] = recursion_limit
    effective_configurable = dict(configurable or {})
    if thread_id:
        effective_configurable.setdefault("thread_id", thread_id)
    if run_id:
        effective_configurable.setdefault("run_id", run_id)
    if a2a_task_id:
        effective_configurable.setdefault("a2a_task_id", a2a_task_id)
    if a2a_context_id:
        effective_configurable.setdefault("a2a_context_id", a2a_context_id)
    if effective_configurable:
        config["configurable"] = effective_configurable
    return config


def _trace_name(protocol: str) -> str:
    names = {
        "a2a": "handle-a2a-task",
        "copilotkit-agui": "handle-copilotkit-run",
        "eval": "run-eval-case",
        "smoke": "run-smoke-check",
    }
    return names.get(protocol, "run-agent")


def _trace_tags(settings: Settings, protocol: str) -> list[str]:
    return ["ops_pilot", protocol, settings.app_env]
