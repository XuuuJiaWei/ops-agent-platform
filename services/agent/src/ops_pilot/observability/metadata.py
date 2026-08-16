"""Host-neutral LangChain trace metadata builders."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from ops_pilot.runtime.spec import RuntimeSpec


def build_trace_metadata(
    runtime: RuntimeSpec,
    *,
    protocol: str,
    thread_id: str | None = None,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "assistant_id": runtime.assistant_id,
        "protocol": protocol,
        "model_provider": runtime.model.provider,
        "model_name": runtime.model.name,
        "langfuse_trace_name": _trace_name(protocol),
        "langfuse_tags": _trace_tags(protocol),
    }
    if thread_id:
        metadata["thread_id"] = thread_id
        metadata["langfuse_session_id"] = thread_id[:200]
    if run_id:
        metadata["run_id"] = run_id
    if extra:
        metadata.update(extra)
    user_id = metadata.get("user_id") or metadata.get("userId")
    if isinstance(user_id, str) and user_id.strip():
        metadata.setdefault("langfuse_user_id", user_id.strip())
    return metadata


def build_runnable_config(
    runtime: RuntimeSpec,
    *,
    callbacks: tuple[Any, ...] = (),
    protocol: str,
    thread_id: str | None = None,
    run_id: str | None = None,
    configurable: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> RunnableConfig:
    metadata = build_trace_metadata(
        runtime,
        protocol=protocol,
        thread_id=thread_id,
        run_id=run_id,
        extra=extra_metadata,
    )
    config: RunnableConfig = {
        "metadata": metadata,
        "run_name": metadata["langfuse_trace_name"],
        "tags": metadata["langfuse_tags"],
        # LangGraph requires recursion_limit at the top level. Keeping it here
        # makes every host use the same guardrail.
        "recursion_limit": runtime.reliability.recursion_limit,
    }
    if callbacks:
        config["callbacks"] = list(callbacks)
    effective_configurable = dict(configurable or {})
    if thread_id:
        effective_configurable.setdefault("thread_id", thread_id)
    if run_id:
        effective_configurable.setdefault("run_id", run_id)
    if effective_configurable:
        config["configurable"] = effective_configurable
    return config


def _trace_name(protocol: str) -> str:
    normalized = "-".join(part for part in protocol.lower().replace(":", "-").split("-") if part)
    return f"run-{normalized or 'agent'}"


def build_model_metadata(runtime: RuntimeSpec, model: Any) -> dict[str, Any]:
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
        runtime.model.name,
    )
    return {
        # Langfuse's LangChain integration reads this standard metadata key to
        # populate generation.model when a provider wrapper cannot serialize it.
        "ls_model_name": request_model,
        "model_request_name": request_model,
        "model_context_window_tokens": profile.get("max_input_tokens"),
        "model_max_output_tokens": profile.get("max_output_tokens"),
        "model_configured_max_output_tokens": runtime.model.max_tokens,
        "model_request_timeout_seconds": runtime.model.request_timeout_seconds,
        "model_reasoning_supported": bool(profile.get("reasoning_output", False)),
        "model_reasoning_mode": runtime.model.reasoning_mode,
        "model_reasoning_effort": runtime.model.reasoning_effort,
        "model_prompt_cache_strategy": "deepagents_provider_middleware",
    }


def _trace_tags(protocol: str) -> list[str]:
    return ["ops_pilot", protocol]
