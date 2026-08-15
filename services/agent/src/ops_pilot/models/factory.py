"""Provider-agnostic chat model factory.

``model.provider`` in config selects the backend:

* ``sap`` (default) uses the SAP Generative AI Hub proxy (``sap_genai``).
* Any other provider (``deepseek``, ``openai``, ``anthropic``, ...) is built
  through LangChain's ``init_chat_model``. DeepSeek and other OpenAI-compatible
  endpoints work via ``model.base_url`` plus a ``MODEL_API_KEY`` secret.
"""

from __future__ import annotations

from typing import Any

from ops_pilot.config.settings import Settings
from ops_pilot.models.sap_genai import (
    SAPModelInitializationError,
    _assert_tool_calling_model,
    _sampling_kwargs,
)
from ops_pilot.models.sap_genai import create_chat_model as _create_sap_chat_model


class ModelInitializationError(RuntimeError):
    """Raised when the configured chat model cannot be created."""


def create_chat_model(settings: Settings) -> Any:
    """Create a LangChain tool-calling chat model for the configured provider."""

    if settings.model_provider == "sap":
        return _create_sap_chat_model(settings)
    return _create_langchain_chat_model(settings)


def _create_langchain_chat_model(settings: Settings) -> Any:
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:  # pragma: no cover - langchain is a hard dep.
        raise ModelInitializationError("langchain is not installed. Run 'uv sync' in services/agent.") from exc

    provider = _init_chat_model_provider(settings.model_provider)
    kwargs: dict[str, Any] = {
        "model": settings.model_name,
        "model_provider": provider,
        **_sampling_kwargs(settings),
    }
    if settings.model_max_tokens is not None:
        kwargs["max_tokens"] = settings.model_max_tokens
    if settings.model_base_url:
        kwargs["base_url"] = settings.model_base_url
    if settings.model_api_key:
        kwargs["api_key"] = settings.model_api_key

    try:
        model = init_chat_model(**kwargs)
    except Exception as exc:  # noqa: BLE001 - normalize provider/init errors.
        raise ModelInitializationError(
            f"Unable to initialize '{settings.model_provider}' chat model '{settings.model_name}': {exc!r}."
        ) from exc

    try:
        _assert_tool_calling_model(model)
    except SAPModelInitializationError as exc:
        raise ModelInitializationError(str(exc)) from exc
    return model


def _init_chat_model_provider(provider: str) -> str:
    # DeepSeek is OpenAI Chat Completions compatible; route it through the
    # ``openai`` integration so no extra provider package is required.
    if provider == "deepseek":
        return "openai"
    return provider
