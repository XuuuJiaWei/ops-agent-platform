from ops_pilot.config.settings import load_settings


def test_load_settings_defaults_without_secrets():
    settings = load_settings({})

    assert settings.app_env == "local"
    assert settings.assistant_id == "agent"
    assert settings.sap_model_name == "anthropic--claude-4.6-sonnet"
    assert settings.sap_temperature == 0.0
    assert settings.sap_top_p is None
    assert settings.sap_max_tokens == 8192
    assert settings.langfuse_enabled is False
    assert settings.enable_smoke_tools is True


def test_load_settings_splits_skill_paths():
    settings = load_settings({"SKILLS_PATHS": "./skills/examples/,./skills/other"})

    assert len(settings.skills_paths) == 2


def test_load_settings_reads_optional_top_p():
    settings = load_settings({"SAP_AI_CORE_TOP_P": "0.8"})

    assert settings.sap_top_p == 0.8


def test_load_settings_reads_optional_max_tokens():
    settings = load_settings({"SAP_AI_CORE_MAX_TOKENS": "4096"})

    assert settings.sap_max_tokens == 4096
