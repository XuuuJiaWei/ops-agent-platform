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


def test_load_settings_reads_optional_max_tokens():
    settings = load_settings({"SAP_AI_CORE_MAX_TOKENS": "4096"})

    assert settings.sap_max_tokens == 4096


def test_load_settings_auto_enables_open_sandbox_when_credentials_exist():
    settings = load_settings(
        {
            "OPEN_SANDBOX_DOMAIN": "opensandbox.example.test",
            "OPEN_SANDBOX_API_KEY": "secret",
        }
    )

    assert settings.open_sandbox_enabled is True
    assert settings.open_sandbox_domain == "opensandbox.example.test"
    assert settings.open_sandbox_api_key == "secret"
    assert settings.open_sandbox_protocol == "https"
    assert settings.open_sandbox_use_server_proxy is True
    assert settings.open_sandbox_disable_metrics is True
    assert settings.open_sandbox_timeout_seconds == 600


def test_load_settings_reads_optional_open_sandbox_timeout():
    settings = load_settings({"OPEN_SANDBOX_TIMEOUT_SECONDS": "3600"})

    assert settings.open_sandbox_timeout_seconds == 3600


def test_load_settings_can_force_open_sandbox_disabled():
    settings = load_settings(
        {
            "OPEN_SANDBOX_ENABLED": "false",
            "OPEN_SANDBOX_DOMAIN": "opensandbox.example.test",
            "OPEN_SANDBOX_API_KEY": "secret",
        }
    )

    assert settings.open_sandbox_enabled is False
