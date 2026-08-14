import pytest

from ops_pilot.config.interpolation import MissingEnvironmentError
from ops_pilot.config.settings import SettingsError, load_settings


def test_load_settings_defaults_with_empty_config():
    settings = load_settings(env={}, config={})

    assert settings.app_env == "local"
    assert settings.assistant_id == "agent"
    assert settings.model_provider == "sap"
    assert settings.uses_sap_ai_core is True
    assert settings.sap_model_name == "anthropic--claude-4.6-sonnet"
    assert settings.model_name == "anthropic--claude-4.6-sonnet"
    assert settings.sap_temperature == 0.0
    assert settings.sap_top_p is None
    assert settings.sap_max_tokens == 16384
    assert settings.model_request_timeout_seconds == 120
    assert settings.model_reasoning_mode == "adaptive"
    assert settings.model_reasoning_effort == "medium"
    assert settings.langfuse_enabled is False
    assert settings.langfuse_timeout_seconds == 30
    assert settings.mcp.servers == ()
    assert settings.reliability_enabled is True
    assert settings.run_deadline_seconds == 600.0
    assert settings.tool_retry_max_attempts == 3
    assert settings.chaos_namespace == "otel-demo"
    assert settings.chaos_flagd_service == "flagd"
    assert settings.chaos_flagd_service_port == 8016
    assert settings.chaos_flagd_ui_port == 4000
    assert settings.chaos_flag_sync_timeout_seconds == 90
    assert settings.chaos_poll_interval_seconds == 1
    assert settings.chaos_stable_reads == 2
    assert settings.chaos_signal_warmup_seconds == 15


def test_load_settings_reads_reliability_policy() -> None:
    settings = load_settings(
        env={},
        config={
            "reliability": {
                "run_deadline_seconds": 90,
                "max_attempts": 2,
                "initial_backoff_seconds": 0,
                "backoff_multiplier": 3,
                "jitter_ratio": 0,
            }
        },
    )

    assert settings.run_deadline_seconds == 90
    assert settings.tool_retry_max_attempts == 2
    assert settings.tool_retry_initial_backoff_seconds == 0
    assert settings.tool_retry_backoff_multiplier == 3
    assert settings.tool_retry_jitter_ratio == 0


def test_load_settings_reads_reasoning_policy():
    settings = load_settings(
        env={},
        config={
            "model": {
                "reasoning": {"mode": "adaptive", "effort": "medium"},
            },
        },
    )

    assert settings.model_reasoning_mode == "adaptive"
    assert settings.model_reasoning_effort == "medium"


def test_load_settings_reads_chaos_readiness_policy():
    settings = load_settings(
        env={},
        config={
            "chaos": {
                "flag_sync_timeout_seconds": 12,
                "poll_interval_seconds": 0.2,
                "stable_reads": 3,
                "signal_warmup_seconds": 0,
            }
        },
    )

    assert settings.chaos_flag_sync_timeout_seconds == 12
    assert settings.chaos_poll_interval_seconds == 0.2
    assert settings.chaos_stable_reads == 3
    assert settings.chaos_signal_warmup_seconds == 0


def test_load_settings_reads_model_request_timeout():
    settings = load_settings(env={}, config={"model": {"request_timeout_seconds": 180}})

    assert settings.model_request_timeout_seconds == 180


def test_load_settings_rejects_invalid_model_reasoning_effort():
    with pytest.raises(SettingsError, match="model.reasoning.effort"):
        load_settings(env={}, config={"model": {"reasoning": {"effort": "max"}}})


def test_load_settings_reads_model_section_for_deepseek():
    settings = load_settings(
        env={"MODEL_API_KEY": "sk-test"},
        config={
            "model": {
                "provider": "deepseek",
                "model_name": "deepseek-chat",
                "base_url": "https://api.deepseek.com",
                "max_tokens": 4096,
            }
        },
    )

    assert settings.model_provider == "deepseek"
    assert settings.uses_sap_ai_core is False
    assert settings.model_name == "deepseek-chat"
    assert settings.model_base_url == "https://api.deepseek.com"
    assert settings.model_api_key == "sk-test"
    assert settings.sap_max_tokens == 4096


def test_load_settings_ignores_removed_sap_alias_section():
    settings = load_settings(
        env={},
        config={
            "sap": {"model_name": "legacy-model", "max_tokens": 1024},
            "model": {"provider": "openai", "model_name": "gpt-4o-mini"},
        },
    )

    assert settings.model_provider == "openai"
    assert settings.model_name == "gpt-4o-mini"
    # The deprecated ``sap:`` section is no longer read; defaults apply.
    assert settings.sap_max_tokens == 16384


def test_load_settings_rejects_unknown_model_provider():
    with pytest.raises(SettingsError, match="model.provider"):
        load_settings(env={}, config={"model": {"provider": "not-a-provider"}})


