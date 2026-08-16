from __future__ import annotations

from typing import Any

import langchain.chat_models

from ops_pilot.models.factory import _create_langchain_chat_model
from ops_pilot.runtime.spec import ModelSpec


def test_openrouter_uses_openai_compatibility_and_enables_reasoning(monkeypatch) -> None:
    received: dict[str, Any] = {}

    class Model:
        def bind_tools(self, *_: object, **__: object) -> None:
            return None

    def init_chat_model(**kwargs: Any) -> Model:
        received.update(kwargs)
        return Model()

    monkeypatch.setattr(langchain.chat_models, "init_chat_model", init_chat_model)

    _create_langchain_chat_model(
        ModelSpec(
            provider="openai",
            name="dots-studio/dots-3-note-preview:free",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        )
    )

    assert received["model_provider"] == "openai"
    assert received["base_url"] == "https://openrouter.ai/api/v1"
    assert received["api_key"] == "test-key"
    assert received["extra_body"] == {
        "reasoning": {"enabled": True},
        "provider": {"require_parameters": True},
    }
