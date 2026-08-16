"""SAP Generative AI Hub model factory."""

from __future__ import annotations

import warnings
from typing import Any

from ops_pilot.runtime.spec import ModelSpec


class SAPModelInitializationError(RuntimeError):
    """Raised when the configured SAP AI Core chat model cannot be created."""


def create_chat_model(spec: ModelSpec) -> Any:
    """Create a LangChain-compatible SAP chat model for DeepAgents."""

    primary_error: Exception | None = None
    try:
        model = _create_with_init_llm(spec)
        _assert_tool_calling_model(model)
        return model
    except Exception as exc:  # noqa: BLE001 - wrap with fallback context below.
        primary_error = exc

    try:
        model = _create_with_proxy_chat_openai(spec)
        _assert_tool_calling_model(model)
        return model
    except Exception as fallback_error:  # noqa: BLE001
        raise SAPModelInitializationError(
            "Unable to initialize SAP AI Core / Generative AI Hub chat model "
            f"'{spec.name}'. Primary init_llm error: {primary_error!r}. "
            f"Fallback ChatOpenAI error: {fallback_error!r}."
        ) from fallback_error


def _create_with_init_llm(spec: ModelSpec) -> Any:
    try:
        from gen_ai_hub.proxy import get_proxy_client
        from gen_ai_hub.proxy.langchain import init_llm
    except ImportError as exc:
        raise SAPModelInitializationError(
            "SAP SDK dependency is not installed. Run 'uv sync' in services/agent."
        ) from exc

    proxy_client = get_proxy_client("gen-ai-hub")
    if _is_bedrock_model(spec.name):
        return _create_bedrock_chat_model(spec, proxy_client)

    return init_llm(
        spec.name,
        proxy_client=proxy_client,
        **_generation_kwargs(spec),
    )


def _create_with_proxy_chat_openai(spec: ModelSpec) -> Any:
    try:
        from gen_ai_hub.proxy import get_proxy_client
        from gen_ai_hub.proxy.langchain import ChatOpenAI
    except ImportError as exc:
        raise SAPModelInitializationError(
            "SAP SDK fallback classes are not installed. Run 'uv sync' in services/agent."
        ) from exc

    proxy_client = get_proxy_client("gen-ai-hub")
    return ChatOpenAI(
        proxy_model_name=spec.name,
        proxy_client=proxy_client,
        **_generation_kwargs(spec),
    )


def _create_bedrock_chat_model(spec: ModelSpec, proxy_client: Any) -> Any:
    try:
        from botocore.config import Config as BotoConfig
        from gen_ai_hub.proxy.langchain.amazon import ChatBedrock
    except ImportError as exc:
        raise SAPModelInitializationError(
            "SAP SDK Bedrock LangChain integration is not installed. Run 'uv sync' in services/agent."
        ) from exc

    deployment = proxy_client.select_deployment(model_name=spec.name)
    # The SAP SDK's ChatBedrock intentionally moves `client_params` into
    # `model_kwargs` and emits a UserWarning about it on every construction.
    # It is expected here, so suppress that one warning to keep startup clean.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="WARNING! client_params is not default parameter.*",
            category=UserWarning,
        )
        return ChatBedrock(
            model_name=deployment.model_name,
            deployment_id=deployment.deployment_id,
            proxy_client=proxy_client,
            config=BotoConfig(
                read_timeout=spec.request_timeout_seconds,
                retries={"mode": "standard", "total_max_attempts": 1},
            ),
            # Langfuse records completion_start_time from LangChain's first
            # on_llm_new_token callback; non-streaming Bedrock calls cannot
            # provide a real TTFT measurement.
            streaming=True,
            model_kwargs=_generation_kwargs(spec),
        )


def _generation_kwargs(spec: ModelSpec) -> dict[str, Any]:
    kwargs: dict[str, Any] = {} if spec.reasoning_mode == "adaptive" else dict(_sampling_kwargs(spec))
    if spec.max_tokens is not None:
        kwargs["max_tokens"] = spec.max_tokens
    kwargs["thinking"] = {"type": spec.reasoning_mode}
    if spec.reasoning_mode == "adaptive":
        kwargs["output_config"] = {"effort": spec.reasoning_effort}
    return kwargs


def _sampling_kwargs(spec: ModelSpec) -> dict[str, float]:
    if spec.top_p is not None:
        return {"top_p": spec.top_p}
    return {"temperature": spec.temperature}


def _is_bedrock_model(model_name: str) -> bool:
    return model_name.startswith(("amazon", "anthropic"))


def _assert_tool_calling_model(model: Any) -> None:
    if not callable(getattr(model, "bind_tools", None)):
        raise SAPModelInitializationError(
            "SAP chat model was created but does not expose bind_tools(); "
            "DeepAgents tool-calling requires a LangChain chat model with tool support."
        )