def test_load_settings_reads_nested_regular_config():
    settings = load_settings(
        env={},
        config={
            "app_env": "test",
            "model": {"model_name": "custom-model", "max_tokens": 4096, "top_p": 0.9},
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
        config={"langfuse": {"base_url": "https://lf.internal", "timeout_seconds": 45}},
    )

    assert settings.langfuse_public_key == "pk"
    assert settings.langfuse_secret_key == "sk"
    assert settings.langfuse_base_url == "https://lf.internal"
    assert settings.langfuse_timeout_seconds == 45
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


def test_load_settings_defaults_to_memory_persistence():
    settings = load_settings(env={}, config={})

    assert settings.persistence_backend == "memory"
    assert settings.persistence_enabled is False
    assert settings.persistence_setup_on_start is True


def test_open_sandbox_domain_interpolates_shoot_domain():
    settings = load_settings(
        env={"OPEN_SANDBOX_API_KEY": "secret", "OTEL_SHOOT_DOMAIN": "abc.shoot.test"},
        config={"open_sandbox": {"domain": "opensandbox.${OTEL_SHOOT_DOMAIN}"}},
    )

    assert settings.open_sandbox_domain == "opensandbox.abc.shoot.test"


def test_open_sandbox_domain_missing_var_fails_fast():
    with pytest.raises(MissingEnvironmentError, match="OTEL_SHOOT_DOMAIN"):
        load_settings(
            env={"OPEN_SANDBOX_API_KEY": "secret"},
            config={"open_sandbox": {"domain": "opensandbox.${OTEL_SHOOT_DOMAIN}"}},
        )


def test_absent_open_sandbox_domain_does_not_raise_without_var():
    settings = load_settings(env={}, config={"open_sandbox": {"enabled": False}})

    assert settings.open_sandbox_domain is None


def test_mcp_url_interpolates_shoot_domain():
    settings = load_settings(
        env={"OTEL_SHOOT_DOMAIN": "abc.shoot.test"},
        config={
            "mcpServers": {
                "prometheus": {
                    "transport": "streamable_http",
                    "url": "https://prometheus-otel.${OTEL_SHOOT_DOMAIN}/mcp",
                }
            }
        },
    )

    assert settings.mcp.servers[0].url == "https://prometheus-otel.abc.shoot.test/mcp"


def test_mcp_missing_var_fails_fast_at_settings_load():
    with pytest.raises(MissingEnvironmentError, match="OTEL_SHOOT_DOMAIN"):
        load_settings(
            env={},
            config={
                "mcpServers": {
                    "prometheus": {
                        "transport": "streamable_http",
                        "url": "https://prometheus-otel.${OTEL_SHOOT_DOMAIN}/mcp",
                    }
                }
            },
        )


def test_process_spec_fields_are_not_interpolated():
    # command/args/cwd are process-spec fields excluded from the whitelist:
    # a literal ${...} must survive verbatim and never trigger a missing-var error.
    settings = load_settings(
        env={},
        config={
            "mcpServers": {
                "local": {
                    "transport": "stdio",
                    "command": "${NOT_EXPANDED}",
                    "args": ["--path", "${ALSO_NOT_EXPANDED}"],
                    "cwd": "${CWD_NOT_EXPANDED}",
                }
            }
        },
    )

    server = settings.mcp.servers[0]
    assert server.command == "${NOT_EXPANDED}"
    assert server.args == ("--path", "${ALSO_NOT_EXPANDED}")
    assert server.cwd == "${CWD_NOT_EXPANDED}"
    assert settings.persistence_database_url is None
    assert settings.sqlalchemy_database_url() is None
    assert settings.psycopg_database_url() is None


def test_load_settings_reads_postgres_persistence():
    settings = load_settings(
        env={"DATABASE_URL": "postgresql://u:p@h:5433/db"},
        config={"persistence": {"backend": "postgres", "setup_on_start": False}},
    )

    assert settings.persistence_backend == "postgres"
    assert settings.persistence_enabled is True
    assert settings.persistence_setup_on_start is False
    assert settings.psycopg_database_url() == "postgresql://u:p@h:5433/db"
    assert settings.sqlalchemy_database_url() == "postgresql+asyncpg://u:p@h:5433/db"


def test_sqlalchemy_url_translates_libpq_sslmode_for_asyncpg():
    database_url = "postgresql://u:p@h:5432/db?sslmode=require"
    settings = load_settings(
        env={"DATABASE_URL": database_url},
        config={"persistence": {"backend": "postgres"}},
    )

    assert settings.persistence_database_url == database_url
    assert settings.psycopg_database_url() == database_url
    assert settings.sqlalchemy_database_url() == "postgresql+asyncpg://u:p@h:5432/db?ssl=require"
    assert settings.configured_system_prompt() is None


def test_sqlalchemy_url_prefers_an_explicit_asyncpg_ssl_parameter():
    settings = load_settings(
        env={"DATABASE_URL": "postgresql+asyncpg://u:p@h/db?sslmode=require&ssl=verify-full"},
        config={"persistence": {"backend": "postgres"}},
    )

    assert settings.sqlalchemy_database_url() == "postgresql+asyncpg://u:p@h/db?ssl=verify-full"


def test_sqlalchemy_and_psycopg_urls_normalize_driver_suffix():
    settings = load_settings(
        env={"DATABASE_URL": "postgresql+asyncpg://u:p@h/db"},
        config={"persistence": {"backend": "postgres"}},
    )

    # SQLAlchemy keeps the explicit async driver; psycopg wants it stripped.
    assert settings.sqlalchemy_database_url() == "postgresql+asyncpg://u:p@h/db"
    assert settings.psycopg_database_url() == "postgresql://u:p@h/db"


def test_load_settings_normalizes_legacy_postgres_scheme():
    settings = load_settings(
        env={"DATABASE_URL": "postgres://u:p@h/db"},
        config={"persistence": {"backend": "postgres"}},
    )

    assert settings.psycopg_database_url() == "postgresql://u:p@h/db"
    assert settings.sqlalchemy_database_url() == "postgresql+asyncpg://u:p@h/db"


def test_load_settings_rejects_postgres_backend_without_database_url():
    with pytest.raises(SettingsError, match="DATABASE_URL is not set"):
        load_settings(env={}, config={"persistence": {"backend": "postgres"}})


def test_load_settings_rejects_unknown_persistence_backend():
    with pytest.raises(SettingsError, match="persistence.backend"):
        load_settings(env={}, config={"persistence": {"backend": "sqlite"}})
