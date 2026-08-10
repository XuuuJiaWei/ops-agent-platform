from ops_pilot.config.settings import Settings
from ops_pilot.models.sap_genai import (
    _create_bedrock_chat_model,
    _generation_kwargs,
    _is_bedrock_model,
    _sampling_kwargs,
)


def test_sampling_kwargs_defaults_to_temperature_only():
    assert _sampling_kwargs(Settings()) == {"temperature": 0.0}


def test_sampling_kwargs_uses_top_p_only_when_configured():
    settings = Settings(sap_temperature=0.2, sap_top_p=0.8)

    assert _sampling_kwargs(settings) == {"top_p": 0.8}


def test_generation_kwargs_sets_project_default_token_limit():
    assert _generation_kwargs(Settings()) == {
        "max_tokens": 16384,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }


def test_generation_kwargs_includes_token_limit_only_when_configured():
    settings = Settings(sap_max_tokens=4096)

    assert _generation_kwargs(settings) == {
        "max_tokens": 4096,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
    }


def test_generation_kwargs_can_disable_reasoning():
    settings = Settings(model_reasoning_mode="disabled")

    assert _generation_kwargs(settings) == {
        "temperature": 0.0,
        "max_tokens": 16384,
        "thinking": {"type": "disabled"},
    }


def test_identifies_bedrock_models():
    assert _is_bedrock_model("anthropic--claude-4.6-sonnet") is True
    assert _is_bedrock_model("amazon--nova-pro") is True
    assert _is_bedrock_model("gpt-4o-mini") is False


def test_bedrock_client_uses_explicit_request_timeout_without_retries(monkeypatch):
    captured = {}

    class ProxyClient:
        @staticmethod
        def select_deployment(*, model_name):
            assert model_name == "anthropic--claude-4.6-sonnet"
            return type("Deployment", (), {"model_name": model_name, "deployment_id": "deployment"})()

    def fake_chat_bedrock(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("gen_ai_hub.proxy.langchain.amazon.ChatBedrock", fake_chat_bedrock)

    _create_bedrock_chat_model(Settings(model_request_timeout_seconds=180), ProxyClient())

    assert captured["config"].read_timeout == 180
    assert captured["config"].retries == {"mode": "standard", "total_max_attempts": 1}
    assert captured["streaming"] is True
