"""Tests for the provider-agnostic chat model factory."""

from __future__ import annotations

import pytest

from ops_pilot.config.settings import Settings
from ops_pilot.models.factory import (
    ModelInitializationError,
    _init_chat_model_provider,
    create_chat_model,
)


def test_deepseek_routes_through_openai_compatible_integration():
    assert _init_chat_model_provider("deepseek") == "openai"
    assert _init_chat_model_provider("openai") == "openai"
    assert _init_chat_model_provider("anthropic") == "anthropic"


def test_create_chat_model_builds_deepseek_openai_client():
    settings = Settings.model_validate(
        {
            "model_provider": "deepseek",
            "model_name": "deepseek-chat",
            "model_base_url": "https://api.deepseek.com",
            "model_api_key": "sk-test",
            "model_max_tokens": 4096,
        }
    )

    model = create_chat_model(settings)

    assert type(model).__name__ == "ChatOpenAI"
    assert callable(getattr(model, "bind_tools", None))
    assert getattr(model, "model_name", None) == "deepseek-chat"


def test_create_chat_model_uses_sap_path_for_default_provider(monkeypatch):
    captured: dict[str, object] = {}

    def fake_sap(settings: Settings) -> object:
        captured["settings"] = settings
        return object()

    monkeypatch.setattr("ops_pilot.models.factory._create_sap_chat_model", fake_sap)

    settings = Settings.model_validate({})  # provider defaults to "sap"
    create_chat_model(settings)

    assert captured["settings"] is settings


def test_create_chat_model_wraps_provider_errors(monkeypatch):
    def boom(**_: object) -> object:
        raise RuntimeError("bad key")

    import langchain.chat_models as chat_models

    monkeypatch.setattr(chat_models, "init_chat_model", boom)

    settings = Settings.model_validate({"model_provider": "openai", "model_name": "gpt-4o-mini", "model_api_key": "x"})

    with pytest.raises(ModelInitializationError, match="openai"):
        create_chat_model(settings)
