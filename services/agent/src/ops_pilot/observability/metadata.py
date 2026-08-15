"""Trace metadata builders shared by /chat and /a2a adapters."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

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
        "assistant_id": settings.assistant_id,
        "protocol": protocol,
        "model_provider": settings.model_provider,
        "model_name": settings.model_name,
        "langfuse_trace_name": _trace_name(protocol),
        "langfuse_tags": _trace_tags(protocol),
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
    thread_id: str | None = None,
    run_id: str | None = None,
    a2a_task_id: str | None = None,
    a2a_context_id: str | None = None,
    configurable: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> RunnableConfig:
    metadata = build_trace_metadata(
        settings,
        protocol=protocol,
        thread_id=thread_id,
        run_id=run_id,
        a2a_task_id=a2a_task_id,
        a2a_context_id=a2a_context_id,
        extra=extra_metadata,
    )
    config: RunnableConfig = {
        "metadata": metadata,
        "run_name": metadata["langfuse_trace_name"],
        "tags": metadata["langfuse_tags"],
    }
    if callbacks:
        config["callbacks"] = list(callbacks)
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


def build_model_metadata(settings: Settings, model: Any) -> dict[str, Any]:
    """Describe effective model capacity and policy without estimating usage."""

    profile = getattr(model, "profile", {})
    if not isinstance(profile, dict):
        profile = {}
    request_model = next(
        (
            value
            for name in ("model_id", "model_name", "model")
            if isinstance((value := getattr(model, name, None)), str) and value
        ),
        settings.model_name,
    )
    return {
        # Langfuse's LangChain integration reads this standard metadata key to
        # populate generation.model when a provider wrapper cannot serialize it.
        "ls_model_name": request_model,
        "model_request_name": request_model,
        "model_context_window_tokens": profile.get("max_input_tokens"),
        "model_max_output_tokens": profile.get("max_output_tokens"),
        "model_configured_max_output_tokens": settings.model_max_tokens,
        "model_request_timeout_seconds": settings.model_request_timeout_seconds,
        "model_reasoning_supported": bool(profile.get("reasoning_output", False)),
        "model_reasoning_mode": settings.model_reasoning_mode,
        "model_reasoning_effort": settings.model_reasoning_effort,
        "model_prompt_cache_strategy": "deepagents_provider_middleware",
    }


def _trace_tags(protocol: str) -> list[str]:
    return ["ops_pilot", protocol]
