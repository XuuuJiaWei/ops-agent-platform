import pytest

from ops_pilot.config.settings import SettingsError, load_settings


def test_load_settings_defaults_with_empty_config():
    settings = load_settings(env={}, config={})

    assert settings.app_env == "local"
    assert settings.assistant_id == "agent"
    assert settings.sap_model_name == "anthropic--claude-4.6-sonnet"
    assert settings.sap_temperature == 0.0
    assert settings.sap_top_p is None
    assert settings.sap_max_tokens == 8192
    assert settings.langfuse_enabled is False
    assert settings.enable_smoke_tools is True
    assert settings.mcp.servers == ()


def test_load_settings_reads_nested_regular_config():
    settings = load_settings(
        env={},
        config={
            "app_env": "test",
            "sap": {"model_name": "custom-model", "max_tokens": 4096, "top_p": 0.9},
            "skills_paths": ["./skills/examples", "./skills/other"],
            "server": {"chat_port": 8130},
        },
    )

    assert settings.app_env == "test"
    assert settings.sap_model_name == "custom-model"
    assert settings.sap_max_tokens == 4096
    assert settings.sap_top_p == 0.9
    assert len(settings.skills_paths) == 2
    assert settings.chat_port == 8130


def test_load_settings_overlays_secrets_from_env():
    settings = load_settings(
        env={"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"},
        config={"langfuse": {"base_url": "https://lf.internal"}},
    )

    assert settings.langfuse_public_key == "pk"
    assert settings.langfuse_secret_key == "sk"
    assert settings.langfuse_base_url == "https://lf.internal"
    assert settings.langfuse_enabled is True


def test_load_settings_parses_mcp_servers_with_permissions():
    settings = load_settings(
        env={},
        config={
            "mcpServers": {
                "dyna": {
                    "transport": "stdio",
                    "command": "npx",
                    "allow_tools": ["get_problems"],
                    "hitl_tools": ["restart_service"],
                }
            }
        },
    )

    assert [s.name for s in settings.mcp.servers] == ["dyna"]
    assert settings.mcp.servers[0].allow_tools == ("get_problems",)
    assert settings.mcp.hitl_tool_names() == {"restart_service"}


def test_load_settings_auto_enables_open_sandbox_when_domain_and_key_present():
    settings = load_settings(
        env={"OPEN_SANDBOX_API_KEY": "secret"},
        config={"open_sandbox": {"domain": "opensandbox.example.test"}},
    )

    assert settings.open_sandbox_enabled is True
    assert settings.open_sandbox_domain == "opensandbox.example.test"
    assert settings.open_sandbox_api_key == "secret"
    assert settings.open_sandbox_scope == "thread"
    assert settings.open_sandbox_workspace_path == "/workspace"


def test_load_settings_reads_open_sandbox_pool_options():
    settings = load_settings(
        env={"OPEN_SANDBOX_API_KEY": "secret"},
        config={
            "open_sandbox": {
                "domain": "opensandbox.example.test",
                "scope": "run",
                "max_active": 3,
                "workspace_path": "/work",
                "internal_root": "/internal",
            }
        },
    )

    assert settings.open_sandbox_scope == "run"
    assert settings.open_sandbox_max_active == 3
    assert settings.open_sandbox_workspace_path == "/work"
    assert settings.open_sandbox_internal_root == "/internal"


def test_load_settings_rejects_invalid_open_sandbox_scope():
    with pytest.raises(SettingsError, match="open_sandbox.scope"):
        load_settings(env={}, config={"open_sandbox": {"scope": "user"}})


def test_load_settings_does_not_enable_open_sandbox_without_key():
    settings = load_settings(env={}, config={"open_sandbox": {"domain": "opensandbox.example.test"}})

    assert settings.open_sandbox_enabled is False


def test_load_settings_can_force_open_sandbox_disabled():
    settings = load_settings(
        env={"OPEN_SANDBOX_API_KEY": "secret"},
        config={"open_sandbox": {"enabled": False, "domain": "opensandbox.example.test"}},
    )

    assert settings.open_sandbox_enabled is False


def test_load_settings_raises_when_config_file_missing(tmp_path):
    missing = tmp_path / "nope.yaml"

    with pytest.raises(SettingsError, match="Config file not found"):
        load_settings(env={"OPS_PILOT_CONFIG": str(missing)})
