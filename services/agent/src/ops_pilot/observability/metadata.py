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
    metadata: dict[str, Any] = {
        "environment": settings.app_env,
        "assistant_id": settings.assistant_id,
        "protocol": protocol,
        "sap_model_name": settings.sap_model_name,
    }
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
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "metadata": build_trace_metadata(
            settings,
            protocol=protocol,
            thread_id=thread_id,
            run_id=run_id,
            a2a_task_id=a2a_task_id,
            a2a_context_id=a2a_context_id,
            extra=extra_metadata,
        ),
    }
    if callbacks:
        config["callbacks"] = list(callbacks)
    effective_configurable = dict(configurable or {})
    if thread_id:
        effective_configurable.setdefault("thread_id", thread_id)
    if effective_configurable:
        config["configurable"] = effective_configurable
    return config
