"""Entrypoint-local runtime configuration and environment-only secrets."""

from __future__ import annotations

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from ops_pilot.config.paths import REPO_ROOT
from ops_pilot.runtime.spec import ModelProvider, PersistenceBackend, ReasoningEffort, ReasoningMode, SandboxScope

ENTRYPOINT_CONFIG_DIR = REPO_ROOT / "config" / "entries"
_SECRET_FIELD_NAMES = frozenset(
    {
        "model_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "database_url",
        "open_sandbox_api_key",
        "mcp_basic_auth_header",
    }
)
_SHARED_MODEL_CONFIG = {
    "env_file": REPO_ROOT / ".env",
    "env_file_encoding": "utf-8",
    "env_ignore_empty": True,
    "env_prefix": "OPS_PILOT_SECRET_",
    # The shared .env also contains credentials consumed directly by SAP and
    # deployment tooling. This settings model intentionally selects only its
    # explicit aliases from that file.
    "extra": "ignore",
    "frozen": True,
    "yaml_file_encoding": "utf-8",
}


class _EntrypointYamlSource(YamlConfigSettingsSource):
    """Reject credentials in a declarative runtime composition file."""

    def __call__(self) -> dict[str, object]:
        values = super().__call__()
        unknown_fields = set(values).difference(self.settings_cls.model_fields)
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown entrypoint YAML fields: {names}")
        declared_secrets = _SECRET_FIELD_NAMES.intersection(values)
        if declared_secrets:
            names = ", ".join(sorted(declared_secrets))
            raise ValueError(f"Secrets must be supplied through .env, not an entrypoint YAML file: {names}")
        return values


class RuntimeEnvironment(BaseSettings):
    """Validated values for one runtime composition.

    Non-sensitive values come from one entrypoint YAML file.  Credentials use
    explicit aliases in `.env`; no `OPS_PILOT_<ENTRY>_*` environment variable
    can select models, tools, MCP servers, or other runtime capabilities.
    """

    model_config = SettingsConfigDict(**_SHARED_MODEL_CONFIG, yaml_file=None)

    model_provider: ModelProvider = "sap"
    model_name: str = "anthropic--claude-4.6-sonnet"
    model_api_key: str | None = Field(default=None, validation_alias=AliasChoices("MODEL_API_KEY"))
    model_base_url: str | None = None
    model_temperature: float = 0.0
    model_max_tokens: int = 16384
    model_timeout_seconds: int = 120
    model_reasoning_mode: ReasoningMode = "adaptive"
    model_reasoning_effort: ReasoningEffort = "medium"
    assistant_id: str | None = None
    system_prompt: str | None = None

    environment: str = "local"
    langfuse_public_key: str | None = Field(default=None, validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY"))
    langfuse_secret_key: str | None = Field(default=None, validation_alias=AliasChoices("LANGFUSE_SECRET_KEY"))
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_timeout_seconds: int = 30

    persistence_backend: PersistenceBackend = "memory"
    database_url: str | None = Field(default=None, validation_alias=AliasChoices("DATABASE_URL"))
    persistence_setup_on_start: bool = True

    open_sandbox_enabled: bool = False
    open_sandbox_domain: str | None = None
    open_sandbox_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPEN_SANDBOX_API_KEY"))
    open_sandbox_protocol: str = "https"
    open_sandbox_use_server_proxy: bool = True
    open_sandbox_image: str = "python:3.11"
    open_sandbox_timeout_seconds: int = 600
    open_sandbox_ready_timeout_seconds: int = 240
    open_sandbox_scope: SandboxScope = "thread"

    reliability_enabled: bool = True
    run_deadline_seconds: float = 600
    model_call_limit: int = 50
    tool_call_limit: int = 200

    kubeconfig: str | None = None
    jaeger_mcp_url: str | None = None
    prometheus_mcp_url: str | None = None
    mcp_basic_auth_header: str | None = Field(default=None, validation_alias=AliasChoices("MCP_BASIC_AUTH_HEADER"))

    host: str = "127.0.0.1"
    port: int = 8123
    chat_base_path: str = "/chat"
    a2a_base_path: str = "/a2a"
    enable_spaces: bool = True
    enable_a2a: bool = True
    frontend_port: int = 3000
    copilot_runtime_host: str = "127.0.0.1"
    copilot_runtime_port: int = 4001
    copilot_runtime_base_path: str = "/api/copilotkit"
    copilot_event_store_backend: PersistenceBackend = "memory"
    copilot_event_store_setup_on_start: bool = True

    aiopslab_dir: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _EntrypointYamlSource(settings_cls),
            file_secret_settings,
        )

    @classmethod
    def for_entrypoint(cls, name: str) -> RuntimeEnvironment:
        """Load one named composition from `config/entries/<name>.yaml`."""

        load_dotenv(REPO_ROOT / ".env", override=False)
        try:
            environment_type = _ENTRYPOINT_ENVIRONMENTS[name]
        except KeyError as exc:
            known = ", ".join(sorted(_ENTRYPOINT_ENVIRONMENTS))
            raise ValueError(f"Unknown runtime entrypoint {name!r}. Expected one of: {known}.") from exc
        return environment_type()


def _entrypoint_environment(name: str) -> type[RuntimeEnvironment]:
    return type(
        f"{name.title()}RuntimeEnvironment",
        (RuntimeEnvironment,),
        {
            "model_config": SettingsConfigDict(
                **_SHARED_MODEL_CONFIG,
                yaml_file=ENTRYPOINT_CONFIG_DIR / f"{name}.yaml",
            )
        },
    )


_ENTRYPOINT_ENVIRONMENTS: dict[str, type[RuntimeEnvironment]] = {
    name: _entrypoint_environment(name) for name in ("web", "eval", "benchmark", "langgraph")
}
