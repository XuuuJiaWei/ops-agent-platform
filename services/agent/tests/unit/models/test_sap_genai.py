from ops_pilot.config.settings import Settings
from ops_pilot.models.sap_genai import _generation_kwargs, _is_bedrock_model, _sampling_kwargs


def test_sampling_kwargs_defaults_to_temperature_only():
    assert _sampling_kwargs(Settings()) == {"temperature": 0.0}


def test_sampling_kwargs_uses_top_p_only_when_configured():
    settings = Settings(sap_temperature=0.2, sap_top_p=0.8)

    assert _sampling_kwargs(settings) == {"top_p": 0.8}


def test_generation_kwargs_sets_project_default_token_limit():
    assert _generation_kwargs(Settings()) == {"temperature": 0.0, "max_tokens": 8192}


def test_generation_kwargs_includes_token_limit_only_when_configured():
    settings = Settings(sap_max_tokens=4096)

    assert _generation_kwargs(settings) == {"temperature": 0.0, "max_tokens": 4096}


def test_identifies_bedrock_models():
    assert _is_bedrock_model("anthropic--claude-4.6-sonnet") is True
    assert _is_bedrock_model("amazon--nova-pro") is True
    assert _is_bedrock_model("gpt-4o-mini") is False
