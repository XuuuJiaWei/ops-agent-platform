"""SAP Generative AI Hub model factory."""

from __future__ import annotations

from typing import Any

from ops_pilot.config.settings import Settings


class SAPModelInitializationError(RuntimeError):
    """Raised when the configured SAP AI Core chat model cannot be created."""


# Compatibility alias for earlier callers.
ModelInitializationError = SAPModelInitializationError


def create_chat_model(settings: Settings) -> Any:
    """Create a LangChain-compatible SAP chat model for DeepAgents."""

    primary_error: Exception | None = None
    try:
        model = _create_with_init_llm(settings)
        _assert_tool_calling_model(model)
        return model
    except Exception as exc:  # noqa: BLE001 - wrap with fallback context below.
        primary_error = exc

    try:
        model = _create_with_proxy_chat_openai(settings)
        _assert_tool_calling_model(model)
        return model
    except Exception as fallback_error:  # noqa: BLE001
        raise SAPModelInitializationError(
            "Unable to initialize SAP AI Core / Generative AI Hub chat model "
            f"'{settings.sap_model_name}'. Primary init_llm error: {primary_error!r}. "
            f"Fallback ChatOpenAI error: {fallback_error!r}."
        ) from fallback_error


def _create_with_init_llm(settings: Settings) -> Any:
    try:
        from gen_ai_hub.proxy import get_proxy_client
        from gen_ai_hub.proxy.langchain import init_llm
    except ImportError as exc:
        raise SAPModelInitializationError(
            "SAP SDK dependency is not installed. Run 'uv sync' in services/agent."
        ) from exc

    proxy_client = get_proxy_client("gen-ai-hub")
    if _is_bedrock_model(settings.sap_model_name):
        return _create_bedrock_chat_model(settings, proxy_client)

    return init_llm(
        settings.sap_model_name,
        proxy_client=proxy_client,
        **_generation_kwargs(settings),
    )


def _create_with_proxy_chat_openai(settings: Settings) -> Any:
    try:
        from gen_ai_hub.proxy import get_proxy_client
        from gen_ai_hub.proxy.langchain import ChatOpenAI
    except ImportError as exc:
        raise SAPModelInitializationError(
            "SAP SDK fallback classes are not installed. Run 'uv sync' in services/agent."
        ) from exc

    proxy_client = get_proxy_client("gen-ai-hub")
    return ChatOpenAI(
        proxy_model_name=settings.sap_model_name,
        proxy_client=proxy_client,
        **_generation_kwargs(settings),
    )


def _create_bedrock_chat_model(settings: Settings, proxy_client: Any) -> Any:
    try:
        from gen_ai_hub.proxy.langchain.amazon import ChatBedrock
    except ImportError as exc:
        raise SAPModelInitializationError(
            "SAP SDK Bedrock LangChain integration is not installed. "
            "Run 'uv sync' in services/agent."
        ) from exc

    deployment = proxy_client.select_deployment(model_name=settings.sap_model_name)
    return ChatBedrock(
        model_name=deployment.model_name,
        deployment_id=deployment.deployment_id,
        proxy_client=proxy_client,
        model_kwargs=_generation_kwargs(settings),
    )


def _generation_kwargs(settings: Settings) -> dict[str, float | int]:
    kwargs: dict[str, float | int] = dict(_sampling_kwargs(settings))
    if settings.sap_max_tokens is not None:
        kwargs["max_tokens"] = settings.sap_max_tokens
    return kwargs


def _sampling_kwargs(settings: Settings) -> dict[str, float]:
    if settings.sap_top_p is not None:
        return {"top_p": settings.sap_top_p}
    return {"temperature": settings.sap_temperature}


def _is_bedrock_model(model_name: str) -> bool:
    return model_name.startswith(("amazon", "anthropic"))


def _assert_tool_calling_model(model: Any) -> None:
    if not callable(getattr(model, "bind_tools", None)):
        raise SAPModelInitializationError(
            "SAP chat model was created but does not expose bind_tools(); "
            "DeepAgents tool-calling requires a LangChain chat model with tool support."
        )
