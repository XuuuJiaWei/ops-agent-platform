"""Provider-agnostic chat model factory.

``model.provider`` in config selects the backend:

* ``sap`` (default) uses the SAP Generative AI Hub proxy (``sap_genai``).
* Any other provider (``deepseek``, ``openai``, ``anthropic``, ...) is built
  through LangChain's ``init_chat_model``. DeepSeek and other OpenAI-compatible
  endpoints work via ``model.base_url`` plus an explicit provider API key.
"""

from __future__ import annotations

from typing import Any

from ops_pilot.models.sap_genai import (
    SAPModelInitializationError,
    _assert_tool_calling_model,
    _sampling_kwargs,
)
from ops_pilot.models.sap_genai import create_chat_model as _create_sap_chat_model
from ops_pilot.runtime.spec import ModelSpec


class ModelInitializationError(RuntimeError):
    """Raised when the configured chat model cannot be created."""


def create_chat_model(spec: ModelSpec) -> Any:
    """Create a LangChain tool-calling chat model for the configured provider."""

    if spec.provider == "sap":
        return _create_sap_chat_model(spec)
    return _create_langchain_chat_model(spec)


def _create_langchain_chat_model(spec: ModelSpec) -> Any:
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:  # pragma: no cover - langchain is a hard dep.
        message = "langchain is not installed. Run 'uv sync --all-packages' in services/."
        raise ModelInitializationError(message) from exc

    provider = _init_chat_model_provider(spec.provider)
    kwargs: dict[str, Any] = {
        "model": spec.name,
        "model_provider": provider,
        **_sampling_kwargs(spec),
    }
    if spec.max_tokens is not None:
        kwargs["max_tokens"] = spec.max_tokens
    if spec.base_url:
        kwargs["base_url"] = spec.base_url
    if spec.api_key:
        kwargs["api_key"] = spec.api_key
    if _is_openrouter(spec):
        kwargs["extra_body"] = {"reasoning": {"enabled": spec.reasoning_mode != "disabled"}}

    try:
        model = init_chat_model(**kwargs)
    except Exception as exc:  # noqa: BLE001 - normalize provider/init errors.
        raise ModelInitializationError(
            f"Unable to initialize '{spec.provider}' chat model '{spec.name}': {exc!r}."
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


def _is_openrouter(spec: ModelSpec) -> bool:
    return bool(spec.base_url and spec.base_url.rstrip("/").startswith("https://openrouter.ai/api/"))
